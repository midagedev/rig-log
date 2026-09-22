*위임된 벤치마크 에이전트가 2026-09-13에 작성했으며, 보고한 그대로 게시했고, 실행한 모든 명령어를 포함한다.
이 문서는 [`log/2026-09-13.md#deepseek-v41-on-ik-llama`](../log/2026-09-13.md#deepseek-v41-on-ik-llama)의 소형 모델 CPU 수치의 출처다.
"리드"는 V4.1 측정을 함께 실행한 세션이며, 오염 섹션은 [`docs/quiet-machine.md`](quiet-machine.md) 뒤에 있는 사건을 다룬다. 내부 오류 하나: 이 에이전트가 404라고 부른 MoE URL은 실제로 401을 반환했다.*

# CPU 커널 벤치: ik_llama.cpp vs 메인라인 llama.cpp, 소형 모델, GPU 없음

머신: AMD 5975WX, 32코어, 251 GB RAM. 날짜: 2026-09-13.
모든 타이밍 런: `-ngl 0`, `CUDA_VISIBLE_DEVICES=` 비어 있음, `-r 3`, `-o md`, 엄격히 직렬.
트리: ik `/home/user/ik_llama.cpp` (HEAD 7b79b229), 메인라인 `/home/user/llama.cpp-v41` (HEAD 5210c7c).

**표보다 오염 섹션을 먼저 읽으라.** 런의 상당 부분이 리드가 시작한 200 GB 모델 로드와 겹쳤다.
해당 행은 `raw/`에 보관되지만 아래 모든 표에서 제외된다.

## 1. 빌드 구성

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

둘 다 명시적 `GGML_AVX*` 엔트리를 모두 OFF로 보고하지만 `GGML_NATIVE=ON`이다. NATIVE를 사용하면 컴파일 시 `-march=native`에서 ISA가 결정되므로, 해당 OFF 값이 AVX2 경로가 비활성화되었음을 의미하지는 않는다. 두 트리는 NATIVE와 OPENMP에 동의한다. CPU 행렬 곱셈에 영향을 주는 두 가지 방식에서 차이가 있다: 메인라인은 `GGML_LLAMAFILE=ON`(tinyBLAS sgemm)과 `GGML_CPU_REPACK=ON`을 가지며, ik의 캐시는 두 변수를 모두 노출하지 않는다.

메인라인의 `llama-bench`는 이번 라운드를 위해 빌드되었다(`cmake --build /home/user/llama.cpp-v41/build --target llama-bench -j 16`, 13:25:24 시작, "Built target llama-bench"). ik의 기존 바이너리는 재사용되었으며, HEAD 7b79b229가 아닌 `build: 3bb386eb (4883)`을 출력한다 — 전제 수정 사항 참조.

## 2. 결과

경쟁 로드와 겹치지 않은 행만 여기에 나타난다. "server-active"는 유휴 8001 `llama-server`가 샘플러의 계산에 따라 약 1코어를 소비한 행을 표시한다.

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

ik 평균 pp512 217.2, 메인라인 103.8 → **pp 비율 2.09**.
ik 평균 tg128 32.01, 메인라인 30.40 (엄격히 깨끗한 행만) → **t=32에서 ik / 메인라인 tg128 = 1.05**.
서버 활성 메인라인 행 두 개를 포함하면 메인라인 평균이 29.73으로 이동하고 비율은 1.08이 된다. 비율은 어느 쪽이든 1.05–1.08 대역에 있다.

ik 스레드 스윕, tg128, tg 전용 호출 (깨끗함; 깨끗한 메인라인 스윕은 존재하지 않음):

| threads | ik tg128 t/s |
| ---: | ---: |
| 16 | 30.57 ± 0.14 |
| 32 | 32.26 ± 0.09 |
| 64 | 20.68 ± 1.46 |

`-rtr 1`은 이 모델에서 거의 아무것도 바꾸지 않는다: pp 216.33 vs 217.2, tg 32.69 vs 32.01.

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

ik 평균 pp512 446.7, 메인라인 201.2 → **pp 비율 2.22**.
ik 평균 tg128 73.47, 메인라인 66.16 → **t=32에서 ik / 메인라인 tg128 = 1.11**.

ik 스레드 스윕, tg128, tg 전용 (깨끗함; 깨끗한 메인라인 스윕은 존재하지 않음):

| threads | ik tg128 t/s |
| ---: | ---: |
| 16 | 66.42 ± 0.32 |
| 32 | 73.57 ± 0.32 |
| 64 | 49.62 ± 6.40 |

융합 MoE를 끄면 pp의 약 2.5%, tg의 약 1.5%가 손실된다. `-rtr 1`은 pp의 약 2.5%, tg의 약 2%를 얻는다. 네 가지 ik 플래그 조합 모두 서로 5% 이내에 있으므로, 융합 MoE 경로나 런타임 리팩 중 어느 것도 추적 중인 크기의 어떤 것도 설명하지 못한다.

### 판정, 모델당 한 문장

- **Qwen2.5-7B (dense):** t=32에서 ik / 메인라인 tg128 비율은 1.05–1.08로, 1.0에 가깝다.
- **DeepSeek-V2-Lite (MoE):** t=32에서 ik / 메인라인 tg128 비율은 1.11로, 1.0에 가깝다.

### 구분: ik 이상치는 호출 형태 패널티가 아닌 오염이었다

라운드 중간에 같은 프로세스에서 tg128 전에 pp512를 실행하면 ik에 패널티가 있는 것처럼 보였다: 13:55 기준선은 ik tg128 26.98과 pp512 115.66을 gave 반면, tg 전용 런은 32.26을 gave. 깨끗한 교차 A/B가 그 가설을 기각했다. s1 세트에서 ik pp-then-tg는 tg 31.15를, ik tg 전용은 32.16을 gave (3% 차이), 반면 메인라인은 pp-then-tg 29.25 vs tg 전용 28.85를 went — 반대 방향이고 더 작았다. 13:55 수치는 단순히 200 GB 로드 중에 측정된 것이었다. **어느 엔진에도 pp-before-tg 패널티는 없다.**

### 보조 측정: ik의 프롬프트 경로는 경쟁 로드 하에서 훨씬 더 저하된다

동일한 ik 명령줄이 경쟁 로드가 실행되는 동안 pp512 115.66 (13:55)과 125.65 (15:28)을 produced, 반면 조용한 박스에서는 215.03 / 218.02 / 218.64를 produced — 약 45% 손실. 동일 조건에서 메인라인의 pp512는 99.12에서 104.27까지로, 5% 미만이다. 이것은 측정이 진단은 아니다: 경쟁 로드는 I/O 및 페이지 캐시가 무거운 200 GB 모델 로드였으므로, 코어 경합과 메모리 대역폭을 여기서 분리할 수 없다. 이를 분리하도록 설계된 컨트롤(런 5: ik `-t 32/31/30/28`)은 리드의 16:02–16:18 윈도우 안에 들어가 무효다.

## 3. 오염, 그리고 게이트가 놓친 이유

내 게이트는 30초 간격으로 두 샘플에서 1분 load average < 4를 요구했다. 그것은 잘못된 도구다: 200 GB 모델 로드는 I/O 바운드이며 늦게야 load average를 올리므로, 기계가 바쁜 동안 게이트가 열렸다. 13:54부터 실행된 10초 샘플러가 `ps -C llama-server` 누적 CPU 시간을 기록하여 `llama-server` 구성요소를 포착했지만, 내 하네스의 어떤 것도 리드의 로드를 보지 못했다. `/tmp/cpu-busy.flag` 프로토콜은 그것을 포착했을 것이다; 그것은 이 라운드들이 이미 시작된 후에 내게 도달했다.

표에서 제외된 행:

| run | window | why |
| --- | --- | --- |
| mainline-qwen7b-baseline | 13:52:32–13:53:14 | 리드의 플래그 윈도우 (13:32부터 플래그 존재) |
| ik-qwen7b-baseline | 13:55:44–13:56:14 | 동일; 이것이 pp 115.66 / tg 26.98 이상치 |
| mainline-qwen7b-tsweep | 14:11:45–14:17:22 | 리드의 로드 윈도우; 또한 서버가 ~0.7코어를 훔쳤고 서버 pid가 런 중간에 변경됨 |
| mainline-dsv2lite-tsweep | 14:32:47–14:37:42 | 리드의 로드 윈도우; tg128 t=32가 깨끗한 66.2 대비 59.69를 읽음 |
| s2-ik-tg-only | 15:13:15–15:13:31 | 리드의 15:06–15:15 로드 |
| s2-ik-pp-then-tg | 15:25:01–15:25:25 | 리드의 15:26–15:35 로드 |
| r1-ik-dense-pp-tg | 15:28:11–15:28:42 | 동일 윈도우; pp가 125.65를 읽음 |
| r1-ml-dense-pp-tg | 15:31:13–15:31:50 | 동일 윈도우 |
| all of raw-r5/ | 16:02–16:17 | 리드의 V4.1 CPU 전용 윈도우 16:02–16:18 |

명명할 가치가 있는 비대칭: 샘플러의 계산에 따르면 모든 메인라인 스레드 스윕은 `llama-server`가 ~0.7–0.8코어를 소비하는 동안 실행되었고, 모든 ik 스윕은 서버가 유휴인 동안 실행되었다. 그것만으로도 스윕 비교를 ik 쪽으로 몇 퍼센트 편향시키며, 이것이 위 표가 엔진 간 비율에 스윕이 아닌 교차 반복을 사용하는 또 하나의 이유다.

## 4. 정확한 명령어

모든 타이밍 런의 환경: `CUDA_VISIBLE_DEVICES=` (비어 있음). 두 바이너리 모두 여전히 CUDA 초기화 라인을 출력하고 백엔드를 "CUDA"로 레이블링한다; 변수가 비어 있으면 `no CUDA-capable device is detected`를 보고하며, 모든 런은 `-ngl 0`을 사용했다.

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

원본 stdout: `raw/` (행렬), `raw-ab/` (호출 형태 A/B), `raw-r4/` (재현성 및 MoE 타이브레이커), `raw-r5/` (무효). 런별 시작/종료와 load average 및 서버 CPU 시간: `commands.log`, `commands-ab.log`, `commands-r4.log`, `commands-r5.log`. 샘플러: `sampler.log`; 윈도우 감사 도구는 `audit.py`.

## 5. 전제 수정 사항

- **사양의 MoE URL이 404를 반환한다.** `bartowski/DeepSeek-V2-Lite-Chat-GGUF/.../DeepSeek-V2-Lite-Chat-Q3_K_M.gguf`는 HTTP 401을 반환한다. `mradermacher/DeepSeek-V2-Lite-Chat-GGUF/resolve/main/DeepSeek-V2-Lite-Chat.Q3_K_M.gguf` (8126607104 바이트)를 사용했다, 동일 모델 및 양자화. dense URL은 정상이었다 (3808391872 바이트). ik는 불만 없이 deepseek2 아키텍처를 로드했다.
- **ik의 llama-bench는 HEAD에서 빌드되지 않았다.** `build: 3bb386eb (4883)`을 출력한다; 트리의 HEAD는 7b79b229다. `git log --since=<libggml.so mtime> -- ggml/`는 비어 있으므로, 바이너리 이후에 CPU 커널 커밋이 없다; `src/`만 이동했다 (7b79b229, DSpark 초안 승인). 커널 비교는 유효하지만, 바이너리는 HEAD가 아니다.
- **메인라인에는 `--no-repack` 런타임 플래그가 없다.** `llama-bench --help`에 나열되지 않는다; `GGML_CPU_REPACK`은 빌드 타임 전용이다. 해당 행은 사양이 허용하므로 건너뛰었다.
- **llama-bench의 ±는 런 간 분산을 심하게 과소평가한다.** 그것은 프로세스 내 확산만이다. 동일한 ik 명령줄이 조용한 박스에서 pp512 215.03, 218.02, 218.64를 gave quoted ± 1–4, 그리고 로드 하에서 115.66을 gave. ±를 하한으로 취급하라.
- ik는 dense 모델을 메인라인이 `qwen2 7B`라고 말하는 곳에서 `qwen2 ?B`로 레이블링하고, MoE에 대해 7.60 GiB / 15.76 B params로 크기를 보고하며, 메인라인의 7.56 GiB / 15.71 B와 대비된다. 미관상 문제이지만, 표는 동일 메타데이터를 비교하지 않는다.

## 6. 내가 할 수 없었던 것

1. **어느 모델에 대해서도 깨끗한 메인라인 스레드 스윕이 없다.** 두 `-t 16,32,64` 메인라인 런 모두 리드 로드 윈도우 안에 들어가, t=16 및 t=64 열은 ik에만 존재하며 엔진 간 스레드 스케일링 비교는 불가능하다.
2. **경합 대 스레드 수 컨트롤은 미답변 상태다.** 라운드 5 (ik `-t 32/31/30/28` 및 메인라인 `-t 31`)는 ik의 pp512 붕괴가 경합에서 오는지 아니면 단순히 코어가 더 적어서인지 테스트하도록 설계되었으나, 리드의 윈도우 안에서 16:02–16:17에 실행되어 무효다. 스탠드다운 시 중단했고 반복하지 않았다.
3. **`/tmp/cpu-busy.flag` 게이트를 구현한 적이 없다.** 지시는 이 라운드들이 시작된 후에 도착했고, 스탠드다운은 새 런을 금지하므로, 이 보고서의 어떤 런도 플래그 게이트를 거치지 않았다. 플래그는 16:40까지 여전히 존재했다. 이것이 오염된 행의 직접 원인이다.
4. **두 개의 정렬된 재런은 그렇게 실행되지 않았다.** 리드는 플래그가 지워진 후 mainline-qwen7b-baseline과 ik-qwen7b-baseline을 반복하도록 요청했다. 나는 그 정확한 호출을 다시 실행하지 않았다; 동일 명령줄의 깨끗한 r2/r3/s1 반복이 동일 측정을 커버하며, 표가 사용하는 것이다. 원래 두 행은 `raw/`에 오염된 것으로 표시된 채 남아 있다.
5. **13:52 및 13:55 런은 샘플러 커버리지가 없다.** 샘플러는 13:54에 시작했으므로, 메인라인 dense 기준선은 결코 샘플러로 감사되지 않았다; 리드의 플래그 윈도우 증거만으로 제외된다.
6. **원인을 할당하지 않는다.** 사양에 따라 이 보고서는 비율에서 멈춘다. dense 및 MoE tg 비율 모두 1.0에 가깝고 어느 것도 0.8에 가깝지 않으므로, 20% DeepSeek-V4.1-Flash 디코드 결손은 어느 소형 모델에서도 재현되지 않았다; 그것이 무엇을 의미하는지는 리드의 호출이다.
