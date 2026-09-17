# What mistral.rs can and cannot offload

*2026-09-17, 18:42–18:59. RTX A6000 48G, one lease per launch, io pressure 0 at every start.
mistral.rs 0.9.3, prebuilt installer binary, CUDA build 13.2 against a 13.0 toolkit on the box.*

The question was plain: does mistral.rs have the CPU and NVMe offloading this box relies on? The
answer is half yes, and the half that is yes is broken on exactly the model class this workstation
cares about.

## What the binary offers

Read off `serve --help` and the binary's own strings, not from documentation:

| | |
|---|---|
| `--cpu` | force CPU-only execution |
| `-n, --device-layers ORD:NUM` | layer-granular placement, the `-ngl` of this engine |
| `--topology <YAML>` | per-layer device *and* per-layer quantization |
| `MISTRALRS_NO_MMAP` | mmap is the default for model loading; this turns it off |
| `MISTRALRS_CPU_KV_F32` | the KV dtype when the model runs on CPU — f16 unless this is set. **Not** a KV-offload switch; an earlier note here called it one and that was a misreading of the string |
| a string in the binary | "No suitable quantization level fits on the available devices. Try a smaller model or enable CPU offload." |

What is absent matters more than what is present. There is **no tensor-level placement** — nothing
resembling ik_llama.cpp's `-ot exps=CPU` or `-ncmoe N`, which is the recipe this box serves
DeepSeek-V4.1-Flash with: attention and the dense trunk on the cards, expert weights in RAM. A
layer either goes to a device whole or it does not go there. And there is **no NVMe or disk
offload**: no `nvme`, no disk-offload string anywhere in the binary. mmap means a GGUF larger than
RAM pages in through the page cache, which is not a placement tier — anything mapped to the GPU is
copied there regardless.

`tune`, which recommends a quantization and a device map, refuses to help here at all:
`Auto-tuning is not supported for pre-quantized GGUF/GGML models.`

## The layer mapping works, and then the model does not

`-n 0:8` on the Qwen3.6-35B-A3B UD-Q6_K, which answers the question the help text could not — the
unlisted layers do go to the host:

```
INFO mistralrs_quant::utils::log: Layers 0-7: cuda[0] (48 GB)
INFO mistralrs_quant::utils::log: Layers 8-39: cpu (252 GB)
```

The server then loads, serves `/health`, and fails every single request:

```
ERROR mistralrs_core::engine: prompt step - Model failed with error: moe experts forward
dtype mismatch in matmul, lhs: BF16, rhs: F32
```

232 identical failures over the nine minutes the readiness loop kept asking. Not intermittent, not
a first-request warmup: every completion, including the one-token readiness probe.

Three launches scope it, each its own lease:

| launch | mapping | result |
|---|---|---|
| `-n 0:40` | `Layers 0-39: cuda[0]` | **works**, 0 dtype errors — so the flag itself is fine |
| `-n 0:39` | `Layers 0-38: cuda[0]` / `Layers 39-39: cpu` | **fails**, 58 dtype errors — **one layer on the host is enough** |
| `-n 0:8`, dense Qwen2.5-7B Q3_K_M | `Layers 0-7: cuda[0]` / `Layers 8-27: cpu` | **works** — partial offload does what it should |

Which layer that one is matters for anyone reproducing it, so it was read out of the GGUF header
rather than assumed. All **forty** repeating blocks carry the expert tensors
(`blk.N.ffn_{gate,up,down}_exps.weight`), so any layer sent to the host takes an expert block with
it. Layer 39 in particular is one of the ten **full-attention** layers — `full_attention_interval`
is 4, so `attn_q`/`attn_k` live at blocks 3, 7, 11 … 39 and the other thirty carry `ssm`/linear-attn
tensors instead. The failing launch therefore put a full-attention + MoE layer on the host, which
means the linear-attention path is not implicated and the expert FFN is. On a model whose layers are
not uniformly MoE, `-n 0:39` would land on whatever block 39 happens to be there.

The dense row's rate is worth one sentence of care, because two claims were struck today for
exactly this shape. That launch measured **17.4 tok/s** on a sixteen-token `curl` burst with twenty
of twenty-eight layers on the host. The nearest paired figure is the sweep's own one-stream take on
the same engine and the same model fully resident, **122.8 tok/s** — but that is a toktape take over
238-token prompts, not a sixteen-token burst, so the pair is an order of magnitude and not a ratio.
What the row is evidence for is that it served at all.

So: the trigger is a MoE expert block placed on the CPU, one is enough, and partial offload is
otherwise functional. The error names the site — the CPU MoE expert forward receives BF16
activations (`DType selected is BF16`, printed at load) against expert weights that arrive as F32.

That is the minimal reproducer, and it is two lines:

```
mistralrs serve -f Qwen3.6-35B-A3B-UD-Q6_K.gguf --host 127.0.0.1 --port 8013 \
  --paged-attn on --pa-context-len 4096 --max-seq-len 4096 --max-batch-size 1 -n 0:39
curl -s localhost:8013/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"default","messages":[{"role":"user","content":"hi"}],"max_tokens":1}'
```

## Scoping honestly, and the two models that could not be asked

One MoE model is one model. The generality is **untested**, and not for want of trying — the two
other MoE GGUFs on this box are refused at load for reasons that have nothing to do with offload:

* `DeepSeek-V2-Lite-Chat.Q3_K_M.gguf`: `GGUF architecture deepseek2 is missing metadata
  {arch}.attention.key_length_mla`. An older conversion, predating a key this loader requires.
* `Qwen3-Coder-Next-IQ4_XS.gguf`: `GGUF tensor blk.0.ssm_ba.weight uses dtype IQ4_XS (23) for native
  binding model.layers.0.linear_attn.in_proj_ba.weight`. The linear-attention projection is expected
  unquantized and this GGUF quantized it.

Both refusals are separate limitations worth knowing about — a GGUF that llama.cpp-family engines load
happily is not necessarily a GGUF mistral.rs will take — and neither can serve as the second data
point for the offload bug. The report therefore says "reproduced on one MoE GGUF, with a dense
control that works and a whole-GPU control that works", which is what was measured.

Duplicate search, three queries on `EricLBuehler/mistral.rs`: `"dtype mismatch in matmul"` (one hit,
[#2072](https://github.com/EricLBuehler/mistral.rs/issues/2072), FP8 *loading*, a different path),
`moe experts forward dtype mismatch` and `device-layers cpu offload gguf moe` — no match.

## The fix, the claim a test killed, and the test that did not ship

Submitted as [EricLBuehler/mistral.rs#2430](https://github.com/EricLBuehler/mistral.rs/pull/2430),
five lines in one file. The cause is one line up from where the error is thrown.
`GgufMatMul::quantized_act_type` (`mistralrs-quant/src/gguf/mod.rs:560`) returns `None` for CPU
weights, with the comment *"cpu handles bf16 activations natively (widened once inside the packed
matmul)"* — true of the packed 2D matmul, and the `None` also switches off the cast that
`QuantMethod::gather_forward` would otherwise apply. The indexed path does not widen: it dequantizes
the experts to F32 and matmuls them against the activations as they arrive. So the fix casts to F32
for that matmul and restores the input dtype, which is what `forward_raw` does for the non-indexed
case and what the CUDA path does inside `quantize_input_q8_1`. It sits after the `indexed_gemv` fast
path, which keeps its original dtype.

Two reviewer questions were answered before submitting rather than after. Fixing
`quantized_act_type` instead would put a cast on the 2D path that widens BF16 for free. And the
`QMatMul::Tensor` branch two lines below has the same shape but cannot be reached with a mismatched
dtype: the CPU early return is guarded by `if let QMatMul::QTensor(qt)`, so a plain tensor falls
through to `Some(DType::F32)` and the trait casts for it already.

> ~~`indexed_gemv` is aarch64 only, so an x86_64 host always reaches the dequantize fallback.~~
> **Struck before submission, by a test that was never shipped.** The sentence was in the PR body
> when it was written. The throwaway test — `QTensor::quantize(Q4K)`, a BF16 activation,
> `gather_forward` — was expected to pass on this Apple Silicon Mac without the fix and to fail only
> on the box. It failed on the Mac:
> `Error: dtype mismatch in matmul, lhs: BF16, rhs: F32`. `indexed_gemv` also declines layouts its
> repacked kernels cannot serve, so aarch64 reaches the same fallback. Third wrong scoping claim of
> the day from reading code, and the first one a test caught before it left the machine.

That test was written, used, and then **not shipped**. It is the FAIL-first — it errors on `d5ae0f1`
without the change and returns BF16 with it, in a plain `cargo test -p mistralrs-quant` that needs no
GPU — but shipping it would have gone against the repo rather than with it. Counted, not read: of
mistral.rs's twenty-two most recently merged `fix` pull requests, **two** touch a test file, one a
website JavaScript test and the other a twenty-five-file correctness sweep; the four adjacent
single-purpose fixes, one of them a dtype bug in this same crate, are each one file with no test. The
module the test had landed in is entirely ISQ and UQFF plumbing, so a forward-pass dtype test is an
outlier there even where tests are wanted. `AGENTS.md` does say "add tests", for *new functionality*,
which a fix is not. So the PR is one file, +5/−2, one commit — the shape those twenty had — and the
before-and-after is a sentence in the body instead. FAIL-first is a discipline, not an artifact; the
rule is now in [`docs/upstream-contributions.md`](upstream-contributions.md).

Repo gates, run here: `cargo fmt --all -- --check` clean, `cargo clippy -p mistralrs-quant --tests --
-D warnings` exit 0, `cargo test -p mistralrs-quant` **361 passed, 0 failed**. The server-level repro
in the PR body is attributed to v0.9.3, because a CUDA build of `d5ae0f1` was still compiling kernels
when the PR went up and a figure is worth only the version it was measured on.

That build finished at 20:58, in 36 min 25 s, and the box tree was still clean at `d5ae0f1` — so the
same binary that the PR body could only describe was available to measure, unpatched, at exactly the
commit named. Both halves, one lease each, twenty minutes apart, the mapping identical
(`Layers 0-38: cuda[0]` / `Layers 39-39: cpu`, `DType selected is BF16`, 28 GB resident before the
request):

| build | one `max_tokens=1` completion | `dtype mismatch` lines |
|---|---|---:|
| `d5ae0f1`, unpatched | **http 500** `model_error`, `Model failed with error: moe experts forward` | 2 |
| `d5ae0f1` + the PR's commit `b0f26d5c` applied verbatim | **http 200**, one token back | **0** |

So the before-and-after is now the same commit on both sides rather than a release tag on one, which
is what the PR body's evidence sentence should say. The patch that produced the second row was the
PR commit's own diff piped to the box and `git apply`-ed, not a hand re-edit — the day's attribution
accident was patching a tree mid-compile and then reading the result as unpatched, and applying the
committed diff is what makes that impossible to repeat. The rebuild took 1 min 31 s and recompiled no
CUDA kernels, so the second row is the first row's binary plus five lines.

The runner is [`tools/mrs/mrs-offload-check.sh`](../tools/mrs/mrs-offload-check.sh), and it exists
because `mrs-mech-probe.sh` answers this question only by accident: that probe's readiness loop
demands a *successful completion*, so a server that loads and then fails every request keeps it
asking for fifteen minutes — which is where the 232 errors above came from. The new runner's
readiness is `/health`, which separates "the weights loaded" from "a forward pass works", and the
distinction is the whole bug. It prints the VRAM figure at readiness as the witness that the verdict
is about the forward pass and not about an unloaded model. The box tree is left patched on purpose;
a session that wants upstream behaviour from `/home/user/mistral.rs` must `git -C … checkout --
mistralrs-quant/src/gguf/cpu.rs` first.

Their contribution rules are worth recording, since they are the opposite of ik_llama.cpp's. There is
no `CONTRIBUTING.md`; the conventions live in `AGENTS.md` and a near-duplicate `CLAUDE.md`, both
committed, and there is no disclosure rule for agent-written patches at all — the maintainer merges
`Co-Authored-By: Claude` commits of his own. What the file does demand is a house style that a
default agent violates on sight: comments default to **none**, one line each when they exist, ASCII
only with no em-dashes or `--`, magic values hoisted to named `const`s, no defensive handling for
cases that cannot occur, and no "Test plan" section in a PR description. This patch adds no comment
at all.

## What it means for this box

The own-engine goal points at Rust, and this is the first thing the Rust engine cannot do that the
current serving stack does daily. Two gaps, in order of how much they cost:

1. **No expert-only placement.** Even with the dtype bug fixed, layer-granular offload cannot
   express "experts in RAM, attention on the card", and for a 100 GB-class MoE that recipe is the
   difference between served and not served. This is a feature-sized hole, not a bug.
2. **MoE layers cannot go to the host at all right now.** A bug, small-looking, and the first thing
   this workstation has sent to the repo it may end up forking: PR #2430.

The measurement that started this is in
[2026-09-17-b](2026-09-17-b-where-the-four-stream-gap-actually-is.md); the probe that produced every
line above is [`tools/mrs/mrs-mech-probe.sh`](../tools/mrs/mrs-mech-probe.sh), which is also what
read the CUDA-graph counters there.
