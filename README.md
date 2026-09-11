# rig-log

A build log for one workstation: what it can actually do, measured.

The plan is to point it at every generative workload that fits on local
hardware — large language models first, then video, images, and audio — and
write down the numbers instead of the vibes. Every entry carries the exact
command line, the measured throughput, and the thing that turned out to be
wrong.

![pi running against the workstation's local model](assets/pi-local.gif)

*A 284 B-parameter mixture-of-experts model answering from this machine: most of
its experts live in system RAM, and it streams at 25–33 tok/s.
[Full write-up.](log/2026-09-11-deepseek-v4-moe-offload.md)*

## The machine

| | |
|---|---|
| CPU | AMD Ryzen Threadripper PRO 5975WX, 32 cores / 64 threads |
| Memory | 256 GB DDR4-3200 ECC, 8 channels populated (32 GB × 8) |
| Measured memory read | 115.8 GB/s (STREAM-style, 32 threads; 204.8 GB/s theoretical) |
| GPU 0 | NVIDIA RTX A6000, 48 GB |
| GPU 1 | NVIDIA GeForce RTX 3090, 24 GB |
| Board | ASUS Pro WS WRX80E-SAGE SE WIFI |
| Storage | Samsung 980 PRO 2 TB NVMe |
| Cooling | NZXT Kraken X-series AIO, pump pinned at 100%, CPU boost disabled |
| OS | Ubuntu 24.04, kernel parameter `pci=realloc=off` (see below) |

Two notes that cost a day each:

- This board needs `pci=realloc=off` on the kernel command line. Without it
  the kernel reassigns PCI resources, the chipset USB controller fails with
  `xhci init -16`, and the 10 GbE ports go down. `pci=nocrs` "fixes" USB and
  breaks the NVIDIA driver instead.
- The X550 10 GbE ports hit `Tx Unit Hang` under sustained load until GRO,
  TSO, GSO and LRO are disabled on the interface.

## Log

| Date | Entry | Headline |
|---|---|---|
| 2026-09-11 | [DeepSeek-V4-Flash across two GPUs and 256 GB of RAM](log/2026-09-11-deepseek-v4-moe-offload.md) | 284 B parameters at 29 tok/s on 72 GB of VRAM |

## Queued

- **Video generation** — how long a clip fits in 48 GB, and whether the 3090
  is useful as a second worker or only as extra memory.
- **Image generation** — batch throughput at high resolution, and whether
  offloading the text encoder to the CPU is free.
- **Audio** — music and speech generation, latency rather than throughput.
- **Back to LLMs** — DeepSeek V4.1 Flash once any engine can load it, and a
  second 32 GB card to see how far the CPU can be pushed out of the loop.

## Layout

```
log/        one file per experiment, dated
configs/    the scripts that are actually running on the machine
tools/      recording: VHS tapes and the scripts they drive
docs/       longer write-ups: upstream bug reports, hardware notes
assets/     the clips
```

## Reusable pieces

- [`configs/llm-serve.sh`](configs/llm-serve.sh) — the serving command from
  the first entry, as a systemd `ExecStart`.
- [`configs/tps.py`](configs/tps.py) — streams a completion and reports the
  decode rate from the server's own timings, not a stopwatch.
- [`tools/pi-local.tape`](tools/pi-local.tape) — the VHS tape for the clip
  above, with the two traps it had to work around written down.
- [`configs/thermal-guard.sh`](configs/thermal-guard.sh) — a watchdog that
  reads CPU, GPU, coolant temperature and pump RPM every 5 seconds and stops
  the inference load, and only the inference load, after 30 seconds of a
  genuine cooling problem. Written for unattended weekends.
