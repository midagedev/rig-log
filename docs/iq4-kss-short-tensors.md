# A published quantization that reserves too few bytes per tensor

What looked like an engine bug for most of a day was a malformed file, and
finding that out took a reference dequantization, a routing trace and a
checksum. Measured 2026-09-11 on the machine in [the README](../README.md).

## The symptom

`KeinNiemand/DeepSeek-V4-Flash-0731-IK_GGUF` at `IQ4_KSS` (149 GB) aborts at
the first sampled token with every candidate logit NaN:

```
=============================== Failed to sample token
src/llama-sampling.cpp:745: Fatal error
```

Reproducible CPU-only — `-ngl 0 -c 8192 -t 32` and one request is enough, no
GPU, no template flags, no tensor overrides. Both `llama-server` and
`llama-cli`. A standard-quantization GGUF of the same model works.

**Temperature decides whether you see it at all.** At `temperature 0` there is
no abort: the argmax of an all-NaN row still returns an index, so the run
emits tokens that render as nothing. Any temperature above zero normalizes the
row and aborts. An early version of this investigation concluded the bug was
`llama-server`-only precisely because its `llama-cli` control had been run at
`--temp 0` — a control that does not exercise the failing path is not a
control, and that mistake cost hours.

## The cause

`IQ4_KSS` carries a 4-byte scale per row, so `ggml_row_size(IQ4_KSS, 4096)` is
**2052**, not 2048. The file reserves 2048 × rows:

| | |
|---|---|
| `blk.0.ffn_up_exps.weight`, `{4096, 2048, 256}` | |
| Reserved by the GGUF | 1 073 741 824 B — exactly 1 GiB |
| Required by the type | 1 075 838 976 B = 2052 × 524 288 |
| Short by | 2 097 152 B = 4 × rows = **1022 rows** |

127 of the file's 129 expert tensors are short in exactly this way. The two
that are correct are `IQ4_K`, which has no per-row header.

So rows 0–1025 of the last expert read correctly and rows 1026–2047 read out
of whatever follows in the file. Those rows dequantize to ±inf, and the expert
matmul returns NaN whenever a token routes to expert 255.

Four predictions, four matches:

| Tensor | Type | Predicted first bad row | Observed |
|---|---|---:|---:|
| `blk.0.ffn_up_exps` | IQ4_KSS | 1026 | 1026 |
| `blk.13.ffn_down_exps` | IQ4_KSS, `{2048, 4096, 256}` | 16 | 17 |
| `blk.22.ffn_up_exps` | IQ4_KS | 1086 | 1098 |
| `blk.41.ffn_down_exps` | IQ4_K | none | none |

## How it was established

**Reference dequantization.** A 60-line harness reads each row straight out of
the file at `ggml_row_size` stride and calls ggml's own
`to_float` for the type, counting non-finite values. Experts 0–254 are clean;
expert 255 has ~90 bad rows of 2048. Reading at the correct stride producing
correct values for 254 experts is also what rules out a wrong assumed layout.

**Routing trace, from the engine side.** `llama-eval-callback` prints every
tensor with its sum, so the first `nan` names the operation and its inputs —
and it also prints `ffn_moe_topk-N`, the six selected experts per layer. For
`"Hello"`, exactly one layer selects expert 255:

```
layer 12: [80, 154, 169, 113, 229, 249]
layer 13: [129, 44, 87, 255, 177, 33]   <-- 255
layer 14: [3, 4, 1, 0, 2, 5]
```

and layer 13 is exactly where the first NaN appears. Other prompts NaN at
other layers — 1 and 16 observed — always the first layer that selects 255.
That confirms the file-reading result from inside the engine, independently.

**Not the fused kernel.** With `-no-fmoe` the first NaN moves from
`MOE_FUSED_UP_GATE` to a plain `MUL_MAT_ID` over the same tensor.

**Not a damaged download.** sha256 of the 149 GB file matches what the
publisher released, byte for byte.

**Not this engine's quantizer.** `quantize_iq4_kss()` returns
`nrows * ggml_row_size(...)`, and `do_quantize()` sums those per expert —
correct at `origin/main` tip and at the older commit checked. The file's
`quantize.imatrix.file` metadata points at a Windows build that cannot be
identified from here.

## How far it goes, and who it does not reach

The maintainer's first question on the pull request was how the file was
produced, which is not something this machine can answer — the file was
downloaded, not made here. What it can answer is the shape of the mistake,
and that turned out to be checkable on other files without downloading any
of them: a GGUF's tensor-info block sits in the first few MB, so
`curl -r 0-5999999` and a walk over the offsets gives every tensor's
reserved region.

Three files from the same publisher, reserved region divided by row count:

| File | Short | Reserved / needed, bytes per row | Correct |
|---|---|---|---|
| IQ4_KSS | iq4_ks ×36, iq4_kss ×91 | 2176/2180, 2048/2052, 1024/1028 | iq4_k ×2, iq6_k ×43 |
| IQ3_K | iq4_kss ×36 | 2048/2052 | iq3_k ×91, iq4_k ×2, iq6_k ×44 |
| IQ2_KL | iq2_kl ×91, iq3_ks ×36, iq4_ks ×2 | 1376/1378, 1632/1634, 1088/1092 | iq6_k ×168 |

Every reserved figure is `nblocks * ggml_type_size(type)`, and every
shortfall is the per-row header `ggml_row_size()` adds on top of the blocks —
4 bytes for `iq4_kss` and `iq4_ks`, 2 for `iq2_kl` and `iq3_ks`. In each
file every type that carries such a header is short and every type without
one is correct. The whole published ladder is affected, not one file.

The control is another publisher's ik quantization of the same model, made
on a different machine: `Downtown-Case/DeepSeek-V4-Flash-0731-128GB-RAM-IK-GGUF`
reserves the full 1634 bytes per row for all 34 of its `iq3_ks` tensors.
Same type, same engine, correct sizes. So it is neither the type nor the
tool, which is what the earlier quantizer reading already suggested and this
measures from the outside.

## The publisher, and who else had hit it

The file's repository already had one open discussion, opened eight days
before this investigation: another user reporting all-NaN logits on the same
two files, with controls on three GPU configurations and on `-no-fmoe`, and
ending on the question of whether it was a fork regression. The publisher's
one-line answer named the commit they were on. The thread then stopped.

That question is the one this machine could answer, so the findings went
there rather than into a new discussion:
[KeinNiemand/DeepSeek-V4-Flash-0731-IK_GGUF, discussion 1](https://huggingface.co/KeinNiemand/DeepSeek-V4-Flash-0731-IK_GGUF/discussions/1).
It is not a fork regression, the whole published ladder is affected, sha256
matches so a re-download does not help, and the `--temp 0` trap is worth
knowing for anyone whose control run looked like it worked.

One thing is still open, and it is the reason the report asks a question
instead of assigning blame: the commit the publisher named returns the full
row size in both quantizer entry points, so the files do not match that code
path. Either the build differed from what they recall, or there is a write
path that has not been found — and the metadata says Windows, which is not a
platform this machine can check.

## What was sent upstream

The reader, not the writer, is the part this machine can improve:
[PR #2437](https://github.com/ikawrakow/ik_llama.cpp/pull/2437) makes the
loader compare `ggml_nbytes()` against the space the GGUF actually reserved,
so the same file now says

```
llama_model_load: error loading model: tensor 'blk.0.ffn_gate_exps.weight' is stored in
1073741824 bytes but iq4_kss needs 1075838976, the model is corrupted or was written by
a broken quantizer
```

The loader already checked shape and type; byte extent was the one it
did not. Method: [`upstream-contributions.md`](upstream-contributions.md).

~~No issue was filed about the NaN itself. It is not a defect in this engine,
and filing it as one would have sent a maintainer looking in his own
quantizer, which is correct.~~ Struck 2026-09-14; see the correction below.

## Correction, 2026-09-14: it is the fork's own tooling

Two days after the issue closed, the publisher answered the question the
maintainer had asked: the files had their chat template rewritten with the
fork's `gguf-py/scripts/gguf_new_metadata.py`. That script reads every tensor
through `GGUFReader` and writes it back through `GGUFWriter`, and gguf-py
sizes a tensor as `type_size * ne / block_size`. `ggml_row_size()` in
`ggml.c` adds `row_meta_size` once per row, and twenty of the fork's quant
types have a non-zero one — IQ4_KSS's is 4. So every read-then-write pass
drops `rows × 4` bytes from each IQ4_KSS tensor, which for a `{4096, 2048,
256}` expert is exactly the 2 MiB measured above.

Reproduced on this machine on the fork at 3bb386eb: Qwen2.5-7B-Instruct
requantized to IQ4_KSS with `llama-quantize` (the quantizer's output is
correct, as the earlier reading said), then `gguf_new_metadata.py
--chat-template "{{ messages }}" --force`.

| | input | rewritten, before the fix | rewritten, after |
|---|---|---|---|
| file size | 4 043 393 728 | 4 037 320 960 | 4 043 391 232 |
| offset of the tensor after `token_embd.weight` (3584 × 152064) | 273 106 944 | 272 498 688 | 273 106 944 |
| `llama-perplexity -ngl 0 -c 512 --chunks 4` | 1.0027 | nan | 1.0027 |

The shortfall, 6 070 272 bytes after the 2 496-byte header change, equals
the sum of rows × 4 over the file's IQ4_KSS tensors; after the fix the data
region is byte-identical to the input under `cmp`. The fix is a table of
`row_meta_size` per type in `constants.py` and its use in the two shape
helpers and the reader, 34 lines:
[#2443](https://github.com/ikawrakow/ik_llama.cpp/pull/2443).

So the sentence above was wrong in the way that matters: the quantizer was
never at fault, but the repository that ships the quantizer also ships the
script that broke its output, and that is a defect of theirs. The declined
loader check would have caught this file; the fix that was wanted was one
layer down, in the writer. The lesson in
[`upstream-contributions.md`](upstream-contributions.md) stands — ask what
the maintainer would pay for — and gains a footnote: a declined issue can
still be the place where the real cause arrives, so keep watching it.
