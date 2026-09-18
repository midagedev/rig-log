# 엔진마다 오프로드 값

*2026-09-17 21:19–21:37. RTX A6000 48G 1장, 테이크마다 임대 1개, 시작마다 io 압력 0. ik c10fbbcc, mistral.rs 소스 빌드 `d5ae0f1` + [#2430](https://github.com/EricLBuehler/mistral.rs/pull/2430), toktape 0.2.4. Qwen3.6-35B-A3B UD-Q6_K, 1스트림, thinking on, `-n 512`, 매 행 같은 238토큰 프롬프트 하나. 숫자는 테이프에서 [`tools/tape-row.py`](../tools/tape-row.py)가 읽음.*

[기록 -c](2026-09-17-c-what-mistral-rs-can-and-cannot-offload.md)가 각 엔진의 오프로드 노브 유무를 확정했다. 값은 말 안 했다. 값이 답 전부다. 같은 모델·카드에 같은 블록을 호스트에 옮기면 한 엔진에 층·토큰당 **0.20 ms**, 다른 엔진에 **442 ms**가 든다.

> ~~두 엔진이 같은 기능을 잘하고 못하고가 아니라 이름 같은 다른 기능이다. ik는 연산을 GPU에 두고 가중치만 옮긴다.~~ **같은 날 밤 Struck.** 코드 리딩이 측정 옷을 입고 있었다 — 그날 네 번째고, 가장 멀리 간 것이다. **양쪽 엔진이 연산을 호스트로 옮긴다.** 정정과 강제 측정은 아래다.

## 설계, 먼저 control 둘

1레벨 뜻은 "모델 40블록 뒤 L블록 expert가 카드 밖"이다. 엔진마다 표현이 다르다 — `-ncmoe L` 대 `-n 0:$((40-L))`. *같은* 블록이 호스트에 간다. 가정 말고 확인했다. ik가 옮기는 텐서를 지목하고(`blk.30.…`–`blk.39.…`, L=10), mistral.rs가 범위를 찍는다(`Layers 0-29: cuda[0]` / `Layers 30-39: cpu`). 러너 [`tools/engine-ab/offload-cost-sweep.sh`](../tools/engine-ab/offload-cost-sweep.sh).

행 쌍을 실측 VRAM에 맞출 계획이었다. 두 번 틀렸고, 서버 로그가 처음 읽히는 줄에 말했다.

```
WARN mistralrs_core::pipeline::normal: Device mapping contains a mix of GPU and CPU.
     There is no CPU support for PagedAttention, disabling PagedAttention.
```

**CPU 층 하나면 실행 전체의 PagedAttention이 꺼진다.** 그래서 760 MB 블록 하나 오프로드의 VRAM 낙폭이 2,720 MiB다. 대부분 사라진 paged pool이지 가중치가 아니다. VRAM은 쌍 축이 못 된다. 더 나쁘게, 순진한 L0–L1 비교가 변수 둘을 한 번에 움직인다. control 행은 그래서 카드 위 40블록 전부에 PagedAttention 손으로 끈 것이다(`PA=off`, `mrs-take.sh`의 새 노브. 기본 `on`이라 이전 행 전부 재현 유지). **켜고 111.2 대 끄고 102.7 tok/s, 7% 효과.** 오프로드 값이 무엇이든 그것이 아니다. 쌍 축은 각 범위 블록의 가중치 바이트다. GGUF 자체 텐서 크기 합산.

## mistral.rs: 오프로드 층·토큰당 442 ms

| 호스트 블록 | 가중치 바이트 | 서버 각 | ITL p50 | TTFT | 출력 토큰 |
|---:|---:|---:|---:|---:|---:|
| 0, PagedAttention on | 0 | **111.2** | 9.5 ms | 169 ms | 512 |
| 0, PagedAttention off | 0 | **102.7** | 10.2 ms | 120 ms | 512 |
| 1 | 0.76 GB | **2.2** | 453.9 ms | 4,709 ms | 512 |
| 4 | 3.0 GB | **0.6** | 1,779.1 ms | 15,998 ms | 126 |
| 10 | 7.6 GB | **0.2** | 4,425.4 ms | 42,716 ms | 64 |

뒤 두 행은 512토큰 못 채우고 240초 벽에 걸렸다. 토큰 수가 짧은 이유다. 속도야 속도다.

control 빼고 나누면 스위프가 곡선이 아니다.

```
(453.9  - 10.2) /  1 = 443.7 ms
(1779.1 - 10.2) /  4 = 442.2 ms
(4425.4 - 10.2) / 10 = 441.5 ms
```

**오프로드 층·토큰당 상수 442 ms**, 오프로드량 10배에 0.5% 평탄이다. 오프로드 층 수에 정확히 선형이고 다른 것과 무관한 비용은 대역폭 이야기가 아니다 — 대역폭 이야기면 전송이 겹들기 시작하며 굽는다. 층·토큰당 한 번 도는 고정 작업량이다.

그 작업이 무엇인지 코드는 말한다. [#2430](https://github.com/EricLBuehler/mistral.rs/pull/2430)이 고친 함수, 패치 착지 한 줄 위(`mistralrs-quant/src/gguf/cpu.rs`):

```rust
// Dequantize all weights to f32
let weights = qtensor.dequantize(device)?;
let unquant = UnquantLinear::new(QuantMethodConfig::Unquantized(Linear::new(weights, None)))?;
```

매 forward 패스에 블록 **전체** expert 스택을 F32에 풀고 새 `UnquantLinear`를 감싼다. 디코드에 forward 패스는 토큰 하나라서, Q6_K 블록 expert 행렬 630 MB가 오프로드 층·토큰마다 3.07 GB F32가 됐다 버려진다. 442 ms에 3.7 GB 트래픽이면 8.4 GB/s다. 호스트 메모리 1패스 풀기의 맞는 자릿수다. MoE 층이 256 중 8 expert를 깨운다는 사실은 안 쓴다. 여덟 위해 전체를 푼다.

뻔히 말할 가치 있다. 오늘 아침 바로 그 함수를 고치며 놓쳐서다. dtype 버그는 아래 줄에서 고쳤고, 토큰당 전체 풀기는 속도 잴 때까지 안 보였다. 코드 읽기가 버그 하나를 찾았고, 돌리기가 중요한 것을 찾았다.

## ik_llama.cpp: 오프로드 층·토큰당 0.20 ms

| 호스트 블록 | 서버 각 | ITL p50 | TTFT | 실효 GB/s |
|---:|---:|---:|---:|---:|
| 0 | **129.0** | 7.7 ms | 284 ms | 383 |
| 1 | **124.7** | 7.9 ms | 274 ms | 370 |
| 4 | **116.2** | 8.5 ms | 308 ms | 345 |
| 10 | **101.8** | 9.7 ms | 334 ms | 302 |

```
(7.9 - 7.7) /  1 = 0.20 ms
(8.5 - 7.7) /  4 = 0.20 ms
(9.7 - 7.7) / 10 = 0.20 ms
```

여기도 정확히 선형, 층·토큰당 고정 비용이다. **442 ms 대 0.20 ms — 2,200배.** 48 GB 카드 밖 expert 가중치 6.3 GB, 10블록이 속도의 21%다.

## 연산의 자리, 이름이 아니라 프로세스에 묻는다

이 기록 첫 버전이 ik 로그 줄에서 답했고 틀렸다. 줄은 진짜다.

```
Tensor blk.39.ffn_up_exps.weight (size = 210.00 MiB) buffer type overridden to CUDA_Host
```

> ~~`CUDA_Host`는 CUDA 커널이 직접 읽는 pinned 호스트 메모리다. 가중치가 카드를 떠나고 matmul은 안 떠난다. 그래서 토큰·층마다 GPU가 라우터가 고른 expert만 읽는다. 그 블록 630 MB 중 약 19.7 MB. PCIe 4.0 x16 직선에 0.79 ms 대 실측 0.20 ms라 전송이 상주층 연산에 대개 겹친다.~~
>
> **Struck. 매 문장이 버퍼 타입명에서 낸 추론이다.** 버퍼 타입은 가중치 사는 곳을 말한다. ggml이 `MUL_MAT_ID`를 어디 스케줄하는지는 다른 질문이고, 이 기록이 안 물었다. 같은 0.20 ms에 산술 둘이 맞는다. 고른 쪽은 모델이 낼 수 없는 4배 겹침이 필요했다. 라우팅된 expert 여덟은 그 층 라우터가 돌아야 *알고*, 뒤 층이 전부 그 층에 의존해서 전송이 숨을 데가 없다. 다른 쪽은 보정 필요 없다 — DDR4-3600에서 19.7 MB, 이 상자 실측 147.7 GB/s에 **0.13 ms**다. 근거에 인용한 `src/llama.cpp:363`은 호스트 버퍼가 "GPU에 복사되거나 GPU에서 복사될 데이터에 써야" 한단다. *결과*를 DMA로 돌려받는 호스트측 텐서 서술이다. CPU 연산 경우다. 반대로 읽었다.

제대로 물었다. [`tools/ik/ik-where-compute.sh`](../tools/ik/ik-where-compute.sh)로. 디코드 창에 서버 프로세스 `utime+stime`과 카드 사용률을 샘플한다 — 코어 하나 바쁘면 서빙 스레드, 스물 몇 개면 호스트 matmul이다.

| | 바쁜 코어 | 평균 GPU 사용률 | 서버 각 |
|---|---|---:|---:|
| ik, 전부 상주 | **1.0** | 96% | 128 |
| ik, 10블록 호스트(`-ncmoe 10`) | **26.7** | 72% | 101 |
| mistral.rs, 전부 상주 | **1.0** | 90% | 111 |
| mistral.rs, 1블록 호스트(`-n 0:39`) | **1.3** | **2%** | 2.2 |

**양쪽 엔진이 연산을 CPU에 옮긴다.** ik가 27코어에 펴고 카드를 72% 바쁘게 둔다. mistral.rs는 1.3코어에 돌리고 카드가 2%에 idle로 호스트를 기다린다. `iqk_mul_mat`, 빠른 양자화 CPU matmul이 ik 존재 이유 대개고, 위 struck 문단이 이 리포가 부정한 것이다.

그래서 2,200배는 티어 간 아키텍처 격차가 아니다. 한 티어의 커널 둘이고, 여기서 잰 계수 둘로 분해된다.

- **스레드.** 26.7 코어 대 1.3, 약 21배. mistral.rs CPU expert 경로는 사실상 직렬이다.
- **닿는 바이트.** ik가 256 중 라우팅 8 expert를 양자화 채로 읽는다. 19.7 MB. mistral.rs가 630 MB 전부 읽고 F32 3.07 GB를 쓴다. 19.7 MB 대 3.7 GB, 약 190배.

곱이 실측 비율의 자릿수에 맞는다. 느슨히 곱한 계수 둘이 주장할 전부다. 정확한 분해로 내놓지 않는다.

### 뒤늦게 지은 control arm

`-ot 'blk\.3[0-9]\.ffn_.*_exps=CPU'` 3행이 진짜 CPU 연산 비교용으로 돌았고, 124.9·116.9·101.9 tok/s에 돌아왔다 — 노이즈 안 `-ncmoe` 행. 로그의 `CUDA_Host`도 같다.

> ~~그래서 arm은 설계 무효다. 확정하는 것은 ik가 여기 CPU 연산 티어가 없다는 것인데, 이 상자의 `-ot exps=CPU` 레시피가 CPU 연산인 적 없다는 뜻도 된다. 호스트 RAM expert 가중치 맞고, 호스트 연산 아니다.~~
> **Struck. 넷 중 파급이 가장 크다** — 이 리포와 읽는 자에게 워크스테이션이 V4.1-Flash 서빙하는 레시피가 안 하는 짓을 한다고 말할 뻔했다. 두 플래그가 *같은 자리에* 닿는다. `src/llama-load-tensors.cpp:265`가 `default_cpu_buft = llama_default_buffer_type_cpu(true)`를 박고 270줄이 호스트 버퍼 타입을 거기로 정규화하는데, CUDA 아래 그게 pinned 호스트 버퍼다. 다만 공유 배치가 **CPU 연산 맞다.** 세 행은 중복 확증이지 무효 arm이 아니고, 레시피는 보이는 그대로였다.

## 선택에 미치는 것, 업스트림에 가는 것

기록 -c가 텐서급 배치 부재를 "버그가 아니라 기능 크기 구멍"이라 했고 dtype 버그 위에 올렸다. 그 순서가 살고 날카로워진다. mistral.rs가 내일 `-ot exps=CPU` 당량을 키워도 층·토큰당 442 ms면 못 쓴다. 필요한 것은 다른 티어가 아니다 — 이미 맞는 티어에 있다. 그 티어 안 ik 커널이다. 라우팅 expert만, 양자화 채로, 기계의 실제 코어에.

토큰당 풀기가 업스트림 후보고 #2430보다 크다. 모양 둘, 엔진 손대는 순서대로. 풀린 스택을 캐시한다. 호스트 RAM을 반복 작업에 맞바꾸고 몇 줄이다. 풀기 전에 라우팅 expert만 모은다. sparsity의 용도 그대로다. 정정한 프레임이 보고를 약화가 아니라 강화한다. 돌아갈 논거다. ik가 같은 모델·하드웨어에 양자화 sparse CPU expert 경로가 층·토큰당 0.20 ms라는 존재 증명이다. 메인테이너 앞에 두기 더 좋은 문장이다, 티어 주장 무엇보다. 미제출. 속도는 진단이 아니다 — 442 ms는 풀기와 다른 몇 가지에 다 맞고, 다음은 오프로드 한 층의 1밀리초 귀속 프로파일이다. ik 배치-2 발견([기록 -b](2026-09-17-b-where-the-four-stream-gap-actually-is.md))을 미제출에 둔 같은 규율이다.

## 상태

스윕 테이프 열둘이 `/home/user/toktape-runs`에 있다. 셋이 `-ot …=CPU` 중복 확증, [`tools/ik/ik-where-compute.sh`](../tools/ik/ik-where-compute.sh)에서 넷 더. matmul이 도는 자리를 묻는 스크래치 질문이 러너로 승격된 것이다. 다음 엔진을 다투지 말고 한 명령에 묻는다. 그중 두 행은 보고 말고 버렸다. 128 tok/s에 512토큰 테이크는 디코드 4초다. 샘플 창보다 짧아서 두 번째 `/proc` 읽기 전에 서버가 갔다. 러너가 그 경우를 이제 지목한다(`INVALID: server N exited during the sampling window, no row`). 빈 필드 찍는 대신이다. 첫 두 행 쌍이 잡힌 경위다. mistral.rs 행 전부 알려진 이유로 `contended: yes`를 단다 — toktape가 붙은 서버를 프로세스명으로 찾고 `mistralrs`가 llama.cpp comm이 아니다. toktape 쪽이 오늘 TTP-107에 닫았다(`e4874f2`, v0.2.5). `/props`가 이제 `engine.server_pid`를 선언할 수 있고, [`tools/mrs/mrs-shim.py`](../tools/mrs/mrs-shim.py)가 한다. 엔진 자체 레이어 범위의 장치별 `placement` 행과, CPU 층이 PagedAttention을 떼면 `vram_kv_bytes: 0`도 함께. 상자는 아직 toktape 0.2.4라 `contended: yes`→`no` 뒤집기는 **미관측**이다. 녹음기 올리고 mistral.rs/ik 쌍 하나 다시 찍는 것이 닫는다. 둘 다 스위프 중간 일 아니다. A6000 idle, 임대 해제.
