# Where ik_llama.cpp loses to mainline on DeepSeek-V4.1: a source reading

*2026-09-14. A read-only comparison of the two trees; nothing in this file was
measured except where a number is cited from the log. The experiment at the
end was run the same morning; its result, and what it did to the table above,
is in the section after it.*

The measured gap, same box, same file, same draft, quiet machine, ~~second pass
after load~~ — corrected below: both no-draft rows are **first pass after
load** ([log](../log/2026-09-13-deepseek-v41-on-ik-llama.md)):

| engine | no draft | DSpark block 3 |
|---|---:|---:|
| ik_llama.cpp | 14.1 | 19.9 |
| mainline (V4.1 runtime branch + master) | 17.7 | 25.6 |

Only the no-draft pair is a like-for-like comparison (the 25.6 came after a
VRAM re-balance the ik run never had). ~~14.1 against 17.7 is 70.9 against 56.5
ms per token: 14.4 ms a token, 360 µs a layer.~~ Both numbers are first-pass
figures, so that per-layer arithmetic was done on a cold number and does not
describe the graph; see the measurement at the end. The draft multiplier is in fact
better on ik (1.41× against 1.29×), so the draft path is not where the gap is.

## What ik already has

The reading started from four mainline mechanisms assumed to be missing on ik.
Three are not.

**Fused hyper-connection ops.** ik's `build_hc_pre()`
(`src/graphs/build_deepseek4.cpp:626-666`) emits one `ggml_hc_pre` node that
carries scale, base, sinkhorn and the pre/post/comb math, and the post side is a
single `ggml_hc_post` (`src/llama-build-context.cpp:641-671`); about ten HC nodes
a layer. All of them have CUDA kernels and `supports_op` returns true
(`ggml/src/ggml-cuda.cu:4251-4270`, `:5158-5167`). Nothing HC-related is pushed
to the CPU. This axis is also closed by measurement: every mainline number up to
17.7 was taken with the fused *pre* op disabled on all 40 layers (the probe bug
fixed in commit e42d711e5), and it still beat a fully fused ik.

**Scheduler and copies.** Both schedulers are the same five-pass design; both
fall back to synchronize-and-blocking-copy at every CPU↔GPU transition because
the CPU backend has no async copy (ik `ggml-backend.cpp:386-402`, mainline
`:511-528`). ik guards the split-backend wait with a `needs_sync[]` array
(`:2019`, `:2044-2053`) where mainline waits on every input, so ik synchronizes
*less*. Pipeline parallelism is off under `-ot` on both, and the ik build is
compiled with `GGML_SCHED_MAX_COPIES=1`. Bytes per transition are 20 KB a
direction at batch 1 (`n_embd` × f32); the cost is the 68 round trips a token,
which both engines pay alike.

**CPU expert matmul.** Both use a barrier-free atomic chunk queue across experts
(ik `ggml/src/ggml.c:18297-18334` under `GGML_EXPERT_CHUNKING`, mainline
`ggml/src/ggml-cpu/ggml-cpu.c:1657-1730`). Mainline's `iqp` path only turns on
at eight or more rows per expert, so it is off at batch 1, 4 and 6. Nothing
hybrid-specific differs.

**Graph size.** ik's graph is smaller: 3631 nodes against 5051 (server logs),
because its reader layers gather compressed KV with `ggml_get_rows_ext`
(`build_deepseek4.cpp:1357-1368`) instead of a dense mask.

## What ik does not have

**A CUDA-graph latch that never releases.** ik's CUDA backend keeps the old
heuristic: four consecutive graph updates on a split set
`disable_due_to_too_many_updates` and CUDA graphs are off for that split
(`ggml/src/ggml-cuda.cu:4736-4761`). A grep for the flag over the whole tree
finds only those lines; nothing sets it back to false. Mainline deleted the
heuristic (`ggml-cuda/ggml-cuda.cu:4401-4404`, `common.cuh:1279`, `:1293` keep
only `disable_due_to_gpu_arch`) and instead skips the update when the graph
`uid` is unchanged (`ggml-cuda.cu:2583-2597`).

The latch condition recurs on V4.1. ik's graph-reuse check hashes the lengths
of the compressed-KV plan vectors (`src/llama.cpp:597-621`), which grow only on
the token that completes a compression row (`src/llama-dsv4.cpp:766-786`), so
the hash changes every `ratio` tokens, each change resets the scheduler
(`src/llama.cpp:6889-6891`), the re-split hands every split a new uid
(`ggml-backend.cpp:1977`), and the CUDA backend goes through a full
node-by-node compare (`ggml-cuda.cu:4576-4608`). Mainline rebuilds on exactly
the same plan lengths (`src/llama-graph.cpp:916-935`); the difference is only
what happens next: mainline re-captures, ik gives up for good.

The size fits. Of ik's 3631 nodes, roughly 2000 are GPU kernel launches a
token; at ~5 µs a launch that is ~10 ms a token, against the 14.4 ms gap. On a
dense GPU model the launch latency hides behind execution; here the pipeline
drains 68 times a token for the CPU experts, so it does not.

**An over-broad `mul_mat_id` incompatibility rule.** ik turns CUDA graphs off
for any `MUL_MAT_ID` with `ne[2] != 1`, i.e. batch 2 and up
(`ggml-cuda.cu:4484-4507`); at batch 1 the fused-MoE special case skips the
down projection and the graph survives. Mainline narrowed this in upstream
#18958 to the cases that really need a stream sync
(`ggml-cuda/ggml-cuda.cu:1872-1899`, `:2562-2572`), so batch 4 keeps its graph.
This lines up with the one measured oddity on ik: block 3 (batch 4) gives
1.41×, block 5 (batch 6) collapses to break-even (14.33), where mainline holds
both. Six affected splits do not obviously explain that much; the cause is not
established.

**Engram row prefetch.** Same graph on both; ik's `llama_set_engram_rows()`
(`src/llama.cpp:5267-5303`) has no `madvise(WILLNEED)` before the
`tensor_set`. A small port of commit 86d01ece1; it moves first-pass and
fresh-text numbers only, not the steady-state table.

## Not established

- Whether the latch actually fires in the served configuration. The debug log
  line is compiled out under `NDEBUG`.
- ik's split count at batch 1 (it logs only the reserve-time 110 at
  `n_ubatch` 2048; mainline's 83 at bs=1 is not comparable).
- Relative speed of the GPU kernels themselves (`DS4_COMP`, `INDEXER_TOPK`,
  `HC_PRE`, the `iqk` flash-attention variants). Never measured on either side;
  the earlier kernel bench was CPU-only. This is the next place to look if the
  latch hypothesis fails.

## The experiment that decides it

Run the ik no-draft configuration once with `GGML_CUDA_DISABLE_GRAPHS=1`
(`ggml/src/ggml-cuda.cu:4711`). ~~If it still measures 14.1, CUDA graphs were
already off in the served run and the latch is the cause.~~ That sentence
did not discriminate: the same number is what "graphs latched off" and
"graphs on but irrelevant" both produce. What the experiment can say is
whether graphs are a lever at all. Then, in order:

| # | change | where | kind | effort | should move |
|---|---|---|---|---|---|
| 1 | remove the consecutive-update latch, re-capture instead | `ggml-cuda.cu:4736-4761`, flag in `common.cuh` | port (mainline deleted it) | S | no-draft 14.1 toward 17.7 |
| 2 | narrow the `mul_mat_id` graph rule | `ggml-cuda.cu:4484-4507` | port of #18958 | M | block 3 / block 5 pairs |
| 3 | engram row prefetch | `src/llama.cpp:5267-5303` | port of 86d01ece1 | S | first-pass faults |
| 4 | keep the reuse hash stable across plan growth | `src/llama.cpp:597-621`, `src/llama-dsv4.cpp:715-800` | ik-specific | M | what is left after 1 |

Not recommended: CPU kernel work (the bench says ik leads), HC fusion (already
there), scheduler copy-path work (ik already syncs less).

## Measured: CUDA graphs are not the lever, and 14.1 was a cold number

*2026-09-14, 05:11–05:33. ik `llama-server`, same file and placement as the
table, `GGML_CUDA_NO_PINNED=1`, no draft, `cache_prompt` off, the first six
of the twenty prompts, 200 greedy tokens each (prompt 3 stops at 26), two
passes per arm, one load per arm, port 8099 with the production server
stopped. Witness: IO pressure `some avg10` 0.63 / 1.81 at the start of each
arm, the avg300 of 5–6 being the load itself; the coolant probe in the
script matched nothing, so no temperature is on record for this window.
Numbers are the server's own `eval time` lines; the script's summary line
had a quoting bug and printed nothing.*

| arm | pass 1, tok/s per prompt | pass 2, tok/s per prompt |
|---|---|---|
| CUDA graphs default | 13.97 · 13.26 · 13.22 · 14.86 · 14.27 · 13.22 | 19.03 · 18.86 · 19.61 · 18.90 · 18.95 · 18.93 |
| `GGML_CUDA_DISABLE_GRAPHS=1` | 14.11 · 13.29 · 13.19 · 14.84 · 12.51 · 12.98 | 18.38 · 18.53 · 19.24 · 18.68 · 18.65 · 18.77 |

Two things follow, one of them about the table at the top of this file.

**Graphs on or off is inside the band.** Pass 2 medians 18.9 against 18.7,
pass 1 13.6 against 13.2; the load-to-load band measured yesterday is 4 %.
Removing the latch (row 1 of the ranked table) cannot gain what disabling
graphs entirely does not lose, so row 1 is closed as a lever. Whether the
latch fires is still not established; it just does not matter here.

**The published 14.1 is a first-pass number, and so is mainline's 17.7.**
Today's pass 1 lands inside yesterday's 14.13 (13.19–14.95) prompt for
prompt, and pass 2 on the same prompts is 18.9, 35 % higher. The log's
mainline row was also the first request after load (the block-5 rows under
it are labelled first and second pass; the no-draft row preceded them). So
the top table compares two cold numbers, which is a fair comparison, but
the 70.9-against-56.5 ms reading treated them as steady state and was
struck above. What a warm ik decodes against a warm mainline at the same
split has not been measured: the mainline second pass without a draft at
this placement does not exist in the log, and 17.7 divided by the 0.88
first-to-second ratio seen with a draft is a derivation, not a number.

Pass 2 on repeated prompts is a best case, not a steady state: the same
tokens route to the same experts and the same engram rows. A novel prompt
in production behaves like pass 1 on both engines, which is the case that
matters and the case where the gap was measured.

Why ik's first pass costs 35 % is not measured yet. The server's load
lines put 411 GB of tensors in CPU buffers on a 251 GB box, so the CPU
weights are memory-mapped and cannot all be resident; a first pass over a
new prompt reads expert rows and engram rows from disk, a second pass finds
them in the page cache. Mainline's first-pass penalty was 12 % with the
engram prefetch in place. The measurement that separates the two is the
major-fault count from `/proc/<pid>/stat` before and after each request,
pass 1 against pass 2; if it is near zero in both, the penalty is not
paging and row 4 (the reuse hash) moves up instead of row 3.

The ranked table, re-read: row 1 closed; row 3 (engram prefetch, port of
86d01ece1) is the candidate for the first-pass penalty pending the fault
count; row 2 still applies to the drafted pairs only; row 4 waits on the
fault count. The next window is one script: ik no-draft with fault counts
per request, then mainline no-draft at the same six-layer split, two passes
each.

## Measured: the fault count, and mainline warm at the same split

*2026-09-14, 05:42–06:01. Same six prompts, same file and placement, two
passes, one load per arm, production server stopped; major faults from
`/proc/<pid>/stat` field 12 before and after each request. IO pressure
`some avg10` at most 0.05 on every row after load. ik arm:
`GGML_CUDA_NO_PINNED=1`; mainline arm: the merged tree with
`--lazy-mode auto`, no draft, the six-layer split ik has. Prompt 3 stops at
14 tokens and is not used for medians.*

| engine | pass 1 tok/s | pass 1 maj faults / token | pass 2 tok/s | pass 2 faults |
|---|---:|---:|---:|---:|
| ik | 13.6 (13.2–14.2) | 41–62 | **18.8** (18.75–18.83) | 0 |
| mainline, 6-layer split | 18.6 (17.2–19.3) | 143 on the first prompt, then 40 → 13–21 | **19.8** (19.80–19.85) | 0 |

Three results, in order of how much they change the picture.

**Warm against warm, the gap is 5 %, not 20 %.** ik 18.8 against mainline
19.8 at the same split, zero faults on either side. Everything in the
"where ik loses" reading above — fused ops, scheduler, CUDA graphs — is
looking for 20 % that a warm graph does not have. The source reading stands
as a description of the two trees; the gap it was written to explain is a
cold-path gap.

**The cold gap is the cost of a page fault, not only the count.** Both
engines fault on a first pass: the CPU weights are memory-mapped on both,
and a new prompt reads expert rows and engram rows the page cache has not
seen. ik at 41–62 faults a token loses 28 % against its own warm number;
mainline at 13–21 faults a token loses 6 %, and even its 143-fault first
prompt runs 17.2. The engram prefetch (86d01ece1, `posix_madvise(WILLNEED)`
on the rows the token will read before the graph runs) is the difference
the source reading already named at row 3: rows fetched ahead become minor
faults or no faults, and the ones that remain overlap the compute. ik has
no such point (`src/llama.cpp:5267-5303`), so every row is a synchronous
fault in the compute thread. This is a reading of the two numbers, not a
separated measurement; the separation would be ik with the prefetch ported.

**Mainline's fault count falls across a first pass, ik's does not.** 143,
40, then 13–21 on mainline against a flat 41–62 on ik. Prompt 1 on mainline
is `--lazy-mode auto` still pulling experts; the 13–21 that remain are the
engram rows of new prompts. ik's flat 47 says it is faulting on more than
engram rows, or on the same rows more often. Not separated here.

The ranked table, third reading: row 3 (engram prefetch port) is first, and
it is the only row with a measured target — ik's first pass from 13.6 toward
its own 18.8, with the fault count as the gate. Row 1 is closed. Rows 2 and
4 address a warm gap of 5 % and a drafted gap not yet re-measured warm; they
wait. The comparison table at the top of this file, cold against cold, was
a fair comparison of what a user sees on a new prompt; it was not a fair
description of the engines.
