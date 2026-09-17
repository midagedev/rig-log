# Where the four-stream gap actually is

*2026-09-17, 15:07–18:45. RTX A6000 48G, one card, one lease per take, io pressure 0 at every
start. ik_llama.cpp c10fbbcc, mistral.rs 0.9.3, toktape 0.2.4.*

The [morning's entry](2026-09-17-a-rust-engine-on-the-same-card.md) measured a Rust engine against
ik_llama.cpp on the same card and the same model and left the interesting half unexplained:
mistral.rs went 105 → 283 tok/s from one stream to four, ik_llama.cpp went 130 → 149, and the two
candidate explanations it offered both turned out to be wrong. This entry is the sweep that settled
it, and the answer is not about mistral.rs at all.

> ~~Either mistral.rs's single stream is overhead-bound and batching amortises a fixed cost, or its
> indexed-MoE path gathers the union of the experts once per step where ik re-reads per sequence.~~
> **Struck the same day.** Both were guesses about the fast engine. The gap is on the other side:
> ik_llama.cpp leaves decode batching on the table on a MoE model, and its concurrent prefill falls
> off a documented cliff. mistral.rs is the control that shows what the card can do.

## The sweep

Eight takes, one lease each, 1/2/4/8 streams on both engines, the same Qwen3.6-35B-A3B UD-Q6_K, the
same eight distinct prompts (a repeated prompt would buy a prefix-cache hit that four real users
would not), `-c 32768`, `-n 512`, thinking left on so that every stream runs to the cap — with
`--no-think` the streams end at EOS at different lengths and the aggregate then measures a shrinking
population rather than the engine. The server is built for eight slots in every row, so only the
client's stream count moves. Driver: [`tools/engine-ab/stream-sweep.sh`](../tools/engine-ab/stream-sweep.sh);
every figure below is read out of the tape by [`tools/tape-row.py`](../tools/tape-row.py), not off a
progress line.

### mistral.rs 0.9.3

| streams | srv each | cli each | aggregate | gain | TTFT p50 | engine prefill | GPU W | ITL p50 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 111.1 | 104.6 | **105** | 1.00× | 160 ms | 140 ms | 246 | 9.5 ms |
| 2 | 99.7 | 93.2 | **184** | 1.75× | 136 ms | 97 ms | 297 | 10.6 ms |
| 4 | 76.9 | 72.2 | **279** | 2.66× | 448 ms | 100 ms | 299 | 13.7 ms |
| 8 | 43.8 | 42.1 | **324** | 3.09× | 667 ms | 128 ms | 299 | 23.7 ms |

### ik_llama.cpp c10fbbcc

| streams | srv each | cli each | aggregate | gain | TTFT p50 | engine prefill | GPU W | ITL p50 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 128.7 | 128.5 | **129** | 1.00× | 248 ms | 218 ms | 299 | 7.7 ms |
| 2 | 65.5 | 65.4 | **130** | 1.01× | 372 ms | 294 ms | 299 | 15.1 ms |
| 4 | 36.8 | 36.7 | **146** | 1.13× | 4 516 ms | 3 391 ms | 296 | 26.7 ms |
| 8 | 19.1 | 19.1 | **152** | 1.18× | 12 529 ms | 10 071 ms | 241 | 51.5 ms |

The second row is the whole story in one line. **ik's per-stream rate halves from one stream to two
— 128.5 to 65.4 — and the aggregate does not move at all: 129 to 130.** Two clients take turns on a
machine that is doing no more total work than it did for one. mistral.rs's second stream costs its
first one 11 % and returns 1.75× in aggregate, which is what batching a memory-bound decode is
supposed to look like. And ik's prefill does not merely fail to scale, it collapses: 218 ms for one
238-token prompt, 10 071 ms for eight of them, which is 5.8× *more* engine time per prompt token at
eight streams than at one.

Two notes on the tapes rather than the engines. The mistral.rs rows all carry `contended: yes` for a
reason that is not contention: toktape identifies the attached server by process name, `mistralrs`
is not in `procmon.IsServerCommand`, so it counts the engine's own process as `other_gpu_procs: 1`.
Every witness in those tapes reads io pressure 0 and loadavg 0.6, and the lease was held by the
sweep. Sent to the toktape session as a request rather than worked around here — the shim already
knows the server's pid (`MRS_PID_FILE`) and could declare it in `/props`. Separately, the first two
rows of one control run were taken while the model was still coming off NVMe (io pressure 17 and 9)
and are not in any table here: the quiet-machine gate flagged them, which is what it is for.

## Two mechanisms, not one

The sweep says concurrency costs ik something the engine does not get back. It does not say what, and
the server is in the way of asking: a take mixes the kernel path with slot scheduling, continuous
batching and the KV layout. `llama-batched-bench` runs the same decode with N sequences in one
process and no server at all, which makes the experiment small enough to be an answer
([`tools/ik/ik-batch-scaling.sh`](../tools/ik/ik-batch-scaling.sh) is the lease-gated wrapper):

```
llama-batched-bench -m <model> -c 32768 -ngl 99 -fa on -t 32 -b 2048 -ub 512 \
                    -npp 238 -ntg 256 -npl 1,2,4,8
```

**DeepSeek-V2-Lite-Chat Q3_K_M — MoE, MLA attention, no linear attention:**

| B | prefill t/s | **decode t/s** | decode vs B=1 |
|---:|---:|---:|---:|
| 1 | 1 960.8 | **202.1** | 1.00× |
| 2 | 6 118.8 | **156.1** | **0.77×** |
| 4 | 6 150.8 | **229.9** | 1.14× |
| 8 | 5 908.1 | **317.0** | 1.57× |

**Qwen2.5-7B-Instruct Q3_K_M — dense, same harness, same card, same minute:**

| B | prefill t/s | **decode t/s** | decode vs B=1 |
|---:|---:|---:|---:|
| 1 | 2 743.8 | **120.7** | 1.00× |
| 2 | 4 785.7 | **195.5** | 1.62× |
| 4 | 5 091.6 | **290.7** | 2.41× |
| 8 | 5 178.7 | **388.5** | 3.22× |

A decode step carrying two tokens instead of one is **slower in total** than the single-token step on
the MoE model, and 1.62× faster on the dense one. Batch 3 lands at 194.8 and batch 4 at 227.7, so
batch 1 is not beaten until four sequences are in flight. Re-run once with `-npl 1,2,3,4`: 201.4,
155.0, 194.8, 227.7 — the same numbers to about half a percent, so this is not a fluke of one run.
Prefill scales fine on both, which is what makes the decode column readable: the same weights, the
same card, the same harness, and only the presence of an expert matmul differs.

Two interventions, both measured, both out:

* **CUDA graphs are not the cause,** although the code makes them look like it.
  `ggml/src/ggml-cuda.cu:4493` disables graph capture for any `MUL_MAT_ID` node whose batch is not a
  single token — the MoE expert matmul, exactly the op the dense model does not have — and the dense
  model therefore keeps its graph at every batch size while the MoE model loses it at two. That is a
  clean story and it is wrong: with `GGML_CUDA_DISABLE_GRAPHS=1` the single-stream rate on
  DeepSeek-V2-Lite goes from 196.8 to 182.7 tok/s, a 7 % effect, and the 1 → 2 collapse survives
  intact (155.4 aggregate, 78.2 per stream). Graph replay is worth 7 %, not 60 %.
* **The fused-MoE path is not the cause.** `-no-fmoe` is worse at every stream count — 171.3 / 118.2
  / 168.8 against 196.8 / 150.2 / 201.8 — so the fused kernel is helping, not standing in the way.

What is left is the batch-2 expert matmul itself, and the tapes point the same way: the effective
bandwidth toktape derives *falls* with the stream count on ik's MoE takes, 257 → 99 → 74 GB/s, while
inter-token latency triples. A path that read the union of the experts per step would keep bandwidth
high and the rate flat; bandwidth falling while latency rises is a decode that is waiting, not
reading. The plausible shape is the awkward middle of a quantized MoE GEMM — one row per expert is a
GEMV the kernel is tuned for, two rows is neither that nor a GEMM worth a tiled kernel — and
[#1785](https://github.com/ikawrakow/ik_llama.cpp/pull/1785) ("Use MMQ for large-batch quantized
matmuls on Volta") is the same family of problem at the other end of the batch range. **That is a
hypothesis; the cause is not measured.** Settling it needs per-op timing, and ik has no profiler
env var, so the next step is nsys or a timing build.

## The prefill cliff is a different bug, and it is already reported

Running the same command on Qwen3.6-35B-A3B, ik prints the answer itself:

```
llama_decode_internal: qwen3next mixed-sequence batch contains repeated seq_id values;
                       falling back to single-token chunking
```

| B | prefill t/s | decode t/s |
|---:|---:|---:|
| 1 | 2 581.9 | 133.8 |
| 2 | **119.7** | 137.9 |
| 4 | **119.0** | 157.2 |

`src/llama.cpp:7051` sets `n_tokens = 1` for the whole ubatch when it holds more than one distinct
sequence *and* a repeated sequence id — which is precisely the shape of several prompts prefilling at
once. Prefill drops from 2 582 to 119 tok/s, a factor of 21, and that is the 3 391 ms and 10 071 ms
in the sweep table and the 2 705 ms TTFT recorded on 09-15. The guard came in with
[#1266](https://github.com/ikawrakow/ik_llama.cpp/pull/1266), the WIP Qwen3Next support, so it is a
correctness guard bought with throughput rather than an oversight.

It is also **already fixed in an open pull request**:
[#2418](https://github.com/ikawrakow/ik_llama.cpp/pull/2418) (Thireus) reserves the graph-meta space
that path needs and splits such a ubatch at sequence-run boundaries instead of at every token, so the
batched path is used where it legitimately can be. Nothing to file here. What this box has that the
PR body does not is the number — 21× on prefill, 5.6 s of TTFT on a four-user take — so the
contribution is a measurement on that PR, not an issue of our own. **Posted 2026-09-17 21:12**, as
[a comment](https://github.com/ikawrakow/ik_llama.cpp/pull/2418#issuecomment-5714136627) carrying the
batched-bench table, the warning the engine prints, and the three TTFT figures. It says in the text
that the branch was never built here, so it is the unpatched behaviour and not a verification of the
fix — that repo's CONTRIBUTING asks contributors not to submit what they have not tested, and the
same sentence is what keeps a measurement from being read as one. The duplicate search that found it:
`repo:ikawrakow/ik_llama.cpp "single-token chunking" OR "mixed-sequence"`, which also turns up
[#1932](https://github.com/ikawrakow/ik_llama.cpp/issues/1932) and the merged
[#1933](https://github.com/ikawrakow/ik_llama.cpp/pull/1933) on recurrent-state corruption in the
same path. The decode finding, searched three ways, has no match — it is an upstream candidate and it
is not filed.

## What this does to the morning's headline

"A Rust engine, 24 % slower alone and 90 % faster at four streams" is accurate and it is not a
statement about Rust, about candle's kernels, or about mistral.rs's scheduler being clever. Read the
two tables together: mistral.rs's single stream is the *slower* of the two (105 against 129) and its
scaling is ordinary — 3.09× from eight streams on a memory-bound MoE decode is roughly what the
arithmetic allows. ik's single stream is the fastest number measured on this card all day, and its
concurrency is flat. The engine that looks 90 % faster at four streams is the one that is merely not
leaving the batching on the table.

That also settles what the morning entry was unsure about. Its open question borrowed the 09-16
ExLlamaV3 arithmetic — two streams route to different experts, so bytes read scale with streams and
the aggregate stays flat — and asked why mistral.rs escaped it. The answer is that the arithmetic was
never a law about MoE decode: on the same model and card, a second stream costs mistral.rs 11 % and
costs ik 50 %. Whatever ExLlamaV3 and ik share, mistral.rs does not share it.

One correction from the same session, to a claim in the morning entry that was marked inferred: it is
measured now. The `-v` server log prints `Preloaded 698 Candle CUDA PTX functions`, so the kernels
under the mistral.rs numbers are candle's, as the code read said.

## State

Measured and settled: ik gains nothing from concurrency on MoE decode and scales normally on dense;
mistral.rs scales on the same MoE model; CUDA graphs and the fused-MoE path are both ruled out by
intervention; the Qwen3Next prefill cliff has a named site, a printed warning and an open upstream
fix. Open: why a two-row expert matmul is slower than a one-row one, which needs per-op timing. Not
filed: the decode finding, with `llama-batched-bench -npp 238 -ntg 256 -npl 1,2,4,8` on
DeepSeek-V2-Lite Q3_K_M as its reproducer and the dense model in the same harness as its control.

Tapes: `assets/qwen36-35b-a3b-q6k-{1,2,4,8}stream-{mistralrs,ik}-sweep-0.2.4.tape`. The
batched-bench tables are console output, not tapes; the command lines above reproduce them.
