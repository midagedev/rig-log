*Written 2026-09-13 by a delegated benchmark agent, published as it reported, with every command it ran.
It is the source of the small-model CPU numbers in
[`log/2026-09-13-deepseek-v41-on-ik-llama.md`](../log/2026-09-13-deepseek-v41-on-ik-llama.md).
"The lead" is the session that ran the V4.1 measurements alongside it; the contamination section
is the incident behind [`docs/quiet-machine.md`](quiet-machine.md). One slip inside: the MoE URL
it calls a 404 returned 401.*

# CPU kernel bench: ik_llama.cpp vs mainline llama.cpp, small models, no GPU

Machine: AMD 5975WX, 32 cores, 251 GB RAM. Date: 2026-09-13.
All timing runs: `-ngl 0`, `CUDA_VISIBLE_DEVICES=` empty, `-r 3`, `-o md`, strictly serial.
Trees: ik `/home/user/ik_llama.cpp` (HEAD 7b79b229), mainline `/home/user/llama.cpp-v41` (HEAD 5210c7c).

**Read the contamination section before the tables.** A large fraction of the runs
overlapped a 200 GB model load started by the lead. Those rows are kept in `raw/`
but excluded from every table below.

## 1. Build configs

`cmake -L -N /home/user/ik_llama.cpp/build | grep -iE "OPENMP|NATIVE|AVX|REPACK|LLAMAFILE|CUDA|BLAS"`

```
GGML_AVX:BOOL=OFF
GGML_AVX2:BOOL=OFF
GGML_AVX512:BOOL=OFF
GGML_AVX512_BF16:BOOL=OFF
GGML_AVX512_VBMI:BOOL=OFF
GGML_AVX512_VNNI:BOOL=OFF
GGML_AVXVNNI:BOOL=OFF
GGML_CUDA:BOOL=ON
GGML_CUDA_COMPRESSION_MODE:STRING=size
GGML_CUDA_DMMV_X:STRING=32
GGML_CUDA_F16:BOOL=OFF
GGML_CUDA_FA_ALL_QUANTS:BOOL=OFF
GGML_CUDA_FORCE_CUBLAS:BOOL=OFF
GGML_CUDA_FORCE_DMMV:BOOL=OFF
GGML_CUDA_FORCE_MMQ:BOOL=OFF
GGML_CUDA_FUSION:STRING=1
GGML_CUDA_IQK_FORCE_BF16:BOOL=OFF
GGML_CUDA_KQUANTS_ITER:STRING=2
GGML_CUDA_MIN_BATCH_OFFLOAD:STRING=32
GGML_CUDA_MMV_Y:STRING=1
GGML_CUDA_NO_PEER_COPY:BOOL=OFF
GGML_CUDA_NO_VMM:BOOL=OFF
GGML_CUDA_PEER_MAX_BATCH_SIZE:STRING=128
GGML_HIPBLAS:BOOL=OFF
GGML_NATIVE:BOOL=ON
GGML_OPENMP:BOOL=ON
```

`cmake -L -N /home/user/llama.cpp-v41/build | grep -iE "OPENMP|NATIVE|AVX|REPACK|LLAMAFILE|CUDA|BLAS"`

```
GGML_AVX:BOOL=OFF
GGML_AVX2:BOOL=OFF
GGML_AVX512:BOOL=OFF
GGML_AVX512_BF16:BOOL=OFF
GGML_AVX512_VBMI:BOOL=OFF
GGML_AVX512_VNNI:BOOL=OFF
GGML_AVX_VNNI:BOOL=OFF
GGML_BLAS:BOOL=OFF
GGML_BLAS_VENDOR:STRING=Generic
GGML_CPU_REPACK:BOOL=ON
GGML_CUDA:BOOL=ON
GGML_CUDA_COMPRESSION_MODE:STRING=size
GGML_CUDA_FA:BOOL=ON
GGML_CUDA_FA_ALL_QUANTS:BOOL=OFF
GGML_CUDA_FA_QUANTS:STRING=q4_0-q4_0;q8_0-q8_0;f16-f16;bf16-bf16
GGML_CUDA_FORCE_CUBLAS:BOOL=OFF
GGML_CUDA_FORCE_MMQ:BOOL=OFF
GGML_CUDA_GRAPHS:BOOL=ON
GGML_CUDA_NCCL:BOOL=ON
GGML_CUDA_NO_PEER_COPY:BOOL=OFF
GGML_CUDA_NO_VMM:BOOL=OFF
GGML_LLAMAFILE:BOOL=ON
GGML_NATIVE:BOOL=ON
GGML_OPENMP:BOOL=ON
GGML_OPENMP_FETCH:BOOL=OFF
```

Both report every explicit `GGML_AVX*` entry as OFF while `GGML_NATIVE=ON`; with NATIVE
the ISA comes from `-march=native` at compile time, so those OFF values do not mean the
AVX2 path is disabled. The two trees agree on NATIVE and OPENMP. They differ in two ways
that touch CPU matmul: mainline has `GGML_LLAMAFILE=ON` (tinyBLAS sgemm) and
`GGML_CPU_REPACK=ON`; ik's cache exposes neither variable.

Mainline's `llama-bench` was built for this round
(`cmake --build /home/user/llama.cpp-v41/build --target llama-bench -j 16`, started
13:25:24, "Built target llama-bench"). ik's existing binary was reused; it prints
`build: 3bb386eb (4883)`, not HEAD 7b79b229 — see premise corrections.

## 2. Results

Only rows that did not overlap a competing load appear here. "server-active" marks rows
where the idle 8001 `llama-server` still consumed ~1 core by the sampler's accounting.

### Qwen2.5-7B-Instruct Q3_K_M (dense), t=32

| engine + flags | run (start) | pp512 t/s | tg128 t/s |
| --- | --- | ---: | ---: |
| ik, defaults | s1 15:03:25 | 218.64 ± 1.16 | 31.15 ± 0.19 |
| ik, defaults | r2 15:45:21 | 215.03 ± 3.43 | 32.20 ± 0.07 |
| ik, defaults | r3 15:51:22 | 218.02 ± 3.51 | 32.30 ± 0.11 |
| ik, defaults, tg only | s1 15:05:19 | — | 32.16 ± 0.18 |
| ik, defaults, tg only | 14:20:52 | — | 32.26 ± 0.09 |
| ik, `-rtr 1` | 14:24:08 | 216.33 ± 4.37 | 32.69 ± 0.08 |
| mainline, defaults | r2 15:48:15 | 103.28 ± 0.68 | 30.33 ± 0.31 |
| mainline, defaults | r3 15:53:13 | 104.27 ± 0.27 | 30.47 ± 0.01 |
| mainline, server-active | s1 15:07:02 | 99.48 ± 0.15 | 29.25 ± 0.18 |
| mainline, server-active, tg only | s1 15:10:10 | — | 28.85 ± 0.04 |

ik mean pp512 217.2, mainline 103.8 → **pp ratio 2.09**.
ik mean tg128 32.01, mainline 30.40 (strictly clean rows only) → **ik / mainline tg128 at t=32 = 1.05**.
Including the two server-active mainline rows moves the mainline mean to 29.73 and the
ratio to 1.08. The ratio is in the 1.05–1.08 band either way.

ik thread sweep, tg128, tg-only invocation (clean; no clean mainline sweep exists):

| threads | ik tg128 t/s |
| ---: | ---: |
| 16 | 30.57 ± 0.14 |
| 32 | 32.26 ± 0.09 |
| 64 | 20.68 ± 1.46 |

`-rtr 1` changes almost nothing on this model: 216.33 vs 217.2 pp, 32.69 vs 32.01 tg.

### DeepSeek-V2-Lite-Chat Q3_K_M (MoE, deepseek2), t=32

| engine + flags | run (start) | pp512 t/s | tg128 t/s |
| --- | --- | ---: | ---: |
| ik, defaults (`-fmoe 1`) | 14:31:05 | 445.66 ± 6.45 | 73.50 ± 0.23 |
| ik, defaults | r4 15:58:11 | 447.66 ± 7.92 | 73.96 ± 0.40 |
| ik, defaults, tg only | 14:50:14 | — | 73.57 ± 0.32 |
| ik, defaults, tg only | r4 16:01:31 | — | 72.83 ± 0.29 |
| ik, `-fmoe 0` | 14:53:16 | 434.77 ± 4.94 | 72.40 ± 0.49 |
| ik, `-rtr 1` | 14:56:23 | 457.73 ± 9.69 | 74.87 ± 0.18 |
| ik, `-fmoe 0 -rtr 1` | 14:59:36 | 441.55 ± 9.73 | 75.02 ± 0.13 |
| mainline, defaults | 14:29:10 | 201.52 ± 0.58 | 66.10 ± 0.66 |
| mainline, defaults | r4 15:56:19 | 200.94 ± 0.71 | 66.22 ± 0.76 |
| mainline, defaults, tg only | r4 15:59:53 | — | 66.16 ± 0.82 |

ik mean pp512 446.7, mainline 201.2 → **pp ratio 2.22**.
ik mean tg128 73.47, mainline 66.16 → **ik / mainline tg128 at t=32 = 1.11**.

ik thread sweep, tg128, tg-only (clean; no clean mainline sweep exists):

| threads | ik tg128 t/s |
| ---: | ---: |
| 16 | 66.42 ± 0.32 |
| 32 | 73.57 ± 0.32 |
| 64 | 49.62 ± 6.40 |

Turning fused MoE off costs ~2.5 % of pp and ~1.5 % of tg; `-rtr 1` gains ~2.5 % of pp
and ~2 % of tg. All four ik flag combinations land within 5 % of each other, so neither
the fused-MoE path nor runtime repack explains anything of the size being hunted.

### Verdict, one sentence per model

- **Qwen2.5-7B (dense):** the ik / mainline tg128 ratio at t=32 is 1.05–1.08, near 1.0.
- **DeepSeek-V2-Lite (MoE):** the ik / mainline tg128 ratio at t=32 is 1.11, near 1.0.

### Disambiguation: the ik outlier was contamination, not an invocation-shape penalty

Mid-round it looked as though running pp512 before tg128 in the same process penalized
ik: the 13:55 baseline gave ik tg128 26.98 and pp512 115.66, while a tg-only run gave
32.26. A clean interleaved A/B killed that hypothesis. In the s1 set, ik pp-then-tg gave
tg 31.15 and ik tg-only gave 32.16 (3 % apart), while mainline went 29.25 pp-then-tg vs
28.85 tg-only — the opposite direction and smaller. The 13:55 numbers were simply taken
during a 200 GB load. **There is no pp-before-tg penalty in either engine.**

### Secondary measurement: ik's prompt path degrades far more under competing load

The same ik command line produced pp512 of 115.66 (13:55) and 125.65 (15:28) while a
competing load ran, against 215.03 / 218.02 / 218.64 on a quiet box — a loss of about
45 %. Mainline's pp512 over the same conditions spans only 99.12 to 104.27, under 5 %.
This is a measurement, not a diagnosis: the competing loads were 200 GB model loads that
are I/O and page-cache heavy, so core contention cannot be separated from memory
bandwidth here. The control designed to separate them (run 5: ik at `-t 32/31/30/28`)
fell inside the lead's 16:02–16:18 window and is void.

## 3. Contamination, and why the gate missed it

My gate required 1-minute loadavg < 4 on two samples 30 s apart. That is the wrong
instrument: a 200 GB model load is I/O-bound and does not raise loadavg until late, so
the gate opened while the machine was busy. A 10-second sampler recording `ps -C
llama-server` cumulative CPU time ran from 13:54 and caught the `llama-server` component,
but nothing in my harness saw the lead's loads. The `/tmp/cpu-busy.flag` protocol would
have caught them; it reached me after these rounds were already launched.

Rows excluded from the tables:

| run | window | why |
| --- | --- | --- |
| mainline-qwen7b-baseline | 13:52:32–13:53:14 | lead's flag window (flag present from 13:32) |
| ik-qwen7b-baseline | 13:55:44–13:56:14 | same; this is the pp 115.66 / tg 26.98 outlier |
| mainline-qwen7b-tsweep | 14:11:45–14:17:22 | lead's load window; also server stole ~0.7 core and the server pid changed mid-run |
| mainline-dsv2lite-tsweep | 14:32:47–14:37:42 | lead's load window; tg128 t=32 read 59.69 against 66.2 clean |
| s2-ik-tg-only | 15:13:15–15:13:31 | lead's 15:06–15:15 load |
| s2-ik-pp-then-tg | 15:25:01–15:25:25 | lead's 15:26–15:35 load |
| r1-ik-dense-pp-tg | 15:28:11–15:28:42 | same window; pp read 125.65 |
| r1-ml-dense-pp-tg | 15:31:13–15:31:50 | same window |
| all of raw-r5/ | 16:02–16:17 | lead's V4.1 CPU-only window 16:02–16:18 |

An asymmetry worth naming: by the sampler's accounting every mainline thread sweep ran
while `llama-server` consumed ~0.7–0.8 core and every ik sweep ran with the server idle.
That alone biases sweep comparisons toward ik by a few percent, which is one more reason
the tables above use the interleaved repeats rather than the sweeps for cross-engine
ratios.

## 4. Exact commands

Environment for every timing run: `CUDA_VISIBLE_DEVICES=` (empty). Both binaries still
print a CUDA init line and label the backend "CUDA"; with the variable empty they report
`no CUDA-capable device is detected`, and every run used `-ngl 0`.

```
# preparation (no gate needed)
13:25:24  cmake --build /home/user/llama.cpp-v41/build --target llama-bench -j 16
13:26     curl -sSL -o /models/small/Qwen2.5-7B-Instruct-Q3_K_M.gguf \
            https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q3_K_M.gguf
13:26     curl -sSL -o /models/small/DeepSeek-V2-Lite-Chat.Q3_K_M.gguf \
            https://huggingface.co/mradermacher/DeepSeek-V2-Lite-Chat-GGUF/resolve/main/DeepSeek-V2-Lite-Chat.Q3_K_M.gguf

# IK=/home/user/ik_llama.cpp/build/bin/llama-bench
# ML=/home/user/llama.cpp-v41/build/bin/llama-bench
# QW=/models/small/Qwen2.5-7B-Instruct-Q3_K_M.gguf
# DS=/models/small/DeepSeek-V2-Lite-Chat.Q3_K_M.gguf
# C="-ngl 0 -r 3 -o md"

13:52:32  $ML -m $QW $C -t 32 -p 512 -n 128           # contaminated
13:55:44  $IK -m $QW $C -t 32 -p 512 -n 128           # contaminated
14:11:45  $ML -m $QW $C -n 128 -p 0 -t 16,32,64       # contaminated
14:20:52  $IK -m $QW $C -n 128 -p 0 -t 16,32,64
14:24:08  $IK -m $QW $C -p 512 -n 128 -t 16,32,64 -rtr 1
14:29:10  $ML -m $DS $C -t 32 -p 512 -n 128
14:31:05  $IK -m $DS $C -t 32 -p 512 -n 128
14:32:47  $ML -m $DS $C -n 128 -p 0 -t 16,32,64       # contaminated
14:50:14  $IK -m $DS $C -n 128 -p 0 -t 16,32,64
14:53:16  $IK -m $DS $C -p 512 -n 128 -t 16,32,64 -fmoe 0
14:56:23  $IK -m $DS $C -p 512 -n 128 -t 16,32,64 -rtr 1
14:59:36  $IK -m $DS $C -p 512 -n 128 -t 16,32,64 -fmoe 0 -rtr 1
15:03:25  $IK -m $QW $C -t 32 -p 512 -n 128
15:05:19  $IK -m $QW $C -t 32 -p 0   -n 128
15:07:02  $ML -m $QW $C -t 32 -p 512 -n 128
15:10:10  $ML -m $QW $C -t 32 -p 0   -n 128
15:13:15  $IK -m $QW $C -t 32 -p 0   -n 128           # contaminated
15:25:01  $IK -m $QW $C -t 32 -p 512 -n 128           # contaminated
15:28:11  $IK -m $QW $C -t 32 -p 512 -n 128           # contaminated
15:31:13  $ML -m $QW $C -t 32 -p 512 -n 128           # contaminated
15:45:21  $IK -m $QW $C -t 32 -p 512 -n 128
15:48:15  $ML -m $QW $C -t 32 -p 512 -n 128
15:51:22  $IK -m $QW $C -t 32 -p 512 -n 128
15:53:13  $ML -m $QW $C -t 32 -p 512 -n 128
15:56:19  $ML -m $DS $C -t 32 -p 512 -n 128
15:58:11  $IK -m $DS $C -t 32 -p 512 -n 128
15:59:53  $ML -m $DS $C -t 32 -p 0   -n 128
16:01:31  $IK -m $DS $C -t 32 -p 0   -n 128
16:02–16:17  raw-r5/: ik -t 32,31,30,28 and mainline -t 31   # all void
```

Raw stdout: `raw/` (matrix), `raw-ab/` (invocation-shape A/B), `raw-r4/` (repeatability
and MoE tiebreaker), `raw-r5/` (void). Per-run start/end with loadavg and server CPU time:
`commands.log`, `commands-ab.log`, `commands-r4.log`, `commands-r5.log`. Sampler:
`sampler.log`; the window audit tool is `audit.py`.

## 5. Premise corrections

- **The MoE URL in the spec 404s.** `bartowski/DeepSeek-V2-Lite-Chat-GGUF/.../DeepSeek-V2-Lite-Chat-Q3_K_M.gguf`
  returns HTTP 401. Used `mradermacher/DeepSeek-V2-Lite-Chat-GGUF/resolve/main/DeepSeek-V2-Lite-Chat.Q3_K_M.gguf`
  (8126607104 bytes), same model and quant. The dense URL was fine (3808391872 bytes).
  ik loaded the deepseek2 architecture without complaint.
- **ik's llama-bench is not built from HEAD.** It prints `build: 3bb386eb (4883)`; the
  tree's HEAD is 7b79b229. `git log --since=<libggml.so mtime> -- ggml/` is empty, so no
  CPU-kernel commit postdates the binary; only `src/` moved (7b79b229, DSpark draft
  acceptance). The kernel comparison stands, but the binary is not HEAD.
- **Mainline has no `--no-repack` runtime flag.** `llama-bench --help` lists none;
  `GGML_CPU_REPACK` is build-time only. That row was skipped, as the spec permits.
- **llama-bench's ± understates run-to-run variance badly.** It is within-process spread
  only. Identical ik command lines gave pp512 of 215.03, 218.02 and 218.64 on a quiet box
  with quoted ± of 1–4, and 115.66 under load. Treat the ± as a lower bound.
- ik labels the dense model `qwen2 ?B` where mainline says `qwen2 7B`, and reports its
  size as 7.60 GiB / 15.76 B params for the MoE against mainline's 7.56 GiB / 15.71 B.
  Cosmetic, but the tables are not comparing identical metadata.

## 6. What I could not do

1. **No clean mainline thread sweep for either model.** Both `-t 16,32,64` mainline runs
   fell inside lead load windows, so the t=16 and t=64 columns exist only for ik and no
   cross-engine thread-scaling comparison is possible.
2. **The contention-vs-thread-count control is unanswered.** Round 5 (ik at
   `-t 32/31/30/28` plus mainline at `-t 31`) was built to test whether ik's pp512
   collapse comes from contention or merely from having fewer cores; it ran 16:02–16:17,
   inside the lead's window, and is void. I stopped it on the stand-down and did not
   repeat it.
3. **I never implemented the `/tmp/cpu-busy.flag` gate.** The instruction arrived after
   these rounds were launched, and the stand-down forbids new runs, so no run in this
   report was flag-gated. The flag still existed at 16:40. This is the direct cause of
   the contaminated rows.
4. **The two ordered re-runs were not executed as such.** The lead asked for
   mainline-qwen7b-baseline and ik-qwen7b-baseline to be repeated after the flag cleared.
   I did not run those exact invocations again; the clean r2/r3/s1 repeats of the identical
   command line cover the same measurement and are what the tables use. The original two
   rows remain in `raw/`, marked contaminated.
5. **Runs 13:52 and 13:55 have no sampler coverage.** The sampler started at 13:54, so
   the mainline dense baseline was never audited by it; it is excluded on the lead's
   flag-window evidence alone.
6. **No cause is assigned.** Per the spec this report stops at the ratios. The dense and
   MoE tg ratios are both near 1.0 and neither is near 0.8, so the 20 % DeepSeek-V4.1-Flash
   decode deficit did not reproduce on either small model; what that implies is the lead's
   call.
