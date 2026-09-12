# Where the time goes on a 347 GB model, and what would move it

**2026-09-12.** Before running DeepSeek-V4.1-Flash on this machine, this is
what the file itself says about how fast it can go, which levers exist, and
what each one is worth. Almost nothing here is a measurement of V4.1 — the
model has not been run yet. The budget is measured, the calibration comes from
a different model measured on this machine yesterday, and every tok/s figure
below is arithmetic built on those two. Each section says which it is.

The companion piece is
[running a model larger than memory](running-a-model-larger-than-memory.md),
which covers why this model needs the NVMe at all.

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

## The calibration, which is borrowed

There is no measurement of how fast this machine streams expert weights for
*this* model. There is one for the previous model, taken on 2026-09-11:
DeepSeek-V4-Flash at **24.6 tok/s** with no speculation, 32 of its 43 expert
layers in system RAM, about 3.54 GB of active expert weight per token.

That gives an effective figure for the path that matters:

```
2.63 GB/token from RAM ÷ 40.7 ms/token = 64.8 GB/s
```

against the **115.8 GB/s** this machine measures in a STREAM-style read
([README](../README.md)). So llama.cpp's gather over 200 GB of mmap'd expert
weight achieves **56% of the bandwidth the same memory delivers to a
sequential read**. That 56% is itself one of the largest opportunities on this
page, and nobody here has established where the other 44% goes.

Applying 64.8 GB/s to the V4.1 budget: VRAM holds the 4 GB of dense tensors,
a KV cache, and about **9.6 layers' worth of routed experts**; the other ~30
layers are read from DDR4 at 3.08 GB per token, which is **47.4 ms**. Add GPU
work and engram reads and the projection is **16–18 tok/s**.

For comparison, the guess that prompted this document was 20 tok/s. It is at
the optimistic edge rather than wrong.

## Levers that reduce bytes per token

This is the category that matters, because bytes per token from DDR4 is
roughly 80% of the budget and tok/s scales almost linearly against it.

Each row is arithmetic on the measured budget above, at the borrowed
64.8 GB/s, assuming 6 GB of KV cache and 4 ms of engram time:

| change | store | expert layers on GPU | GB/token from RAM | projected |
|---|---:|---:|---:|---:|
| baseline, Q3_K_M, 6 of 384 | 258.8 GB | 9.6 | 3.08 | **17.4 tok/s** |
| `-ser` 5 active experts | 258.8 GB | 9.6 | 2.56 | 20.2 tok/s |
| `-ser` 4 active experts | 258.8 GB | 9.6 | 2.05 | 24.0 tok/s |
| `-ser` 3 active experts | 258.8 GB | 9.6 | 1.54 | 29.6 tok/s |
| REAP 256E (a published variant) | 172.5 GB | 14.4 | 2.59 | 20.0 tok/s |
| experts at ~3.0 bpw | 203.8 GB | 12.2 | 2.22 | 22.6 tok/s |
| experts at ~2.4 bpw | 163.0 GB | 15.2 | 1.58 | 29.1 tok/s |

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

## Levers that raise the 56%

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
plausible explanation for part of the missing 44% and it costs one flag.

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

1. **Run it.** Everything above is built on one borrowed measurement. The
   first real number replaces the 64.8 GB/s assumption and re-ranks this list.
2. **Confirm the premise.** Resident set 84.6 GB below the file size means the
   engram tables stayed on the drive. If not, force `--lazy-mode on`.
3. **Sweep `-ser`** on ik — free, large, and the quality cost is measurable
   with perplexity in the same session.
4. **`-thp`** — one flag, and it tests the huge-page theory for the missing
   44% of bandwidth.
5. **Push the `-ot` split** from the deliberately conservative starting point
   toward the ~9.6 layers the arithmetic allows.
6. Only then the expensive ones: MTP conversion, low-bit requantization, the
   ik architecture port.

Steps 3 and 4 need ik_llama to load this model, which it cannot yet. Steps 1,
2 and 5 do not.

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
