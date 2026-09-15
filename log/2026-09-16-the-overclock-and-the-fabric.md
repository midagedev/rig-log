# The night of ten boots, and the errors that came back at stock

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

Before that there is one arm that does not: force `00:03.1` to Gen3 and
repeat the load. Zero BadTLP at 8 GT/s would confirm a signal-margin
problem and hand over a mitigation at the same time — half the PCIe
bandwidth, which only CPU-offload work pays for. Errors persisting at Gen3
would mean something worse than margin, and would make the slot swap
urgent rather than merely next.

What is not supported by anything measured here is the simplest reading of
the symptom. A dead board, or a fault in the fabric as such, would not
confine itself to one of two root complexes while the other stays clean
through the same load.

The tool for all of it is
[`tools/pcie-aer-snapshot.sh`](../tools/pcie-aer-snapshot.sh) for the
before-and-after pair and `tools/fabric-sample.sh` for the line-per-tick
view through a window, both of which exist because a counter that is
cumulative since boot says nothing on its own.
