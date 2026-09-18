# 두 GPU·256 GB RAM에 걸친 DeepSeek-V4-Flash

**2026-09-11.** 284 B 파라미터, 디스크 155 GB, VRAM 72 GB 워크스테이션에 서빙 **25–33 tok/s** — 가운데 29, 흩어짐은 아래 설명한다. routed expert를 층 단위로 A6000·3090·시스템 RAM에 나누고, 안 드는 32층은 CPU가 계산한다.

전부 이 기계·이 날짜 측정이다. 도출값은 도출이라 밝힌다.

![expert의 위치와 엔진별 측정](../assets/placement-sheet.png)

## 모델

`deepseek-ai/DeepSeek-V4-Flash-0731`, Unsloth GGUF(`UD-Q4_K_XL`, 5샤드 155.1 GB).

GGUF 텐서표에서 직접 읽음:

| | |
|---|---|
| 파라미터 | 284.3 B |
| routed expert 보유 | 277.0 B — **97%** |
| 레이어 | 43 |
| 레이어당 routed expert | 256개 중 토큰당 **6**개 동작 |
| 레이어당 shared expert | 1개, 항상 동작 |
| 토큰당 활성 | ≈ 13 B(위에서 도출) |

97%가 동작하는 전부 이유다. dense 284 B를 4.5 bpw에 읽으면 토큰당 155 GB를 옮겨야 하고 이 기계의 도움은 없다. 여기 토큰이 레이어마다 256 중 6 expert를 건드리니 토큰당 읽는 가중치가 13 B어치 — 대부분이 VRAM이 아니라 DDR4에 있어도 산다.

## 실제 구성

[ik_llama.cpp](https://github.com/ikawrakow/ik_llama.cpp) `3bb386eb`, sm_86 CUDA 빌드. 포크가 중요한 이유는 플래그 하나다. `-ot`가 정규식으로 텐서 개별로 장치를 박아서, expert 배치가 균일 층 분할에 묶이지 않고 안 맞는 GPU 둘이 다른 양을 든다.

```bash
llama-server \
  -m DeepSeek-V4-Flash-0731-UD-Q4_K_XL-00001-of-00005.gguf \
  -c 32768 -ngl 99 -ts 2,1 -mla 3 -t 32 -b 2048 -ub 1024 \
  -ot "blk\.[0-6]\.ffn_.*_exps=CUDA0"   \
  -ot "blk\.1[1-4]\.ffn_.*_exps=CUDA1"  \
  -ot "exps=CPU"                        \
  -md dspark-DeepSeek-V4-Flash-0731-Q8_0.gguf -ngld 99 -cd 8192 \
  --spec-type dspark:n_max=2 \
  --jinja --reasoning-format none
```

로드된 배치:

| 장치 | 보유 | 사용 |
|---|---|---|
| RTX A6000 48 GB | 어텐션+dense 텐서, 0–6층 routed expert, draft 모델 | 40.1 GB |
| RTX 3090 24 GB | 어텐션+dense 몫, 11–14층 routed expert | 17.8 GB |
| DDR4 256 GB | 나머지 32층 routed expert | 상주 ~97 GB |

정규식은 순서대로 첫 매치가 이긴다. catch-all `exps=CPU`가 마지막이어야 한다. 한 레이어 256 expert가 텐서 하나(`4096 × 2048 × 256`)라서 배치 단위는 레이어 통째지 expert 부분집합이 아니다.

## 숫자

디코드 400토큰 완성, 프리필 2810토큰 프롬프트. 서버 자체 `timings` 블록에서, 스톱워치 추측 아님.

| 구성 | 디코드 | 프리필 |
|---|---|---:|
| FreeToken 0.1.2, `offload` 백엔드 | 16.0 tok/s | — |
| FreeToken 0.1.2, `hybrid` 백엔드 | 21.0 tok/s | 420 tok/s |
| FreeToken, 4동시 요청 | 합계 47 tok/s | — |
| ik, expert 분할, 추측 없음 | 24.6 tok/s | 259 tok/s |
| **ik + DSpark 추측(depth 2)** | **29.1 tok/s** | 227 tok/s |
| 동일, 1500토큰 완성 | 23.5 tok/s | — |

FreeToken은 한 GPU 메모리에 expert LRU 캐시를 두고 miss를 CPU에 계산한다. 진짜 좋은 설계다 — 그 캐시에 두 번째 GPU를 못 쓸 뿐이고, 텐서병렬 모드가 랭크당 동등 VRAM을 요구하는데 48 GB와 24 GB가 아니다.

프리필은 추측 켜면 *내려가고*, FreeToken 대비도 내려간다. 프롬프트 처리는 compute-bound 배치라서다. 추측은 토큰 단위 경로만 돕는다.

## 값진 발견

expert 배치가 아니다. **추측 깊이다.**

| draft 깊이(`n_max`) | 디코드 | accept |
|---:|---:|---:|
| 1 | 27.8 tok/s | 80% |
| **2** | **29.1 tok/s** | **68%** |
| 3 | 26.8 tok/s | 53% |
| 5 | 19.2 tok/s | 28% |

DeepSeek가 본 가중치 옆에 10.9 GB DSpark draft 모델을 내놓는다. 다음 몇 토큰을 제안하고 큰 모델이 한 배치 패스에 검증한다. GPU 상주 모델보다 여기서 값어치가 크다. DDR4에서 레이어 expert 읽기가 1토큰이나 2토큰이나 거의 같아서 — 검증이 메모리 쪽에서 거의 공짜다.

깊게 가면 accept가 벼랑에 떨어져서 안 산다. depth 5에 draft 토큰 72%를 버렸고, draft 모델 자체 시간도 공짜가 아니다. 이 하드웨어 정점은 depth 2다.

대조로 GPU에 expert를 *더* 올리면 거의 안 움직였다.

| GPU expert 층 | 디코드 |
|---|---:|
| 14 | 24.2 tok/s |
| 16 | 24.6 tok/s |
| 11 + 추측 depth 2 | 29.1 tok/s |
| 16 + 추측 depth 3 | 24.5 tok/s |

draft 달고 GPU expert 11층이 draft 없이 16층을 이긴다. draft 모델에 쓴 VRAM이 expert에 쓴 VRAM을 이겼다.

## 시간 버린 것 넷

**draft 모델이 조용히 죽었다.** draft 컨텍스트를 기본에 두면 타깃 32k를 물려받고, KV 스케줄러가 65,531행 작업 버퍼를 예약하려 한다. 그 할당이 깨지고, 서버가 매 디코드 스텝에 `failed to initialize DFlash K/V scheduler`를 찍고, draft 토큰 0 accept에 17.0 tok/s — 추측 없음보다 느리고, 원인이 VRAM이라는 표시 없음. `-cd 8192`가 고쳤다. 에러 메시지에 메모리가 없다.

**공개 양자화가 깨졌는데 엔진 버그처럼 보였다.** 이 모델의 ik 전용 `IQ4_KSS` 빌드(149 GB, 공개 KL-divergence ladder상 더 좋은 파일)가 첫 샘플 토큰에 전 로짓 NaN으로 죽는다. `llama-server` 전용 이론에 4시간이 갔다. `llama-cli`가 같은 파일에서 생성하는 것처럼 보였는데 아니었다. 그 control이 `--temp 0`에 돌았는데, 샘플러가 all-NaN 행 정규화 대신 argmax를 취해서 중단에 안 닿고 렌더링 안 되는 토큰을 뱉는다. **실패 경로를 안 밟는 control은 control이 아니다.** 실제 모양: NaN이 routed-expert matmul에서 나온다. CPU only, 프롬프트 expert가 라우팅되는 레이어에서. 이유는 공개 파일이 행당 4바이트 모자라서 129개 중 127개 expert 텐서의 마지막 expert가 이웃 텐서 바이트를 읽는다. 최소 재현자·핀 과정은 [v41-serving](../docs/v41-serving.md).

**reasoning이 대다수 클라이언트 안 보는 필드에 들어갔다.** `--reasoning-format deepseek`에 서버가 thinking을 `reasoning_content`에 넣고 `message.content`를 비운다. 이 모델이 길게 생각해서, 400토큰 질문에 비스트리밍 클라이언트가 빈 답과 꽉 찬 `reasoning_content`를 받는다. 스트리밍 클라이언트는 무영향(그 모드는 `none`처럼 동작). `--reasoning-format none` 서빙이 `<think>` 블록을 `content` 인라인에 둔다. OpenAI 호환 클라이언트가 전부 렌더한다.

**`--swa-compress`가 긴 프롬프트를 죽였다.** KV 캐시 압축이 로드 잘 되고 짧은 요청에 답하다가 2810토큰 프롬프트에 크래시. 뺐다.

## 실행간 편차와 끄는 것

위 29.1은 control 벤치 하나다. 프롬프트 바꾸면 흩어지고, 흩어짐이 변수 하나를 탄다. draft 제안 중 검증 생존율.

| 프롬프트 | draft accept | 디코드 |
|---|---|---:|
| 19토큰, 링버퍼 구현 | 70% | 33.4 tok/s |
| 19토큰, 같은 부류 질문 | 70% | 33.0 tok/s |
| 24토큰, control 벤치 | 68% | 29.1 tok/s |
| 19토큰, 아래 녹화 테이크 | 59% | 29.5 tok/s |
| 178토큰, 설계 리뷰 | 61% | 29.4 tok/s |
| 178토큰, 동일 | 53% | 27.1 tok/s |
| 178토큰, 동일 | 51% | 26.3 tok/s |
| 19토큰, 운 나쁜 실행 | 45% | 25.2 tok/s |

그래서 25–33 tok/s가 정직한 범위, 가운데 ~29. accept가 거의 전부 설명한다. 예측 가능·상투 출력은 draft가 잘 되고, 낯선 산문은 안 된다. 추측 디코딩 구성에 숫자 하나를 인용하는 것은 이 분포에서 한 draw를 인용하는 것이다.

## 녹화

![로컬 모델 상대 pi, 인터랙티브](../assets/pi-local.gif)

2막, Tailscale 너머 랩톱에서 [VHS](https://github.com/charmbracelet/vhs) 녹화.

1. [`tools/pi-demo.sh`](../tools/pi-demo.sh)가 [pi](https://github.com/badlogic/pi-mono) 에이전트를 워크스테이션에 붙이고 Rust 스레드안전 LRU 캐시를 시킨다. 화면을 채우는 것은 위 속도에 스트리밍되는 모델 자체 reasoning이다.
2. [`tools/tps-demo.sh`](../tools/tps-demo.sh)가 같은 서버에 [`configs/tps.py`](../configs/tps.py)를 돌린다. 도착하는 대로 토큰을 찍고, 끝의 디코드 속도는 스톱워치가 아니라 서버 `timings` 블록에서 읽는다.

테이크가 우회한 것 둘. pi 기본 시스템 프롬프트가 도구 프로토콜을 서술해서, 모델이 평범 코딩 질문에 디렉터리 나열을 시도했다 — 데모 스크립트가 시스템 프롬프트를 갈고 도구를 끈다. 측정 막은 모델이 테이크 안에 *끝낼* 수 있는 요청이어야 한다. 1600토큰 예산에 전체 구현을 시키니 reasoning에 전 토큰을 쓰고 속도가 안 찍혔다.

## 열. 시끄러운 기계라서

1500토큰 생성 중 측정, 부스트 끔·펌프 100%:

| | |
|---|---|
| CPU 패키지(Tctl) | 81 °C, 아직 느리게 상승 중(제한 95 °C) |
| 올코어 클럭 | 3.05 GHz |
| 냉각수 | 60초에 39 °C → 43.5 °C |
| A6000 / 3090 | 66 °C / 47 °C |

짧은 프리필 버스트가 91 °C를 찍었다. 스펙 안이지만 냉각수 온도가 평탄 전이라 보이는 것보다 마진이 적다.

이 보드에서 팬 제어는 리눅스에서 안 된다. `nct6775` 로드에 nct6798 7팬 채널·7 PWM이 나오고 전부 0 RPM을 읽는다. 헤더가 ASUS 자체 컨트롤러에 물려서다. 팬 커브는 펌웨어에 박는다.

그래서 [`configs/thermal-guard.sh`](../configs/thermal-guard.sh)의 워치독은 진짜 냉각 실패만 본다 — 펌프 500 RPM 미만, 냉각수 52 °C 초과, CPU 93 °C 초과, GPU 90 °C 초과 — 30초 연속 뒤에만. 추론 부하를 멈추고 기계는 살린다. 상자가 다른 건물에 있을 때 원하는 거동이다. 이른 버전이 15초에 90 °C로 끊었고 정상 작업을 죽였을 것이다.

## 다음

- DeepSeek **V4.1 Flash**가 이 기록 전날 새 아키텍처로 나왔다. 아직 올리는 엔진이 없다. llama.cpp 변환 PR open, ik 아무것도 없음, FreeToken 미지원. fp8 원본 510 GB라 어차피 2비트 양자화해야 여기 든다.
- 세 번째 카드, 순수 expert 창고용. VRAM 3.5 GB마다 CPU에서 한 층을 내린다. 재미있는 질문은 연산 떨어지는 싼 32 GB가 연산 좋은 비싼 24 GB보다 값어치 있는지다. 이 텐서들은 곱해지는 것보다 읽히기 때문이다.
- 동시성. FreeToken 4병렬 합계 47 tok/s 대 싱글 21. 이 스택 같은 측정이 안 됐다.
