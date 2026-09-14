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

*09:43–10:05, the decode window.* Both files at the seven-layer placement
(blk 7 back on the CPU), mainline, DSpark block 3, `-ub 512` as served,
the twenty prompts, two passes.

| seven layers, block 3 | pass 1 | pass 2 | drafted / accepted | VRAM used |
|---|---:|---:|---|---|
| grafted (attention, shexp, indexer Q8_0) | 21.76 | **25.22** | 3533 / 2168 (61.4 %) | 46.0 + 21.9 GB |
| served file, same placement | 21.32 | 23.00 | 3366 / 1998 (59.4 %) | 43.3 + 20.7 GB |

The graft is not slower; it is faster, by 10 percent at the same placement,
and at 25.2 it matches the served eight-layer configuration's 25.6 within
the band. Two things add up to that. The attention projections run on the
cards every token, and the Q8_0 matmul path is a cheaper kernel than the
Q2_K dequantize-and-multiply it replaces — the sensitive group was also the
slow group. And the draft agrees with the better target two points more
often (61.4 against 59.4 percent), which is the same direction WKS-11 saw
from the engram tables, now with a larger precision step. One of twenty
outputs is byte-identical between the files, as expected for a 10 percent
perplexity change.

So the expert layer the graft costs in VRAM is paid back by the kernel and
the acceptance, and the served profile can move to the grafted file at
seven layers with perplexity 1.90 instead of 2.12 and the same tok/s.

## WKS-18, stage 1: the on-card experts at their native MXFP4 do not move perplexity

*10:20–10:39.* The uploader's "Q8_0" set keeps the routed experts at
MXFP4 in its first seven shards — the precision the model was released
at — and every other quant of that set requantizes them below it. Stage 1
of WKS-18 asked how much of the remaining perplexity is in that
requantization, using only the eight layers that sit on the cards: shards
1–2 (87 GB) fetched under the download guards, the 24 expert tensors of
blk 0–7 grafted into a copy of the attention-Q8_0 file. The served
precision was Q3_K for gate and up and Q4_K for down (Q5_K on blk 0–1);
MXFP4 is 2.41 GB a tensor, so the eight layers grow by 5.1 GB, all of it
VRAM, none of it CPU-side bytes. The graft took three and a half minutes;
the shards with nothing to swap are hard links.

| file | perplexity | chunks |
|---|---:|---|
| attention Q8_0 (WKS-13) | 1.8992 ± 0.0491 | 1.5949 / 1.4946 / 1.4904 / 1.8992 |
| + blk 0–7 experts MXFP4 | 1.8964 ± 0.0491 | 1.5919 / 1.4841 / 1.4863 / 1.8964 |

A 0.15 percent drop, one twentieth of the error bar. All four chunks are
slightly lower, so the direction is consistent; the size is noise. And
the decode arm never ran: the seven-layer placement fails to load, the
24 GB card short by 515 MiB once blk 4–6 gained 2.3 GB. Getting the file
to serve would cost a sixth expert layer, about 3 percent of decode, for
nothing measurable.

That settles stage 2 for now. Eight of forty layers is a fifth of the
expert bytes and moved perplexity under 0.2 percent; the full graft
extrapolates to under one percent, for 11.6 percent more bytes a token
on every decode. The perplexity was in the Q2_K attention — WKS-13's 10
percent — not in the experts' fp4-to-Q3_K step. The 289 GB download is
parked, and the stage-1 file stays on disk (94 GB, mostly links) in case
the MXFP4 CPU kernel's speed per byte becomes the question.

*The serving switch.* With WKS-18 out, the choice is the WKS-13 file at
seven layers: perplexity 1.90 instead of 2.12, drafted decode 25.2
against the served 25.6, one expert layer of VRAM freed. The serve script
moves to that file and the seven-layer placement; 8001 comes back on it
when the context-length windows finish, and the rate is confirmed then.

## WKS-12, the context windows: the ceiling is not the KV cache

*10:39–11:06.* Two chained windows on the attention-Q8_0 file asked how
much context the served VRAM leaves. The answer came out of the loader,
not the benchmark: only the seven-layer, 16k arm loaded at all. Every
other arm died in `graph_reserve` with "failed to allocate compute pp
buffers", and the size of the allocation it wanted is the finding.

| arm | `-ub` | `-c` | failed allocation |
|---|---:|---:|---:|
| seven layers | 512 | 64k | 9.1 GB (device 1) |
| seven layers | 512 | 128k | 19.0 GB |
| five layers | 2048 | 64k | 35.8 GB |
| five layers | 2048 | 128k | 68.8 GB |
| four layers | 2048 | 256k | 135.0 GB |
| four layers, KV q8_0 | 2048 | 256k | 134.9 GB |
| no expert layers | 2048 | 512k | 269.1 GB |
| no expert layers, KV q8_0 | 2048 | 512k | 267.8 GB |

The number doubles with the context and quadruples with the micro-batch,
and quantizing the KV cache moves it by a tenth of a percent. The KV
cache itself is small — 2.5 GB on the 48 GB card at 128k, about 20 KB a
token, so 256k is 5 GB and 512k is 10 GB, and the estimate earlier today
of 46 KB a token was twice too high. What does not fit is the attention
scores matrix: context × micro-batch × heads × four bytes is 17.2 GB at
128k and 512, which is the 19 GB the loader asked for. That matrix only
exists when attention runs without a fused kernel, and the serve log
prints no flash-attention line for this architecture.

So the context question becomes a flash-attention question. If `-fa on`
takes on the V4.1 path, a 256k coding profile is 5 GB of KV plus the
micro-batch-scaled compute buffer and fits with four expert layers; if
the kernel is refused for this attention shape, the ceiling stays near
16k–32k at `-ub 512` and that is a finding for upstream. The one-arm
test is next, after the pause the user asked for.

*11:06, the serving switch.* 8001 came back on the attention-Q8_0 file at
seven expert layers with 46.0 + 21.9 GB of VRAM in use. The first
request after load ran cold at 14.8 tok/s over 300 tokens, the same
page-fault pass every fresh load shows; the warm number is the user's
toktape session.

## The hero take on the new serving file, and what page faults measure

*11:38–11:53.* The toktape session recorded its v0.2.0 demo clip on 8001,
recorded with [toktape](https://github.com/midagedev/toktape), after the
serving switch: the attention-Q8_0 file at seven expert layers, DSpark
block 3, `--reasoning-budget 64` for the take only, five 500-token warm-up
runs (14.5, 17.8, 19.0, 18.8, 22.5 tok/s), coolant down to 40 °C, then
the recording-only 3.6 GHz cap.

| take, two streams, 30 s | value |
|---|---|
| decode | 22.5 tok/s aggregate, 11.2 a stream |
| prefill | 51.8 tok/s aggregate at 279 prompt tokens a stream, TTFT 10.75 s |
| draft | n_max 3, 52 % accepted, 4.0 tokens a verify step |
| major faults | 4.4 a token during decode |
| host bytes | 394.1 GiB placed (200.8 RAM / 193.3 disk), RSS 202.2 GiB |
| bandwidth (toktape, derived) | ≈ 115 GB/s off host RAM per verify step, 99.0 % of the 115.8 GB/s measured bus |
| Tctl | 66 → 78 °C, cap held, IO pressure 0.00 |

The clip is the toktape v0.2.0 demo, [on Drive](https://drive.google.com/file/d/1DcyQCgp0_Uo9B8lRyMvI3ZjpPOg-Xug4/view?usp=drivesdk),
released with [toktape v0.2.0](https://github.com/midagedev/toktape/releases/tag/v0.2.0).
The bandwidth line is the recorder's derivation — bytes of RAM-resident
expert weight read per verify step against the wall time — and it says
what this whole log has been circling: at this placement decode sits on
the host memory bus, and an `-ot` change that does not move that figure
did not move the bottleneck.

Against the 07:04 take on the old file at eight layers (26.9 aggregate,
TTFT 1.21 s at a 30-token prompt) this is lower on decode, and the reason
is not the file: the single-stream pair this morning had the grafted file
faster at the same placement. The difference is warmth. The 11:45 probe
right after warm-up ran at 19.4 tok/s with 36.9 major faults a token on
fresh text, and the take on the same text after one more pass ran at 4.4.

Those two numbers correct a claim made earlier in the day. The prediction
was that warm-up would bring faults to single digits regardless of the
prompt, because the experts are what page in; it did not, and the fault
count that remained is the engram tables. Every token reads 48 rows from
the two lazy-mode tables on the NVMe, each row its own page, so fresh text
sits at a floor of 30–48 faults a token and only repeated text — the same
rows already cached — drops under it. WKS-14's zero faults on the second
pass were that effect, not expert warmth. Two consequences: faults a token
is not a cold-expert witness on fresh text, and the engram row reads may
cost a measurable share of a token — 37 random 4 KB reads at NVMe latency
is one to four milliseconds against a 40 ms token if they are issued
serially, a tenth of that if the threads fault in parallel. Which it is,
and what pinning the tables in RAM or prefetching them would buy, is
WKS-20. Splitting the tables across drives would not help: the need is
about 1 200 IOPS against a drive good for hundreds of thousands, and the
latency per read does not fall with more drives. Separating the engram
from the expert weights' drive would only matter while experts are
paging in and queueing ahead of the row reads.

8001 went back to the standard script — same file and placement, no
reasoning budget — at 11:56.

## The context ceiling, found: the indexer scores every token against every position

*12:01–12:09.* The flash-attention hypothesis from the previous window
lasted eight minutes. All three arms — seven layers at 64k, four layers at
256k with the KV cache at q8_0, the same at f16 — logged `flash_attn =
enabled` and then died on exactly the allocation they died on without it:
9.1 GB at 64k and `-ub 512`, 135 GB at 256k and `-ub 2048`. Whatever
scales with context times micro-batch, flash attention does not touch it.

The source does. In this build's V4.1 graph the sparse-attention indexer
scores each query token against every compressed position with a plain
matrix multiply, producing a `[positions, tokens, 32 indexer heads]`
tensor in fp32, and then copies it once more to permute it. On the layers
whose compression ratio is one, positions equals the context. At 256k and
a 2048 micro-batch that is 68.7 GB, twice, which is the 135 GB the loader
asked for; at 64k and 512 it is 4.3 GB twice, which is the 9.1 GB. The
arithmetic matches both failures to within the other buffers, and the KV
cache, at about 20 KB a token, is a footnote.

So the context ceiling on this machine is a graph shape, not a memory
budget: the indexer materializes its scores for the whole micro-batch
against the whole context. Three ways out, in order of value. The V3.2
path in the same tree has a fused indexer op that never materializes the
scores — whether it fits V4.1's compressed keys and has a CUDA kernel is
the next read. Failing that, the scoring can be chunked over positions or
tokens in the graph. Failing both, `-ub` shrinks for long contexts: at
256k, a micro-batch of 128 brings the buffer to 8.6 GB and 64 to 4.3, and
prefill pays for it. The prompt-cache measurement is still owed; no arm
that could carry it loaded.

## The thermal guard ended two windows, and its limit moved

*12:18 and 12:27.* The coolant limit in the thermal guard was 52 °C, set
when sustained load measured 43–45. This afternoon two single-stream
decode windows at the 2.7 GHz cap crossed 52 after about six minutes each
— the WKS-20 second pass and the fused-indexer identity pass — and the
guard did what it is for: stopped the server, and the run with it. Both
are re-queued behind a coolant gate in the runner (wait for 45 °C before
each pass). The user raised the limit to 59 °C at 12:32; the pump's rating
is well above that, and 52 was a number chosen with headroom on a cooler
day. The change is in `configs/thermal-guard.sh`.

## 256k loads, and the prompt cache works with a fixed tax

*12:21–12:40.* The fused-indexer build (the V4.1 branch at 75a0eb4f1: the
indexer scored through `ggml_lightning_indexer` under `fused_lid`, as the
V4 and V3.2 graphs in the same tree already did) went through the arms
that had all died before it.

| arm | before (unfused) | after (fused) |
|---|---|---|
| seven layers, 16k, `-ub 512` | loads; compute 4297 + 2447 MiB | loads; compute 4297 + **399** MiB; VRAM 45.8 + 20.0 GB |
| seven layers, 64k, `-ub 512` | 9.1 GB asked on the 24 GB card, dies | loads; compute 5014 + 911 MiB |
| four layers, 256k, `-ub 2048`, KV q8_0 | 135 GB asked, dies | **loads**; compute 6252 + 6102 MiB; VRAM 45.3 + 12.2 GB |

The KV cache at 256k and q8_0 is 2.7 GB on the 48 GB card — about 10.7 KB
a token — and the 24 GB card ends the load with 12 GB free, which is room
for a fifth expert layer at 256k. Decode on the fused build ran the twenty
prompts at a 22.64 median on the first pass, the same band as the unfused
build's first pass this morning; the byte-identity check against the
unfused outputs is queued again behind a coolant gate, because the guard
took the second pass.

The prompt cache, measured on the 256k server with wiki text. The base
prompt of 14 101 tokens took 220 s cold (64 tok/s, the experts paging
in); every request after it ran at 111–125 tok/s.

| request | new tokens | `prompt_n` | wall |
|---|---:|---:|---:|
| base | 14 101 | 14 101 | 222 s |
| base again | 0 | **2 048** | 18.5 s |
| base + 8k chars | ~1 985 | 4 033 | 35.8 s |
| base + 16k chars | ~1 782 | 3 830 | 33.8 s |
| other text | 13 005 | 13 005 | 118 s |
| base + 16k again | 0 | **2 048** | 18.3 s |

Two things are true at once. The cache works, and it survives a session
switch: after 13 000 tokens of unrelated text, the first conversation
came back at the price of 2 048 tokens, not 17 883 — the evicted state
was kept in host memory and restored. And every hit pays exactly 2 048
tokens, which is `-b`, whether the prefix matched in full or not. ~~That
looks like a restore granularity in the V4.1 cache — the compressed
state is snapshotted at batch boundaries, and a match rounds down to the
last one — rather than a cache miss.~~ Corrected an hour later from the
server log: the mechanism is the server's own SWA context checkpoints.
The model has a 128-token sliding window, so a partial reuse has to
restore a checkpoint taken at least 128 tokens before the divergence
point, and the server takes checkpoints at batch ends — "checking
checkpoint with [14096] against 13972 … restored context checkpoint
(pos_min = 12052)". The tax is the distance back to that checkpoint, up
to one `-b`. The next window tries `--swa-full`, which would make the
reuse exact at the cost of full-context KV on the window layers, and
`-b 512`, which caps the tax at 512 but halves prefill. `--cache-reuse` is
a no-op here: the V4.1 cache refuses partial removals, and the server
says so at load. For a coding session the shape is right either way: a
growing transcript costs its new tokens plus a fixed 17 s, and the 256k
first fill of half an hour happens once.

So the coding profile has a candidate: the attention-Q8_0 file, five
expert layers, `-ub 2048`, `-c 262144`, KV q8_0, the fused indexer, cache
on. The decode profile keeps seven layers and can take 64k for free.

## WKS-20: what the engram rows cost on fresh text

*12:45–13:04.* The clean version of the morning's question, with a
coolant gate before each pass so the guard would not end it: the fused
build at the served placement, experts warmed on five other prompts, then
the twenty prompts three times.

| pass | median tok/s | major faults a token |
|---|---:|---:|
| 1 — engram rows cold for this text | 23.36 | 22.1 |
| 2 — rows cached | 25.07 | 0 |
| 3 | 25.08 | 0 |

Acceptance was identical across passes, as greedy decoding on the same
tokens should be, so the whole difference is the rows: **6.8 percent of
decode** goes to about 22 random 4 KB reads a token from the NVMe, which
is 2.9 ms a token or 130 µs a read — the drive's latency, taken one read
at a time. This is with the row prefetch already in the branch; it is the
part prefetch does not hide. Pinning the two tables in RAM would recover
most of it, at 84 GB of the 251 that the expert weights also want, so
that trade is a measurement of its own. Splitting the tables across
drives would not: 22 reads a token at 25 tok/s is 550 IOPS, and the
latency of each is what costs, not the count.

The same window answers a question about the fused indexer for free: its
warm decode, 25.07, is the unfused build's 25.22 from this morning within
the band. The fused op is not a decode cost.

*13:04–13:13, the identity check.* Twenty greedy 200-token prompts on the
fused build at the served placement, two passes behind the coolant gate:
22.61 cold, 25.16 with the engram rows cached, and **all twenty outputs
byte-identical** to the unfused build's from this morning, and to each
other across passes. The fused lightning indexer is exact on V4.1, free at
decode, and the reason 64k and 256k load. 8001 has been on that build
since 12:45.

## WKS-22: where the host bandwidth wall actually is

*13:36–14:21, 8001 down for the whole window, coolant gate 50 °C.* The
question was why decode pulls 115.8 GB/s from eight populated channels of
DDR4-3200 whose peak is 204.8. Three probes answer it, and the answer is in
the CPU package, not in the software.

First, a plain read probe (`tools/membw/bw.c`: each thread streams its own
slice with 256-bit loads, 16 GiB, best of five) swept threads and clock caps:

| threads | 2.7 GHz | 3.6 GHz |
|---|---|---|
| 4 | 85.9 | 90.5 |
| 8 | 121.7 | 121.9 |
| 16 | 128.6 | 128.8 |
| 32 | 131.3 | 132.0 |
| 64 | 132.3 | 133.1 |
| 32, no thread binding | 131.3 | 132.2 |
| 32, `numactl --interleave=all` | 132.1 | 132.3 |

The read cap is about 132 GB/s. Eight threads already reach 92 % of it, and
clock, binding and interleave move it by less than 1 % (one NUMA node, NPS1).
Serving's 115.8 is 88 % of that cap, so the software side has at most 14 % to
find, and the 204.8 figure was never on the table.

Second, the per-CCD probe (`tools/membw/ccd-bw.sh`, `taskset` to one, two
or four core complexes). The 5975WX has four CCDs of eight cores, each
hanging off the IO die on one GMI2 link that reads 32 bytes per fabric
clock, 51.2 GB/s at FCLK 1600. Measured: one CCD reaches 40.2 GB/s at two
threads and stays there through eight, and through its SMT siblings; each of
the four CCDs alone gives the same 40.2–40.3; two CCDs give 79.7; four give
131.2. So there are two caps, and the binding one at full load is not the
fabric link. One CCD sits at 79 % of its link, in the normal Zen 3 range,
which also says FCLK is at 1600 and not mis-set (a 1067 fabric would have
shown about 33). But four CCDs together stop at 131, not at four times 40,
so the IO die or the DRAM side is the wall at full load. Public numbers for
the same part put read bandwidth near 147 (and 137–139 for the 3975WX, 160
for the eight-CCD 5995WX), so about 10 % of the memory-side cap is
recoverable and it lives in memory timings, the 2Rx8 consumer UDIMMs, or the
interleave setting rather than in any flag we can pass. The rest is
structural: a four-CCD part cannot draw what eight channels can supply, and
the eight-CCD parts are the ones that can.

Third, decode against thread count, on the seven-layer decode profile at
16k with the DSpark draft, two passes each, the warm pass counting:

| -t | cold | warm |
|---|---|---|
| 16 | 17.77 | 19.77 |
| 24 | 20.73 | 23.19 |
| 32 | 23.36 | 25.07 |
| 48 | 20.51 | 24.10 |
| 64 | 13.08 | 18.88 |

The physical core count wins and SMT only contends. The read probe saturates
at eight threads but decode needs thirty-two, which says the expert kernel
is bounded by per-thread dequantization work as much as by bandwidth: the
Q3_K blocks have to be unpacked before they can be multiplied, and eight
cores cannot do that at 130 GB/s. That is also why the 3.6 GHz cap helped
the hero take: it is not moving bytes faster, it is unpacking them faster.

What this changes. The BIOS plan on WKS-22 is now memory clock first with
the fabric at 1:1 (3400, then 3600), since a fabric-only raise would lift
the 40 GB/s per-CCD figure that is not the binding one; expected recovery is
132 → 145–150 GB/s and, since decode tracks bandwidth nearly linearly,
25 → about 28 tok/s. Derived, not measured, and the eight non-ECC UDIMMs
mean every step gets a memtest pass and the twenty-prompt identity check
before it counts. Filed alongside: WKS-24 (V4.1 on the 48 GB card alone, so
the 24 GB card can hold a resident coding model), WKS-25 (that coding
model's candidates and protocol), WKS-26 (speculative decoding as the only
lever that uses the idle GPU without more VRAM — the expert weights are read
once per verify batch, so acceptance and draft length are the knobs).

## The short-prompt prefill floor: a weight copy, not a batch boundary

*14:40–14:58, for a toktape re-shoot that was then cancelled.* The 11:51 hero
take waited 10.7 s for its first token on two 280-token prompts, and the
recorder's session asked how to shorten it. My first answer was wrong, and
the measurement that killed it found the real cost, so both go here.

The wrong answer: two prompts of 279 and 283 tokens add to 562, past the
`-ub 512` of the hero script, so they would run as two ubatches, and if each
ubatch pays a fixed cost then `-ub 1024` should nearly halve the wait. The
server was restarted that way (a copy of the hero script with the one flag
changed; seven layers still loaded, 45.9 + 20.4 GB) and probed with two
concurrent chat prompts of about 265 tokens each, at the 2.7 GHz cap:

| case | prompt_n | prompt_ms |
|---|---|---|
| 2 streams, fresh text (engram rows faulting in) | 267 / 262 | 13 829 |
| 2 streams, same text again with a changed prefix (rows cached, KV miss) | 268 / 263 | 10 353 |
| 1 stream, fresh | 292 | 9 205 |
| 2 streams, fresh | 262 / 254 | 11 244 |
| 1 stream, fresh | 251 | 8 719 |
| the 11:51 take, 3.6 GHz, `-ub 512` | 279 / 283 | 10 732 |

One ubatch instead of two changed nothing. The numbers fit a fixed cost of
about 7.7 s per prefill plus 5 ms a token, and the 11:51 take sits on the
same line (7.7 + 0.005 × 562 = 10.5). Ubatch count, stream count and clock
cap do not move it. The 3.5 s difference between the first two rows is the
engram rows for fresh text, the WKS-20 cost showing up in prefill.

The cause was watched directly: `nvidia-smi dmon -s tu` during a one-stream
251-token prefill shows the 48 GB card receiving 13–19 GB/s over PCIe for
about seven seconds, with its SMs at 50–71 % and the other card idle. That
is the op-offload path: for any ubatch of 32 tokens or more the scheduler
runs the CPU-resident expert matmuls on the GPU, and to do so it copies the
expert tensors of the 37 CPU layers, about 166 GB at Q3_K_M, across the bus
once per prefill. 166 GB at 18.5 GB/s is the 7.7 s. The bus is PCIe 4.0
x16, whose practical ceiling is nearer 25 GB/s; the weights are memory-mapped
pageable memory, so the copy stages through a pinned buffer and loses the
rest.

So on this placement any prompt over 32 tokens waits about seven seconds
before its first token, and the "prefill tok/s" on a short prompt is not a
throughput but the prompt length divided by that constant: 26 tok/s at 280
tokens and 120 tok/s at 14k are the same hardware doing the same copy. The
recorder's card will say so. What could lower the floor is now WKS-27: let
the CPU compute short prompts itself (`--no-op-offload`, or the offload
threshold raised past the prompt), which wins only if the CPU does 280
tokens faster than 40 tok/s and loses on long prompts, so it is a study
arm and not a serving setting; pinned weights would recover perhaps a
quarter of the copy time but 200 GB of them do not fit beside the engram
table. The re-shoot was cancelled on these numbers — trimming the prompts
to 150 tokens would have saved a second — and the recorder shows the last
three seconds of the wait instead. 8001 went back to the normal serving
script at 14:58; the hero script copy keeps `-ub 1024` as a harmless
change, with this section as the record that it was not the fix.

## The thirty seconds per turn are the checkpoint, not the prefill

*15:17–16:14, prefill window 6 on the 256k coding profile.* The question
from the morning was what a follow-up turn costs in a 100k-token coding
session once the prompt cache is warm, and the estimate was "about thirty
seconds". The window measured it on a 12k conversation: a system prompt and
a 12k-token document, a 300-token answer at temperature 0, then four
follow-ups of about 600 new tokens each.

| arm (code4, c256k, fused) | VRAM | 14k prefill cold / warm | turn 1 TTFT | turns 2–5 re-prefill | turns 2–5 TTFT |
|---|---|---|---|---|---|
| ub 2048, KV q8_0 | 45.3 + 12.2 GB | 71.9 / 114.6 tok/s | 109.5 s | ~2 600 tok | 26–27 s |
| ub 4096, KV q8_0 | 48.1 + 19.6 GB | 86.9 / 142.7 | 76.7 s | ~4 650 | 30–31 s |
| ub 8192 | did not load | | | | |
| ub 2048, `--no-op-offload` | 44.5 + 12.3 GB | 54.1 / 63.1 | 186.9 s | ~2 600 | 40 s |
| three layers, ub 2048, KV f16 | 42.5 + 12.7 GB | 67.7 / 116.7 | 96.3 s | ~2 600 | 26–27 s |

Thirty seconds it is, and the table says why: the new tokens in each
follow-up are about 900, but the server re-processes 2 600 of them at a
2048 batch and 4 650 at 4096. The re-prefill is the distance back to the
last context checkpoint, and the checkpoint is not where one would expect.
~~The server creates its "near the end of the prompt" checkpoint *before* it
decodes the final prompt batch, so the checkpoint lands on the last batch
boundary, 10 240 or 8 192 tokens into an 11 944-token prompt. On the next
turn the re-rendered history diverges right after that prompt (the
assistant's thinking and template tokens are not what was generated), the
sliding-window state at that point is gone after 300 generated tokens, and
the only checkpoint the server can restore is the one at the batch boundary.
Everything after it is prefilled again. Mainline master has the same lines.~~

~~The fix is twelve lines in the fork: create one more checkpoint the moment
the prompt is fully processed. Expected, not yet measured: the re-prefill
drops to the ~900 genuinely new tokens and the turn waits 10–14 s instead
of 26–31.~~

**Corrected 2026-09-15, measured.** The checkpoint *is* where it should be
— the server creates one four tokens before the end of the prompt — and the
server rejects it. Mainline hides the dsv4 memory's 128-token raw window
from the server (`llama_model_n_swa()` returns 0 for `DEEPSEEK4`, because
that cache cannot roll back inside the window); the V4.1 port added
`DEEPSEEK41` without extending that one case, so the checkpoint search
demanded a 128-token margin that an exact-position checkpoint can never
satisfy and fell back 2 048 tokens to the previous one. Mainline master
with V4-Flash does not have the problem (turns of 862 tokens, 5.4 s). The
fix is one line in the fork, not twelve, and it measured: turns 2–5
re-prefill 2 606 → 562 tokens, TTFT 21.0 → 8.8 s, all five answers
byte-identical. The whole trail, including the server-side guard patch that
worked for the wrong reason and was reverted, is
[`docs/checkpoint-restore-dsv4.md`](../docs/checkpoint-restore-dsv4.md).

Two smaller findings from the same window. `-ub 4096` gives long prefill a
quarter more throughput but leaves one GiB on the 48 GB card, so it is not
a profile candidate, and 8192 does not fit at all. `--no-op-offload` halves
long prefill (63 against 115 tok/s), the exact opposite of what it did to
short prompts an hour earlier on WKS-27, which is why the answer is a
threshold and not a switch: the tree already reads `GGML_OP_OFFLOAD_MIN_BATCH`,
and the sweep at 768, 1024 and 2048 is the next window. Three resident layers
with KV f16 load with room to spare and prefill like four layers with q8_0,
so if the q8_0 check fails there is a coding profile at no prefill cost.
Decode inside the 256k profile with 300-token answers runs about 16 tok/s
in every arm — fewer resident layers than the decode profile, and a long
context.

## The offload threshold: 768 is the whole answer

The sweep from the previous section ran 16:20–17:01 on the 256k coding
profile (four resident layers, KV q8_0, `-b/-ub 2048`), one server per
arm with `GGML_OP_OFFLOAD_MIN_BATCH` set in the environment, coolant 44–48 °C,
IO pressure avg10 ≤ 1.4 at every arm start. Same prompts as window 6: the
14k wiki article cold then warm, a 257-token and a 900-token fresh prompt,
and the five-turn chat.

| min batch | wiki 14k warm | 257 fresh | 900 fresh (825 tok) | chat turn 2–5 TTFT |
|---:|---:|---:|---:|---:|
| 32 (default, window 6) | 115 tok/s | 10.2 s | — | 26–31 s |
| 768 | 114.7 tok/s | 4.5 s | 11.4 s (72 tok/s) | 24.4–25.5 s |
| 1024 | 104.8 tok/s | 4.5 s | 13.1 s (63 tok/s) | 24.5–25.3 s |
| 2048 | 105.4 tok/s | 4.4 s | 12.9 s (64 tok/s) | 39.5–40.0 s |

768 does exactly what the crossover estimate said it would. A 257-token
prompt goes to the CPU linear path and finishes in 4.5 s instead of 10.2,
the 825-token prompt stays above the threshold and takes the copy path at
11.4 s, and long prefill loses nothing (114.7 against 115). At 1024 the
825-token prompt falls below the threshold and the CPU path is slower than
the copy would have been (13.1 against 11.4 s), which puts the real
crossover between 768 and 825 tokens, right where the ~7.7 s fixed copy
against ~65 tok/s of CPU linear puts it. At 2048 the chat turns pay:
every re-prefill of ~2600 tokens leaves a sub-threshold tail and the turn
runs at 65 tok/s end to end, TTFT 40 s instead of 25. The 14k cold rows
are not comparable across arms (79, 56 and 59 tok/s) — the first arm
started with the file still in page cache from normal serving, the later
two did not — so only the warm rows are in the table.

So the serving scripts get `GGML_OP_OFFLOAD_MIN_BATCH=768` and nothing else
changes; the short-prompt floor from WKS-27 is closed at the cost of one
environment variable. The chat turns did not move because, as the previous
section measured, their 25 s is the checkpoint placement, not the copy.
