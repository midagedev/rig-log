# Mac numbers for the 0.3.9 film

Model in every row: Qwen3.6-35B-A3B (qwen35moe, 35B total, about 3B active).
`[dev]` marks a development-loop number. The Mac has no timing runner, so there is no lease and no witness block. Each `[dev]` row was measured with arms interleaved, arm order rotated, on AC power, with the 1-min load recorded.

## 1. M4 Pro (48 GB, 20-core GPU), maintainer's sittings — all `[dev]`

### 1a. Decode, bloomery vs mlx-lm vs llama.cpp in one sitting (the cleanest cross-engine row)

- Date: 2026-10-24.
- Rounds: 4 rounds, each arm its own process.
- Load: 2.6–4.9.
- Source: #593 comment of 2026-10-24T02:32Z, corrected in place for #768.

| engine | file | decode tok/s (mean ± SD) |
|---|---|---|
| bloomery `generate_metal` f2b73ba65 | MLX 4-bit (mlx-community folder, converted with `prepare`) | **101.6 ± 0.64** |
| mlx-lm 0.32.2 / mlx 0.32.4, 16-token prompt | the same MLX 4-bit folder | 93.1 ± 0.40 |
| mlx-lm 0.32.2, 512-token prompt | the same MLX 4-bit folder | 92.0 ± 0.41 |
| bloomery `generate_metal` f2b73ba65 | Q4_K_M GGUF | **86.4 ± 0.66** |
| llama.cpp b11827 `llama-bench` tg128 | Q4_K_M GGUF | 67.1 ± 0.33 |

- bloomery prompt: "The capital of France is", `-n 128`, `--ctx 4096`.
- bloomery on the MLX file vs mlx-lm at the same depth: +9.2 % (95 % interval ±1.0 %).
- The first 40 greedy tokens are the same text as mlx-lm's (#757).

### 1b. Prompt (prefill), bloomery at main after #797 — no same-sitting engine row

| engine | prompt | tok/s (two runs) |
|---|---|---|
| bloomery, #797 branch (after) | 873 ids, English text | **1019.4 / 1036.7** |
| bloomery, #797 branch (after) | 7985 ids, English text | **1007.9 / 1008.5** |
| bloomery, #792 (base, same sitting) | 873 ids | 928.9 / 977.9 |
| bloomery, #792 (base, same sitting) | 7985 ids | 1000.5 / 999.2 |

- Date: 2026-10-25 06:11–06:22 KST.
- Model file: MLX 4-bit converted split.
- Command: `generate_metal --prompt "$(cat p.txt)" -n 8 --ctx 8192`, one cold process per run.
- Source: `~/.cache/bloomery/mac-port/fc/fc-sit.log`; PR #797.
- Load: 2.8–5.1.

mlx-lm on the same M4 Pro, from an earlier sitting:

| engine | prompt | tok/s (three rounds) |
|---|---|---|
| mlx-lm 0.32.2 `mlx_lm.benchmark` | pp512, random tokens | 940.0 / 933.2 / 939.9 |
| mlx-lm 0.32.2 `mlx_lm.benchmark` | pp4096, random tokens | 1037.3 / 1038.4 / 1038.2 |
| llama.cpp b11827 `-ngl 99 -fa on -ub 512` | pp512, bartowski Q4_K_M | 864.8 / 865.3 |
| llama.cpp b11827 `-ngl 99 -fa on -ub 512` | pp4096, bartowski Q4_K_M | 815.6 / 821.9 / 822.6 |

- Date: 2026-10-23 07:29–07:41 KST.
- Load: 3.4–8.6.
- Source: `~/.cache/bloomery/mac-port/m4bench/sit2-table.md`.

1b is not a same-sitting comparison; the same-sitting M4 rows (section 4) replace it for the film. The two sides of 1b differ:
- they come from different sittings, on different days;
- the prompt lengths differ (873 vs 512 ids, 7985 vs 4096 ids);
- the prompts differ (text vs random tokens);
- the measurement differs: mlx-lm warms up and averages, bloomery runs one cold call per process.

On the M4 Pro, bloomery's prompt rate is in the same range as mlx-lm's (about 1000 tok/s at a few thousand ids) and above llama.cpp's Q4_K_M rate (about 820 at 4096).

### 1c. Chat turn 2 (server, a 75-id follow-up after a long first turn)

- Turn 2 `prompt_ms`: 187–191 ms at #779 → **113–114 ms** at #792. Before #779 it was three calls of about 305 ms. Source: PR #792 body.
- Checkpoint copy: 24.7 → 1.3 ms (#779).

## 2. Contributor rows, M3 Ultra and M5 Ultra — by @avlp12 on #593

These are the contributor's own numbers on their machines. Conditions are as they reported them.

Machines and software:
- M3 Ultra: 512 GB, macOS 26.6.2.
- M5 Ultra: 256 GB, macOS 27.0.
- bloomery binaries were built on the M3 Ultra and copied to the M5 Ultra.
- GGUF: lmstudio-community `Qwen3.6-35B-A3B-Q4_K_M.gguf` (rev 68a34855).
- llama.cpp b11851 (MTL,BLAS).
- mlx-lm 0.32.2 / mlx 0.32.4 with mlx-community 4-bit (rev 38740b84). That is a different quant, so mlx-lm is a reference column, not same weights.
- One runtime ran at a time.

**Caveat:** on the M5 Ultra, `mediaanalysisd` used about 360 % CPU during every arm of the prompt run.

### 2a. Prompt tok/s at main 6c15ff0f (after #773 and #768, before #777/#779/#792/#797/#796)

| machine | prompt ids | bloomery `generate_metal` (Q4_K_M) | mlx-lm `-p` (MLX 4-bit) | llama-bench pp (Q4_K_M) |
|---|---|---|---|---|
| M3 Ultra | 512 | 1775.7 | 2644.0 | 2409.27 ± 9.91 |
| M3 Ultra | 4096 | 2772.0 (2775.2 / 2768.8) | 3317.1 | 2308.09 ± 1.18 |
| M5 Ultra | 512 | 2216.8 | 5901.5 | 4879.73 ± 28.21 |
| M5 Ultra | 4096 | 3578.9 (3582.8 / 3575.0) | 10157.5 | 4750.81 ± 5.09 |

- Date: 2026-10-24.
- Source: #593 comment of 2026-10-24T15:42Z.
- Measurement differs by engine:
  - bloomery: seeded random ids, a fresh process per run; the 512 value is the second of two runs.
  - mlx-lm: a warmup, then the mean of 3 trials.
  - llama-bench: mean ± sd of 3 repetitions.
- These are behind mlx-lm, and behind llama.cpp at 512 ids. Of the gap, #797 (fixed cost per call) and #796 (M5 matrix units) target it, but neither is measured on these machines yet.

### 2b. Decode right after a 4096-id natural-text prompt, same run

| machine | bloomery | llama-bench tg128 `@ d4096` | mlx-lm tg after `-p 4096` |
|---|---|---|---|
| M3 Ultra | **128.8** | 104.21 ± 4.01 | 118.8 |
| M5 Ultra | **188.8** | 148.06 ± 6.94 | 163.7 |

### 2c. Decode near depth 0, at main 608c0909

| machine | bloomery | llama.cpp tg128 | mlx-lm 4-bit |
|---|---|---|---|
| M3 Ultra | 150.5 | 112.35 ± 0.35 | 123.5 |
| M5 Ultra | 219.7 | 156.84 ± 0.50 | 165.8 |

- Date: 2026-10-24.
- Source: #593 comment of 2026-10-24T08:40Z.
- Two caveats on these rows:
  - The bloomery rows count 128/127 high: before #768 they included the prompt's first token, about +0.8 %.
  - The M5 llama.cpp and mlx-lm cells marked * in the source ran with `mediaanalysisd` busy.

### 2d. Chat TTFT, `bloomery-serve-metal -c 8192`, at 6c15ff0f

| machine | turn 1 prompt (ids) | turn 1 TTFT | before #773 | turn 2 TTFT |
|---|---|---|---|---|
| M3 Ultra | 913 | 0.62 s | 7.27 s | 0.39 s |
| M5 Ultra | 913 | 0.48 s | 4.97 s | 0.26 s |

## 3. What 0.3.9 adds on Mac, one line each

- **#726**: Qwen3.6-35B-A3B decodes and serves on Mac GPUs (`generate_metal`, `bloomery-serve-metal`), with KV checkpoints and prefix reuse across requests.
- **#757**: `prepare` converts an mlx-community 4-bit folder to a GGUF split that bloomery runs. Greedy output matches mlx-lm for 40 tokens.
- **#762**: known prompt ids run ahead, and inner rows skip the head.
- **#773**: batched prompt prefill: one pass per ubatch, flash prefill attention, MoE over rows. The M4 Pro prompt rate went from about 100 to 760–855 tok/s `[dev]`; chat turn 1 TTFT on the M3 Ultra went from 7.27 to 0.62 s (avlp12).
- **#777**: the routed experts run in 64-row tiles: M4 Pro prompt +16–19 % (764 → 914 at 873 ids, 856 → 990 at 7985 ids) `[dev]`.
- **#779**: a layer's ops share one command buffer and a checkpoint is one copy (24.7 → 1.3 ms) `[dev]`.
- **#792**: a chat's message marks stay inside one prompt call: M4 Pro turn 2 `prompt_ms` 187–191 → 113–114 ms `[dev]`.
- **#797**: the session's open makes the rows arena and builds the prefill pipelines, so the first prompt call costs what a later one does: M4 Pro 873-id prompt +7.8 % (953 → 1028 tok/s) `[dev]`.
- **#796**: on an M5, the prompt GEMMs run on the GPU's matrix units (Metal 4 tensor ops); the device picks them by MLX's rule. Checked on M1 and M4, which have no matrix units. Not yet timed or bit-checked on an M5. Derived only: a 2048-row pass ~572 → ~255 ms.

## Numbers I would put on screen

The film's hero numbers come from section 4 (one sitting, 2026-10-25, the code 0.3.9 ships), `[dev]`:
- M4 Pro decode, depth about 0: bloomery 101.2 vs mlx-lm 93.0 on the same MLX 4-bit weights; bloomery 85.6 vs llama.cpp 66.2 on the same Q4_K_M file.
- M4 Pro prompt at 4,096 ids: bloomery 1076.5 vs mlx-lm 1038.0 (MLX 4-bit); bloomery 1044.5 vs llama.cpp 825.1 (Q4_K_M).
- On the Ultras, mlx-lm still leads prompts (section 2a, @avlp12, measured before #777, #779, #792, #797 and #796): M5 Ultra 4096 ids, bloomery 3578.9 vs mlx-lm 10157.5.

Other rows that hold:
- Contributor M5 Ultra, after a 4096-id prompt: bloomery 188.8 tok/s vs mlx-lm 163.7 vs llama.cpp 148.1 (@avlp12).
- Chat turn 1 TTFT, contributor M3 Ultra: 7.27 → 0.62 s with batched prefill (@avlp12).
- Sections 1a and 1b are superseded by section 4 for the film. They are kept as the earlier record.

## 4. Same-sitting M4 Pro (2026-10-25) — `[dev]`

Conditions:
- Machine: M4 Pro (48 GB, 20-core GPU), macOS 27.0.1, AC power.
- One engine at a time, each arm its own processes, arm order rotated every round, 3 rounds. A witness line (time, 1-min load, GPU utilization, power) was taken before and after every arm.
- Prompt sitting: 07:57–08:13 KST, load 4.4–13.2. Decode sitting: 08:13–08:21 KST, load 3.3–12.3.

Engines and files:
- **bloomery** `generate_metal` at fdaedece4: main e0c82e177 plus #796. Its `crates/metal` is main be9bd1118 less one gate-only commit, and the M4 Pro does not select the tensor-op GEMMs.
  - Files: the mlx-community 4-bit folder converted with `prepare` (19.5 GB split), and the Q4_K_M GGUF (21,166,757,728 B, the same file llama.cpp ran).
  - One cold process per run, `--ctx 8192` (`4096` for decode).
- **mlx-lm** 0.32.2 / mlx 0.32.4: `mlx_lm.benchmark`, mlx-community `Qwen3.6-35B-A3B-4bit`, its warmup and then the mean of 3 trials (the averages line).
- **llama.cpp** b11827 `llama-bench`, `-ngl 99 -fa on`, default batch/ubatch, `-r 3` (mean ± sd), MTL,BLAS backend, 10 threads.

### 4a. Prompt tok/s (random token ids, all three engines)

| engine | file | 512 ids (r1 / r2 / r3) | mean | 4096 ids (r1 / r2 / r3) | mean |
|---|---|---|---|---|---|
| bloomery | MLX 4-bit | 929.3 / 950.6 / 949.2 | **943.0** | 1077.7 / 1077.2 / 1074.6 | **1076.5** |
| mlx-lm | MLX 4-bit | 942.3 / 938.1 / 940.0 | 940.1 | 1037.4 / 1037.6 / 1039.0 | 1038.0 |
| bloomery | Q4_K_M | 909.5 / 903.0 / 903.4 | **905.3** | 1043.8 / 1044.0 / 1045.8 | **1044.5** |
| llama.cpp | Q4_K_M | 871.18 ± 4.63 / 869.81 ± 5.40 / 870.40 ± 3.21 | 870.5 | 825.10 ± 0.91 / 824.20 ± 0.51 / 825.87 ± 0.72 | 825.1 |

Commands:
- bloomery: `generate_metal --tokens <seeded random ids> -n 128 --ctx 8192`.
- mlx-lm: `mlx_lm.benchmark -p 512|4096 -g 128 -n 3`.
- llama.cpp: `llama-bench -p 512,4096 -n 0`.

Ratios, M4 Pro, this sitting:
- Same MLX 4-bit weights, bloomery vs mlx-lm: +0.3 % at 512 ids (within run spread) and +3.7 % at 4096 ids.
- Same Q4_K_M file, bloomery vs llama.cpp: +4.0 % at 512 and +26.6 % at 4096.

How each engine measures: bloomery's number is one cold call in a fresh process; mlx-lm's is the mean of 3 trials after a warmup.

### 4b. Decode tok/s, depth about 0

| engine | file | r1 / r2 / r3 | mean |
|---|---|---|---|
| bloomery | MLX 4-bit | 101.2 / 100.6 / 101.9 | **101.2** |
| mlx-lm | MLX 4-bit | 93.12 / 92.93 / 93.03 | 93.0 |
| bloomery | Q4_K_M | 85.5 / 85.3 / 86.0 | **85.6** |
| llama.cpp | Q4_K_M | 62.93 ± 7.62 / 67.57 ± 0.49 / 68.14 ± 0.42 | 66.2 (r2–r3: 67.9) |

Commands:
- bloomery: `--prompt "The capital of France is" -n 128` (5 prompt ids, 128 decoded, stop=length).
- mlx-lm: `-p 16 -g 128 -n 3`, its `generation_tps`.
- llama.cpp: `tg128`.

Ratios:
- Same MLX weights: bloomery +8.8 % over mlx-lm.
- Same Q4_K_M file: bloomery +29 % over llama.cpp, or +26 % against its two quiet rounds. llama.cpp's round 1 had sd 7.62; that round followed a load spike.

Decode after 512 random ids, same prompt sitting:
- mlx-lm: `generation_tps` 92.40 / 91.78 / 92.03.
- llama.cpp: `tg128 @ d512` 67.08 / 67.18 / 67.12.
- bloomery has no row: it stopped at an end-of-generation id 2 tokens after the random 512-id prompt, and it has no ignore-eos flag.

Logs:
- M4 Pro: `~/bench-mac/runs/same039-20261025T075750/` and `~/bench-mac/runs/same039dec-20261025T081352/`.
- Lead Mac: `~/.cache/bloomery/mac-port/same039/{sit.out,dec.out,sit.sh,dec.sh}`.
