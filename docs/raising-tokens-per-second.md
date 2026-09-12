# Where the time goes on a 347 GB model, and what would move it

**2026-09-12.** What the file says about how fast this model can go, which
levers exist, and what each one is worth. Written before the first run and
then corrected by it: the sections marked *projected* were arithmetic on a
constant borrowed from a different model, and where a run has since replaced
that arithmetic the measured figure is given alongside and the projection is
left visible rather than quietly edited.

The companion pieces are
[running a model larger than memory](running-a-model-larger-than-memory.md),
which covers why this model needs the NVMe at all, and
[the experiment plan](v41-experiment-plan.md), which is what the runs were
supposed to settle.

## Which engine does what, because this is easy to get wrong

Splitting a model across two GPUs and system RAM is **mainline llama.cpp**, not
an ik_llama feature. Everything measured here runs on
`vcruz305/llama.cpp`, a fork of mainline carrying sixteen commits, all of them
DeepSeek-V4.1 architecture — engram gate scales, sparse attention, the DSV4
compressed-stream helpers. None of them touch placement. The flags doing the
work are upstream:

```
common/arg.cpp:2750   {"-ot", "--override-tensor"}, "<pattern>=<buffer type>,..."
common/arg.cpp:2763   {"-ncmoe", "--n-cpu-moe"}, "N"
```

What ik_llama adds is not the ability to do this but the speed and the quants
on top of it — and that happens to be where the two largest levers below live,
which is the whole argument for porting the architecture to it. Every lever in
this document is tagged with the engine it needs.

## The budget, which is measured

Read from the tensor headers of all nine shards — 1046 tensors, summed by role
using each tensor's own shape and quantization type:

| role | tensors | size |
|---|---:|---:|
| routed experts | 120 | 258.8 GB |
| engram tables | 8 | 84.6 GB |
| attention + hyper-connection | 623 | 2.2 GB |
| embeddings, norms, output | 175 | 1.1 GB |
| shared expert | 120 | 0.7 GB |
| **total** | **1046** | **347.4 GB** |

Two things in that table decide everything that follows.

The first is that the **dense part of this model is 4.0 GB**. Attention,
hyper-connection, embeddings, output head and shared experts together are
barely more than one percent of the file. On the previous model, dense tensors
and KV cache took a real bite out of 72 GB of VRAM; here they take almost
none, and essentially all of the VRAM is available for routed experts.

The second is that **routed experts are 75% of the file and are read
sparsely**. The model has 384 experts per layer and uses 6, so a token touches
`258.8 GB × 6/384 = 4.04 GB` of expert weight. That number, and where those
bytes live, is the whole performance story. Everything else on the critical
path is under 3 GB per token and sits on a GPU.

The engram tables are 84.6 GB in two tensors, `blk.1.engram_embd` and
`blk.14.engram_embd`, each `[256, 384006168]` at Q3_K — 42.2 GB apiece. They
are read as a few dozen individual rows per token, so they cost I/O operations
rather than bandwidth, and they are the reason the NVMe is in this at all.

## The calibration: borrowed, then measured

Before the first run there was no figure for how fast this machine streams
expert weights for *this* model, only one for the previous model, taken on
2026-09-11: DeepSeek-V4-Flash at **24.6 tok/s** with no speculation, 32 of its
43 expert layers in system RAM, 2.63 GB of active expert weight per token from
RAM. That gave `2.63 GB ÷ 40.7 ms = 64.8 GB/s`, and applying it to the V4.1
budget projected **16–18 tok/s**.

The first run replaced it. With six expert layers on the GPUs and the engram
rows already in the page cache — so the DDR4 path and nothing else:

```
49.65 ms/token, less 6.6 ms of GPU work = 43.1 ms on DDR4
3.44 GB/token ÷ 43.1 ms = 79.8 GB/s
```

against the **115.8 GB/s** this machine measures in a STREAM-style read
([README](../README.md)). So the gather over ~200 GB of mmap'd expert weight
achieves **69% of what the same memory gives a sequential read**, not the 56%
the previous model implied. The borrowed constant was pessimistic by a fifth,
and every projection below that uses it is correspondingly low.

The remaining 31% is still the largest unexplained quantity here, and it is
what `-thp` would test.

### What the runs actually returned

| configuration | steady state | notes |
|---|---:|---|
| 6 expert layers (4+2), engram cached | 20.14 tok/s | the DDR4 ceiling, not a real workload |
| 8 expert layers (6+2), varied prompts | **~20.1 tok/s** | four prompts, settled |
| 8 expert layers (6+2), first run after load | 9.28 tok/s | GPU0 at 46.2 of 49.1 GB |

The projection said 17.4 and the machine returns about 20. The guess that
prompted this document was 20 tok/s, which turned out to be better than the
arithmetic.

**Measuring this correctly took two corrections.** The first run let the model
stop where it liked and got a 19-token sample, in which one-time cache warming
dominated everything. The second repeated an identical prompt at temperature
0 — which generates identical tokens, touches identical engram rows, and finds
them all in the page cache the second time: 20.14 tok/s at **zero** major
faults, a number the model cannot produce on work it has not already done.
Both are in [`configs/bench-serve.sh`](../configs/bench-serve.sh) now as
comments, because both looked like results.

The honest protocol is a different prompt per run, and it exposed something
neither cold nor warm showed: major faults fall from 38.6 to 9.4 per token
across four *different* prompts. Engram has locality. Common n-grams recur
across unrelated English text, so the hot rows of a 384-million-row table
converge into the page cache and stay there. The working set is far smaller
than the table.

## Levers that reduce bytes per token

This is the category that matters, because bytes per token from DDR4 is
roughly 80% of the budget and tok/s scales almost linearly against it.

Each row is arithmetic on the measured budget above, at the *borrowed*
64.8 GB/s, assuming 6 GB of KV cache and 4 ms of engram time. Since the
measured figure is 79.8 GB/s, read every projection as a floor — the baseline
row projects 17.4 and the machine returns 20.1, about 16% high.

| change | engine | store | layers on GPU | GB/tok from RAM | projected |
|---|---|---:|---:|---:|---:|
| baseline, Q3_K_M, 6 of 384 | **mainline** | 258.8 GB | 9.6 | 3.08 | 17.4 → **20.1 measured** |
| `-ser` 5 active experts | ik only | 258.8 GB | 9.6 | 2.56 | 20.2 tok/s |
| `-ser` 4 active experts | ik only | 258.8 GB | 9.6 | 2.05 | 24.0 tok/s |
| `-ser` 3 active experts | ik only | 258.8 GB | 9.6 | 1.54 | 29.6 tok/s |
| REAP 256E (a published variant) | either | 172.5 GB | 14.4 | 2.59 | 20.0 tok/s |
| experts at ~3.0 bpw | ik quants | 203.8 GB | 12.2 | 2.22 | 22.6 tok/s |
| experts at ~2.4 bpw | ik quants | 163.0 GB | 15.2 | 1.58 | 29.1 tok/s |

Only the first row runs today. Everything with a larger number needs the ik
architecture port, which is what makes that port the critical path rather than
the conversion work.

**`-ser`, smart expert reduction, is the cheapest thing on this list** — an
ik_llama flag that changes how many experts run, with no new file. ik's own
documentation calls it "basically REAP from just command line." It is a
quality trade and the size of that trade is unmeasured here; it is also the
only lever that can be swept in an afternoon without downloading anything,
which makes it the right first experiment.

**Expert pruning (REAP) does not reduce bytes per token at all** — this is
worth stating because it looks like it should. Dropping 384 experts to 256
leaves the same 6 running, so the active bytes are identical. What it buys is
that a third of the store disappears, so a larger *fraction* of it fits in
VRAM: 14.4 layers instead of 9.6. The gain is real and indirect. Someone has
already published `DeepSeek-V4.1-Flash-REAP-256E`.

**Lower-bit experts are the largest single lever**, and the least available.
The expert tensors here average 3.81 bits per weight; ik_llama's IQ2/IQ3
quants would put them near 2.4–3.0, which both shrinks the per-token read and
fits more layers in VRAM — the two effects compound. It requires ik_llama to
support this architecture, which it does not yet, and it requires quantizing
510 GB of original weights, which is why those are downloading now.

## Levers that raise the 69%

These do not change what is read, only how fast it arrives. None of them is
quantified for this workload and one of them may be large.

**Transparent huge pages (`-thp`, ik only).** 200 GB of expert weight in 4 KB
pages is 50 million page-table entries, and a token gathers randomly across
all of them. Every gather is a likely TLB miss. 2 MB pages would cut the entry
count by 512×. This machine's THP is set to `madvise`:

```
$ cat /sys/kernel/mm/transparent_hugepage/enabled
always [madvise] never
```

which means huge pages are only handed out to a process that asks — so the
flag is not redundant with the system setting, it is the thing that activates
it. This is the most interesting unmeasured item on the page, because it is a
plausible explanation for part of the missing 31% and it costs one flag.

**`-rtr`, run-time repack, conflicts with this model.** It repacks tensors
into layouts the CPU kernels prefer, and reportedly helps. It also disables
mmap. Without mmap the engram tables cannot stay on the drive, and 84.6 GB of
engram plus ~197 GB of experts is 282 GB against 251 GB of RAM. **`-rtr` and
NVMe-resident engram are mutually exclusive here.** Whether the repack is
worth more than the engram offload is a question, not a conclusion.

**NUMA is ruled out.** The guides all recommend NUMA binding and
`--numa distribute` for large CPU offload. This is a single-socket
Threadripper PRO reporting one node:

```
available: 1 nodes (0)
node 0 size: 257559 MB
```

There is nothing to bind. Worth recording so the next person does not spend an
evening on it.

**Read-ahead amplification is already handled.** A concern going in was that
mmap'd engram rows — 110 bytes each — would each drag in 64 KB of read-ahead
(`RA 128` sectors on both drives). The v41 branch sets `POSIX_MADV_RANDOM` on
lazy ranges (`src/llama-mmap.cpp:506`), which suppresses it. One fewer thing
to fix.

## Prefill, which was being measured wrong

The first runs reported prefill at 39–46 tok/s, which is not a prefill figure
at all: the benchmark's prompt was 24 tokens, far below the point where batch
throughput means anything, and in a MoE it is worse than that. A 24-token
batch routes to up to 144 distinct experts per layer against a single token's
6, so a short prefill reads an order of magnitude more weight per token than a
decode step does. Dividing by 24 produces a number that describes fixed
overhead.

Measured properly, prefill rises with prompt length and settles:

| prompt | prefill |
|---:|---:|
| 18 tokens | 30.2 tok/s |
| 133 | 46.6 tok/s |
| 535 | 117.5 tok/s |
| 2135 | 150.0 tok/s |
| 4281 | 160.6 tok/s |

That was still low, and two settings were holding it down. **`-np 4` costs
prefill**: it splits the context into four slots and turns off the unified KV
cache, and removing it took the 4288-token figure from 160 to 214 tok/s.
**`-ub 512` costs much more.** Prompt processing is compute-bound and batched,
so a larger micro-batch amortizes each expert tensor read across more tokens:

| configuration | prefill @ 4288 tok | decode |
|---|---:|---:|
| 8 expert layers (6+2), `-ub 512` | 214.0 tok/s | 16.35 tok/s |
| **6 expert layers (4+2), `-ub 2048`** | **344.2 tok/s** | 16.47 tok/s |
| 4 expert layers (CUDA0 only), `-ub 3072` | 245.2 tok/s | 15.75 tok/s |
| 4 expert layers (CUDA0 only), `-ub 4096` | 282.8 tok/s | 14.98 tok/s |

**61% more prefill for no decode cost**, which is a better return than
anything in the lever table above and needed no new engine, file, or flag that
did not already exist.

The ceiling is set by the smaller card. `-ub 3072` fails like this:

```
ggml_backend_cuda_buffer_type_alloc_buffer: allocating 13864.60 MiB on device 1:
  cudaMalloc failed: out of memory
graph_reserve: failed to allocate compute buffers
```

The prefill compute buffer scales with micro-batch and lands on CUDA1, the
24 GB card, so micro-batch and expert layers compete for the same memory.
Freeing GPU1 entirely — no experts on it at all — allowed `-ub 4096` and made
prefill *worse* (282.8), because its layers then do attention with their
experts across the bus. Two expert layers on the small card and a 2048
micro-batch is the balance point on this pair of GPUs.

Context length is the other side of the same trade, and it is a clean one:

| | decode, short context | prefill @ 4288 tok |
|---|---:|---:|
| `-c 32768 -ub 1024` | 19.89 tok/s | 187.8 tok/s |
| `-c 16384 -ub 2048` | 19.97 tok/s | **343.4 tok/s** |

Doubling the context costs **45% of prefill and buys nothing in decode**.
Quantizing the KV cache does not recover it — `-c 32768 -ub 2048 -ctk q8_0
-ctv q8_0` still fails to allocate, because what does not fit is the compute
buffer, not the cache. So the serving config takes 16k, and a 32k session is
a deliberate choice to halve prompt throughput rather than a free default.

## Levers that amortize the read

**Speculation.** Reading a layer's experts costs nearly the same for two
tokens as for one, so verifying drafted tokens is close to free on the memory
side — which is why the V4 run gained 24.6 → 29.1 tok/s from a draft model at
depth 2, and lost it again at depth 3 as acceptance fell. Applying that same
1.18× gives about **20.5 tok/s**.

V4.1 has no DSpark draft model published. It does ship an MTP module —
`mtp.0.*`, a complete MoE layer, present in the original safetensors — but the
GGUF conversion dropped it: there is no `deepseek41.nextn_predict_layers` key
and the 1046 tensors account for the main model exactly. Restoring it is a
conversion change, and the branch's own most recent commit is
`gguf-py : fix the DEEPSEEK41 tensor list so V4.1 can actually convert`, which
suggests the tensor list is exactly where it went missing.

**Concurrency.** The same V4 run measured 47 tok/s aggregate across 4
concurrent requests against 29 for one. If the goal is a served endpoint
rather than one fast stream, this is the biggest number on this page and it
requires no changes at all.

## What cannot be done from the command line

The obvious refinement — put the *most frequently routed* experts on the GPU
rather than whole layers — is not available, and the reason is in the file:

```
blk.0.ffn_gate_exps.weight   Q3_K   [5120, 2304, 384]
blk.0.ffn_down_exps.weight   Q5_K   [2304, 5120, 384]
blk.0.ffn_up_exps.weight     Q3_K   [5120, 2304, 384]
```

All 384 experts of a layer are **one tensor**. `-ot` matches tensor names, so
its finest granularity is "every expert in this layer, or none of them." Since
expert routing in a MoE is skewed, and VRAM currently holds 24% of the expert
store, a frequency-ordered placement could plausibly serve far more than 24%
of routes from VRAM. Getting there means changing the engine, not the flags —
which is the argument for the placement planner described in the companion
document, now with a measurement behind it.

## A risk that is not a lever

197 GB of experts and 84.6 GB of engram are both mmap'd, totalling 282 GB
against 251 GB of RAM. The intent is that engram stays on the drive, but the
kernel does not know that: engram pages entering the page cache can evict
expert pages, and an evicted expert page turns a 47 ms token into a much worse
one. Whether `--lazy-mode` marking is enough to prevent this, or whether the
engram ranges need `MADV_DONTNEED` after use, is unknown. It is the first
thing to watch when the model finally loads, alongside the resident set size
itself.

## The order to try things in

1. ~~**Run it.**~~ Done. 20.1 tok/s steady state on mainline, and the
   measured 79.8 GB/s replaces the borrowed 64.8.
2. ~~**Confirm the premise.**~~ Done, and it holds: resident set 215 GB
   against a 347 GB file. The engram tables are on the drive, costing
   3.3 ms per token — 6.3% of the budget, and cheaper than expected because
   the hot rows cache.
3. ~~**Push the `-ot` split.**~~ Done, and it is nearly exhausted: 8 layers
   fit at 32k context and the ninth does not. The measured slope is
   **+0.27 tok/s per layer**, about half the predicted +0.5, so the
   remaining headroom is worth under 1 tok/s even if it could be found.
4. **Recover the VRAM the KV cache is holding.** `-ctk q8_0 -ctv q8_0`, or a
   smaller `-c`, is the only way left to fit more expert layers on mainline.
   Given the measured slope this is worth about +0.5 tok/s, which is honest
   rather than exciting.
5. **Concurrency.** Untested here and the largest number available without
   changing engines — the previous model gained 1.6× aggregate at four
   streams.
6. **The ik architecture port**, which unblocks `-ser`, `-thp`, `-rtr` and the
   low-bit quants in one move. Every projection above 20 tok/s is behind it.
7. Then MTP conversion and requantization.

Steps 4 and 5 run on mainline today. Everything past them needs the port,
which the measured slope has now turned from an optimization into the only
remaining lever of any size.

## Sources

The ik-specific flags and their descriptions come from
[ik_llama.cpp's parameter documentation](https://github.com/ikawrakow/ik_llama.cpp/blob/main/docs/parameters.md)
and the project's
[news wiki](https://github.com/ikawrakow/ik_llama.cpp/wiki/Previous-Latest-News);
the placement and batching practices from
[a community guide to large MoE models across CPU+GPU](https://gist.github.com/DocShotgun/a02a4c0c0a57e43ff4f038b46ca66ae0)
and [discussion #532](https://github.com/ikawrakow/ik_llama.cpp/discussions/532).
The mmap trade-off around `-rtr` is described in
[discussion #323](https://github.com/ikawrakow/ik_llama.cpp/discussions/323).
None of their numbers were taken for this machine; they are here as claims to
test, not results.
