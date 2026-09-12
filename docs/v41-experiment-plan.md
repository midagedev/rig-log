# What to run, in what order, and what would prove it wrong

**2026-09-12.** A plan, written before the first run rather than after it, so
that the numbers it produces can disagree with it.

[The lever survey](raising-tokens-per-second.md) projects **16–18 tok/s** for
DeepSeek-V4.1-Flash on this machine and ranks six ways to raise it. Every one
of those figures rests on a single borrowed constant — 64.8 GB/s of effective
memory bandwidth, back-calculated from a *different* model measured on
2026-09-11. The first purpose of these experiments is to replace that constant.
The second is to find out whether the premise the whole configuration is built
on — that 84.6 GB of engram tables can stay on the drive — is true.

## The protocol every run follows

**The machine must be quiet.** `llm.service` holds both GPUs and 113 GB of
resident model; it stops first. The 510 GB original-weights download writes to
the same NVMe that holds the model, which both evicts expert pages from the
page cache and competes for exactly the IOPS these runs are trying to
attribute to engram — it pauses too. It is resumable by design, so pausing
costs nothing but time.

**Measure with [`configs/bench-serve.sh`](../configs/bench-serve.sh).** It
records, per run: decode and prefill throughput, `VmRSS` split into `RssAnon`
and `RssFile`, major faults, and the model drive's read count and bytes — the
last four as deltas across the run. Throughput on its own cannot distinguish a
run slowed by expert pages missing from the page cache from one slowed by
engram rows coming off the drive; those counters can.

**One variable per run.** The `-ot` split, `-c`, and the quantization each
move VRAM around, and moving two at once produces a number that cannot be
attributed. Where a change is expected to be free, say so in advance and let
the run contradict it.

## E0 — Does it load, and does the premise hold

The only experiment whose result is not a number.

Start the server as [`configs/v41-serve.sh`](../configs/v41-serve.sh) is
written — deliberately conservative, four expert layers on the A6000 and two
on the 3090 — and read the resident set once loading settles.

| outcome | meaning | next |
|---|---|---|
| not-resident ≈ 84.6 GB | engram stayed on the file, as designed | E1 |
| not-resident ≈ 0 | `--lazy-mode auto` did not mark the 42 GB tensors | retry with `--lazy-mode on` |
| load fails or OOMs | the split is wrong, or the branch cannot serve this file | narrow the split, then read the error properly |

`auto` marks tensors above 4 GiB; the engram tensors are 42.2 GB each, so it
should catch them. "Should" is why this is an experiment.

The load itself is worth timing. 347 GB off a drive whose measured sustained
read is around 6 GB/s is a floor of about a minute, and a load much slower
than that says something about how the file is being read.

## E1 — The number that replaces the assumption

A fixed prompt, `temperature 0`, 128 tokens, one stream.

The projection is 17.4 tok/s. What matters is not whether it lands there but
what the run implies about effective bandwidth, which is recoverable from it:

```
effective GB/s = (bytes per token from RAM) / (ms per token)
```

with bytes-per-token known from the measured budget and the `-ot` split. If it
comes back near 64.8 GB/s, the V4 calibration transfers and the whole lever
table stands. If it comes back near 115.8, the gather is not the problem and
most of the table is wrong. If it comes back far below 64.8, something
specific to this model — engram, hyper-connection, the host-side hash — is
eating time that the budget does not account for, and E2 finds it.

## E2 — What engram actually costs

The arithmetic says a token touches about 48 engram rows of 110 bytes each,
which is nothing in bytes and possibly a lot in latency: 48 serial page faults
at this drive's measured 0.056 ms QD1 random read would be **2.7 ms per
token**, against a 3.6 ms budget for the entire rest of the per-token GPU work.

This needs no new run — E1's counters answer it:

- **major faults per token** near 48 means the rows are coming off the drive
  one fault at a time, and the cost is fault latency, not bandwidth.
- **near zero** means the rows are being served from the page cache, which
  would be good for speed and bad for the premise: it means engram is
  competing with expert weights for the 251 GB of RAM after all.
- **drive bytes per token** much above 5 KB means read-ahead is amplifying
  110-byte rows into pages, despite the `POSIX_MADV_RANDOM` the branch sets.

The middle case is the one to watch for, because it is the failure mode that
looks like success.

## E3 — Widen the split until it stops paying

The starting split is six expert layers on the GPUs. The measured budget says
about **9.6** fit once 4.0 GB of dense tensors and the KV cache are placed —
but the KV size for this architecture at 32k is not yet measured, so the
ceiling is a guess and E3 is how it gets found.

Raise the count one layer at a time and record tok/s and free VRAM. Each layer
moves `4.04/40 = 0.101 GB` per token off DDR4, which at 64.8 GB/s is 1.56 ms —
about **+0.5 tok/s per layer** at this speed. That predicted slope is the
point of the sweep: if the measured slope matches, the model of what is
happening is right, and the remaining levers can be trusted. If tok/s is flat
while layers move to VRAM, the bottleneck is not where this document says it
is, and everything downstream needs rethinking.

Stop when a layer fails to allocate, and keep the last configuration that
loaded with headroom to spare. The previous model's entry records the cost of
getting this wrong silently: a draft model that could not allocate its KV
scheduler logged an error on every decode step and ran *slower* than no
speculation, with nothing pointing at VRAM.

## E4 — Concurrency, which may be the largest number here

`-np 4`, four concurrent completions, aggregate throughput.

The V4 run measured 47 tok/s aggregate against 29 single-stream — a 1.6×
that costs nothing but a flag, because a layer's experts are read once and
used by every token in the batch. If the goal is a served endpoint rather than
one fast stream, this outranks every other lever on the list.

It also interacts with engram in a way nothing else does: four streams at
different positions need four different sets of engram rows, so major faults
per token should stay roughly constant while tok/s rises. If they scale
super-linearly instead, engram is a concurrency bottleneck and that is a new
finding.

## E5 — Prefill, separately

Prompt processing is compute-bound and batched, and the previous run found it
moves in the opposite direction from decode: speculation lowered it, and so
did a smaller batch. `-b 4096 -ub 4096` is the documented recommendation for
heavy CPU offload; the current script uses `-b 2048 -ub 512`.

Worth one sweep, reported separately from decode, because a configuration that
is right for one can be wrong for the other and this repo has already published
a table where that happened.

## Blocked, and on what

These are the large levers, and none of them can run yet.

| experiment | what it would settle | blocked on |
|---|---|---|
| `-ser` sweep, 6 → 5 → 4 → 3 experts | the cheapest 1.4× available, and what it costs in perplexity | ik_llama cannot load `deepseek41` |
| `-thp` | whether huge pages recover part of the missing 44% of memory bandwidth | same |
| `-rtr` | whether repacking beats keeping engram off RAM — they are mutually exclusive | same |
| MTP restored in conversion | speculation, projected 1.18× | a conversion change; original weights downloading |
| experts at ~2.4 bpw | the largest single lever, projected 29 tok/s | ik support, plus requantizing 510 GB |

The ik architecture port unblocks the first three at once, which is the
argument for doing it before the conversion work rather than after.

## What this plan is not measuring

Quality. Every lever in the middle of the table — fewer active experts, pruned
experts, lower-bit quantization — buys speed with accuracy, and none of the
runs above would notice. A perplexity baseline on this file, taken once while
the machine is quiet, is what makes those trades comparable later. It is not
on the critical path to a first number, and it should not be skipped on that
basis.
