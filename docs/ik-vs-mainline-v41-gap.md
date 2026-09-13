# Where ik_llama.cpp loses to mainline on DeepSeek-V4.1: a source reading

*2026-09-14. A read-only comparison of the two trees; nothing in this file was
measured except where a number is cited from the log. The one experiment that
decides it is at the end and has not been run yet.*

The measured gap, same box, same file, same draft, quiet machine, second pass
after load ([log](../log/2026-09-13-deepseek-v41-on-ik-llama.md)):

| engine | no draft | DSpark block 3 |
|---|---:|---:|
| ik_llama.cpp | 14.1 | 19.9 |
| mainline (V4.1 runtime branch + master) | 17.7 | 25.6 |

Only the no-draft pair is a like-for-like comparison (the 25.6 came after a
VRAM re-balance the ik run never had). 14.1 against 17.7 is 70.9 against 56.5
ms per token: 14.4 ms a token, 360 µs a layer. The draft multiplier is in fact
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
(`ggml/src/ggml-cuda.cu:4711`). If it still measures 14.1, CUDA graphs were
already off in the served run and the latch is the cause. Then, in order:

| # | change | where | kind | effort | should move |
|---|---|---|---|---|---|
| 1 | remove the consecutive-update latch, re-capture instead | `ggml-cuda.cu:4736-4761`, flag in `common.cuh` | port (mainline deleted it) | S | no-draft 14.1 toward 17.7 |
| 2 | narrow the `mul_mat_id` graph rule | `ggml-cuda.cu:4484-4507` | port of #18958 | M | block 3 / block 5 pairs |
| 3 | engram row prefetch | `src/llama.cpp:5267-5303` | port of 86d01ece1 | S | first-pass faults |
| 4 | keep the reuse hash stable across plan growth | `src/llama.cpp:597-621`, `src/llama-dsv4.cpp:715-800` | ik-specific | M | what is left after 1 |

Not recommended: CPU kernel work (the bench says ik leads), HC fusion (already
there), scheduler copy-path work (ik already syncs less).
