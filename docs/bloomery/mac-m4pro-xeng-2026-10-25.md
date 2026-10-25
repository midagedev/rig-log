# M4 Pro, three engines in one sitting (2026-10-25) — `[dev]`

Short record: [`log/2026-10-25.md#mac-m4pro-xeng`](../../log/2026-10-25.md#mac-m4pro-xeng). These are development-loop
numbers: the Mac has no timing runner (no lease, no witness blocks), so they are not bloomery's landing evidence.

## Conditions

- Machine: Apple M4 Pro, 48 GB, 20-core GPU, macOS 27.0.1, AC power.
- One engine at a time. Each arm ran in its own processes. Arm order rotated every round, 3 rounds. A witness line (time,
  1-minute load, GPU utilization, power) was taken before and after every arm.
- Prompt sitting 07:57–08:13 KST, load 4.4–13.2. Decode sitting 08:13–08:21 KST, load 3.3–12.3.
- Model: Qwen3.6-35B-A3B in two files.
  - mlx-community `Qwen3.6-35B-A3B-4bit`. mlx-lm reads the folder. bloomery reads it after one `prepare` conversion
    (19,522,095,840 B split).
  - The Q4_K_M GGUF from `lmstudio-community/Qwen3.6-35B-A3B-GGUF` (21,166,757,728 B). bloomery and llama.cpp read the
    same file.

## Engines and commands

- **bloomery** `generate_metal`, built at main e0c82e177 with #796 applied. #796 merged as be9bd1118. Its `crates/metal`
  equals be9bd1118 except one gate-only commit. The M4 Pro does not select #796's tensor-op GEMMs (`gemm_path=simdgroup`).
  Each run is one cold process.
  - Prompt: `BLOOMERY_REF_MODEL=<file> generate_metal --tokens <ids> -n 128 --ctx 8192`. The ids are 512 or 4096
    token ids from Python `random.Random(39)`, each in [1000, 100000).
  - Decode: `generate_metal --prompt "The capital of France is" -n 128 --ctx 4096` (5 prompt ids, 128 decoded,
    stop=length).
- **mlx-lm** 0.32.2 with mlx 0.32.4. The commands are `mlx_lm.benchmark --model <folder> -p 512|4096 -g 128 -n 3`
  (prompt) and `-p 16 -g 128 -n 3` (decode). Each figure is the averages line: one warmup, then the mean of 3 trials.
  The tool draws its own random prompt.
- **llama.cpp** b11827 `llama-bench -m <gguf> -ngl 99 -fa on -r 3 -o md`, with `-p 512,4096 -n 0` (prompt) and
  `-p 0 -n 128` (decode). Default batch and ubatch. MTL,BLAS backend, 10 threads. Each figure is the mean ± sd of
  3 repetitions. The tool draws its own random prompt.

How each engine measures differs. bloomery's prompt figure is one cold call in a fresh process. mlx-lm's figure comes
after its warmup, and llama-bench reports a mean over repetitions.

## Prompt tok/s

| engine | file | 512 ids, r1 / r2 / r3 | mean | 4096 ids, r1 / r2 / r3 | mean |
|---|---|---|---|---|---|
| bloomery | MLX 4-bit | 929.3 / 950.6 / 949.2 | 943.0 | 1077.7 / 1077.2 / 1074.6 | 1076.5 |
| mlx-lm | MLX 4-bit | 942.3 / 938.1 / 940.0 | 940.1 | 1037.4 / 1037.6 / 1039.0 | 1038.0 |
| bloomery | Q4_K_M | 909.5 / 903.0 / 903.4 | 905.3 | 1043.8 / 1044.0 / 1045.8 | 1044.5 |
| llama.cpp | Q4_K_M | 871.18 ± 4.63 / 869.81 ± 5.40 / 870.40 ± 3.21 | 870.5 | 825.10 ± 0.91 / 824.20 ± 0.51 / 825.87 ± 0.72 | 825.1 |

## Decode tok/s, depth about 0

| engine | file | r1 / r2 / r3 | mean |
|---|---|---|---|
| bloomery | MLX 4-bit | 101.2 / 100.6 / 101.9 | 101.2 |
| mlx-lm | MLX 4-bit | 93.12 / 92.93 / 93.03 | 93.0 |
| bloomery | Q4_K_M | 85.5 / 85.3 / 86.0 | 85.6 |
| llama.cpp | Q4_K_M | 62.93 ± 7.62 / 67.57 ± 0.49 / 68.14 ± 0.42 | 66.2 (r2–r3: 67.9) |

llama.cpp's round 1 has sd 7.62. That round came right after a load spike.

## Decode after 512 random ids (prompt sitting)

- mlx-lm `generation_tps`: 92.40 / 91.78 / 92.03.
- llama.cpp `tg128 @ d512`: 67.08 / 67.18 / 67.12.
- bloomery: no row. After the random 512-id prompt it picked an end-of-generation id at token 2, and
  `generate_metal` has no flag to ignore it.

## Not covered

- The M5's matrix units. The M4 Pro has none, so #796's kernels did not run.
- Depth beyond 512.
- The server's serving path. These are CLI runs.

The sitting scripts, the runs and this write-up were made with Claude Code. The maintainer reviewed them.
