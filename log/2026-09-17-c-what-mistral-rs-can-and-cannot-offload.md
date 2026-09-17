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
| `-n 0:39` | `Layers 0-38: cuda[0]` / `Layers 39-39: cpu` | **fails**, 58 dtype errors — **one MoE layer on the host is enough** |
| `-n 0:8`, dense Qwen2.5-7B Q3_K_M | `Layers 0-7: cuda[0]` / `Layers 8-27: cpu` | **works**, 17.4 tok/s against ~120 fully resident — partial offload does what it should |

So: the trigger is a MoE layer placed on the CPU, the count does not matter, and partial offload is
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

Both are separate limitations worth knowing about — a GGUF that llama.cpp-family engines load
happily is not necessarily a GGUF mistral.rs will take — and neither can serve as the second data
point for the offload bug. The report therefore says "reproduced on one MoE GGUF, with a dense
control that works and a whole-GPU control that works", which is what was measured.

Duplicate search, three queries on `EricLBuehler/mistral.rs`: `"dtype mismatch in matmul"` (one hit,
[#2072](https://github.com/EricLBuehler/mistral.rs/issues/2072), FP8 *loading*, a different path),
`moe experts forward dtype mismatch` and `device-layers cpu offload gguf moe` — no match. **Not
filed**; the reproducer and the controls are here, the decision is the user's.

## What it means for this box

The own-engine goal points at Rust, and this is the first thing the Rust engine cannot do that the
current serving stack does daily. Two gaps, in order of how much they cost:

1. **No expert-only placement.** Even with the dtype bug fixed, layer-granular offload cannot
   express "experts in RAM, attention on the card", and for a 100 GB-class MoE that recipe is the
   difference between served and not served. This is a feature-sized hole, not a bug.
2. **MoE layers cannot go to the host at all right now.** A bug, small-looking, and the kind of
   thing a first contribution to a repo is made of.

The measurement that started this is in
[2026-09-17-b](2026-09-17-b-where-the-four-stream-gap-actually-is.md); the probe that produced every
line above is [`tools/mrs/mrs-mech-probe.sh`](../tools/mrs/mrs-mech-probe.sh), which is also what
read the CUDA-graph counters there.
