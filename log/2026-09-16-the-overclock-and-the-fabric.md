# The night of ten boots, and a slot that was out of margin

**2026-09-16, early morning.** Both GPUs came back. The machine had been
unusable since 00:01:51, when the RTX 3090 fell off the bus with Xid 79
during another session's DDP run and the driver logged Xid 154 — "recovery
action changed from 0x0 (None) to 0x2 (OS Reboot)" — for **both** cards; a
`torch.cuda` init failed on the A6000 as well. The reboot was the user's
call and it was taken into BIOS setup rather than straight back to the
desktop, because by then the fabric had a suspect.

Everything below was measured on this machine on this date, either side of
that reboot.

## What the boot list says the suspect is

The kernel journal keeps every boot, and the ones before the failing boot
are the record of an evening:

```
 -10  Mon 2026-09-14 21:23:17 → 21:51:06
  -9  Mon 2026-09-14 21:53:35 → 21:53:35     0 s
  -8  Mon 2026-09-14 22:15:22 → 22:25:38
  -7  Mon 2026-09-14 22:27:14 → 22:27:22     8 s
  -6  Mon 2026-09-14 22:28:32 → 22:28:32     0 s
  -5  Mon 2026-09-14 22:29:48 → 22:29:48     0 s
  -4  Mon 2026-09-14 22:30:37 → 22:32:03
  -3  Mon 2026-09-14 22:34:34 → 22:52:30
  -2  Mon 2026-09-14 23:11:57 → 23:13:57
  -1  Mon 2026-09-14 23:20:43 → 23:35:03
   0  Mon 2026-09-14 23:41:03 → Wed 2026-09-16 05:05:21
```

That is the memory-clock walk in
[`2026-09-14-memory-clock-3600.md`](2026-09-14-memory-clock-3600.md) seen
from the journal's side: DDR4-3200 through 3400, 3600, 3666, then 3733,
3766 and 3800, which did not train — the three zero-second boots and the
eight-second one. The board did not fall back on its own, the physical CLR
CMOS button was used, and every BIOS item was re-entered by hand. Boot 0,
at 23:41, is the first boot of the configuration that came out of that
evening: **DDR4-3600 at 1.30 V**. It is also the boot carrying the PCIe
errors, and it is the boot the machine was still running when the 3090 fell
off the bus thirty hours later.

That entry had already written the warning down without knowing it was one.
Under "Two things seen in passing":

> The PCIe AER counter recorded corrected Data Link Layer errors on the root
> port of the RTX A6000 (`00:03.1`, two events) during the 3600 run […]
> filed under WKS-21 as a pattern to watch, not attributed to the memory
> clock.

Two events during the 3600 stress became 630 corrected errors on that port
over the following day. Whether that was the clock is the question this
entry set out to answer, and the answer below is no — or at least not by
itself.

The mechanism is available. This firmware has no Infinity Fabric item at all
— established by trying, in the same entry — and the fabric follows the
memory clock 1:1 up to 1800 MHz on its own. DDR4-3600 is MEMCLK 1800, which
is that ceiling exactly, and on WRX80 the same IO die carries the memory
controllers and the PCIe root complexes. The 3666 attempt failing a
verifying memory stress (139 wrong readbacks in ten minutes, invisible to
MCE on non-ECC DIMMs) says the same thing from the memory side: 3600 was the
edge of this IMC with eight dual-rank DIMMs, which is why it was given
1.30 V in the first place.

None of that is proof, and there are two other candidates with physical
access to the same slot: the machine was moved between buildings on
2026-09-11 (115 BadTLP appear in the 09-12 boot and in none of the three
before it, WKS-21) and the CPU cooler was swapped for a tower air cooler on
the evening of 09-14, hours before the clock walk. What the overclock has
that the other two do not is a one-boot experiment.

## The correction I owe the counters

Reported yesterday, and by the other session on this machine to its own
user: the errors were Data Link Layer timeouts. ~~1 891 corrected AER errors
on the A6000's root port, all Data Link Layer timeouts.~~ That reading came
from sampling individual `AER:` lines in the kernel log. The persistent
per-device counters, read before the reboot, say something else:

| device | corrected | breakdown |
|---|---:|---|
| `0000:00:03.1` A6000 root port | 630 | **BadTLP 619**, BadDLLP 10, Timeout 1 |
| `0000:01:00.0` RTX A6000 | 65 | Timeout 65 |
| `0000:01:00.1` its audio function | 65 | Timeout 65, NonFatalErr 1 |
| `0000:2b:00.0` | 5 | RxErr 5 |

The timeouts are on the card and its audio function; the port's errors are
almost entirely BadTLP, which is a CRC failure on a received packet —
signal integrity, not a device that answered late.

Half of that correction was itself wrong, and the half that was wrong was
mine. The kernel prints **`aer_layer=Data Link Layer`** for a BadTLP as
well, because BadTLP *is* a data link layer error in the AER taxonomy —
`aer_status 0x40`, bit 6. So "Data Link Layer" was never the mistake. Only
"timeouts" was: the layer is right, the type is not, and the log line is
simply coarser than the counter. The lesson is narrower than the one I drew
— not that log lines are a sample and counters are the population, but that
a log line names the layer and only the counter names the type.

## The two things changed in firmware

One boot, one variable, and the variable is the memory configuration
returning to stock:

1. `AMD CBS → UMC Common Options → DDR4 Common Options → DRAM Timing
   Configuration → Accept → Overclock Enabled → Memory Clock Speed`:
   1800 MHz → **1600 MHz** (DDR4-3600 → DDR4-3200)
2. `Ai Tweaker → DRAM ABCD Voltage` / `DRAM EFGH Voltage`: 1.30 → **Auto**

Nothing else was touched — not Above 4G Decoding, not Re-Size BAR, not
NPS1, and deliberately not a forced PCIe Gen3, which is the obvious second
knob and would have made the result unreadable. Both changes took: eight
DIMMs read `Configured Memory Speed 3200 MT/s`, and the BMC reads
`+VDDIO_ABCD 1.22 V` / `+VDDIO_EFGH 1.21 V`, which is the SPD default this
board calls Auto.

The cost is known in advance and it is the whole reason the clock was raised:
131.2 GB/s of 32-thread host read instead of 147.7, −12.6 %. That is a
CPU-offload number. Nothing that fits in VRAM pays it.

## Both cards initialize

```
index, name, memory.used, pstate, pcie.link.gen.current, pcie.link.width.current
0, NVIDIA RTX A6000, 1 MiB, P8, 1, 16
1, NVIDIA GeForce RTX 3090, 1 MiB, P8, 1, 16
torch 2.5.1+cu124, device_count 2
```

## The 2.5 GT/s was idle downclocking

This was left open yesterday, and it mattered more than the error count did:
the A6000's link read `2.5GT/s (downgraded)` against a 16 GT/s LnkCap, and
if that were a fallback after errors rather than idle behaviour, then every
measurement in the last week that streamed weights over PCIe — prefill, the
`-ot` moves, the exl3 expert tail — had been running on a quarter-speed
link, and the numbers would have to be thrown away.

It is idle behaviour. On a fresh boot with zero errors on any device, all
six GPU functions and both root ports still read 2.5 GT/s at idle, with
`ASPM Disabled` in LnkCtl — so it is not ASPM either, it is the GPUs' own
link power management following P8. Put traffic on the link and it comes up
and stays up:

| `LnkSta` | idle (P8) | during 12 s of host↔device copies |
|---|---|---|
| `00:03.1` A6000 root port | 2.5 GT/s ×16 | **16 GT/s ×16** |
| `01:00.0` RTX A6000 | 2.5 GT/s ×16 (downgraded) | **16 GT/s ×16** |
| `40:01.1` 3090 root port | 2.5 GT/s ×16 | **16 GT/s ×16** |
| `41:00.0` RTX 3090 | 2.5 GT/s ×16 (downgraded) | **16 GT/s ×16** |

Sampled every two seconds for the length of the load; all four read 16 GT/s
at every sample. The PCIe-bound rows in
[`2026-09-15-glm-5.3-flash-first-run.md`](2026-09-15-glm-5.3-flash-first-run.md)
lose their asterisk.

The load is `tools/pcie-aer-snapshot.sh --load`, which holds pinned
host↔device copies on every visible GPU while the link state is read. Its
51.6 GB/s aggregate is not a bandwidth figure and is not offered as one —
both directions share the link and the loop synchronizes every iteration.
It exists to make the link busy.

## Errors since the reboot: they came back

Zero at 72 seconds, zero across the first 12-second load, zero at five
minutes idle. Then, eight and a half minutes into the boot and with the
fabric under a real load, the same port logged the same thing:

```
Sep 16 05:21:47 kernel: pcieport 0000:00:03.1: AER: aer_status: 0x00000040
Sep 16 05:21:47 kernel: pcieport 0000:00:03.1: AER: aer_layer=Data Link Layer,
                                                    aer_agent=Receiver ID
```

`aer_status 0x40` is BadTLP: the same device and the same error type as the
boot that was replaced, on stock DDR4-3200 with the DRAM voltage back on
Auto. Sampled every twenty seconds through ten minutes of two-rank NCCL
all-reduces, the count went 3 → 30, about **200 corrected errors an hour
under load**, with all four links holding 16 GT/s ×16 at every sample and no
Xid at all.

**So the memory clock is not the cause on its own.** It may still be a
contributor — the idle rate at 3200 is being measured now and is the number
that would say, because a fabric coupled to an over-clocked memory controller
would be expected to produce errors with nothing running, which is what the
old boot did, while a physical margin problem produces them under traffic,
which is what this one does. Until that soak reports, the honest statement
is that DDR4-3600 is not sufficient to explain the errors, not that it is
innocent.

The load was a reproduction rather than a training job: two ranks, one per
card, back-to-back 256 MB NCCL all-reduces. It is worth saying what that
actually exercises, because the assumption everyone on this machine started
from was wrong. `nvidia-smi topo -p2p rw` reads **GNS**, "GPU not
supported", in both directions — GeForce has had peer-to-peer removed since
Ampere, and this is a GeForce paired with a workstation card. The DDP run
that preceded the crash was therefore never doing card-to-card DMA. NCCL
staged every transfer through pinned host memory: both links saturated in
both directions at once, through the host bridge. Still the heaviest fabric
pattern this box had seen; not the one it was described as.

## Two problems, and only one of them is measured

The card that fell off the bus is not the card with the errors. Every
corrected error in this machine's history is on the A6000's link; the
3090's root port has three, total, ever. So the chronic AER story and the
Xid 79 may be two unrelated things, and the entry above measures only the
first.

For the second, the capacity explanation is out: the power supply is a
2000 W unit, against a peak draw of roughly 1000 W with both cards and the
CPU at full tilt, and the DDP run was plausibly the first time both cards
drew full *compute* power at once — LLM decode on this box is bandwidth
bound, not power bound. A 2000 W supply at half load does not sag. That
leaves the 3090's own link, its seating, or the load itself, and none of
those has been tested.

## What discriminates the remaining candidates

The A6000 sits directly in its slot — no riser, which the exl3 handoff had
assumed — so the classic test is available and it is decisive: **swap the
two cards between slots.** If the errors follow the A6000, it is the card.
If they stay on `00:03.1`, it is the slot, its traces, or that root
complex. That needs hands on the case.

## Gen3 stops it dead

The arm that needed no hands was to cap `00:03.1` at 8 GT/s and repeat the
load. Three conditions, one afternoon, the same machine and the same
two-rank NCCL all-reduces:

| link | condition | window | corrected errors |
|---|---|---:|---:|
| Gen4 (16 GT/s) | idle | 450 s | **0** |
| Gen4 (16 GT/s) | under load | 483 s | **27** — one every 17.9 s |
| Gen3 (8 GT/s) | the same load | 301 s | **0** — the Gen4 rate predicts ~17 |

Nothing changed but the signalling rate, and the errors stopped. Both halves
of that matter: the link is quiet when idle *at Gen4*, so traffic is
necessary, and it is quiet under traffic *at Gen3*, so 16 GT/s is necessary
too. Errors that need both are an eye-margin problem — damage does not care
what speed it runs at, and a dead lane would have shown as a width
negotiation, not a retried packet.

The RTX 3090 is the control that makes this a slot story rather than a board
story. Same board, same Gen4, same load, driven through the same host bridge
for the whole of every window: zero errors on its port, throughout.

The speed is set through the port's Link Control 2 register and takes effect
on a retrain, which is
[`tools/pcie-force-speed.sh`](../tools/pcie-force-speed.sh). Like the board
power cap before it, the speed is machine state, so it is restored on every
exit path including a signal.

It is also a mitigation, if one is ever wanted: capping that port costs half
the PCIe bandwidth on the A6000's link, which is nothing at all for work
that fits in VRAM and real money only for host-offload streaming. It does
not survive a reboot, so standing use would need a unit file.

## The slot, and what the owner knew that the machine did not

The last piece came from the person who built it. The A6000 is in nearly the
bottom slot, put there deliberately to keep thermal distance from the 3090 —
and the bottom slot is the longest trace run from the CPU on this board,
which is exactly where Gen4 margin runs out first. That turns "move it up"
from a guess into the indicated repair, and it is worth recording that the
measurement could not have found it: the machine can read its own link speed
and its own error counters, but not how far the packets have to travel to
get there.

The thermal reason for the bottom slot does not look expensive to give up.
At the end of six minutes of sustained copies the A6000 read 72 °C against a
93 °C throttle, and the 3090 53 °C.

The box was powered off at 05:47 for the move.

## The new slot is clean, and the experiment that was not run

The A6000 came back at `0000:61:00.0` under root port `0000:60:01.1` — a
different IO die quadrant altogether, not one slot up. The 3090 did not
move. Same load, same eight minutes, Gen4:

| slot | link | condition | window | corrected |
|---|---|---|---:|---:|
| `00:03.1` (near the bottom) | Gen4 | idle | 450 s | 0 |
| `00:03.1` | Gen4 | under load | 483 s | **27** — one every 17.9 s |
| `00:03.1` | Gen3 | under load | 301 s | 0 |
| `60:01.1` (moved up) | Gen4 | under load | 502 s | **0** |

Zero on every device, zero AER lines in the kernel log, no Xid, the link
holding 16 GT/s ×16 at every twenty-second sample. The old slot's rate
predicts 28 errors across that window. So the machine is repaired, Gen3 is
not needed, and the full link is back.

**What this cannot say, and it is my fault that it cannot.** Moving the card
changed the slot and the seating in the same motion. The bottom slot may
have been short of Gen4 margin, or the card may simply not have been fully
home in it since the case was opened on 2026-09-12 to add the NVMe — the
intervention immediately before the first boot that logged errors. Reseating
in the same slot first would have separated those, and that was the
suggestion; the card was already moved and booted by the time it was made.
The distinction is now unrecoverable, and it matters for whoever next puts a
Gen4 card in that bottom slot.

There is a second thing the record cannot settle, for a duller reason: the
journal does not reach back past 2026-09-12, and the three boots before the
first erroring one were nine and ten minutes each and idle. Today's idle
measurement says an idle window that short produces zero errors anyway. So
"none in the three boots before" was never evidence that the errors were
new. There is no loaded baseline from before the move at all.

## The first real workload on the new slot, and what it costs in heat

The measurements above are synthetic: an all-reduce hammer written to
reproduce a failure. The first ordinary load across the moved card was
another session's vocoder training, started 06:12 and still running an hour
later with 38.7 GB resident on the A6000. The fabric is clean under it —
zero corrected errors on every device, no AER lines, the link at 16 GT/s —
which is the result that matters, because a training step drives the link
differently from an all-reduce: host-to-device batches every step rather
than symmetric peer traffic.

What the run surfaced instead is heat.

| | |
|---|---:|
| GPU temperature | 86–87 °C |
| board's own slot sensor, `PCIE05` | 86 °C |
| power | 296 W of a 300 W board limit |
| SM clock | 1710–1740 MHz of 2100 |
| fan | 72–73 % |

**A correction I made within the hour.** Reading the throttle flags once
during the run, I reported `SW Power Cap: Active` with both thermal
slowdowns inactive, and told the user the card was power-capped rather than
hot. Twenty minutes later `SW Thermal Slowdown` read `Active` too. The
counters say how much that first reading was worth: sampled thirty seconds
apart, `SW Thermal Slowdown` advanced 29.7 s and `SW Power Capping` 26.4 s,
so both are on essentially all the time, and the totals since boot are
1611 s and 1535 s of a 2982 s uptime. A throttle flag read once is the same
mistake as an AER counter read once, made in the same session, about the
same card. The flag is a state with a duty cycle; only the counter gives it.

The hardware thresholds put that in proportion. `GPU Target Temperature
Specification` is 84 °C, `Max Operating` 93, `HW Thermal Slowdown` 95,
`Shutdown` 98. The card is three degrees over the temperature the driver
tries to hold and eight degrees under the one the hardware acts on; every
`HW` flag reads `Not Active`. So this is the driver trimming clocks to hold
a target, not a card in trouble. But it is trimming them continuously, and
because the power cap is pinned at the same time, **the clock loss cannot be
attributed to either**. Separating them means taking the budget away — drop
the board limit and see whether the temperature falls below the target and
the thermal flag clears — which is the same instrument
[`tools/ik/gpu-power-sweep.sh`](../tools/ik/gpu-power-sweep.sh) exists for,
and it is not something to do underneath a live training run.

### The board reads the slot, and it agrees

`ipmitool sdr type temperature` through the BMC has a sensor per PCIe slot:

| sensor | reading | what is in it |
|---|---:|---|
| `PCIE01 Temp.` | 34 °C | the 3090, idle |
| `PCIE05 Temp.` | 86 °C | the A6000, under the training load |
| `CPU Temp.` | 43 °C | |
| `LAN Temp.` | 51 °C | |

That is worth having for two reasons. It is independent of the card — 86 °C
of slot against 87 °C of die says the air around the card really is at that
temperature, rather than one sensor reporting a hot spot. And it is
readable when the driver is not: during this morning's incident `nvidia-smi`
could not open either GPU, and this channel would still have answered.

### The fans, and what "Disabled" does not mean

All six `CHA_FAN` headers read `Disabled` over IPMI; only `CPU_FAN`
(2200 RPM), `SOC_FAN` (2700) and `CHIPSET_FAN` (2300) report. On this board
the BMC is the only source for fan speed at all — the nct6798 Super I/O
reports zero on every channel — so there is nowhere else to look.

It would be wrong to read that as no chassis airflow. The case has front and
rear fans; they are wired to the power supply directly rather than to a
board header, so nothing reports them and nothing controls them. `Disabled`
means no tachometer on that header, not no fan in the case. The instrument's
silence is about the instrument. Re-routing them to the headers is on the
list, and until it happens the chassis fans run at whatever constant speed
the PSU gives them, with no curve and no telemetry.

Which leaves the question this section opened with unanswered: whether the
new slot runs hotter than the bottom one did. The only sustained sample from
before the move is 72 °C at 138 W, at a fraction of this load, and the 58 °C
at 298 W that looks comparable was decode bursts of seconds rather than an
hour at 100 %. There is no baseline to compare against, and saying the move
made the card hotter would be inventing one.

## Still open: the card that actually fell

Nothing measured today explains the Xid 79. The 3090's link was the clean
one before the reboot, stayed clean through every load after it, and did not
move slots. The error storm and the card that fell off the bus may be one
fault or two, and this entry has closed only the first.

What is not supported by anything measured here is the simplest reading of
the symptom. A dead board, or a fault in the fabric as such, would not
confine itself to one of two root complexes while the other stays clean
through the same load.

The tool for all of it is
[`tools/pcie-aer-snapshot.sh`](../tools/pcie-aer-snapshot.sh) for the
before-and-after pair and `tools/fabric-sample.sh` for the line-per-tick
view through a window, both of which exist because a counter that is
cumulative since boot says nothing on its own.
