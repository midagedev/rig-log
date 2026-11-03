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
그래서 작은 텐서가 GPU를 못 채우는 것을 의심했고, 변종 D(512행 텐서만 4워프 split-K)를 만들었다.

| 변종(11-04 01:08 KST, 같은 벤치 재실행) | 토큰당 | GB/s |
|---|---:|---:|
| A | 6.85 ms | 218 |
| D | **6.71 ms** | 222 |

D는 −0.13 ms(−2 %)뿐이다. ncu 아래의 73 GB/s는 ncu가 실행마다 캐시를 비우고 직렬로 돌린 값이라 그래프 안의 실제보다 훨씬 나쁘다.
결론: bloomery의 Q8_0 gemv 모양은 홀로는 이미 약 220 GB/s(GB10 실효의 약 80 %)이고, 간단한 변형으로는 llama.cpp의 232 GB/s를 따라잡지 못했다.
실제 디코드의 202 GB/s와의 차이(약 0.5 ms)는 커널 밖, 즉 그래프 안의 앞뒤 커널과의 간섭이나 L2 상태에서 올 가능성이 크다. 이 제안은 순위를 내린다.

## 개선 제안(순위, 11-04 01:15 KST)

순위는 "기대 이득 × 증거의 굳기"다. 이득은 위 측정에서 계산한 값이고, 소스 빌드로 확인한 것은 없다(빌드는 이번 밤에 미뤘다. 아래 "못 한 것").

| # | 어디 | 바꿀 것 | 기대 이득 | 증거 |
|---|---|---|---|---|
| 1 | `crates/gpu/src/arch/qwen3moe/mtp35.rs` `walk_rows`·`STORE_ROWS = 2`, `crates/app/src/arch/qwen3moe/mtp35.rs`의 저장 걷기 호출 | Qwen3.6 저장 걷기를 ubatch 전체의 GEMM으로: `eh_proj`·k·v를 `gemm_q8_0p`로 한 번 읽고, append만 행별로 | 4K 프롬프트당 −0.6 s. MTP 켠 pp4096 2,484 → 약 4,100(**+65 %**), pp512 1,754 → 약 2,500 | nsys: rec가 `q8_0_gemv` +16,800회 · +470 ms, `mtp_input` 4,200회. Atlas 드래프터 프리필 136 ms |
| 2 | `mtp35.rs` `mtp_chain`·`chain_rows`("a chain of {own} own rows"), `WALK_ROWS = 2` | 드래프트가 자기 행을 이어 받게 해 폭 2–3. 걷기를 그래프로 잡고 제안 id를 카드에 둔다(`MtpArena::Step` 길을 체인에도) | 코드 디코드 73.7 → 85–95(+15–30 %). 산문은 +5 % 안팎 | llama.cpp가 같은 MTP 층으로 n-max 3에서 코드 96.9 / 산문 74.7. bloomery는 폭 1이 최대(서버 `mtp width`) |
| 3a | Qwen3.6 검증 헤드(`qwen3moe_head_q6k_argmax_prefetch`) | 2행 검증 헤드를 한 번에: Q6_K 417 MB를 한 번 읽고 두 행의 argmax | 창당 −1.9 ms(25.0 → 23.1, +8 %) | nsys: 창당 2회 × 1.87 ms |
| 3b | Qwen3.6 드래프트 헤드(`q6k_gemv_prefetch`, `BLOOMERY_MTP_HEAD_ROWS`는 Qwen3.8만) | Qwen3.8의 줄인 어휘 헤드(76k 목록)를 Qwen3.6에도. 토크나이저가 같다 | 창당 약 −1.3 ms(+5 %), 수락률 소폭 손해 가능 | nsys 1.85 ms/창. 어휘가 둘 다 248,320 |
| 3c | 2행 f32 사이트(`f32_tile_gemm`) | 1–2행이면 `mcol` 식 gemv로 | 창당 −0.9 ms(+4 %) | 4,320회 1.3 ms vs 1행 `f32_gemv` 0.35 ms |
| 4 | `q5k_gemv_sel` | llama.cpp type 13 식 읽기(196 GB/s) | 토큰당 −0.48 ms(+3 %) | nsys 136 vs 196 GB/s |
| 5 | `crates/gpu/src/arch/qwen3moe/mtp38.rs` `MTP_STORE_ROWS = 64` | Qwen3.8 저장 걷기를 ubatch로 | pp4096(MTP) +3.5 % | nsys +63 ms / 4,200토큰 |
| 6 | `crates/gpu/src/q8f32.rs` `q8_0_gemv` | 512행 텐서 split-K(변종 D), gate+up 한 실행 | 토큰당 −0.13 ms 확인(+1 %). llama.cpp와의 나머지 차이는 원인 미확정 | 마이크로벤치 A 6.85 → D 6.71 ms. dp4a 변종은 더 느렸다 |

1과 2는 같은 파일이고, 둘 다 "MTP 층을 디코드 모양으로만 돌린다"는 한 뿌리다. 그래서 함께 고치는 편이 싸다.
3a–3c는 서로 독립이고, 합치면 창당 약 −4 ms(+15–20 %)다. 2와 겹치지 않는다(창 비용과 창 길이는 곱으로 효과가 난다).

## 밤에 더한 행(11-04 01:20 KST)

클라이언트 시계, tok/s. 디코드 코드 / 산문 / pp512 / pp4096 순이다.

| 보드 · 파일 · 엔진 행 | 코드 | 산문 | pp512 | pp4096 |
|---|---:|---:|---:|---:|
| Qwen3.8 FP4-Local · Flare cc696a6b 기본(패키지 MTP 켬) | 47.5 | 36.8 | 1112 | 2232 |
| Qwen3.8 FP4-Local · Flare nomtp(`--mtp-draft-tokens 0`) | 26.7 | 27.0 | 1122 | 2353 |
| (비교) Qwen3.8 FP4-Local · bloomery rec | 63.9 | 42.9 | 1243 | 2330 |
| Qwen3.8 GSQ-RCO IQ3_S · Strata 0.2.10 기본(MTP) | **66.8** | **49.6** | 450 | 1577 |
| Qwen3.8 GSQ-RCO IQ3_S · Strata nomtp | 31.7 | 34.5 | 388 | 1585 |
| Qwen3.8 GSQ-RCO IQ3_S · llama.cpp b12069 `-c 16896` | 30.9 | 31.1 | 655 | 752 |
| Qwen3.8 GSQ-RCO IQ3_S · bloomery | 거절 | | | |

- Flare는 bloomery보다 디코드가 26 %(코드)·14 %(산문) 느리고, pp4096은 비슷하다. 첫 실행은 무인 실행에 키 승인을 요구해 거절됐다. 패키지는 우리가 내보낸 것이고 서명 키는 로컬 개발 키라서 그 지문(일치 확인)을 넘겨 다시 돌렸다.
- 같은 IQ3_S GGUF에서 Strata와 llama.cpp를 비교하면, MTP 없이 디코드는 Strata가 3–11 % 빠르다. 프리필은 pp512에서 llama.cpp가 1.7배, pp4096에서 Strata가 2.1배 빠르다. Strata의 MTP는 Qwen3.8에서는 효과가 있다(+111 % / +44 %). Qwen3.6에서 효과가 없던 것과 다르다.
- bloomery는 이 파일을 연다고 하지 않는다. `blk.0.ffn_down_shexp.weight: type iq4_nl has no device format`이다. 공유 드래프트를 붙인 rec는 `token_embd`가 iq4_xs라서 거절된다("the MTP draft reads the target's token_embd as Q8_0 or BF16").
  그러니 Strata가 고른 Qwen3.8 무게(83.6 GB, 공유 전문가 IQ4_NL)는 bloomery에 없는 형식이다. 이 자리의 bloomery 비교 행은 `UD-Q4_K_XL`이다(rec 52.1 / 36.9 / 816 / 1524).

**bloomery가 못 여는 Qwen3.6 safetensors.** 0.3.12 GB10 아카이브의 `bloomery-serve`는 Qwen3.6 MoE 체크포인트 폴더를 받지 않는다.
NVIDIA NVFP4(ModelOpt)는 `config.json: config.dtype is not a key this converter reads`, Qwen FP8은 `lm_head.weight: not a Qwen3.6 tensor`, TensorFold MLX 4-bit MTP는 `a qwen35moe model, where this seat serves qwen35`(`serve_seats/folder.rs`)다.
README가 말하는 Qwen3.6 폴더 길은 `prepare`로 GGUF를 만드는 것이다(`docs/mac.md`). `prepare`는 이 아카이브에 없다. 그래서 보드 2의 NVFP4·FP8·MLX 열에 bloomery 행은 없다.

## 같은 Qwen3.6, 다른 Q4_K_M 파일(11-04 01:30 KST)

juliankang4의 테이프(bloomery 0.3.0, 드라이버 595.84)는 lmstudio-community의 `Q4_K_M`에서 잰 것이다. 우리 보드 2의 GGUF는 unsloth의 `UD-Q4_K_M`이다. 이름은 같아도 밀집 텐서가 다르다(헤더에서 읽음, 임베딩·MTP 층 뺌).

| 파일 | 밀집 | 전문가 전체(토큰당 8/256) | 헤드 | 토큰당 읽기 |
|---|---|---:|---:|---:|
| lmstudio `Q4_K_M` @68a34855 | Q4_K 645 MB + Q6_K 215 MB | 19.5 GB(0.61 GB) | Q6_K 417 MB | 약 1.9 GB |
| unsloth `UD-Q4_K_M`(MTP 판) | **Q8_0 1,525 MB** | 20.1 GB(0.63 GB) | Q6_K 417 MB | 약 2.6 GB |

| lmstudio `Q4_K_M` 행 | 코드 | 산문 | pp512 | pp4096 |
|---|---:|---:|---:|---:|
| bloomery 0.3.12 기본 | **92.0** | **92.7** | **2582** | **4549** |
| llama.cpp b12069 기본 | 76.7 | 77.5 | 1919 | 2415 |

토큰당 읽기로 나누면 bloomery는 두 파일에서 같은 실효 대역폭(약 174 GB/s)을 낸다. llama.cpp는 `UD`에서 176, lmstudio에서 146 GB/s다.
그러니 `UD` 파일에서 bloomery가 llama.cpp와 비기는 것은 llama.cpp의 Q8_0 경로가 강해서다. lmstudio 파일에서는 bloomery가 디코드 +20 %, pp4096 +88 %로 앞선다.

**테이프 교차 확인.** toktape 0.8.0, prompts@v2, 기본 인자, 세 번. 프롬프트 7,258 id.

| | 디코드 | 프리필 | ITL p50 |
|---|---:|---:|---:|
| juliankang4, bloomery 0.3.0, 드라이버 595.84, 2슬롯 | 86.9 | 4,301 | 11.28 ms |
| 우리, bloomery 0.3.12, 드라이버 580.178.04, 1슬롯(0.3.12 기본) | 80.7–81.1 | 4,779–4,827 | 12.20–12.27 ms |
| 우리, llama.cpp b12069 | 70.1–70.5 | 2,417–2,427 | 14.03–14.14 ms |

프리필은 우리가 12 % 빠르고 디코드는 7 % 느리다. 차이의 후보는 셋이다. 드라이버(580 대 595), 판(0.3.0 대 0.3.12, 0.3.0의 GB10 아카이브는 없어 같은 판으로 못 돌렸다), 슬롯 수다.
드라이버는 하드 스톱이라 바꾸지 않았다. 0.3.11 아카이브는 있으니, 판 차이를 좁히는 다음 값싼 시험은 0.3.11로 같은 테이프를 다시 받는 것이다.

## Qwen3.8: TensorFold가 코드 디코드에서 앞서는 이유(11-04 01:45 KST)

TensorFold 1.2.1은 자기 MLX 4-bit MTP 판(113 GB, @2b170fa6)으로 잰다. 가중치가 bloomery의 FP4-Local과 다르니, 같은 파일 비교는 아니다.

| 행 | 코드 | 산문 | pp512 | pp4096 |
|---|---:|---:|---:|---:|
| TensorFold MLX 4-bit MTP 기본 | **74.4** | **44.0** | 978 | 1503 |
| TensorFold MLX 4-bit MTP `--no-drafts` | 29.3 | 28.1 | 1052 | 1584 |
| bloomery FP4-Local rec | 63.9 | 42.9 | **1243** | **2330** |
| bloomery FP4-Local nomtp | 29.6 | 29.8 | 1285 | 2452 |

MTP 없이 두 엔진은 같다(29.3 대 29.6). 차이는 MTP 체인 길이에서 나온다.
TensorFold 서버 기록으로는 코드 요청이 54–63라운드에 192–201개를 받는다. 라운드당 약 4.7토큰이고 수락률은 약 73 %다.
bloomery rec의 `mtp width` 기록에서 코드 요청은 폭 3(최대)을 고르고, 세 드래프트의 수락률이 0.93–0.97이다. 창당 e = 3.3–3.6, 창 비용은 폭 3에서 53–55 ms다.
수락률이 0.95인데도 폭이 3에서 멈추는 이유는 `crates/runtime/src/stores.rs`의 `DELTA_VERIFY_ROWS = 4`다. Qwen3.8의 gated-delta 층 검증 기록이 4행(대상 1 + 드래프트 3)까지이고, 폭 선택기의 배열도 4칸이다.

**제안 7(새로).** `DELTA_VERIFY_ROWS`를 6으로 올리고 폭 선택기를 5까지 넓힌다. 검증 기록은 행당 `3·state` f32라 늘어나는 메모리는 작다.
폭 1→2→3의 창 비용 증가가 약 8 → 7 → 5 ms이니 폭 5를 약 64 ms로 잡는다. 수락률 0.95가 이어지면 e ≈ 5.3이고, 코드 디코드는 약 64 → 83 tok/s(+30 %)다. 산문은 선택기가 폭 2를 고르니 그대로다.
값싼 확인으로 `BLOOMERY_MTP_HEAD_ROWS=full`과 `BLOOMERY_MTP_WIDTH=fixed` 행을 큐에 넣었다(`queue-night6.sh`).

## SGLang의 Qwen3.8 한 대 셀(11-04 02:05 KST)

`lmsysorg/sglang:dev-qwen38-next-local`(4ccff141db), NVIDIA `Qwen3.8-Flash-Next-NVFP4`(ModelOpt MIXED_PRECISION), 쿡북의 한 대 셀 그대로다(`rows-sglang-q38.sh`). N-gram 표 47.7 GiB는 NVMe 파일에 두고 부팅마다 새로 만든다. 부팅은 11–13분 걸렸고, 부하 중 MemAvailable은 15–20 GB였다.

| 행 | 코드 | 산문 | pp512 | pp4096 |
|---|---:|---:|---:|---:|
| SGLang MTP(NEXTN 3단, 4 드래프트) | 30.2 | 21.5 | 560 | 1598 |
| SGLang MTP 없음 | 15.2 | 14.9 | 633 | 1561 |

쿡북의 측정(MTP 27.5, 없음 15.9 tok/s 한 요청)과 맞는다. 한 대에서는 표를 NVMe에서 읽느라 bloomery FP4-Local(rec 63.9 / 42.9, nomtp 29.6)의 절반이다. 수락 길이는 2.2–3.8이었다.

**테이프 차이 좁히기(11-04 02:10 KST, `queue-night5.sh`).** 같은 lmstudio `Q4_K_M`, 같은 테이프 프로브, 세 번.

| | 디코드 | 프리필 | ITL p50 |
|---|---:|---:|---:|
| bloomery 0.3.11 기본(1슬롯) | 81.0–83.7 | 4,578–4,582 | 11.65–12.20 ms |
| bloomery 0.3.12 `--parallel 2` | 81.6–81.8 | 4,767–4,793 | 12.09–12.11 ms |
| (앞) bloomery 0.3.12 기본(1슬롯) | 80.7–81.1 | 4,779–4,827 | 12.20–12.27 ms |

슬롯 수와 0.3.11→0.3.12는 디코드 차이(테이프 86.9 대 약 81)를 설명하지 못한다. 남은 후보는 드라이버(580 대 595.84)와, 테이프의 0.3.0이 소스 빌드였다는 점이다. 드라이버는 하드 스톱이라 시험하지 않았다. 0.3.12는 0.3.11보다 프리필이 4 % 빠르다.

**레버 두 개(11-04 02:20 KST, `queue-night6.sh`).** Qwen3.8 FP4-Local, rec와 같은 서버에 레버 하나씩.

| 행 | 코드 | 산문 | pp512 | pp4096 | 수락(코드/산문) |
|---|---:|---:|---:|---:|---|
| rec(폭 `cost`, 줄인 헤드) | 63.9 | 42.9 | 1243 | 2330 | 0.86 / 0.54 |
| `BLOOMERY_MTP_HEAD_ROWS=full` | 58.5 | 38.6 | 1218 | 2286 | 0.89 / 0.57 |
| `BLOOMERY_MTP_WIDTH=fixed` | 62.7 | 42.3 | 1212 | 2280 | 0.86 / 0.43 |

전체 어휘 헤드는 수락률을 조금 올리지만 드래프트 걷기가 비싸져 9–10 % 느리다. 줄인 헤드가 맞는 기본값이다.
폭을 늘 3으로 고정해도 코드는 rec와 같다. 코드에서는 `cost`가 이미 폭 3을 고르고 있었다는 뜻이다. 그러니 코드 디코드의 상한은 선택기가 아니라 4행 검증 상한(`DELTA_VERIFY_ROWS`)이다. 제안 7의 근거가 하나 더 선다.

## 아침 요약(11-04 02:30 KST 기준, Atlas NVFP4는 02:25에 더함)

모두 이 Spark 한 대(GB10, 드라이버 580.178.04)에서 잰 것이다. 클라이언트 시계, tok/s, 세 번의 중앙값이다. 디코드는 코드·산문 각 256토큰이고, pp는 479 / 4,200 id 프롬프트다. 엔진은 한 번에 하나씩 돌렸고, 로드 전마다 drop_caches를 했다.

**보드 1: Qwen3.8-Flash-Next**

| 파일 | 엔진 · 행 | 코드 | 산문 | pp512 | pp4096 |
|---|---|---:|---:|---:|---:|
| FP4-Local | bloomery rec | 63.9 | 42.9 | **1243** | 2330 |
| FP4-Local | bloomery 기본 | 62.5 | 42.9 | 1241 | 2268 |
| FP4-Local | bloomery nomtp | 29.6 | 29.8 | 1285 | **2452** |
| FP4-Local | Flare 기본 / nomtp | 47.5 / 26.7 | 36.8 / 27.0 | 1112 / 1122 | 2232 / 2353 |
| FP4-Local | vLLM rec / nomtp(기본 행은 실패) | 56.8 / 26.9 | 35.5 / 26.9 | 998 / 1110 | 2002 / 2146 |
| TF MLX 4-bit MTP | TensorFold 기본 / `--no-drafts` | **74.4** / 29.3 | **44.0** / 28.1 | 978 / 1052 | 1503 / 1584 |
| NVIDIA NVFP4 | SGLang MTP / 없음(N-gram 표 NVMe) | 30.2 / 15.2 | 21.5 / 14.9 | 560 / 633 | 1598 / 1561 |
| UD-Q4_K_XL | bloomery 공유 드래프트 / nomtp | 52.1 / 28.8 | 36.9 / 29.0 | 816 / 842 | 1524 / 1558 |
| UD-Q4_K_XL | llama.cpp `-c 16896` | 27.5 | 27.4 | 672 | 767 |
| GSQ-RCO IQ3_S | Strata 기본(MTP) / nomtp | 66.8 / 31.7 | 49.6 / 34.5 | 450 / 388 | 1577 / 1585 |
| GSQ-RCO IQ3_S | llama.cpp `-c 16896` | 30.9 | 31.1 | 655 | 752 |
| GSQ-RCO IQ3_S | bloomery | 거절(iq4_nl) | | | |

**보드 2: Qwen3.6-35B-A3B**

| 파일 | 엔진 · 행 | 코드 | 산문 | pp512 | pp4096 |
|---|---|---:|---:|---:|---:|
| lmstudio Q4_K_M | bloomery 기본 | 92.0 | **92.7** | 2582 | 4549 |
| lmstudio Q4_K_M | llama.cpp 기본 | 76.7 | 77.5 | 1919 | 2415 |
| UD-Q4_K_M(MTP 판) | bloomery rec / nomtp | 73.7 / 66.4 | 69.3 / 66.6 | 1754 / 2553 | 2484 / 4296 |
| UD-Q4_K_M(MTP 판) | llama.cpp rec / 기본 | 96.9 / 66.5 | 74.7 / 66.9 | 1746 / 1895 | 2263 / 2425 |
| UD-Q4_K_XL(MTP 판) | bloomery rec / nomtp | 68.2 / 63.9 | 64.0 / 64.2 | 1757 / 2563 | 2487 / 4306 |
| UD-Q4_K_XL(MTP 판) | llama.cpp rec / 기본 | 94.4 / 65.5 | 71.3 / 65.8 | 1718 / 1898 | 2253 / 2429 |
| UD-Q4_K_XL(MTP 판) | Strata 기본 / nomtp(MTP 효과 없음) | 58.0 / 58.6 | 64.4 / 64.4 | 2048 / 2114 | 2782 / 2896 |
| NVIDIA NVFP4 | SGLang MTP / rec(기본 행은 실패) | **120.1** / 79.7 | 91.4 / 79.9 | 3467 / **3874** | 4179 / **6742** |
| NVIDIA NVFP4 | TensorFold 기본 / nomtp | 64.1 / 64.0 | 63.9 / 64.1 | 3489 / 3484 | 5188 / 5175 |
| TF MLX 4-bit MTP | TensorFold 기본 / nomtp | 82.0 / 82.4 | 82.4 / 82.5 | 3584 / 3587 | 5514 / 5509 |
| Qwen FP8 | SGLang MTP / 기본 | 68.0 / 53.0 | 51.6 / 53.1 | 2267 / 1537 | 5805 / 4643 |
| NVIDIA NVFP4 | Atlas `:dev` nvfp4 레시피(MTP K=1) / nomtp | **141.2** / 95.8 | **123.6** / 96.4 | 1505 / 1591 | 2628 / 2788 |
| Qwen FP8 | Atlas 기본 / rec / nomtp | 66.8 / 64.8 / 55.3 | 67.3 / 58.6 / 55.0 | 521 / 427 / 433 | 1017 / 962 / 982 |
| NVFP4 · FP8 · MLX | bloomery | 거절(폴더 형식) | | | |

**bloomery가 지는 곳과 원인(증거)**

1. Qwen3.6 MTP를 켠 프리필: pp4096 −42 %. 저장 걷기가 행마다 디코드 모양 gemv로 돈다(nsys `q8_0_gemv` +16,800회, +470 ms).
2. Qwen3.6 MTP 디코드: 코드 73.7 대 llama.cpp 96.9. 제안이 늘 한 토큰이고(`mtp_chain`이 자기 행 거절), 창 25 ms 안에 헤드를 두 번 읽는다.
3. Qwen3.8 코드 디코드: 63.9 대 TensorFold 74.4. 수락률 0.95인데 검증 4행 상한(`DELTA_VERIFY_ROWS`)에서 폭 3에 멈춘다.
4. Qwen3.6 NVFP4/FP8 폴더를 못 연다. 이 칸의 최고는 디코드 Atlas 141.2 / 123.6, 프리필 SGLang rec pp4096 6,742다.
   Atlas는 MTP 폭 1(K=1)로 코드 +47 %를 얻는다. 같은 폭 1에서 bloomery는 +11 %다. 폭이 아니라 창 비용(bloomery는 폭 1 창이 평 걸음의 1.63배, Atlas는 e ≤ 2로 계산하면 1.36배 이하)이 차이다. 제안 ③④의 근거다.
5. unsloth `UD` 파일의 Q8_0 밀집에서 llama.cpp와 비긴다(실효 174 대 176 GB/s). lmstudio 파일에서는 bloomery가 +20 %다.
6. Strata가 고른 IQ3_S(공유 전문가 IQ4_NL)를 못 연다.

**제안 순위(위 "개선 제안" 표 + 제안 7)**: ① Qwen3.6 저장 걷기를 ubatch GEMM으로(pp4096 MTP +65 %) ② Qwen3.8 검증 상한 4 → 6, 폭 5(코드 +30 %) ③ Qwen3.6 체인 폭 2–3과 걷기 그래프 캡처(코드 +15–30 %) ④ Qwen3.6 창의 헤드 한 번 읽기·줄인 드래프트 헤드·mcol f32(창당 −4 ms, +15–20 %) ⑤ Qwen3.6 NVFP4 폴더 열기(형식) ⑥ Q5_K sel(+3 %) ⑦ Qwen3.8 `MTP_STORE_ROWS`(+3.5 %) ⑧ Q8_0 gemv split-K(+1 % 확인).

**실패와 못 한 것**: SGLang Qwen3.6 NVFP4 기본 행(`'FusedMoE' object has no attribute 'g1_scale_c'`), vLLM Qwen3.8 기본 행, Strata Qwen3.6 MTP 효과 없음, TensorFold Qwen3.6 MTP 효과 없음(수락 0/0), bloomery 소스 빌드(CUDA 13.3이 필요해 미룸) — 그래서 제안 이득은 모두 계산값이다.

**폭과 창 비용 가르기(11-04 02:33 KST).** 같은 MTP 판 `UD-Q4_K_M`, llama.cpp를 bloomery와 같은 폭 1로(`--spec-draft-n-max 1`, `rows-gguf.sh llamacpp-mtp1`).

| 행 | 코드 | 산문 | 수락(코드/산문) | MTP 끔 대비 코드 |
|---|---:|---:|---|---:|
| bloomery rec(폭 1) | 73.7 | 69.3 | 0.89 / 0.74 | +11 % |
| llama.cpp n-max 1 | 83.1 | 76.6 | 0.93 / 0.74 | +25 % |
| llama.cpp n-max 3 | 96.9 | 74.7 | 0.78 / 0.48 | +46 % |

수락률이 비슷한 같은 폭 1에서 llama.cpp가 코드 +13 %, 산문 +11 % 앞선다. 이 몫은 창 비용(제안 ④: 헤드 한 번 읽기, 줄인 드래프트 헤드, mcol f32, 걷기 그래프 캡처)이다.
폭 1 → 3이 코드에 +17 %를 더한다. 이 몫이 체인 폭(제안 ③)이다. 산문은 폭 3에서 수락률이 떨어져 오히려 −2 %다. 그러니 폭은 bloomery의 `cost` 선택기처럼 요청마다 골라야 한다.

**테이프 표본으로 본 차이(11-04 02:35 KST).** toktape는 요청 중 GPU 클록·전력·온도·사용률을 표본으로 남긴다. 디코드 중 표본의 중앙값이다.

| 테이프 | bloomery | 드라이버 | 호스트 커널 | 디코드 | ITL p50 | 클록 | 전력 | 사용률 |
|---|---|---|---|---:|---:|---:|---:|---:|
| juliankang4 | 0.3.0 | 595.84 | 6.17.0-1032-nvidia | 86.9 | 11.28 ms | 2,502 MHz | 53.7 W | 94 % |
| 우리 ×3 | 0.3.12 | 580.178.04 | 7.0.0-1024-nvidia | 80.6–81.1 | 12.20–12.27 ms | 2,548 MHz | 50.6–52.1 W | 90 % |

클록은 우리가 더 높으니 클록이나 온도 탓은 아니다. 토큰당 0.93 ms 차이를 사용률로 나누면, GPU가 바쁜 시간은 10.6 대 11.0 ms(+0.4 ms), 노는 시간은 0.68 대 1.22 ms(+0.5 ms)다.
노는 시간이 두 배인 것은 실행 경로(드라이버의 그래프 실행, 호스트 커널)를 가리킨다. 드라이버와 커널이 둘 다 다르고 둘 다 하드 스톱이라, 여기서 더 가를 수는 없다. 출력 길이도 1,590 대 약 1,495토큰으로 다르다(판이 달라 답이 다르다).

## 소스 빌드로 잰 제안 ②⑦(11-04 03:20 KST)

Spark의 `nvidia/cuda:13.3.1-devel-ubuntu24.04` 컨테이너에서 bloomery v0.3.12(a44384d2)를 빌드했다. 호스트 드라이버 580과 커널은 그대로다. 13.3로 빌드한 바이너리는 드라이버 580에서 그대로 돌았다. 그래서 CUDA 13.0이나 PTX 우회는 필요 없었다.
패치는 Spark의 스크래치 클론에만 했다(origin 원격 제거, 푸시·PR 없음). 비교 기준은 릴리스 바이너리가 아니라 같은 컨테이너에서 빌드한 무패치 `base`다. Qwen3.8 FP4-Local, MTP `cost`, `--parallel 1`, 클라이언트 시계로 행마다 두 번 쟀다(take.sh, 엔진 하나씩, drop_caches).

| 빌드 | 바꾼 것 | 코드 | 산문 | 수락(코드/산문) | pp512 | pp4096 |
|---|---|---:|---:|---|---:|---:|
| 릴리스 0.3.12 | — | 63.9 | 42.9 | 0.86 / 0.54 | 1243 | 2330 |
| `base` ×2 | — | 63.7 / 63.2 | 43.9 / 44.8 | 0.87 / 0.55 | 1240 / 1245 | 2445 / 2434 |
| `w5` ×2(②) | `DELTA_VERIFY_ROWS` 4 → 6, 폭 상한 3 → 5 | **69.0 / 68.9** | 43.0 / 43.3 | 0.78 / 0.56 | 1242 / 1242 | 2446 / 2452 |
| `s512` ×2(⑦) | `MTP_STORE_ROWS` 64 → 512 | 63.1 / 63.1 | 41.6 / 43.9 | 0.87 / 0.55 | 1265 / 1263 | **2510 / 2497** |

| 제안 | 추정 | 잰 값(`base` 대비) |
|---|---|---|
| ② 검증 4 → 6행, 폭 5 | 코드 64 → 83(+30 %) | 코드 +8.6 %(63.5 → 69.0), 산문 −2.5 %, 프리필 그대로 |
| ⑦ 저장 행 512 | pp4096 +3.5 % | pp4096 +2.6 %(2,440 → 2,504), 디코드 그대로 |

②가 추정의 3분의 1에 그친 이유는 서버 로그 `mtp width`에 있다. 코드 요청에서 선택기는 폭 5를 가장 많이 골랐다(62창 중 30). 창 비용은 행마다 약 6.5 ms 늘었다(폭 2–5에서 47.1 / 54.8 / 61.9 / 67.3 ms). 추정은 이 증가를 4행까지의 기울기보다 작게 잡았다.
선택기 자신의 비율 추정(rates)은 폭 5가 폭 3보다 +17 %였고, 잰 값은 +9 %다. TensorFold 74.4까지는 아직 7 % 남는다. 창 비용을 줄이는 쪽(행당 비용)이 다음 수다.
산문은 폭 3을 넘는 창에서 수락이 떨어져 선택기가 대개 폭 2–3에 머문다. 그래서 산문은 그대로다.
패치에는 두 곳을 함께 고쳐야 했다. `place.rs`의 `mtp_arena_bytes` 상수가 gpu 크레이트의 아레나 검사와 맞아야 로드된다(w5: 793 → 797, s512: 5,049,938 → 40,399,896). 첫 시도는 그 검사에서 거절됐다.
덤: 같은 소스라도 이 컨테이너(CUDA 13.3) 빌드는 릴리스 바이너리보다 pp4096이 +4.7 %(2,330 → 2,440)다. 디코드는 같다. 원인은 따로 가르지 않았다.
③(Qwen3.6 체인 폭 2–3)은 상수나 플래그가 아니다. 앱의 `mtp35.rs`가 `WIDTH = 1`이고, gpu 크레이트의 `mtp_chain`이 자기 행을 거절한다. 그래서 이번 범위에서 뺐다.
