# rig-log

A build log for one workstation: what it can actually do, measured.

The plan is to point it at every generative workload that fits on local
hardware — large language models first, then video, images, and audio — and
write down the numbers instead of the vibes. Every entry carries the exact
command line, the measured throughput, and the thing that turned out to be
wrong.

Running unreleased models on mismatched hardware walks into other people's
untested paths, so the second half of this log is what got sent back:
[how a failure here becomes an upstream report](docs/upstream-contributions.md),
and the record of what was sent.

![pi running against the workstation's local model](assets/pi-local.gif)

*A 284 B-parameter mixture-of-experts model answering from this machine: most of
its experts live in system RAM, and it streams at 25–33 tok/s.
[Full write-up.](log/2026-09-11-deepseek-v4-moe-offload.md)*

[![Where the experts live, and what each engine measured](assets/placement-sheet.png)](assets/placement-sheet.png)

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
docs/       longer write-ups: upstream bug reports, method, hardware notes
assets/     the clips
CLAUDE.md   context for an agent working in this repo
```

## Upstream

| Date | Project | What | Outcome |
|---|---|---|---|
| 2026-09-11 | ik_llama.cpp | [#2436](https://github.com/ikawrakow/ik_llama.cpp/pull/2436) — a detected allocation failure became a segfault because a `nullptr` graph was dereferenced | open |
| 2026-09-11 | ik_llama.cpp | [#2437](https://github.com/ikawrakow/ik_llama.cpp/pull/2437) — the loader accepted a tensor whose GGUF region is smaller than its type requires, so every short tensor read its tail from the next one | open |
| 2026-09-11 | — | [A published IQ4_KSS file reserves 4 bytes per row too few](docs/iq4-kss-short-tensors.md), which is where the NaN came from. Not an engine defect; nothing filed upstream | for the publisher |

The method, including the two mistakes that cost the most, is in
[`docs/upstream-contributions.md`](docs/upstream-contributions.md).

## Reusable pieces

- [`configs/llm-serve.sh`](configs/llm-serve.sh) — the serving command from
  the first entry, as a systemd `ExecStart`.
- [`configs/tps.py`](configs/tps.py) — streams a completion and reports the
  decode rate from the server's own timings, not a stopwatch.
- [`tools/pi-local.tape`](tools/pi-local.tape) — the VHS tape for the clip
  above, with the two traps it had to work around written down.
- [`assets/placement-sheet.html`](assets/placement-sheet.html) — the source of
  the sheet above; edit and re-screenshot at 1280×720 for the next entry.
- [`tools/dequant-scan.cpp`](tools/dequant-scan.cpp) — reads one tensor out of
  a GGUF at `ggml_row_size` stride, dequantizes each row with ggml's own
  reference path, and reports every non-finite value with the raw block that
  produced it. This is what turned "the logits are NaN" into "expert 255 of
  this tensor is read out of the next tensor's bytes".

  ```
  g++ -O2 -o dequant-scan tools/dequant-scan.cpp -I<ik>/ggml/include \
      -L<ik>/build/ggml/src -lggml -Wl,-rpath,<ik>/build/ggml/src
  ./dequant-scan model.gguf blk.13.ffn_up_exps.weight        # all experts
  ./dequant-scan model.gguf blk.13.ffn_up_exps.weight 255 256 # one expert
  ```

- [`tools/gguf-region-scan.py`](tools/gguf-region-scan.py) — reports any tensor
  whose GGUF region is smaller than its type needs. It reads only the
  tensor-info block, so a published file costs one range request instead of a
  download. This is what showed the short-tensor defect covers a publisher's
  whole quantization ladder, and that a second publisher's file of the same
  type does not have it.

  ```
  ./tools/gguf-region-scan.py model.gguf
  ./tools/gguf-region-scan.py https://huggingface.co/<repo>/resolve/main/model.gguf
  ```

- [`configs/thermal-guard.sh`](configs/thermal-guard.sh) — a watchdog that
  reads CPU, GPU, coolant temperature and pump RPM every 5 seconds and stops
  the inference load, and only the inference load, after 30 seconds of a
  genuine cooling problem. Written for unattended weekends.
