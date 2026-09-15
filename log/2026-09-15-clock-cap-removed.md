# The clock cap comes off, and a hero take without it

**2026-09-15, 16:00.** The 2.7 GHz CPU cap that has been on this machine
since 2026-09-13 (`configs/cpu-clockcap.service`, re-applied at every
boot) and the boost lock (`cpu-noboost.service`, already disabled) are no
longer applied: the user's instruction today was that performance limits
are no longer needed. The cap was a thermal measure for the AIO loop, and
the loop is gone (2026-09-14). `cpu-clockcap.service` is now disabled; the
unit file and the script stay in `configs/` as the record of what ran.
`thermal-guard.service` stays — it stops LLM load on CPU or GPU
over-temperature and is a safety net, not a limit.

Two facts about what "uncapped" means on this board. `acpi-cpufreq`
exposes three P-states (3.6 / 2.7 / 1.8 GHz) and refuses any
`scaling_max_freq` above 3.6, so the interface reads 3.6 GHz either way;
with `boost` at 1 the cores turbo above it, and single threads were seen
at 4.54 GHz during the take below. The 3.6 GHz "recording mode" of the
old hero recipe was therefore a hard cap; today's runs are not.

## The hero take, uncapped

The toktape session asked for a hero-grade take of the served V4.1 profile
(`rig-log-v41-serve-hero64.sh`: DSpark draft block 3, reasoning budget
64, engramQ8 / tokembdBF16 target) for the recorder's README. Warm-up
5 × 500 tokens single-stream: 20.5 / 21.7 / 20.7 / 21.7 / 27.1 tok/s.
Then one run, `toktape --sessions 2 --think-budget 64 --for 30s`,
recorded with [toktape](https://github.com/midagedev/toktape)
v0.2.1-3-ga1eafc6; the clip and card are rendered on the toktape side
from the tape.

| take 16:03:37, two streams, 30 s | |
|---|---|
| decode | **12.8 tok/s per stream**, 25.7 aggregate (09-14 hero at the 3.6 GHz cap: 11.2 per stream) |
| draft | 57 % accepted (331/576), 194 verify steps of 4.0 tokens, ≈ 119 GB/s from RAM per step |
| prefill | 279 prompt tokens, TTFT p50 9.47 s |
| VRAM | 45.8 / 20.9 GiB; host RSS 197.5 GiB, 0.6 major faults a token |
| CPU, prefill window (11 s) | mean over 64 threads 2.7 GHz (2.1–3.6), single thread up to 4.54 |
| CPU, decode window (20 s) | mean 3.44 GHz (3.24–3.65), single thread up to 4.30 |
| Tctl | 61 °C at start, 62–65 °C throughout, 61.6 °C after; thermal guard silent; card `throttled: no`, `contended: no` |
| GPUs | llama-server only; io pressure avg10 0.01 at start |

The per-stream number is 14 % above the capped hero's. This take does not
separate the two candidate causes — the clock, and the serving profile,
which changed since 09-14 (engram tensors at Q8_0, bf16 token embedding
for the draft, the re-balanced expert placement). The 09-13 measurement
that 2.7 and 3.6 GHz decode identically says the clock is the less
likely one, and the all-thread mean during decode was at or below 3.6
anyway; the honest statement is "uncapped, turbo engaged", not "faster
because uncapped". Tctl of 65 °C under a 32-thread decode with turbo is
22 °C above the same load under the cap on the new cooler, and 24 °C
below where the old loop warned.

Witness files: the tape and card, `runs.tsv`, and the 2 s clock/Tctl CSV
went to the toktape session's scratch directory; the run scripts are
`hero-ready3.sh`, `hero-take3.sh`, `hero-clock3.sh` on the machine.
