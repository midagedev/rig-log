# A 347 GB model with 84 GB of it left on the drive

**2026-09-12.** DeepSeek-V4.1-Flash runs on this machine at **20 tok/s**, with
two 42 GB conditional-memory tables never loaded into RAM at all. The premise
the whole configuration was built on — that those tables can stay on an NVMe
and be read a few dozen rows at a time — holds, and costs 3.3 ms per token.

The projection written before the run said 16–18 tok/s. It was low, for a
reason worth keeping: it used a memory-bandwidth constant borrowed from a
different model.

Everything below was measured on the machine in [the README](../README.md) on
this date, on `vcruz305/llama.cpp` at 5210c7c — **mainline llama.cpp**, not
ik_llama. The harness is [`configs/bench-serve.sh`](../configs/bench-serve.sh),
the launch script [`configs/v41-serve.sh`](../configs/v41-serve.sh), and the
reasoning behind both is in
[where the time goes](../docs/raising-tokens-per-second.md).

## What the file is

| role | tensors | size |
|---|---:|---:|
| routed experts | 120 | 258.8 GB |
| **engram tables** | 8 | **84.6 GB** |
| attention + hyper-connection | 623 | 2.2 GB |
| embeddings, norms, output | 175 | 1.1 GB |
| shared expert | 120 | 0.7 GB |
| **total** | **1046** | **347.4 GB** |

Read from the tensor headers of all nine shards, each tensor's own shape and
quantization type. The engram tables are `blk.1.engram_embd` and
`blk.14.engram_embd`, both `[256, 384006168]` at Q3_K, 42.2 GB apiece.

The dense part of this model is **4.0 GB** — about one percent of the file.
That is the fact that makes the whole arrangement work: almost all of 72 GB of
VRAM is available for routed experts rather than being eaten by attention.

## It loads, and the tables stay on the drive

Two minutes and one second to load, from a page cache dropped immediately
before. Then:

```
VmRSS:     215056592 kB      215.1 GB
RssAnon:      347388 kB        0.3 GB
RssFile:   214358332 kB      214.4 GB
```

215 GB resident against a 347 GB file. `--lazy-mode auto` marks tensors above
4 GiB, the engram tensors are 42.2 GB each, and they were left mapped rather
than faulted in. The rest of the gap is expert weight that was copied to VRAM
and then dropped from the page cache.

## What engram costs, by accident

The second benchmark run repeated the first one's prompt at `temperature 0`.
That generates the same tokens, which hash to the same engram rows, which are
by then in the page cache. The result was an unintentionally clean experiment:

| | decode | major faults/token |
|---|---:|---:|
| fresh rows | 18.88 tok/s | 46.3 |
| same rows again | 20.14 tok/s | **0** |

```
3.31 ms/token difference ÷ 46.3 faults = 0.072 ms per fault
```

against the **0.056 ms** this drive measures for a queue-depth-1 random read
([the NVMe entry](2026-09-12-nvme-sustained-write.md)). The 0.016 ms gap is
page-fault overhead. And 46.3 faults per token is what the arithmetic
predicted: two engram layers × 8 heads × 4 n-gram sizes is 48 row lookups.

So engram costs **3.3 ms per token, 6.3% of the budget** — the low end of the
1–7% band estimated before any of this ran.

## The measurement that was wrong twice

Neither of those two numbers is what this model does on real work.

The first run let the model stop where it wanted and produced 19 tokens, in
which one-time cache warming dominated everything — it reported 563 major
faults per token, twelve times the steady-state figure. The fix is
`ignore_eos`: a benchmark decides how many tokens it measures.

The second is worse, because it looks correct. 20.14 tok/s at zero major
faults is a real measurement of a thing that cannot happen — the model
answering a question it has already answered, at temperature 0, token for
token. Reporting it as throughput would have overstated the machine on every
workload anyone actually runs.

The honest protocol is a different prompt per run, and it showed something
neither of the others could:

| run | prompt | decode | major faults/token |
|---|---|---:|---:|
| 1 | A | 19.63 tok/s | 38.6 |
| 2 | B | 20.01 tok/s | 19.5 |
| 3 | C | 20.33 tok/s | 12.7 |
| 4 | D | 20.11 tok/s | 9.4 |

Four *different* prompts, and the fault count falls by a factor of four.
**Engram has locality.** It is indexed by token n-grams, and common n-grams
recur across unrelated English text, so the hot rows of a 384-million-row
table converge into the page cache and stay. The working set is far smaller
than the table, which is why 84.6 GB on a drive costs 3.3 ms instead of the
dozens it could have.

## Expert placement, which barely matters

The obvious lever was to move more expert layers onto the GPUs. Measured, with
the four-prompt protocol:

| expert layers on GPU | mean decode |
|---:|---:|
| 6 (4 + 2) | 19.36 tok/s |
| 8 (6 + 2) | 20.02 tok/s |

**+0.33 tok/s per layer**, against a predicted +0.5. Nine layers does not fit
at all. So the entire remaining headroom on this axis is under 1 tok/s, and
the effective memory bandwidth this implies is:

```
49.65 ms/token − 6.6 ms GPU work = 43.1 ms on DDR4
3.44 GB/token ÷ 43.1 ms = 79.8 GB/s
```

69% of the 115.8 GB/s this machine measures in a STREAM-style read — better
than the 56% the previous model implied, which is why the projection was low.

One placement result is worth recording because it is a trap. At 8 layers,
GPU0 sits at 46.2 GB of 49.1, and the first run after loading collapsed to
**9.28 tok/s** while the settled runs were normal. Major faults were
unchanged, so it was not engram. Nothing in the log pointed at VRAM.

## The thing that actually paid

Prefill, which was being measured wrong the entire time.

The benchmark prompt was 24 tokens, and dividing by 24 measures fixed
overhead. It is worse in a MoE: a 24-token batch routes to up to 144 distinct
experts per layer against a single token's 6. The reported 39–46 tok/s was
not a prefill figure.

Measured across prompt lengths it settles near 160 tok/s — and two settings
were holding it there. `-np 4` splits the context into four slots and disables
the unified KV cache, costing 160 → 214. `-ub 512` cost far more:

| configuration | prefill @ 4288 tok | decode |
|---|---:|---:|
| 8 expert layers, `-ub 512` | 214.0 tok/s | 16.35 tok/s |
| **6 expert layers, `-ub 2048`** | **343.4 tok/s** | 16.93 tok/s |
| 4 expert layers (CUDA0 only), `-ub 3072` | 245.2 tok/s | 15.75 tok/s |
| 4 expert layers (CUDA0 only), `-ub 4096` | 282.8 tok/s | 14.98 tok/s |

**61% more prefill at no cost to decode** — a better return than anything on
the lever list, from a flag that was already there and set wrong.

The ceiling is the smaller card:

```
ggml_backend_cuda_buffer_type_alloc_buffer: allocating 13864.60 MiB on device 1:
  cudaMalloc failed: out of memory
```

The prefill compute buffer scales with micro-batch and is allocated on CUDA1,
the 3090, where it competes with expert layers and KV cache. Emptying that
card of experts allowed `-ub 4096` and made prefill *worse*, because its
layers then reach across the bus for their experts.

Context is the same trade, and a clean one:

| | decode | prefill @ 4288 |
|---|---:|---:|
| `-c 32768 -ub 1024` | 19.89 tok/s | 187.8 tok/s |
| `-c 16384 -ub 2048` | 19.97 tok/s | 343.4 tok/s |

Doubling context costs 45% of prefill and buys nothing in decode. `-ctk q8_0
-ctv q8_0` does not recover it: what does not fit is the compute buffer, not
the cache.

## What a busy machine costs, measured

The benchmark protocol says to pause the 510 GB download before measuring.
Resuming it while the server ran put a number on why:

| | decode | major faults/token |
|---|---:|---:|
| first run after resuming the download | 7.55 tok/s | 91.3 |
| settled, download running | 17.5 – 18.4 tok/s | 60 – 162 |
| download paused | **20.2 – 20.4 tok/s** | 0 |

A download writing to the same NVMe evicts expert pages from the page cache
and competes for the IOPS engram needs, and it costs about **10% of steady
throughput** — with a much worse transient while the cache re-warms. The
7.55 tok/s reading is not a property of the model; it is what this machine
reports when asked to serve and to pull 100 MB/s at the same time.

Worth having as an operational number rather than only as a benchmarking rule.

## Where this leaves it

**20 tok/s decode, 343 tok/s prefill, 16k context, on mainline llama.cpp.**
Splitting a model across two GPUs and system RAM is upstream `-ot`, not an
ik_llama feature — the fork running here carries sixteen commits and all of
them are V4.1 architecture.

What is left on mainline is small. The placement axis is exhausted at
+0.33 tok/s per layer with under a layer of headroom; prefill has been taken;
concurrency is untested and is the one remaining item of any size.

Everything larger needs ik_llama, which cannot load this architecture yet:
`-ser` projects 24 tok/s, low-bit expert quants project 29. That turns the
architecture port from an optimization into the only remaining lever, which
is not where it sat this morning.

## Still open

- Concurrency. The previous model gained 1.6× aggregate at four streams and
  nothing here has measured it.
- The 9.28 tok/s collapse at 8 expert layers. Reproduced once, not explained,
  and the kind of silent failure this log exists to catch.
- Perplexity. Every lever worth more than a token per second trades accuracy,
  and there is no baseline on this file to trade against.
- The MTP module, which the original weights carry as `mtp.0.*` and the GGUF
  conversion dropped. Speculation projects 1.18×.
