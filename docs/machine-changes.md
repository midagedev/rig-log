# What this machine used to be

The table in [`README.md`](../README.md) says what the machine **is**. This
file says what it **was**, and when each thing changed. The two are separate
on purpose: a specification table that carries its own revision history stops
being readable as a specification, and every superseded value in it is a
number someone can quote by accident.

The rule that applies here is the repo's own — a claim that turns out to be
wrong gets struck rather than deleted — so nothing below is removed, it is
just kept out of the table. Each row links the entry that measured it.

## Memory

| when | from | to | why |
|---|---|---|---|
| 2026-09-14 | DDR4-3200 | **DDR4-3600, DRAM 1.30 V** | Bandwidth followed the clock one-for-one: 131.2 → 147.7 GB/s of 32-thread read. 3666 lost the 1:1 fabric and returned 139 wrong bytes in ten minutes *with the MCE counter at zero*; 3733 and up do not POST. DRAM voltage on Auto stays 1.2 V whatever the clock, so 3600 runs at a manual 1.30 V, and this firmware has no FCLK item at all. [Log](../log/2026-09-14-memory-clock-3600.md) |
| 2026-09-14 | "ECC" | **non-ECC** | A description of the machine, not a change to it: `dmidecode` reports no error correction on these Samsung M378A4G43AB2-CWE UDIMMs. The earlier claim was wrong and the timing made it matter — the 3666 test above found silent wrong bytes the same week, which is exactly what ECC would have caught |
| — | 115.8 GB/s | **147.7 GB/s** | The 115.8 figure predates the probe being fixed; it is not a DDR4-3200 measurement of anything. 3200 measured 131.2 |

**Two probes disagree by 2 %, and it matters which one a ratio used.** The
32-thread 8 GiB read probe gives **147.7 GB/s** at DDR4-3600. A second probe,
run three times on 2026-09-16 after the slot move, gives **144.8 GB/s** — and
144.8 is the figure passed to toktape as `--ram-gbs-measured`, so every host
percentage on a recorded card is derived against that one, not against 147.7.
Theoretical peak at this clock is 230.4 GB/s.
[Log](../log/2026-09-16-the-overclock-and-the-fabric.md)

## Cooling

| when | from | to | why |
|---|---|---|---|
| 2026-09-14 | NZXT Kraken AIO | **ARCTIC Freezer 4U-M tower air cooler** on CPU_FAN | The loop was letting a 2.7 GHz CPU decode reach Tctl 89 °C. The air cooler holds a 64-thread stress at 43 °C. [Log](../log/2026-09-14-air-cooler-swap.md) |
| 2026-09-15 | 2.7 GHz clock cap + its boot service | **no cap** | The cap existed to work around the AIO, so it retired with it. Uncapped, the served V4.1 profile runs a decode-window mean of 3.44 GHz at Tctl 62–65 °C with the thermal guard silent. [Log](../log/2026-09-15-clock-cap-removed.md) |

CPU boost stays disabled, which is not a change — it has been off throughout.

## GPUs and the fabric

| when | what | why |
|---|---|---|
| 2026-09-16 | The A6000 moved out of the near-bottom slot, bus **01 → 61** | A four-condition experiment on its link (idle/loaded × Gen4/Gen3) put 27 corrected errors in 483 s of Gen4 under load against zero in every other cell: eye margin at 16 GT/s, not damage. The new slot gave zero in 502 s of the same load. The move changed slot and seating together and that is unrecoverable — it is one result, not two. [Log](../log/2026-09-16-the-overclock-and-the-fabric.md) |
| 2026-09-16 | `CUDA_DEVICE_ORDER=PCI_BUS_ID` → **`CUDA_VISIBLE_DEVICES` by UUID** ([`configs/gpu-order.env`](../configs/gpu-order.env)) | The slot move put the A6000 on a *higher* bus than the 3090, so bus order made the 24 GB card device 0. Every `-ot` string, `-ts` and `-gs` in this repo assumes CUDA0 is the 48 GB card; a training launcher with `CUDA_VISIBLE_DEVICES=0` put a 38 GB job on the 3090 and OOMed at step 52000. Fixed once, by UUID, and proven by a load rather than by reading the file. [Log](../log/2026-09-16-every-kept-model-re-verified.md) |
| 2026-09-16 | An asterisk removed from a week of PCIe-bound numbers | The idle 2.5 GT/s that had been read as a downgraded link is the GPU's own downclocking; all four ports read 16 GT/s ×16 under load on a clean boot. The numbers stand. [Log](../log/2026-09-16-the-overclock-and-the-fabric.md) |
| 2026-09-18 | The 3090 **removed** (2026-09-17) and **reseated in the same slot**, bus 41 | It came out to be sold after a second hard hang. Back in, its battery completes: memtest 3 passes 0 errors, gpu_burn 30 min `GPU 0: OK`, and Gen4 x16 with every error bit clear on the card and root port `40:01.1` read **under full load** — the row the cut run of 09-17 never had. A reseat into the same slot cannot speak to the hang, whose fingerprint was a second CUDA context on a loaded card. [Log](../log/2026-09-18-the-3090-goes-back-in.md) |
| 2026-09-18 | Both GPUs' fans: card-controlled → **`configs/gpu-fan.service`**, a curve per card | Measured in one 10-minute burn on both cards at once: the 300 W A6000 ran 88 °C against the 3090's 77, answered with 22 points less fan, and spent **500 s of 600 in SW thermal slowdown**. Both cards' own controllers treat their thermal target as somewhere to sit; the curves top out at it (75 °C for the 3090, 80 °C for the A6000). Worth 3 °C for the same peak fan on a matched three-minute pair on the 3090, and on the A6000 a peer session's five-hour training run read 87 °C at 72 % fan before and 77 °C at 92 % after, with its thermal-slowdown counter frozen across 5 h 16 m and its throughput 4 % *lower*. **Every thermal number on either card from this date is taken with a curve in place** — stop the unit for a matched pair against anything earlier. [Log](../log/2026-09-18-the-3090-goes-back-in.md) |
| 2026-09-12 | Phison E18 4 TB NVMe added as `/models` | The root 980 PRO could not hold the model set |

## Still open

**Why the 3090 leaves the bus under NCCL DDP.** Reproduced three times on
2026-09-18 and narrowed a long way: not bus traffic (a DMA loop at 37 GB/s for
900 s, two to three orders of magnitude above what DDP moves, clean), not
sustained power (the same loop at 419 W, clean, against a fault at 384 W), not
temperature (67 °C), not the link (error registers byte-identical across every
run). **Both cards capped to 250 W ran the same DDP for 900 s clean at 1.51× the
single-card rate**, which is a usable configuration but not a proof — nothing
here can measure the transient the explanation rests on. The cable topology has
not been inspected: the 3090 takes three 8-pin connectors and how many separate
runs reach the PSU is unknown as of 2026-09-18.
[Log](../log/2026-09-18-b-the-fault-reproduced.md)

~~**Why the 3090 fell off the bus at 00:01 on 2026-09-16**~~ — Xid 79, then Xid 154
~~on both cards~~ (**corrected 2026-09-18**: Xid 154 comes off a system-wide
flag and is printed once per card, so only the 3090 fell), under another job's
DDP. Its own link was clean throughout, and
the marginal slot the same night's experiment *did* explain belonged to the
other card. One `BadTLP` has been recorded on the 3090's root port since. This
is the one hardware question on the machine with no answer.
[Log](../log/2026-09-16-the-overclock-and-the-fabric.md)

Still open after the reseat of 2026-09-18. Ten minutes of both cards at full
load added no kernel line and left the AER registers of both cards and both
root ports byte-identical — but neither hang's trigger was reproduced, and the
one that would (a load plus a loop creating a second CUDA context on the same
card) has not been run. The ranked causes are in
[the 09-17 entry](../log/2026-09-17-the-3090-comes-out.md).

**Why the `SW Thermal Slowdown` counter and the reason bits disagree on the
3090** — new on 2026-09-18. The counter read 5.0 s and was static across three
samples at 23:33, and 476 s by 23:58, accrued during a burn whose reason column
said `SW Power Cap` and nothing else and whose die never passed 75 °C. One of
the two instruments is measuring something other than what its name says.
[Log](../log/2026-09-18-the-3090-goes-back-in.md)
