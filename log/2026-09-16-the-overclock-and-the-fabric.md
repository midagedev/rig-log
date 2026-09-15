# The night of ten boots, and a link that was never damaged

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
over the following day, arriving whether or not anything was running.

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
almost entirely BadTLP, which is a CRC failure on a packet — physical-layer
signal integrity, not a device that answered late. That fits a fabric
running out of margin better than the timeout reading did, and it is the
reading that should have been taken first: the log lines are a sample, the
sysfs counters are the population.

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

## Errors since the reboot

Zero, so far, on every device: none at 72 seconds, none across the 12-second
load, none after it. That is not yet an answer. On the boot being replaced,
the first corrected error arrived about three minutes in and the count grew
all day with both GPUs idle, so the test is a quiet soak and not a snapshot.
The machine is being left idle — `llm.service` down, and the other session
on this box has removed its crontab so that its midnight job cannot start
inside the window — and the counters get re-read on a clock.

**Update to follow.** Whatever the counters say, the next arm is already
named: if they stay at zero, the memory clock is the cause and the standing
question becomes whether DDR4-3400 is available as a compromise; if they do
not, the clock is exonerated and the remaining candidates are physical —
reseat the A6000 and its riser, then a slot move.

The tool for both is [`tools/pcie-aer-snapshot.sh`](../tools/pcie-aer-snapshot.sh),
which is yesterday's hand-rolled probe promoted: it reads the counters, the
link state idle and under a load it starts itself, and it is meant to be run
twice, because a counter that is cumulative since boot says nothing on its
own.
