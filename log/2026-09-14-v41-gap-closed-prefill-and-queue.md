# 2026-09-14: the ik gap was page faults, prefill on the served profile, and a queue with labels

*The entries before 07:45 today were appended to
[yesterday's file](2026-09-13-deepseek-v41-on-ik-llama.md) as they happened
("The deciding experiment for the ik gap, run", "Prefill, first window",
"Prefill, second window"); this file starts the day's own record and carries
the rest. Same machine, same files as yesterday unless a row says otherwise.
Every measurement here ran with the production server stopped and the
window's IO pressure recorded per row.*

## Where the morning ended up

Two things were settled before this file was opened, and both change what
the rest of the day is for.

**The ik gap was never in the GPU path.** The 20 % that yesterday's entry
attributed to ik_llama.cpp's decode was a first-pass number on both engines.
Warm, at the same six-layer split and without a draft, ik decodes 18.8 tok/s
and mainline 19.8. Cold, ik lost 28 % to 41–62 major page faults a token on
the memory-mapped engram rows; mainline lost 6 % because the V4.1 branch
prefetches those rows (86d01ece1). The same prefetch ported to ik in
twenty-three lines (fork commit 57735010) took ik's first pass from 13.6 to
18.4, inside the load-to-load band of mainline's 18.6. The whole reading is
in [`docs/ik-vs-mainline-v41-gap.md`](../docs/ik-vs-mainline-v41-gap.md);
the CUDA-graph latch it started from was measured as not a lever (graphs on
or off within 1 %).

**The served profile cannot prefill for coding.** A 4823-token source prompt
prefills at 59.5 tok/s warm and a 11186-token one at 60.2 on the production
configuration (`-ub 512`, eight expert layers on the cards). The table and
the reading — offload off caps the CPU path near 70 tok/s at any micro-batch;
offload on is a transfer-bound path that only pays at `-ub 2048` (127.8 on
4.8k) and then runs the 24 GB card out of cuBLAS pool on the 11k prompt — are
in yesterday's file. What makes the served profile usable for a coding
client today is the prompt cache: after an 11k prefix has been processed
once, a request with 260 tokens appended evaluates 775 tokens, 15 s against
185 s cold.

## Upstream, this morning

- ik_llama.cpp [#2444](https://github.com/ikawrakow/ik_llama.cpp/pull/2444),
  `GGML_CUDA_NO_PINNED_WEIGHTS`, +5/−1 off upstream main. Open.
- ik_llama.cpp [#2438](https://github.com/ikawrakow/ik_llama.cpp/issues/2438#issuecomment-5656281274):
  the V4.1 port branch offered as a reference, verified and unverified scope
  listed, the maintainer asked whether to split it into PRs or leave it. The
  V4 port went in as his own work after an external +3689-line PR was closed
  (#2110 → #2165), and small external PRs merge same-day (#2404, +90), so the
  branch is offered, not pushed.
- The `reasoning_budget` per-request question from the recorder session
  (WKS-15) was not a server defect: the field is `reasoning_budget_tokens`
  (alias `thinking_budget_tokens`, `tools/server/server-common.cpp:1388`)
  and the bare name is silently ignored. Measured on the served port: the
  wrong name left reasoning at 387 characters, the right one cut it at 294
  (about 64 tokens). Closed as a client-side rename; the server README does
  not list the field, which is a documentation gap and no more.

## The recording window

At 06:55 the machine was handed to the recorder session for the toktape
hero clip: production configuration (eight expert layers, DSpark block 3),
reasoning on with a 64-token budget after a 300-token probe showed 264
tokens of thinking on a 400-token answer, five warm-up prompts, coolant
cooled to 40–41 °C, clock capped at 3.6 GHz with the 50 °C watchdog, and a
45-minute hold that ended on a file touch at 07:07. Nothing else ran on the
box. The take kept is two streams at 240 tokens: 26.9 tok/s aggregate, TTFT
1.21 s, 71 % draft acceptance, 5.8 major faults a token. A four-stream take
at 360 tokens (27.3 aggregate) was recorded and set aside because its TTFT
(p50 5.45 s, p95 8.65 s) is queueing on the prefill path measured above and
would leave the first ten seconds of an autoplaying GIF on a spinner. The
recorder's conditions line fired for the first time on real hardware — CPU
Tctl 69 → 84 °C during the take, clock cap unchanged — and the clip carries
"toktape · github.com/midagedev/toktape" in its last frame, which is the
credit rule in `CLAUDE.md`. Recorded with [toktape](https://github.com/midagedev/toktape).

## The queue, and the label

Experiments now go to the WKS board with the label `experiment`, one issue
each with the measured state and what would settle it; the same list is
`docs/v41-experiment-plan.md`, "The queue as of 2026-09-14 morning".

| issue | experiment | state at 07:50 |
|---|---|---|
| WKS-11 | engram quantization and quality: draft acceptance Q3_K against Q8_0 tables, then the intermediate-precision knee, then long-form quality | acceptance window queued behind WKS-14 |
| WKS-12 | prefill for a coding profile: `-ub`, host-op offload, prompt cache | two windows run; next is a placement with fewer expert layers on the 24 GB card at `-ub 2048` and 4096 |
| WKS-13 | precision on the GPU-resident tensors: attention and shared experts at Q8_0 by graft | perplexity baseline of the served file queued at the end of the WKS-11 window |
| WKS-14 | ik against mainline with the draft, same split, after the prefetch | running since 07:46 |
| WKS-15 | per-request reasoning budget | done: wrong field name |

Results land below as the windows return.

## WKS-14: ik with the draft, after the prefetch

*07:46–08:00. ik fork 57735010, DSpark block 3 (`--spec-type dspark:n_max=3`),
the six-layer split, the served target file (engram Q8_0, bf16 token
embedding), the same twenty greedy 200-token prompts as yesterday's table,
two passes, IO pressure 0.00 on every row after load.*

| ik, block 3 | median tok/s | min–max | drafted / accepted | major faults |
|---|---:|---|---|---:|
| pass 1 | 23.96 | 15.66–30.47 | 3321 / 1996 (60.1 %) | 48 597 (≈12 a token) |
| pass 2 | **24.88** | 16.10–31.04 | 3321 / 1996 (60.1 %) | 0 |

Yesterday's ik number with the same draft and block was 19.86, first pass,
before the prefetch. Acceptance is identical to the count (1996 of 3321),
which it should be: the prefetch changes when a row is read, not what it
holds. The first pass is now 4 % under the second rather than 28 % under.
Against mainline's 25.6 on the eight-layer placement, ik at 24.9 on six
layers is inside the band that separates those two placements; the mainline
arm at the same six-layer split is what makes the pair, and its first launch
died on a port-bind race a second after the ik server released 8099 — it is
queued again behind the engram window with a pause before the bind.
