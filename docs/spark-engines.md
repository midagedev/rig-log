# DGX Spark 엔진 비교: 설치 경로와 드라이버 580

2026-11-03에 정리했다. 우리 Spark는 드라이버 580.178.04, CUDA 13.0, 커널 7.0.0-1024-nvidia이고 이 비교 동안 드라이버를 올리지 않는다.
이 표의 "580에서"는 출처가 말하는 최소 드라이버·빌드 CUDA와, 이 기계에서 실제로 떠서 답한 것을 나눠 적는다. 이전 세션의 조사
라운드 보고서는 다른 Mac에만 있어 여기서 읽지 못했고, 아래 출처는 이 세션이 직접 열어 대조한 것이다.

## 엔진

| 엔진 | 설치 경로(이 Spark) | 580에서 | 근거 |
|---|---|---|---|
| bloomery 0.3.12 | 릴리스 GB10 아카이브 `linux-aarch64-cuda-sm121a`(sha256 확인) → `/opt/engines` | **이 기계에서 뜸**(FP4-Local, 11-03) | bloomery `docs/dgx-spark.md` §1 "R580 or newer (CUDA 13)" |
| llama.cpp b12069 | 소스 빌드, `CMAKE_CUDA_ARCHITECTURES=121a-real`, 호스트 nvcc 13.0. 릴리스 arm64 CUDA 빌드는 13.4라 쓰지 않음 | 빌드됨 | NVIDIA dgx-spark-playbooks `nvidia/llama-cpp` 3단계 |
| Strata 0.2.10(엔진 0.1.56) | 릴리스 `strata-engine-…-linux-aarch64-cuda-cuda13`(피드 sha256 확인). 모델은 자체 pack이 필요 | 피드: CUDA 13.0 빌드, `min_driver 580.65` | `strata-feed-linux-aarch64.json`, Strata `docs/DGX_SPARK_LINUX.md`(580.173에서 시험) |
| TensorFold 1.2.1 | 릴리스 `tensorfold-1.2.1-linux-aarch64`(sha256 확인), `tensorfold-native` | README: "R580 or newer (CUDA 13.0)" | ashhart/TensorFold README "Linux with an NVIDIA GPU" |
| vLLM | eugr/spark-vllm-docker의 이미지(`eugr/spark-vllm-b12x`, `eugr/spark-vllm`; CUDA 13.0.2 베이스) | README: "Requires NVIDIA driver 580.x. Driver 590.x has a CUDAGraph capture deadlock on GB10" | eugr/spark-vllm-docker README(fbcc05dc), NVIDIA 포럼 379168: NGC vLLM 26.03+ 컨테이너는 CUDA 13.2라 595.58+ 필요 |
| SGLang | `lmsysorg/sglang:v0.5.23-cu130`(Qwen3.6), `lmsysorg/sglang:dev-qwen38-next-local`(Qwen3.8, Spark용) | 두 이미지 모두 `CUDA_VERSION=13.0.3` | 이미지 config, SGLang cookbook Qwen3.8-Flash-Next, NVIDIA playbook `nvidia/sglang`(`latest-cu130`) |
| Atlas | `avarok/atlas-gb10`(Docker). Qwen3.8은 `:5be3fc1` 고정 이미지 + `Inferact/Qwen3.8-Flash-Next-NVFP4`(183 GB, 다른 변환) | 가이드: "Min driver 580 (CUDA 13.0) … driver floor is hard" | Atlas `docs/GB10_DEPLOYMENT_GUIDE.md`, atlas-recipes `qwen3.8-flash-next-nvfp4.yaml` |
| Flare | 아티팩트 없음. 소스(NVIDIA/spark-local-inference, 옛 이름 flare-local-inference) cargo 빌드 + Ignition(uv, torch 2.14.1+cu132)으로 모델 준비 | 서빙은 SASS 패키지라 드라이버를 고정하지 않는다고 문서에 씀. **준비 쪽 cu132 torch가 580에서 도는지는 미확인** | Flare `docs/runtime-package-design.md`, `pyproject.toml` |
| sparkinfer | 제외(사용자 결정 11-03) | — | arm64 아티팩트 없음(릴리스는 x86_64 sm120뿐), CMake 아키텍처 목록에 121 없음, README에서 Spark는 "bring-up", Qwen3.8은 27B만 |

드라이버 580이 막는 엔진은 이번 조사에서 없었다. 거꾸로 vLLM(eugr 이미지)은 580을 요구한다. 그러니 드라이버를 올릴 이유가 없다.

## 판별 가중치

| | ① Qwen3.8-Flash-Next | ② Qwen3.6-35B-A3B |
|---|---|---|
| bloomery | FP4-Local, NVFP4, UD-Q4_K_XL(+MTP Q8_0) | UD-Q4_K_M(파일 안 MTP) |
| llama.cpp | UD-Q4_K_XL | UD-Q4_K_M, MTP는 `--spec-type draft-mtp` |
| vLLM | FP4-Local(eugr B12X 레시피) | NVFP4, FP8(eugr 레시피) |
| SGLang | NVFP4 + 파일 PLE(`--ple-offload-backend file`), 132.7 GB 폴더가 메모리에 그대로는 안 들어감 | NVFP4/FP8 |
| Atlas | Inferact NVFP4만(우리 다운로드 목록 밖, 자체 레시피가 19.3 tok/s라고 씀) | FP8, NVFP4(atlas-recipes) |
| Strata | 자체 pack(ISTA-DASLab GSQ-RCO IQ3_S GGUF 84 GB) | 지원 목록에 없음 |
| TensorFold | MLX 4-bit(별도 73 GB) | nvidia NVFP4 @1355db6a(우리 것과 같은 커밋) |
| Flare | FP4-Local → 준비된 패키지 | 레시피 없음 |

Strata와 llama.cpp는 같은 IQ3_S GGUF로도 잰다(사용자 결정 11-03). Strata의 튜닝 몫을 엔진 몫과 가르기 위해서다.

이해관계: 우리는 Strata에 커밋 넷(#1004, #1663, #1664, #1700)이 들어가 있다.

## 측정(11-03, 첫 판)

모두 드라이버 580.178.04이고 다운로드는 일시정지했다. 요청마다 `--temp 0 --no-think`, 디코드 256토큰, 프리필 프롬프트는 479토큰과 4,200토큰이다.
값은 세 요청의 중앙값(tok/s)이다. 엔진 사이를 비교할 때는 클라이언트 시계(`CLIENT=1 take-rows.py`)를 쓴다. 괄호 안은 bloomery·llama.cpp가 직접 보고한 서버 시계다.
수락률은 서버가 보고한 draft 수락/제안이다. vLLM의 수락률은 서버 로그의 SpecDecoding 줄에서 읽는다.

| 행 | 디코드 코드 | 디코드 산문 | 수락 코드/산문 | pp512 | pp4096 |
|---|---:|---:|---|---:|---:|
| Q3.8 FP4-Local · bloomery 기본(MTP 켜짐) | 62.5 (62.7) | 42.9 (43.1) | 0.87/0.53 | 1241 (1295) | 2268 (2281) |
| Q3.8 FP4-Local · bloomery rec | 63.9 (64.2) | 42.9 (43.1) | 0.86/0.54 | 1243 (1276) | 2330 (2335) |
| Q3.8 FP4-Local · bloomery MTP 끔 | 29.6 (29.7) | 29.8 (29.9) | — | 1285 (1311) | 2452 (2465) |
| Q3.8 FP4-Local · vLLM 기본 | 뜨지 않음: `PLE format 'nvfp4' requires the b12x execution backend` | | | | |
| Q3.8 FP4-Local · vLLM rec(eugr B12X, MTP 4) | 56.8 | 35.5 | 수락 길이 2.3–3.8 | 998 | 2002 |
| Q3.6 UD-Q4_K_M · bloomery 기본 | 67.4 (67.7) | 67.1 (67.4) | 파일에 MTP 없음 | 2504 (2569) | 4362 (4381) |
| Q3.6 UD-Q4_K_M · bloomery rec | 67.1 (67.4) | 67.4 (67.7) | 〃 | 2553 (2600) | 4384 (4407) |
| Q3.6 UD-Q4_K_M · bloomery MTP 끔 | 66.1 (66.3) | 66.1 (66.4) | — | 2549 (2590) | 4354 (4378) |
| Q3.6 UD-Q4_K_M · llama.cpp 기본 | 67.6 (67.6) | 68.0 (68.0) | — | 1915 (2204) | 2456 (2531) |
| Q3.6 UD-Q4_K_M · llama.cpp rec(playbook MTP) | 뜨지 않음: 이 파일에 MTP 층이 없다. playbook 체크포인트는 `unsloth/Qwen3.6-35B-A3B-MTP-GGUF`다 | | | | |

증인은 테이크마다 8개다. 로드 뒤 io avg10 최대는 0.46–1.97, MemAvailable 최저는 Q3.8에서 20.5 GB(vLLM)와 28.8–36.5 GB(bloomery)다.
bloomery MTP 끔 행만 load1이 7.00까지 올랐다. 원인은 가르지 않았다.
vLLM rec는 로드에 1,100초가 걸렸다. 대부분 b12x 커널 튜닝이다(`--rm` 컨테이너라 캐시가 남지 않는다).

## bloomery가 뒤지는 곳(첫 판)

1. **Qwen3.6 GGUF 순수 디코드.** MTP를 끈 bloomery는 66.1이다. 드래프트 없는 llama.cpp는 67.6–68.0이라 2–3 % 뒤진다. bloomery 기본(67.1–67.4)도 0.3–1.3 % 뒤진다.
   기본과 rec, MTP 끔의 차이는 `BLOOMERY_HOST_ROOM=96G --parallel 1 --ctx-size 16896`뿐이다. 이 파일에는 드래프트가 없으니, 1.0–1.3 tok/s 차이는 컨텍스트·호스트 룸 설정이 디코드에 미치는 몫이다.
   다음 판: nsys로 두 엔진의 토큰당 커널 시간을 비교한다(MoE gemv, attention, 샘플링 꼬리).
2. **MTP를 켜면 긴 프리필이 준다.** FP4-Local pp4096이 2452에서 2268–2330으로 5–8 % 준다. MTP 헤드의 프리필 몫, 또는 draft가 차지한 메모리 탓일 수 있다. MemAvailable은 36.5에서 28.8 GB로 줄었다.
   제안: 프리필 동안 MTP 헤드 KV 채우기를 미루거나 겹친다. MTP 헤드를 프리필 청크와 합친다.
3. **산문에서 MTP 이득이 작다.** 수락 0.53–0.54로 1.44배다. 코드는 0.87로 2.15배다. vLLM은 MTP 4개를 쓰고 1번 자리 수락이 0.66–0.91이다.
   제안: 산문에서는 `BLOOMERY_MTP_WIDTH`가 폭을 줄이는지 확인한다. cost 모드가 수락률에 따라 폭을 바꾸는지 기록을 본다.
4. **자기 README(드라이버 595.84) 대비.** README의 FP4-Local pp4096은 2,840/2,894이고 여기는 2,330이다(−18 %). 후보는 셋이다.
   (a) 드라이버 580 대 595.84. (b) 방법 차이: README는 `/completion`에 id를 보내고 워밍업 2회에 라운드마다 새 서버를 띄운다. 여기는 chat 경로에 워밍업이 없다. (c) 말뭉치.
   다음 판: 같은 기계에서 README 방법으로 다시 재서 (a)와 (b)를 가른다.

vLLM보다는 같은 FP4-Local에서 디코드 13–21 %, 프리필 16–25 % 앞선다. llama.cpp보다는 Qwen3.6 프리필이 1.3–1.8배 앞선다.

## 원인 조사(11-03 22:30 KST까지, 중간)

**MTP 폭(항목 3).** bloomery rec 서버 로그의 `mtp width` 줄에서 읽었다. 요청마다 한 줄이 남는다.

| 요청 | 창 | 폭 분포 [0,1,2,3] | 창당 남긴 토큰 e | 자리별 수락 a1/a2/a3 |
|---|---:|---|---:|---|
| 코드 ×3 | 71–76 | 대부분 3 (60–70창) | 3.26–3.61 | 0.93–0.98 / 0.94–0.97 / 0.93–0.97 |
| 산문 ×3 | 108–130 | 2 위주 (88–112창이 2 또는 3) | 1.97–2.38 | 0.65–0.73 / 0.48–0.68 / 0.22–0.56 |

같은 로그의 창 비용은 폭 0/1/2/3에서 33.6 / 42.4 / 49.0–50.4 / 53.2–55.4 ms다. 폭 0, 곧 드래프트 없는 한 스텝 33.6 ms는 MTP 끔 디코드 29.7 tok/s와 맞는다.
`cost` 규칙은 산문에서 실제로 폭을 2로 줄인다. 셋째 자리 수락이 0.2대라 3의 비용(+10 %)을 못 갚기 때문이다.
vLLM rec(MTP 4)의 산문 첫 자리 수락도 0.66–0.76이다(SpecDecoding 줄). 그러니 산문의 작은 이득은 bloomery의 폭 정책 탓이 아니라 모델의 산문 수락률 탓이다.
남는 레버는 검증 비용이다. 한 행 더 검증할 때마다 창이 +26 %(1행), +49 %(2행) 든다. 행마다 새 전문가를 읽는 MoE에서는 자연스러운 증가다.
드래프트 행들의 전문가 합집합을 한 번에 읽는 융합(행별 gemv 대신 그룹 gemm)이 이 비용을 줄일 후보다. nsys로 검증 창의 커널을 나눠 본 뒤에 판단한다.

**MTP와 긴 프리필(항목 2).** bloomery README 표의 Qwen3.6 `UD-Q4_K_M`은 파일 안 MTP 층이 있는 판(`unsloth/Qwen3.6-35B-A3B-MTP-GGUF`)이다. 그 판에서 pp4096이 2,826–2,848이다.
여기서 잰 MTP 없는 판은 MTP를 꺼도 켜도 4,354–4,384다. 드라이버와 방법이 다르니 그대로 빼면 안 된다. 그래도 FP4-Local에서 본 −5–8 %보다 훨씬 큰 차이(−35 %)일 수 있다는 신호다.
MTP 판이 받아지면 같은 기계, 같은 방법으로 MTP 켬/끔을 잰다. nsys 프리필 프로브(`probes-lag.sh nsys-prefill`)는 FP4-Local에서 MTP 헤드가 프롬프트 패스에 더하는 커널을 나눈다.
가설은 둘이었다. MTP 층이 모든 프롬프트 행을 지나간다(48층 중 1층, 약 2 %), 또는 헤드 로짓을 모든 행에서 계산한다. nsys는 둘 다 아니라고 말한다(아래 "nsys로 나눈 것").

**README 방법(항목 4).** README 표는 `/completion`에 id를 보내고, `cache_prompt` false, 128토큰, 서버 시계, 워밍업 2회, 라운드마다 새 서버로 쟀다. 디코드 칸은 512/4,096 프롬프트 뒤의 디코드다.
이것을 그대로 따르는 `ids-probe.py`를 큐에 넣었다. 말뭉치는 우리 것이라 방법만 README와 같다.
덧붙여, 우리 pp4096 세 프롬프트는 실제로 4,200 / 3,593 / 4,506 id다(pp512는 479 / 470 / 608). 표의 값은 그 중앙값이다.

## nsys로 나눈 것(11-03 23:30 KST)

도구: `nsys-probe.sh`(`--trace=cuda --cuda-graph-trace=node`, `cuda_gpu_kern_sum`). 요약 CSV는 테이크 디렉터리의 `kern.csv`다.

**디코드(항목 1): Qwen3.6 `UD-Q4_K_M`, MTP 끔, 산문 128토큰, 토큰당.**
bloomery는 커널 16.25 ms / 846회, llama.cpp는 15.90 ms / 1,515회다. 대역폭은 파일의 텐서 크기(gguf-py로 읽음)를 커널 시간으로 나눈 값이다. 전문가는 256개 중 8개를 읽는다.

| 텐서 무리 | 토큰당 바이트 | bloomery | llama.cpp | 차 |
|---|---:|---|---|---:|
| Q8_0 밀집(qkv·gate·ssm_out·q·o·k·v·공유 전문가) | 1,493 MB | `q8_0_gemv` 7.39 ms, 248회 · 202 GB/s | `mmvq` type 8 세 변종 6.42 ms, 168회 · 232 GB/s | **+0.97 ms** |
| 전문가 down Q5_K(37층) | 213 MB | `q5k_gemv_sel` 1.57 ms · 136 GB/s | type 13 1.09 ms · 196 GB/s | **+0.48 ms** |
| 전문가 gate+up Q4_K | 377 MB | `kq_gate_up_act_q4k` 2.31 ms · 163 GB/s | type 12 2.54 ms · 148 GB/s | −0.23 ms |
| 출력 헤드 Q6_K | 417 MB | 1.87 ms(argmax 융합) | 2.01 ms | −0.14 ms |
| 라우터·f32·양자화 | | 1.31 ms | 1.43 ms | −0.12 ms |

bloomery가 지는 곳은 Q8_0 밀집 gemv와 Q5_K down 둘이고, 합쳐 토큰당 1.45 ms(9 %)다. 전문가 gate/up과 헤드에서는 이긴다.
v0.3.12의 `q8_0_gemv`(`crates/gpu/src/q8f32.rs`)는 행 하나를 워프 하나가 맡고, 256스레드 블록이 8행을 맡는다. 활성은 f32 그대로 읽는다.
그래서 행마다 가중치 2.2 KB에 활성 8 KB(L1/L2)를 읽는다. 공유 전문가처럼 512행짜리 텐서는 64블록이라 48 SM을 겨우 한 번 채운다.
llama.cpp는 활성을 한 번 q8_1로 양자화하고(0.48 ms) 정수 내적으로 읽는다. 같은 입력의 gemv(공유 전문가 gate+up+GLU)는 한 번에 묶는다(변종 `<8,1,1,…>` 78회).
bloomery의 248회는 텐서 수(Q8_0 250개)와 같다. 융합이 없다는 뜻이다.

**프리필(항목 2): Qwen3.8 FP4-Local, 4,200토큰, rec와 nomtp.**
커널 합은 1,738 ms 대 1,649 ms(+89 ms, +5.4 %)다. 차이의 대부분은 MTP 저장 걷기(`WalkMode::Store`)다.

| 커널 | nomtp → rec 횟수 | 차 |
|---|---|---:|
| `hc_gated_down_mma_4` | 192 → 260 | +29.7 ms(+68회, 회당 436 µs) |
| `bf16_mma_gemm` | 2 → 202 | +25.5 ms(회당 126 µs) |
| `hc_gated_up_mma_mix_4`, `mtp_input`, `hc_gated_norm_4w_bf16`, `embed_rows_bf16` | 0–2 → 67–69 | +7.4 ms |
| 나머지: 대상 층 커널이 1–3회씩 더 돈다 | | 약 +26 ms |

67회는 4,200 / 64다. `mtp38.rs`의 `MTP_STORE_ROWS = 64`가 저장 걷기를 64행씩 자른다.
저장 걷기는 이미 k·v만 만든다. 쿼리·게이트·헤드는 건너뛴다. 그러니 헤드 로짓 가설은 틀렸다. 비용은 행 수가 아니라 걷기 수에서 나온다.
`hc_gated_down_mma_4`는 본 패스에서 약 2,100행에 757 µs인데, 저장 걷기에서는 64행에 436 µs다. 행당 19배 비싸다. 걷기마다 혼합 가중치를 다시 읽기 때문이다.
나머지 26 ms는 대상 패스다. `gate_up_nvfp4_mma`가 95 → 96회처럼 층 커널이 한 번씩 더 돈다.
MTP가 모든 행의 마지막 층 출력(`Hidden::Target`)을 요구해서 nomtp가 건너뛰던 끝 층 일부를 다 돌리는 것으로 읽는다. 확인은 하지 않았다.

## Qwen3.6의 MTP(11-04 00:30 KST)

MTP 층이 든 `unsloth/Qwen3.6-35B-A3B-MTP-GGUF` 판에서 잰 것이다. 클라이언트 시계로, tok/s다.

| 행 | 디코드 코드 | 디코드 산문 | pp512 | pp4096 |
|---|---:|---:|---:|---:|
| UD-Q4_K_M · bloomery rec(MTP) | 73.7 | 69.3 | 1754 | 2484 |
| UD-Q4_K_M · bloomery nomtp | 66.4 | 66.6 | 2553 | **4296** |
| UD-Q4_K_M · llama.cpp 기본 | 66.5 | 66.9 | 1895 | 2425 |
| UD-Q4_K_M · llama.cpp rec(`draft-mtp`, n-max 3) | **96.9** | **74.7** | 1746 | 2263 |
| UD-Q4_K_XL · bloomery rec | 68.2 | 64.0 | 1757 | 2487 |
| UD-Q4_K_XL · bloomery nomtp | 63.9 | 64.2 | 2563 | 4306 |
| UD-Q4_K_XL · llama.cpp rec | 94.4 | 71.3 | 1718 | 2253 |
| UD-Q4_K_XL · Strata 0.2.10(설정이 쓴 run config, `--mtp 2`) | 58.0 | 64.4 | 2048 | 2782 |

bloomery가 이 판에서 지는 곳은 두 군데다.

1. **MTP 디코드.** llama.cpp는 MTP로 코드 +46 %, 산문 +12 %를 얻는다. bloomery는 +11 %와 +4 %다.
   서버 기록(`mtp width`)을 보면 bloomery의 Qwen3.6 창은 폭 1이 최대다. 폭 0/1의 창 비용은 15.3 / 25.0 ms이고, e는 1.73–1.92다.
   `mtp35.rs`에서 `WALK_ROWS = 2`이고, `mtp_chain`은 자기 행(own row)을 이름으로 거절한다("a chain of {own} own rows"). 그러니 제안은 늘 한 토큰이다.
   llama.cpp는 같은 층을 세 번 이어 돌린다(평균 수락 길이 2.2–3.4).
   창 비용도 크다. 행 하나를 더 검증하는 데 +9.7 ms(+63 %)가 든다. 걷기가 eager로 돌고 그래프에 잡히지 않으며, 제안 id를 호스트로 읽어 오기 때문이다(모듈 문서 "A walk is eager. A captured walk is refused by name.").
2. **MTP를 켠 프리필.** pp4096이 4,296에서 2,484로 −42 %, pp512가 −31 %다. llama.cpp는 MTP를 켜도 −7 %다.
   `mtp35.rs`의 저장 걷기는 `STORE_ROWS = 2`다. 4,200행 프롬프트면 저장 걷기를 2,100번 돌리고, 걷기마다 `eh_proj`와 k·v 가중치를 다시 읽는다.
   더해진 시간은 1.69 − 0.98 = 0.71 s, 걷기당 약 0.34 ms다. nsys 확인은 큐에 있다(`probes-lag.sh nsys-prefill-q36mtp`).

Strata는 `--mtp 2`가 있어도 디코드가 MTP를 뺀 행과 같다(서버 로그에 드래프트 기록이 없다). 그래서 Strata의 MTP 행은 "효과 없음"으로 적는다.

## Qwen3.6 MTP를 nsys로 나눈 것(11-04 01:00 KST)

**프리필.** MTP 판 `UD-Q4_K_M`, 4,200토큰 프롬프트 하나, rec와 nomtp(`probes-lag.sh nsys-prefill-q36mtp`).
커널 합은 1,488.6 ms 대 940.8 ms, 실행은 40,006회 대 2,207회, 벽시계는 1.64 s 대 0.96 s다.

| 커널 | rec에서 더해진 횟수 | 더해진 시간 |
|---|---:|---:|
| `q8_0_gemv` | 16,800(행당 4) | **+470.5 ms** |
| `mtp_input` | 4,200 | +42.4 ms |
| `norm_quant` | 4,200 | +12.2 ms |
| `rms_norm` | | +10.5 ms |
| `head_norm_neox_append_256` | 4,200 | +9.1 ms |
| `embed_rows_q8_0` | | +7.9 ms |

저장 걷기는 프롬프트 행마다 한 번씩 디코드 모양 gemv로 돈다. `STORE_ROWS = 2`로 묶인 걷기 안에서도 커널은 행 단위다.
그래서 행마다 MTP 층의 Q8_0 가중치(`eh_proj`, k·v)를 4번 다시 읽는다. 앞 절의 0.71 s 가설이 맞고, 그 2/3가 `q8_0_gemv` 하나다.
참고로 Atlas는 MTP 드래프터 프리필이 4,505위치에 136 ms다. 프롬프트 전체를 한 번에 넘기는 MTP 패스가 싸게 된다는 증거다.

**디코드.** 같은 판, rec, 산문 요청 하나, 창 71개. 창당 커널은 약 28.7 ms(nsys 아래)다.

| 커널 | 창당 | 메모 |
|---|---:|---|
| `q8_0_gemv_mcol`(2행 검증) | 8.1 ms | 1행이면 7.39 ms |
| `qwen3moe_head_q6k_argmax_prefetch` | 2 × 1.87 ms | 검증 헤드(417 MB)를 행마다 따로 읽는다 |
| `q6k_gemv_prefetch` | 1.85 ms | 드래프트의 Q6_K 전체 어휘 헤드 |
| `kq_gate_up_*` | 3.7 ms | |
| `q5k_gemv_sel` | 2.65 ms | |
| `f32_tile_gemm` | 1.3 ms | 4,320회. 1행 `f32_gemv`는 0.35 ms |
| `gdn_delta_recovery(+_layers)` | 약 1.0 ms | 거절된 행의 상태 복구 |
| 라우터 | 1.05 ms | |
| `best_merge`/`part` | 0.4 ms | |

## Q8_0 gemv 마이크로벤치(11-04 01:00 KST)

bloomery 밖에서 잰다. `tools/spark/q8gemv-bench.cu`는 Qwen3.6 디코드 한 토큰의 Q8_0 텐서 250개(1,492.9 MB)를 모양 그대로 만들고, 변종별로 CUDA 그래프 하나로 300번 돌린다. 가중치는 임의 값이다.

| 변종 | 내용 | 토큰당 | GB/s |
|---|---|---:|---:|
| A | bloomery `q8_0_gemv` 모양: 워프당 1행, 4 B 코드, f32 활성 | 6.78 ms | 220 |
| B | A + 16 B 코드 읽기 | 6.91 ms | 216 |
| C | 활성 q8_1 양자화 + `dp4a`(llama.cpp 방식, 우리 구현) | 9.42 ms | 159 |
| F | C + 같은 입력 텐서 융합 | 9.30 ms | 161 |

그래프로 홀로 돌린 A는 220 GB/s다. 실제 디코드(nsys)의 202 GB/s, llama.cpp의 232 GB/s 사이다. 우리가 짠 C와 F는 오히려 느리다. 그러니 "dp4a로 바꾸면 된다"는 이 측정으로는 서지 않는다.
ncu(`--graph-profiling node`)로 보면 A는 행 수가 큰 텐서(1,024블록)에서 점유율 87 %이고, 512행 텐서(64블록)에서는 **21 %**다.
512행 텐서는 공유 전문가 gate·up 80개와 전체 주의층 k·v 20개, 토큰당 100개다. 하나에 1.1 MB를 15.2 µs(ncu 아래)에 읽는다. 약 73 GB/s다.
그래서 Q8_0 차이(+0.97 ms)의 유력한 자리는 커널 모양이 아니라 **작은 텐서가 GPU를 못 채우는 것**이다. 변종 D(512행 텐서만 4워프 split-K)는 다음 큐에 있다(`queue-night2.sh`).

## 개선 제안(순위, 11-04 01:15 KST)

순위는 "기대 이득 × 증거의 굳기"다. 이득은 위 측정에서 계산한 값이고, 소스 빌드로 확인한 것은 없다(빌드는 이번 밤에 미뤘다. 아래 "못 한 것").

| # | 어디 | 바꿀 것 | 기대 이득 | 증거 |
|---|---|---|---|---|
| 1 | `crates/gpu/src/arch/qwen3moe/mtp35.rs` `walk_rows`·`STORE_ROWS = 2`, `crates/app/src/arch/qwen3moe/mtp35.rs`의 저장 걷기 호출 | Qwen3.6 저장 걷기를 ubatch 전체의 GEMM으로: `eh_proj`·k·v를 `gemm_q8_0p`로 한 번 읽고, append만 행별로 | 4K 프롬프트당 −0.6 s. MTP 켠 pp4096 2,484 → 약 4,100(**+65 %**), pp512 1,754 → 약 2,500 | nsys: rec가 `q8_0_gemv` +16,800회 · +470 ms, `mtp_input` 4,200회. Atlas 드래프터 프리필 136 ms |
| 2 | `mtp35.rs` `mtp_chain`·`chain_rows`("a chain of {own} own rows"), `WALK_ROWS = 2` | 드래프트가 자기 행을 이어 받게 해 폭 2–3. 걷기를 그래프로 잡고 제안 id를 카드에 둔다(`MtpArena::Step` 길을 체인에도) | 코드 디코드 73.7 → 85–95(+15–30 %). 산문은 +5 % 안팎 | llama.cpp가 같은 MTP 층으로 n-max 3에서 코드 96.9 / 산문 74.7. bloomery는 폭 1이 최대(서버 `mtp width`) |
| 3a | Qwen3.6 검증 헤드(`qwen3moe_head_q6k_argmax_prefetch`) | 2행 검증 헤드를 한 번에: Q6_K 417 MB를 한 번 읽고 두 행의 argmax | 창당 −1.9 ms(25.0 → 23.1, +8 %) | nsys: 창당 2회 × 1.87 ms |
| 3b | Qwen3.6 드래프트 헤드(`q6k_gemv_prefetch`, `BLOOMERY_MTP_HEAD_ROWS`는 Qwen3.8만) | Qwen3.8의 줄인 어휘 헤드(76k 목록)를 Qwen3.6에도. 토크나이저가 같다 | 창당 약 −1.3 ms(+5 %), 수락률 소폭 손해 가능 | nsys 1.85 ms/창. 어휘가 둘 다 248,320 |
| 3c | 2행 f32 사이트(`f32_tile_gemm`) | 1–2행이면 `mcol` 식 gemv로 | 창당 −0.9 ms(+4 %) | 4,320회 1.3 ms vs 1행 `f32_gemv` 0.35 ms |
| 4 | `crates/gpu/src/q8f32.rs` `q8_0_gemv` | 512행 텐서(공유 전문가 gate·up, k·v)를 split-K로, 또는 gate+up을 한 실행으로 | 토큰당 최대 −1.0 ms(MTP 끔 디코드 +6 %) | ncu: 64블록 점유 21 %, 약 73 GB/s. 변종 D 결과는 큐에 |
| 5 | `q5k_gemv_sel` | llama.cpp type 13 식 읽기(196 GB/s) | 토큰당 −0.48 ms(+3 %) | nsys 136 vs 196 GB/s |
| 6 | `crates/gpu/src/arch/qwen3moe/mtp38.rs` `MTP_STORE_ROWS = 64` | Qwen3.8 저장 걷기를 ubatch로 | pp4096(MTP) +3.5 % | nsys +63 ms / 4,200토큰 |

1과 2는 같은 파일이고, 둘 다 "MTP 층을 디코드 모양으로만 돌린다"는 한 뿌리다. 그래서 함께 고치는 편이 싸다.
3a–3c는 서로 독립이고, 합치면 창당 약 −4 ms(+15–20 %)다. 2와 겹치지 않는다(창 비용과 창 길이는 곱으로 효과가 난다).
