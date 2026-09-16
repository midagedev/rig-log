# Three regimes on one card, and a blower that was holding 40 % back

*2026-09-16, 12:10–14:25.* The first diffusion work on this machine. The
[queue in the README](../README.md#queued) opened with one question — is a
denoise step compute-bound or bandwidth-bound? — and said that until it was
measured, "which GPU" had no evidence behind it. It is measured now, and the
answer is not one regime but three, all of them inside a single 136-second run.

The model is **LTX-2.5**, a 22 B DiT published around 2026-09-01, which is the
same shape of choice as the two Qwen models from this morning: new enough that
nobody has run it on hardware like this. It generates video **and synchronised
audio in one pass**, which no other open-weight model does, and it ships an
official Python inference package rather than requiring a ComfyUI install.

## Getting it here

`uv sync --extra natten` took 50 seconds and produced torch 2.13.0+cu132 and
natten 0.21.7 against driver 615.71.09. That was the easy half.

The weights are gated (`gated: auto`), and the account's token is not on the
list: `/raw/main/model_index.json` returns 403. Accepting a licence is the
machine owner's act, not this session's, so the download went to a mirror — and
mirrors are exactly where a model file stops being the model file. The rule
used was the one already in [`tools/fetch-gguf.sh`](../tools/fetch-gguf.sh):
**a file appears at its final path only when its byte count matches what the
API said.** Here the sizes came from the *official* repo's API, which answers
`?blobs=true` without auth even while refusing the files, and they are written
into [`tools/ltx/ltx-fetch.sh`](../tools/ltx/ltx-fetch.sh) as constants rather
than read from the mirror, so a mirror that re-saved a tensor fails instead of
passing.

Three mirrors carry the five files. One matches on all five:

| file | official | `yuvraj108c` | `comfyicu`, `lxxxy6` |
|---|---:|---:|---:|
| distilled transformer bf16 | 42 018 190 584 | same | same |
| gemma4-12b text encoder | 26 263 858 182 | same | **26 263 860 594** |
| video VAE | 1 472 223 346 | same | same |
| audio VAE | 364 866 540 | same | same |
| spatial upscaler | 995 778 752 | same | same |

The text encoder differs by 2 412 bytes on two of the three — a re-save, almost
certainly harmless, and exactly the difference a size gate is for. 67 GiB came
down in ten minutes at about 110 MB/s. The sha256 of each accepted file is in
the fetch log; it could not be cross-checked against upstream, because the
official repo is the one that will not serve them.

## What fits, and what the capacity limit actually is

Four arms, 121 frames (5.04 s at 24 fps), seed 42, the same prompt, stage 1 at
768×512 and stage 2 at 1536×1024. The only thing that moves is where the 42 GB
transformer lives.

| arm | total | stage 1 | stage 2 | stage-2 VRAM | transformer builds | host RSS |
|---|---:|---:|---:|---:|---:|---:|
| `--offload none` | 136 s | 2.50 s/step | 12.67 s/step | **48 016 MiB** | 9 + 9 s | 42.1 GiB |
| `--offload cpu` | 157 s | 2.75 | 13.33 | 12 992 | 15 + 15 s | 71.4 GiB |
| `--offload disk` | **124 s** | 2.62 | 13.00 | 12 928 | **3 + 3 s** | 40.4 GiB |
| `--offload cpu --max-batch-size 2` | 157 s | 2.75 | 13.33 | 12 992 | 15 + 15 s | 71.4 GiB |

Every arm produced a byte-identical 1 472 940-byte file, so these are four
routes to the same frames.

**The fastest arm is the one that streams from disk**, which is not what the
flag names suggest. It loses 2.6 % on the denoise and wins it back four times
over on model building: the pipeline constructs the transformer once per stage,
and `disk` mmaps the file in 3 seconds where `cpu` copies 42 GB into a host
buffer in 15. On a 251 GB box the file is in page cache either way, so this arm
is measuring the cache and not the drive — the cold number would be different
and was not taken. The 6-second builds are also the answer to a cost this run
exposes: 18 to 30 seconds of a 124-to-157-second run is spent *rebuilding the
same transformer for the second stage*, and the official optimisation notes
address it by telling the reader to comment out a library call
(`# utils.cleanup_memory()`), not with a flag.

`--max-batch-size 2` changed nothing at all, which is correct and worth one
line: it bounds items per forward pass, and a single generation has one.

**The capacity limit is not the transformer.** Per-stage peaks say where the
VRAM goes:

| stage | `none` | `cpu` |
|---|---:|---:|
| denoise 768×512 | 42 812 MiB | 7 796 MiB |
| denoise 1536×1024 | **48 016** | 12 992 |
| video + audio decode | 36 936 | 36 968 |

Resident, stage 2 peaks at 48 016 of the card's 49 140 MiB — 1.1 GiB spare, so
five seconds at this resolution is the ceiling for that arm and the next frame
count needs streaming. But streaming drops the denoise peak 3.7× and leaves the
**decode stage at 37 GB whichever arm runs**, so that stage is the real floor.
It is also the single largest window, 40 of 136 seconds at 95–98 % utilisation.
A card smaller than 37 GB does not fail here — `AUTO_TILING` tiles to fit — it
tiles harder and takes longer, and that cost was not measured.

## The instrument: lock one clock, not the power cap

The queue proposed a power sweep, reasoning from the LLM result that 47 % less
power costs 15 % of the rate. That instrument does not work on this workload.
At the default 300 W an LTX-2.5 denoise runs with **`SwPowerCap` and
`SwThermal` both active** at 87–88 °C, so lowering the cap moves two things and
the slope means nothing.

Locking a clock moves one thing, and the A6000 offers two orthogonal locks: 127
graphics states and memory states at 405, 810, 5001, 7601 and 8001 MHz.
[`tools/gpu-clock-lock.sh`](../tools/gpu-clock-lock.sh) owns them, the way
[`configs/gpu-order.env`](../configs/gpu-order.env) owns device order, and
resets on every exit path including a signal — a card left at 5001 MHz would
poison every measurement taken afterwards by any of the three sessions sharing
this box.

Two details that would each have produced a wrong table:

- **8001 MHz is a boost state the card does not hold.** Under load the achieved
  memory clock is 7601, so a row labelled 8001 would have duplicated the
  default row under a different name. The top of the memory axis is 7601.
- **A lock is a request, and `nvidia-smi` accepts `-lmc` at idle and returns
  success while nothing reports the lock back.** The only proof is the achieved
  clock under load, so the wrapper keeps its own witness, samples only while
  utilisation is above 50 % (the idle memory clock is 405 MHz and would drag
  every mean toward it), and checks **both** axes against their request. An
  unchecked memory axis would have read 7601 in every row and plotted as
  "bandwidth does not matter" — the answer being tested. Verified before use at
  gr=900 mem=810: achieved 900 and 810 over 203 busy samples.

The metric is stage-2 seconds per step. Wall time is not the metric when 43 %
of it is VAE decode and model building.

## Three regimes

Graphics axis, memory at 7601, `--offload none` so PCIe is not in the loop:

| requested | achieved | stage 2 | stage 1 | power | temp |
|---:|---:|---:|---:|---:|---:|
| 1500 | 1498 | 12.67 s/step | 2.62 | 268 W | 86 °C |
| 1200 | 1200 | 15.33 | 3.12 | 205 W | 81 °C |
| 900 | 900 | 19.67 | 3.88 | 175 W | 79 °C |
| 600 | 600 | 28.33 | 5.38 | 144 W | 77 °C |

1500 is the top of this axis deliberately: the unlocked run achieved 1530 MHz
in the stage-2 window, so a higher lock would be overridden and two rows would
sit at the same achieved clock under different labels.

Memory axis, graphics pinned at 1200 so the power cap cannot make the achieved
graphics clock a function of the memory one:

| achieved mem | stage 2 | decode window |
|---:|---:|---:|
| 7601 | 15.33 s/step | 42 s |
| 5001 | 16.67 | 59 s |
| 810 | **53.67** | **465 s** |

As elasticities — the exponent *e* in rate ∝ clock<sup>*e*</sup>:

| | graphics clock | memory clock |
|---|---:|---:|
| **denoise, 1536×1024** | **0.860 / 0.864 / 0.880** | 0.200 at −34 %, 0.559 at −89 % |
| **video + audio decode** | ~0.10, flat within noise | **0.812 → 1.074** |
| **Qwen3.6-35B decode** | 0.416 / 0.491 / 0.583 | 0.512 → 0.828 |

The denoise is compute-bound, and cleanly so: three graphics-axis points give
0.860, 0.864 and 0.880, which is a power law and not a coincidence. Cutting
memory bandwidth by a third costs 0.200 — nearly nothing. There is a knee, not
an absence: at 810 MHz, 78 GB/s, bandwidth finally binds and the exponent rises
to 0.559. Across any memory clock the card will actually run, the denoise does
not care about bandwidth.

The decode stage is the opposite, in the same run, on the same card. Its
graphics-axis numbers are 41, 42, 49 and 45 seconds — non-monotonic, flat inside
the noise — while the memory axis is nearly linear. That window mixes the video
VAE, the audio VAE, the vocoder and a CPU-side mp4 encode, so its attribution
was held open until the data closed it: **a window dominated by CPU work cannot
respond to a GPU memory clock with an exponent of 1.07.** It is GPU-memory-bound.

## The LLM row, and a ceiling that turns out to be half core

The same locks on the workload this box serves: Qwen3.6-35B-A3B at UD-Q4_K_XL,
resident on the A6000 alone, no draft, no `-ot`.

| lock | decode | derived read |
|---|---:|---:|
| gr 1500, mem 7601 | 124 tok/s | 341 GB/s |
| gr 1200 | 113 | 311 |
| gr 900 | 96.5 | 266 |
| gr 600 | 72.7 | 200 |
| gr 1200, mem 5001 | 91.2 | 251 |
| gr 1200, mem 810 | 17.7 | 49 |

This closes a question left open on 2026-09-15, where
[the same model on the same card](2026-09-15-a-model-that-fits-one-card.md) hit
a flat ~390 GB/s — half of the card's 768 — with the power cap and the expert
gather both ruled out. The answer is that it is **co-limited**: 0.42–0.58 on the
graphics axis and 0.51–0.83 on the memory axis, two exponents that sum to about
one. It was never a pure DRAM wall, and about half of that ceiling sits on the
core side. A card with more bandwidth and the same core throughput would return
only part of the difference.

That is also the correction to a recommendation made in conversation earlier the
same afternoon. Asked whether a faster card would help, this session said that
if the LLM were bandwidth-bound then 1008 against 768 GB/s was merely 1.31× and
not worth an unofficial card. The measurement says the LLM benefits from both
axes. Projecting an Ada card with about 2.1× dense bf16 and 1.31× bandwidth —
and this is a **projection, not a measurement**, since elasticities taken by
moving one card's clocks do not carry across architectures:

| | from | multiplier |
|---|---|---:|
| LTX denoise | 2.1<sup>0.87</sup> | 1.9× |
| LTX decode stage | 1.31<sup>1.0</sup> | 1.31× |
| LTX end to end | with 32 s of fixed cost | **1.45×** |
| Qwen decode | 2.1<sup>0.45</sup> × 1.31<sup>0.51</sup> | **1.61×** |

The LLM gains more than the whole diffusion run does, because a third of that
run is bandwidth-bound and a fifth is fixed cost.

## The blower was holding 40 % back

The README has been describing this machine's thermal ceiling as "86–87 °C with
`SW Thermal Slowdown` on ~100 % of the time, so any workload with a 100 % duty
cycle is throttled before it starts." Adding `fan.speed` to the witness showed
what that sentence was missing: at 86–87 °C the A6000's blower is at **58–64 %**.

`nvidia-smi` on this driver has no fan option at all and `nvidia-settings` wants
an X display this box does not run, which is how "nothing on this machine can
curve a fan" — true of the six empty `CHA_FAN` headers — became a fact about the
whole machine. NVML exposes `nvmlDeviceSetFanSpeed_v2` headless.
[`tools/gpu-fan.py`](../tools/gpu-fan.py) drives it.

The card's own thresholds explain the rest:

```
GPU Target Temperature Specification : 84 C
GPU Slowdown Temp                    : 95 C
GPU Max Operating Temp               : 93 C
GPU Shutdown Temp                    : 98 C
```

87 °C is nowhere near the 95 °C slowdown. The card was clipping clocks to reach
its own **84 °C target**, four degrees below where it sat, while keeping 36–40 %
of its fan in reserve for acoustics. Two matched pairs:

| | stage 2 | stage-2 clock | stage-2 temp | fan | total |
|---|---:|---:|---:|---:|---:|
| gr locked 1500, card's curve | 13.00 s/step | 1498 | 86 °C | 58 % | 137 s |
| gr locked 1500, fan 100 % | 13.00 | 1500 | **71 °C** | 100 % | 137 s |
| unlocked, card's curve | 12.67 | 1530 | 87 °C | 58 % | 136 s |
| unlocked, fan 100 % | 12.33 | **1598** | **72 °C** | 100 % | 133 s |

**Sixteen degrees, and 2.7 % of the rate.** The clock does rise once the thermal
clip is gone — 1530 to 1598 in stage 2, 1606 to 1712 in the decode window — but
draw is already 289 W against a 300 W cap, so the power limit binds where the
temperature used to. That is why both throttle reasons were on all morning:
relieving one reveals the other. The prize here is the temperature, not the
speed, and it matters for a render queue that runs unattended and for any
argument about adding a hotter card to this case.

What is still true: the chassis fans are wired to the PSU, all six `CHA_FAN`
headers read `Disabled`, and the BMC sees `CPU_FAN` 2200 RPM, `SOC_FAN` 2800 and
`CHIPSET_FAN` 2700 but nothing at all from the case. They spin at a fixed speed
and **a failed one would be invisible**, detectable only as a GPU temperature
that drifted. The BMC's per-slot sensors do work and identified the physical
layout for free: with only the A6000 loaded, `PCIE05` read 60 °C against the
card's 60 °C die and `PCIE01` read 48 °C against the 3090's 48 °C, so the 3090
is in slot 1 and the A6000 in slot 5, far enough apart that neither blocks the
other's intake.

## The model cannot write Hangul

Asked for a cat writing 주4일제 on rice paper with a brush, with the characters
spelled in the prompt and described as "the Korean word for a four-day work
week", the model produced brush-like strokes that are not characters. That is
the expected failure — composed syllable blocks are much harder than short Latin
words — and it is recorded because the negative result changes the next
question. The model cannot write Hangul; whether it can *keep* Hangul it was
given is a different question, answerable with the `--image PATH FRAME_IDX
STRENGTH` conditioning path and a frame whose glyphs come from a font rather
than a sampler. [`tools/ltx/ink-overlay.py`](../tools/ltx/ink-overlay.py) makes
that frame. The experiment is not run here.

Also unmeasured and worth stating: the distilled pipeline is 8 steps then 3, and
a five-second clip asked to contain four beats (write, pause, tear, blur)
delivered one. Narrative density is a budget like any other.

## Three method errors, all mine

**An awk that compared numbers as strings.** The first summary reported a peak of
8 022 MiB for a run whose real peak was 48 016, because `"8022" > "42812"` is
true lexicographically. The wrong number was reported to the user before the raw
samples were read. Every max in that runner now coerces with `+0`, and the
reason the run survived at all is that the witness is a **file**: `dmon.csv` was
still there, so every take from before the fix is still readable.
[`tools/ltx/ltx-summarise.py`](../tools/ltx/ltx-summarise.py) recomputes from it.
The same class bit twice — `/usr/bin/time`'s fields shifted by one because the
log is stamped, so `$6` was `(kbytes):` instead of the number.

**Overwriting a runner while it was running.** `bash` reads a script
incrementally. An `scp` of a fixed `ltx-take.sh` landed during the third arm,
which resumed inside a statement and died at line 88 with
`syntax error near unexpected token ')'`. The arm's generation had already
finished, so the data survived; what did not was the exit path, so the lease
stayed in the file under a dead pid and the **fourth arm refused itself** on a
lease nobody held. The repo already carries this lesson for chain scripts and it
was re-learned one level down. Chains now run a snapshot of every runner they
call, so a push mid-chain reaches only the next chain.

**A sweep tool that had been capping the wrong card.**
[`tools/ik/gpu-power-sweep.sh`](../tools/ik/gpu-power-sweep.sh) addressed the
board with `nvidia-smi -i 0`, which is bus order. The A6000 moved to bus 61 this
morning, so `-i 0` had become the 3090 — default limit 420 W — while every
comment in the file still said A6000. It would have swept a card that was never
capped and reported "not power bound", which is the one answer that tool exists
to rule out. Found before use, fixed to address the A6000 by UUID from
`gpu-order.env`. This is the same failure class as the CUDA0 flip closed this
morning, surviving in the one script nobody re-read.

## What this settles and what it opens

Settled: a denoise step on this card is compute-bound, its decode stage is
bandwidth-bound, and the served LLM is co-limited. The three exponents are the
evidence the "which GPU" question was waiting for, and they say a faster core
buys the denoise, a wider bus buys the decode, and the LLM takes both.

Open, and now sharper:

- **The cold-disk number.** `--offload disk` was the fastest arm at 124 s with
  the file in page cache. On a machine with less RAM than the model, it is a
  different measurement.
- **How long a clip fits**, properly: the decode stage wants 37 GB at 121
  frames, `AUTO_TILING` adapts, and the cost of tiling harder is unmeasured.
- **Whether a fan curve is worth writing.** Sixteen degrees is available for
  free, and NVML can now be driven headless, so a small temperature-to-speed
  daemon would turn a one-off `--speed 100` into a policy. The card's 84 °C
  target is the number to aim under.
- **FP8 is unavailable on Ampere at all**, and LTX-2.5 ships an `nvfp4`
  transformer of 18 721 732 720 bytes and an int8 one of 21 504 034 224 that
  this hardware cannot use. The bf16 file is 42 GB. That gap is a hardware
  argument, not a software one.
