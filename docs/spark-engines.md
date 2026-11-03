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
