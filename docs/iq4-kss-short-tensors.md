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

No issue was filed about the NaN itself. It is not a defect in this engine,
and filing it as one would have sent a maintainer looking in his own
quantizer, which is correct.
