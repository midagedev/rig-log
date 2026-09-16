# Engram, finished: concurrency is free, the row-wise path earns its keep, and the faults are not on the critical path

*2026-09-16, 09:10–10:00.* Two engram questions were still open on the V4.1
experiment list, and one of them was open in the wrong way. The plan's E4
asked what four concurrent streams do to engram, with a stated prediction and
a stated falsification: *"four streams at different positions need four
different sets of engram rows, so major faults per token should stay roughly
constant while tok/s rises. If they scale super-linearly instead, engram is a
concurrency bottleneck and that is a new finding."* The other was the
follow-up WKS-20 left behind — pin the tables in RAM and compare — and that
one is closed by arithmetic rather than by measurement.

Every arm below ran on the served file (the WKS-13 attention graft) at the
served seven-layer placement, one server start per arm, behind the GPU lease,
with the I/O pressure recorded at each start. **Each arm got prompts that
nothing on this box had used**, because a shared prompt lets a later arm read
engram rows an earlier arm already pulled into the page cache, which would
have made the whole comparison meaningless.

## RAM pinning is not available, and that is the answer

WKS-20 measured the row cost at 6.8 % of decode and wrote "RAM pinning is the
follow-up". It is not a measurement this box can take. The two engram tables
in the served file are `blk.1.engram_embd.weight` and
`blk.14.engram_embd.weight`, **97.3 GiB each at Q8_0** — 195 GiB for the pair,
against 251 GB of RAM that already has to hold thirty-three expert layers at
about 6.5 GB each. There is no configuration in which both tables are resident
and the model still serves. That is not a limitation to work around; it is the
premise the lazy path was built on, now stated in bytes.

## E4: concurrency is close to free, and engram does not notice it

| streams | aggregate | per stream | major faults a token | total faults during decode |
|---:|---:|---:|---:|---:|
| 1 | 19.1 tok/s | 19.1 | 22.6 | 6 587 |
| 2 | 21.7 | 11.1 | 25.9 | 15 564 |
| 4 | **26.3** | 7.0 | **24.2** | 27 917 |

The prediction held. Faults per token are flat across a fourfold change in
concurrency — 22.6, 25.9, 24.2 — while the total climbs in proportion to the
tokens produced. Four streams at four different positions really do read four
different sets of rows, and the per-token cost of doing so does not change.
Engram is not a concurrency bottleneck, and the falsifying outcome the plan
named did not occur.

The aggregate gain is 1.38×, against the 1.6× the previous model measured
(47 tok/s against 29). Per-stream throughput collapses from 19.1 to 7.0, so
this is a throughput lever and not a latency one.

### The control, because the first reading of this was confounded

The three arms ran in order, and their load times fell 208 → 171 → 130 s: each
arm started with warmer weights than the one before, so part of the aggregate
rise could have been the cache rather than the concurrency. That confound was
recorded before it was resolved, and then resolved: **np1 re-run last, on the
warmest cache of the day** (load 77 s), with a prompt nothing had used.

| np1, same configuration | decode | load | faults a token |
|---|---:|---:|---:|
| first, coldest | 19.1 tok/s | 208 s | 22.6 |
| last, warmest | 18.8 | 77 s | 56.6 |

One stream stays at 19 tok/s whatever the cache holds, so the 1.38× is real.
The caveat is withdrawn.

### The faults are not on the critical path

That control table carries a second result worth more than the first. Between
those two runs the faults per token went **22.6 to 56.6, a factor of 2.5, and
the decode rate did not move** — 19.1 against 18.8. The plan's worst case
reasoned that 48 serial page faults at 0.056 ms each would be 2.7 ms a token
against a 3.6 ms budget, which would have been most of the decode. It is not
happening: the faults are being overlapped, prefetched, or absorbed, and their
count is a poor predictor of the rate. Anyone tuning this configuration by
watching `maj/token` alone would be tuning the wrong number.

## The row-wise path against plain mmap, and a trap in the placement string

The branch's `--lazy-mode` has an `off` setting, so the special row-wise read
can finally be compared against ordinary mmap of the same tensors. The first
attempt at that arm failed, and the failure is the more useful half:

```
ggml_backend_cuda_buffer_type_alloc_buffer: allocating 232372.03 MiB on device 0:
  cudaMalloc failed: out of memory
```

With lazy mode on or auto, the engram tensors are handled by the lazy path and
never placed. Turn it off and they become ordinary layer tensors — and
`engram_embd` matches no pattern in the documented placement string, whose
catch-all is `exps=CPU`. So `-ngl 99` sends 195 GiB of hash table to a 48 GB
card and the loader asks for 232 GB. **`--lazy-mode` is not only an I/O
optimisation; it is what keeps these tables off the GPU**, and any placement
string that might be used with it off needs `engram_embd=CPU` named
explicitly. The serving script does not name it, which is safe only because
it never turns lazy mode off.

MATCHED_PAIR_PLACEHOLDER
