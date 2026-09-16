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
| 2026-09-12 | Phison E18 4 TB NVMe added as `/models` | The root 980 PRO could not hold the model set |

## Still open

**Why the 3090 fell off the bus at 00:01 on 2026-09-16** — Xid 79, then Xid 154
on both cards, under another job's DDP. Its own link was clean throughout, and
the marginal slot the same night's experiment *did* explain belonged to the
other card. One `BadTLP` has been recorded on the 3090's root port since. This
is the one hardware question on the machine with no answer.
[Log](../log/2026-09-16-the-overclock-and-the-fabric.md)
