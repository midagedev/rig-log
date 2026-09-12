# Two NVMe drives, and the benchmark that kept measuring the cache

**2026-09-12.** A 4 TB Phison E18 was added to this machine today. Measured
against the 2 TB Samsung 980 PRO already in it, the useful difference is not in
the burst numbers everyone quotes — those are within a few percent of each
other — but in what happens after about four minutes of writing, which is
exactly the regime this machine works in when it moves a 155 GB model file.

Everything below was measured on the machine in [the README](../README.md) on
this date, with `llm.service` stopped and the page cache dropped before each
run. The harnesses are [`configs/disk-bench.sh`](../configs/disk-bench.sh) and
[`configs/disk-sustained.sh`](../configs/disk-sustained.sh).

Both drives are on PCIe 4.0 x4 and negotiate the full link:

```
23:00.0  Phison E18   LnkCap: Speed 16GT/s, Width x4   LnkSta: Speed 16GT/s, Width x4
2c:00.0  Samsung      LnkCap: Speed 16GT/s, Width x4   LnkSta: Speed 16GT/s, Width x4
```

## Burst, which says almost nothing

32 GiB per test, O_DIRECT, libaio, one job.

| | Phison E18 4 TB (empty) | Samsung 980 PRO 2 TB (36% full, root) |
|---|---|---|
| seq write 1M QD8 | 5.23 GB/s | 5.23 GB/s |
| seq read 1M QD8 | 6.00 GB/s | **7.09 GB/s** |
| rand read 4K QD32 | **152,519 IOPS** | 138,773 IOPS |
| rand read 4K QD1 | 15,836 IOPS, 0.056 ms | **18,038 IOPS, 0.048 ms** |
| rand write 4K QD32 | **137,888 IOPS** | 97,883 IOPS |
| temperature, before → after | 49 → 50 °C | 35 → 39 °C |

The Samsung reads faster and answers a single queued 4K read sooner; the Phison
takes more random writes. On sequential writes they are identical to two
decimal places, which is the first hint that 32 GiB is not measuring either
drive — it is measuring both drives' SLC write caches, and those happen to
saturate the same part of the path.

One real difference does show up here. The Phison's p99 latency on sequential
1M writes is 11.3 ms against the Samsung's 1.5 ms, and on reads 10.4 ms against
1.2 ms. Average throughput hides that entirely.

## Sustained, which is the whole story

Write until the cache runs out, and report every ten seconds. Both drives
TRIMmed and left idle three minutes first, so the comparison starts from the
same kind of state.

**Samsung 980 PRO 2 TB — 400 GiB:**

```
 40s   5.16 GB/s
 50s   3.67 GB/s     <- transition
 60s   1.48 GB/s
...
170s   1.47 GB/s
overall 2.45 GB/s over 175 s
```

**Phison E18 4 TB — 1400 GiB:**

```
 60s   5.74 GB/s
 90s   3.74 GB/s     <- transition
...
360s   3.70 GB/s
overall 4.16 GB/s over 361 s
```

| | cache phase | cliff at about | floor after it |
|---|---|---|---|
| Phison E18 4 TB, empty | 5.74–5.85 GB/s | 430 GiB | **3.70 GB/s** |
| Samsung 980 PRO 2 TB, 36% full | 5.16 GB/s | 230 GiB | **1.47 GB/s** |

The floor is where the drives actually differ, and by two and a half times. Two
things produce that and only one of them is a verdict about the hardware: the
Phison has twice the NAND dies to fold data into, and it was empty while the
Samsung was 36% full, which shrinks a dynamic SLC pool. This is a fair
statement about these two drives in this machine today. It is not a fair
statement about the two products.

There is a third state worth recording, because it is the one a busy machine is
usually in. Running 1400 GiB on the Phison **immediately after** a 400 GiB run,
with no TRIM and no idle, gives a flat 3.09 GB/s from the very first ten-second
window — no cache phase at all, and 17% below the 3.70 GB/s floor the same
drive reaches when rested. Recent write history costs more than position within
a transfer does.

## The mistake, twice

The first Samsung run was 200 GiB. It reported a flat 5.16 GB/s and no cliff.
The first clean Phison run was 400 GiB. It reported a flat 5.85 GB/s and no
cliff. Both were about to go into this entry as "no cliff observed."

The cliffs are at 230 GiB and 430 GiB. Each run stopped just short of the one
it was looking for, and a benchmark that stops before the cliff does not report
a fast drive — it reports the size of the cache, in units of throughput, and
gives no sign that is what it did. Both runs looked *more* trustworthy for
being flat.

What caught it was running the two drives at the same size rather than at a
size chosen per drive. The Samsung cliff appeared when its run was extended
from 200 to 400 GiB for comparability, and finding it there is what made the
Phison's flat 400 GiB suspicious enough to re-run at 1400.

So: a sustained-write test needs a stopping rule tied to the drive's behaviour,
not to a number that seemed big. Write until the rate has been flat for several
minutes *after* a transition, or until it is clear the drive has none.

## What it means here

The model library is 587 GB and lives on the root disk. Moving it to the
Phison takes roughly two minutes — about 430 GiB at 5.7 GB/s, the rest at
3.7 — against roughly four and a half on the Samsung, and it gets bulk writes
off the disk holding the operating system. The decision was already right for
space; the write floor makes it right twice.

The tail-latency result argues the other way for anything latency-sensitive,
and the root filesystem is exactly that. Leaving the OS on the Samsung is the
correct split.
