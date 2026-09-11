# DeepSeek-V4-Flash across two GPUs and 256 GB of RAM

**2026-09-11.** 284 B parameters, 155 GB on disk, served at **25–33 tok/s**
on a workstation with 72 GB of VRAM — 29 in the middle, and the spread is
explained below. Routed experts are split by layer across an
A6000, a 3090, and system RAM; the CPU computes the 32 layers that don't fit.

Everything below was measured on the machine in [the README](../README.md) on
this date. Where a number is derived rather than measured, it says so.

## The model

`deepseek-ai/DeepSeek-V4-Flash-0731`, quantized to GGUF by Unsloth
(`UD-Q4_K_XL`, 155.1 GB across 5 shards).

Read out of the GGUF's own tensor table:

| | |
|---|---|
| Parameters | 284.3 B |
| Held in routed experts | 277.0 B — **97%** |
| Layers | 43 |
| Routed experts per layer | 256, of which **6** run per token |
| Shared expert per layer | 1, always runs |
| Active per token | ≈ 13 B (derived from the above) |

That 97% is the entire reason this works. A dense 284 B model at 4.5 bits per
weight would need to move 155 GB per token and nothing about this machine
would help. Here each token touches 6 experts of 256 in each layer, so the
weights that must be read per token are roughly 13 B worth — small enough
that having most of them in DDR4 instead of VRAM is survivable.

## What actually runs

[`ik_llama.cpp`](https://github.com/ikawrakow/ik_llama.cpp) at `3bb386eb`,
built with CUDA for sm_86. The fork matters for one flag: `-ot` assigns
individual tensors to individual devices by regex, so expert placement is not
tied to a uniform layer split and the two mismatched GPUs can hold different
amounts.

```bash
llama-server \
  -m DeepSeek-V4-Flash-0731-UD-Q4_K_XL-00001-of-00005.gguf \
  -c 32768 -ngl 99 -ts 2,1 -mla 3 -t 32 -b 2048 -ub 1024 \
  -ot "blk\.[0-6]\.ffn_.*_exps=CUDA0"   \
  -ot "blk\.1[1-4]\.ffn_.*_exps=CUDA1"  \
  -ot "exps=CPU"                        \
  -md dspark-DeepSeek-V4-Flash-0731-Q8_0.gguf -ngld 99 -cd 8192 \
  --spec-type dspark:n_max=2 \
  --jinja --reasoning-format none
```

Placement, as loaded:

| Device | Holds | Used |
|---|---|---|
| RTX A6000 48 GB | attention + dense tensors, routed experts of layers 0–6, the draft model | 40.1 GB |
| RTX 3090 24 GB | its share of attention + dense tensors, routed experts of layers 11–14 | 17.8 GB |
| 256 GB DDR4 | routed experts of the other 32 layers | ~97 GB resident |

The regexes are evaluated in order and first match wins, so the catch-all
`exps=CPU` must come last. Each layer's 256 experts are one tensor
(`4096 × 2048 × 256`), which is why placement granularity is a whole layer
and not a subset of experts.

## Numbers

Decode is a 400-token completion; prefill is a 2810-token prompt. Both from
the server's own `timings` block, not wall-clock guesses.

| Configuration | Decode | Prefill |
|---|---:|---:|
| FreeToken 0.1.2, `offload` backend | 16.0 tok/s | — |
| FreeToken 0.1.2, `hybrid` backend | 21.0 tok/s | 420 tok/s |
| FreeToken, 4 concurrent requests | 47 tok/s aggregate | — |
| ik_llama.cpp, experts split, no speculation | 24.6 tok/s | 259 tok/s |
| **ik_llama.cpp + DSpark speculation (depth 2)** | **29.1 tok/s** | 227 tok/s |
| same, 1500-token completion | 23.5 tok/s | — |

FreeToken keeps an LRU cache of experts in one GPU's memory and computes
misses on the CPU, which is a genuinely good design — it just cannot use a
second GPU for that cache, and its tensor-parallel mode requires equal VRAM
per rank, which 48 GB and 24 GB are not.

Prefill went *down* when speculation was enabled, and down again versus
FreeToken. Prompt processing is compute-bound and batched; speculation only
helps the token-at-a-time path.

## The finding that mattered

Not expert placement. **Speculation depth.**

| Draft depth (`n_max`) | Decode | Accepted |
|---:|---:|---:|
| 1 | 27.8 tok/s | 80% |
| **2** | **29.1 tok/s** | **68%** |
| 3 | 26.8 tok/s | 53% |
| 5 | 19.2 tok/s | 28% |

DeepSeek ships a 10.9 GB DSpark draft model alongside the main weights. It
proposes the next few tokens and the big model verifies them in one batched
pass. This is worth more here than on a GPU-resident model, because reading
a layer's experts out of DDR4 costs almost the same for two tokens as for
one — the verification is nearly free on the memory side.

Going deeper stops paying because acceptance falls off a cliff: at depth 5,
72% of drafted tokens were thrown away, and the draft model's own time was
not free. Depth 2 is the peak on this hardware.

For contrast, moving *more* experts onto the GPUs barely registered:

| GPU expert layers | Decode |
|---:|---:|
| 14 | 24.2 tok/s |
| 16 | 24.6 tok/s |
| 11 + speculation depth 2 | 29.1 tok/s |
| 16 + speculation depth 3 | 24.5 tok/s |

Eleven expert layers on the GPUs with a draft model beat sixteen without
one. VRAM spent on the draft model outperformed VRAM spent on experts.

## Three things that wasted time

**The draft model failed silently.** With the draft context left at the
default it inherits the target's 32k, and its KV scheduler tried to reserve a
working buffer for 65,531 rows. That allocation failed, the server logged
`failed to initialize DFlash K/V scheduler` on *every* decode step, accepted
zero drafted tokens, and ran at 17.0 tok/s — slower than no speculation at
all, with no indication that the cause was VRAM. `-cd 8192` fixed it. The
error message never mentions memory.

**The engine's own quantization crashes the server.** The ik-specific
`IQ4_KSS` build of this model (149 GB, and by the published KL-divergence
ladder the better file) aborts with all-NaN logits at the first sampled
token under `llama-server`. It generates correctly under `llama-cli` with the
identical device placement, and a CPU-only build is also fine, so the file,
the CUDA kernels, and the `-ot` split are all exonerated. Write-up:
[docs/ik-server-nan-bug.md](../docs/ik-server-nan-bug.md).

**Reasoning went into a field most clients ignore.** With
`--reasoning-format deepseek` the server puts the model's thinking in
`reasoning_content` and leaves `message.content` empty — and this model thinks
at length, so a non-streaming client asking a 400-token question gets an empty
answer and a full `reasoning_content`. Streaming clients are unaffected (that
mode behaves as `none`). Serving with `--reasoning-format none` keeps the
`<think>` block inline in `content`, which every OpenAI-compatible client
renders.

**`--swa-compress` killed long prompts.** KV-cache compression loaded fine
and answered short requests, then crashed on a 2810-token prompt. Left off.

## Run-to-run variance, and what drives it

The 29.1 figure above is one controlled bench. Repeating the measurement with
different prompts gives a spread, and the spread tracks one variable: how many
of the draft model's proposals survive verification.

| Prompt | Draft acceptance | Decode |
|---|---:|---:|
| 19 tokens, ring-buffer implementation | 70% | 33.4 tok/s |
| 19 tokens, same class of question | 70% | 33.0 tok/s |
| 24 tokens, controlled bench | 68% | 29.1 tok/s |
| 19 tokens, recorded take below | 59% | 29.5 tok/s |
| 178 tokens, design review | 61% | 29.4 tok/s |
| 178 tokens, same | 53% | 27.1 tok/s |
| 178 tokens, same | 51% | 26.3 tok/s |
| 19 tokens, unlucky run | 45% | 25.2 tok/s |

So 25–33 tok/s is the honest range, ~29 the middle, and the acceptance rate
explains almost all of it. Predictable, boilerplate-shaped output drafts well;
prose about an unusual subject does not. Anything that quotes a single number
for a speculative-decoding setup is quoting one draw from this distribution.

## The recording

![pi, interactive, against the local model](../assets/pi-local.gif)

Two acts, recorded with [VHS](https://github.com/charmbracelet/vhs) from a
laptop over Tailscale:

1. [`tools/pi-demo.sh`](../tools/pi-demo.sh) launches the
   [pi](https://github.com/badlogic/pi-mono) agent against the workstation and
   asks for a thread-safe LRU cache in Rust. What fills the screen is the
   model's own reasoning, streaming at the rate above.
2. [`tools/tps-demo.sh`](../tools/tps-demo.sh) runs
   [`configs/tps.py`](../configs/tps.py) against the same server: tokens are
   printed as they arrive, and the decode rate at the end is read out of the
   server's `timings` block rather than timed with a stopwatch.

Two things the take had to work around. pi's default system prompt describes
its tool protocol, and the model answered a plain coding question by trying to
list the directory — so the demo script replaces the system prompt and
disables tools. And the measurement act needs a request the model can *finish*
inside the take: asked for a full implementation with a 1600-token budget, it
spent every token on reasoning and the rate never printed.

## Thermals, since this thing is loud about it

Measured during a 1500-token generation, boost disabled and pump at 100%:

| | |
|---|---|
| CPU package (Tctl) | 81 °C, still climbing slowly (limit 95 °C) |
| All-core clock | 3.05 GHz |
| Coolant | 39 °C → 43.5 °C over 60 seconds |
| A6000 / 3090 | 66 °C / 47 °C |

Short prefill bursts touched 91 °C. That is inside spec but leaves less
margin than it looks, because the coolant temperature had not plateaued yet.

Fan control is not available from Linux on this board: loading `nct6775`
exposes an nct6798 with seven fan channels and seven PWM outputs, and all
seven read 0 RPM, because the headers are wired to ASUS's own controller.
The fan curve has to be set in firmware.

So the watchdog in [`configs/thermal-guard.sh`](../configs/thermal-guard.sh)
watches for a real cooling failure — pump RPM below 500, coolant above 52 °C,
CPU above 93 °C, GPU above 90 °C — and only after 30 consecutive seconds. It
stops the inference load and leaves the machine up, which is the behaviour
you want when the box is in another building. An earlier version tripped at
90 °C after 15 seconds and would have killed normal work.

## What is next

- DeepSeek **V4.1 Flash** shipped the day before this entry with a new
  architecture (`DeepseekV41ForCausalLM`). No engine loads it yet:
  llama.cpp has an open conversion PR, ik_llama.cpp has nothing, FreeToken
  does not list it. At 510 GB original it would need a 2-bit quantization to
  fit here anyway.
- A third card, purely as expert storage. Every 3.5 GB of VRAM takes one more
  layer off the CPU. The interesting question is whether a cheap 32 GB card
  with poor compute is worth more than an expensive 24 GB one with good
  compute, given that these tensors are read far more than they are
  multiplied.
- Concurrency. Four parallel requests on FreeToken gave 47 tok/s aggregate
  against 21 single-stream. The same measurement on this stack is not done.
