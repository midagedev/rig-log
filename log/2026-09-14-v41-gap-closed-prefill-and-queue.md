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
| WKS-11 | engram quantization and quality: draft acceptance Q3_K against Q8_0 tables, then the intermediate-precision knee, then long-form quality | first question answered below: acceptance does not move with the table precision |
| WKS-12 | prefill for a coding profile: `-ub`, host-op offload, prompt cache | third window below: five expert layers at `-ub 2048` prefill the 11k prompt at 136 tok/s without the crash |
| WKS-13 | precision on the GPU-resident tensors: attention and shared experts at Q8_0 by graft | grafted and measured below: 2.1190 → 1.8992, the largest quality move on this file so far |
| WKS-14 | ik against mainline with the draft, same split, after the prefetch | done below: 24.88 against 24.22 |
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

*08:34–08:42, the mainline arm.* Same six-layer split, same draft, same
block (`--spec-type draft-dspark --spec-draft-n-max 3`), same twenty prompts,
two passes, IO pressure 0.02 at launch and 0.00 on the measured rows.

| six-layer split, block 3 | pass 1 | pass 2 | drafted / accepted | faults, pass 1 |
|---|---:|---:|---|---:|
| ik fork 57735010 | 23.96 | **24.88** | 3321 / 1996 (60.1 %) | 48 597 |
| mainline V4.1 branch | 22.63 | 24.22 | 3430 / 2027 (59.1 %) | 88 064 |

So the pair at the same placement is 24.88 against 24.22, ik ahead by
under 3 percent, which is inside the run-to-run band on this prompt set;
yesterday's table had ik behind by 20 percent on the same two engines, and
the whole of that was the page faults the prefetch removed. Three of the
twenty greedy outputs are byte-identical across the two engines, which is
about what two different kernels at Q3_K produce. Mainline on its
eight-layer placement (25.6 yesterday) stays the served configuration: the
extra layer is worth about what the engine difference is, and mainline is
what upstream maintains. The ik fork's value is now the port itself and
the prefetch, not a speed lead.


## WKS-11, first question: does the engram table precision move acceptance?

*08:04–08:20. Mainline V4.1 branch, DSpark block 3 with the tl37 draft,
the eight-layer served placement, the same twenty prompts and two passes.
Two target files that differ only in the engram tables: the uploader's
Q3_K_M (tables Q3_K) and the repack (tables Q8_0, token embedding BF16).
IO pressure 0.00 on every measured row after load.*

| target engram tables | pass | median tok/s | min–max | drafted / accepted |
|---|---|---:|---|---|
| Q3_K | 1 | 20.48 | 13.67–28.31 | 3486 / 2022 (58.0 %) |
| Q3_K | 2 | 23.63 | 14.58–30.50 | 3486 / 2022 (58.0 %) |
| Q8_0 | 1 | 20.36 | 11.65–25.68 | 3405 / 2007 (58.9 %) |
| Q8_0 | 2 | **23.75** | 14.54–29.35 | 3405 / 2007 (58.9 %) |

Acceptance is 58.0 against 58.9 percent, and decode is 23.63 against 23.75,
which is the same number twice. The hypothesis was that Q3_K tables put
enough noise into the engram path that the draft, trained against the real
model, would agree with the target less often; it does not — the draft
agrees with both targets equally, and the extra 0.9 points is inside what
one prompt order gives. The texts do differ: only 1 of the 20 greedy
outputs is byte-identical between the two files, which matches yesterday's
finding that the table precision changes 22 percent of the text without
moving the accuracy probe. So the engram repack is justified by perplexity
(2.2438 → 2.1090 yesterday), not by speed, and the drafted pipeline is
indifferent to it. The intermediate-precision knee (Q4_K, Q5_K, Q6_K
tables) is the remaining WKS-11 question and is worth asking only for the
disk and perplexity trade, not for tok/s.

## WKS-13: the perplexity baseline of the served file

*08:20–08:33. `llama-perplexity` from the mainline V4.1 build, the served
file (engram Q8_0, token embedding BF16), wiki.test.raw, context 2048,
batch 2048, four chunks, CPU only, 32 threads.*

```
[1]1.7335,[2]1.6745,[3]1.6964,[4]2.1190
Final estimate: PPL = 2.1190 +/- 0.05906
```

Yesterday's four-chunk figure for the same repack was 2.1090 ± 0.0585; today's
2.1190 ± 0.0591 is a 0.01 shift well inside one standard error, from a build
that has moved since. The graft in WKS-13 (attention and shared experts to
Q8_0) will be measured with exactly this command, and this is the number it
has to beat by more than the error bar to be worth its 5 GB of VRAM.

## WKS-12, third window: fewer expert layers on the cards, bigger micro-batch

*08:57–09:15. Mainline V4.1 build, served file, no draft, `-c 16384`,
`-b` = `-ub`. Placements: five expert layers (blk 0–3 on the 48 GB card,
blk 4 on the 24 GB card) and four (blk 0–3 on the 48 GB card, the 24 GB
card holding attention only). Prompts 4.8k and 11k tokens from
`llama-context.cpp`, two passes each, then one greedy 200-token completion
for the decode side of the trade. IO pressure on every row; PCIe gen4 x16
on both cards during every prefill.*

| placement, `-ub` | 4.8k pass 1 → 2 | 11k pass 1 → 2 | decode, no draft |
|---|---|---|---|
| 5 layers, 2048 | 69.0 → 125.5 | 129.8 → **136.2** | 18.4 (18 tokens, early stop) |
| 4 layers, 2048 | 52.4 → 123.1 | 121.9 → 133.1 | 17.5 (81 tokens) |
| 4 layers, 4096 | aborted on the first request | — | — |

Yesterday the six-layer placement at `-ub 2048` reached 127.8 on the short
prompt and aborted on the 11k prompt with the cuBLAS pool out of memory on
the 24 GB card. Taking one expert layer off that card is enough: five layers
at `-ub 2048` finish the 11k prompt at 136 tok/s, 2.3× the served profile's
59.5, and the fourth layer buys nothing more (133). The prefill number is
the same for both placements because the transfer-bound part — the CPU
experts pulled over PCIe for every batch — is the same; the layers on the
cards are only the ones not transferred. The pass-1 figures on the short
prompt are first-touch faults again (69 and 52 against 125 and 123).

Decode without the draft came out at 18.4 and 17.5 against about 19.8 for
the six-layer placement measured this morning, which is the expected cost:
each expert layer moved off the cards is about 3 % more bytes a token. The
two decode rows here are single completions, one of them only 18 tokens
long before the model stopped, so they bound the cost rather than measure
it; the drafted decode for a coding profile would be measured in its own
window.

`-ub 4096` on the four-layer placement aborted in the same place as
yesterday's `-ub 2048` at six layers — `ggml_cuda_pool_vmm::alloc` under
`ggml_cuda_mul_mat_cublas`, out of memory — but this time on the 48 GB card,
at the first request, with the 24 GB card nearly empty. The pool the cuBLAS
path grows for the dequantized operands scales with the micro-batch, and
the server neither bounds it nor recovers from the failure: the process
aborts and takes every slot with it. That is the robustness candidate
noted yesterday, now reproduced at a different size on a different device,
which makes it a report rather than a configuration mistake. The user
writes anything mainline-facing; the fact sheet is these two crashes.

So the coding profile is now concrete: five expert layers, `-ub 2048`,
`-c 16384`, the draft kept, prompt cache on. What it costs the decode
profile is roughly one expert layer of tok/s, and what it buys is 11k
tokens of prompt in 82 s instead of 185. Whether to run two profiles or
one is a question of how often the box is asked long prompts, which the
server logs answer over a week.

## WKS-13: attention and shared experts at Q8_0, grafted

*09:16–09:41. The graft (`tools/attn-q8-graft/graft-attn-q8.py`) rebuilt
shards 1 and 3–9 of the served set with 328 tensors taken raw from shard
10 of the uploader's Q8_0 build: the five attention projections, the three
shared-expert projections and the indexer query projection of all forty
layers. 2.19 GB became 6.93 GB. Shard 2 is a hard link; the write took
eleven minutes at idle IO priority while the box kept serving. Then the
same perplexity command as the baseline, 8001 down.*

| file | chunk 1 | 2 | 3 | 4 | final |
|---|---|---|---|---|---|
| served (attention mostly Q2_K, shexp Q3_K) | 1.7335 | 1.6745 | 1.6964 | 2.1190 | 2.1190 ± 0.0591 |
| grafted (attention, shexp, indexer Q8_0) | 1.5949 | 1.4946 | 1.4904 | 1.8992 | **1.8992 ± 0.0491** |

A 10.4 % drop in perplexity, four times the error bar, every chunk in the
same direction. For comparison the engram repack yesterday was 6 % on the
same four chunks. The reason is in the inventory the graft printed: the
Q3_K_M upload's attention was not Q3_K, as the plan assumed from its
label, but **Q2_K on 288 of the 328 projections**. The most
quantization-sensitive group in the model was the lowest-precision group
in the file, and it costs nothing on the CPU side to fix — those tensors
live on the cards.

What it costs is VRAM, and the served eight-layer placement does not have
it: the grafted file failed to load with the 48 GB card short by a 7.6 GB
compute-buffer allocation. So the price of the 10 % is one expert layer
off the cards, about 3 % of decode, or the `-ub` headroom. Which one, and
the drafted decode number on the grafted file, is the next window; the
perplexity result stands on its own.
