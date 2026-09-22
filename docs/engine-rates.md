# 이 기계에서 엔진이 무엇을 내는가, 모델별

[`log/`](../log)의 실측 엔트리는 시간순이며 각각 그날 열려 있던 질문에 답한다. 이 페이지는 다른 관점이다: **어떤 모델, 어떤 엔진, 어떤 속도.** 다른 곳에서 수행한 측정의 요약이므로, 모든 행은 해당 엔트리를 소유하며 이 기계에서 실측되지 않은 것은 아무것도 나타나지 않는다.

마지막 실측 2026-09-17. RTX A6000 48 GB 1개, 런당 카드 1개, 임대 1개, 시작할 때마다 io pressure 0. ik_llama.cpp `c10fbbcc`, mistral.rs `0.9.3` (그리고 오프로드 행을 위한 소스 빌드 `d5ae0f1` 및 [#2430](https://github.com/EricLBuehler/mistral.rs/pull/2430)), toktape 0.2.4. 속도는 [toktape](https://github.com/midagedev/toktape)로 기록하고 [`tools/tape-row.py`](../tools/tape-row.py)로 테이프에서 읽어 들이며, 진행 표시줄에서 절대 읽지 않는다.

## 각 엔진이 로드할 수 있는 모델

| 모델 | 크기 | ik_llama.cpp | mistral.rs |
|---|---:|---|---|
| Qwen3.6-35B-A3B UD-Q6_K | 29.3 GB | 로드함 | 로드함 |
| Qwen2.5-7B-Instruct Q3_K_M | 3.3 GB | 로드함 | 로드함 |
| DeepSeek-V2-Lite-Chat Q3_K_M | 6.4 GB | 로드함 | **거부됨**: GGUF에 `deepseek2.attention.key_length_mla` 누락 |
| Qwen3-Coder-Next IQ4_XS | — | 로드함 | **거부됨**: `blk.0.ssm_ba.weight`가 비양자화 텐서가 예상되는 곳에 IQ4_XS임 |
| DeepSeek-V4.1-Flash Q3_K_M | ~100 GB 클래스 | **일일 서빙 모델** | **거부됨**, 동일한 `deepseek2` 키 |

마지막 행은 아래 어떤 속도보다 더 많은 것을 결정한다: 이 워크스테이션이 실제로 서빙하는 모델은 mistral.rs에서 전혀 로드되지 않으므로, 여기서 중요한 유일한 모델에 대해서는 아직 비교가 존재하지 않는다.

## Qwen3.6-35B-A3B UD-Q6_K — 두 엔진이 모두 실행하는 모델

29.3 GB, MoE, 토큰당 8개 라우팅되는 256개 expert, 40개 블록, 그중 10개는 풀 어텐션, 30개는 선형 어텐션(GDN). 카드에 **완전히 들어맞으므로**, 여기 있는 모든 행은 오프로딩이 필요 없는 모델이다; 오프로드 행은 이 모델이 원해서가 아니라 기능을 측정하기 위해 존재한다. 238토큰 프롬프트, thinking on, `-n 512`.

### 단일 스트림, 모든 것 상주

| 엔진 | tok/s |
|---|---:|
| ik_llama.cpp | **129** |
| mistral.rs | **111** |

ik가 16% 더 빠르다. 이것이 일반적인 서빙 조건이다.

### 동시성, 스트림 간 집계

| 스트림 | ik_llama.cpp | mistral.rs |
|---:|---:|---:|
| 1 | 129 | 105 |
| 2 | **130** | 184 |
| 4 | 146 | 279 |
| 8 | 152 | 324 |

"Rust 엔진이 4개 스트림에서 90% 더 빠르다"는 헤드라인은 이 표에서 나온 것이며 mistral.rs에 대한 진술이 아니다. **ik의 집계는 1개 스트림에서 2개 스트림으로 전혀 움직이지 않는다** — 129에서 130으로, 반면 스트림당 속도는 절반으로 줄어든다 — 따라서 부하 하에서 더 빨라 보이는 엔진은 단순히 배치 처리를 테이블에 남겨두지 않은 엔진이다. 서버가 전혀 없는 `llama-batched-bench`에서 재현했으며, CUDA 그래프나 fused-MoE 경로도 원인이 아니다; 둘 다 개입으로 배제되었다. 배치 2 expert matmul의 원인은 아직 미해결이다. [log/2026-09-17-b](../log/2026-09-17.md#b-where-the-four-stream-gap-actually-is)에서 실측.

ik의 동시 **프리필**은 이 모델에서 별개이고 더 큰 문제다: 혼합 시퀀스 ubatch가 단일 토큰 청킹으로 폴백하여, 2 582 → 119 tok/s가 되며, 이는 4개 및 8개 스트림에서 4.5초 및 12.5초 TTFT다. 이미 오픈 PR [#2418](https://github.com/ikawrakow/ik_llama.cpp/pull/2418)로 수정됨; 우리의 측정은 [해당 코멘트](https://github.com/ikawrakow/ik_llama.cpp/pull/2418#issuecomment-5714136627)에 있다.

### 블록을 호스트 RAM으로 이동, 단일 스트림

| 호스트의 40개 블록 중 | 이동된 가중치 | ik_llama.cpp | mistral.rs |
|---:|---:|---:|---:|
| 0 | 0 | 129 | 111 |
| 1 | 0.76 GB | 125 | **2.2** |
| 4 | 3.0 GB | 116 | 0.6 |
| 10 | 7.6 GB | 102 | 0.2 |

두 엔진 모두 오프로드된 expert matmul을 **CPU에서** 실행한다 — 이는 버퍼 타입 이름에서 추론한 것이 아니라 서버 프로세스를 샘플링하여 확인했으며, 엔트리의 첫 번째 버전에서 반대로 기록되었다. ik는 26.7개 코어에 분산하고 양자화된 형태로 라우팅된 256개 expert 중 8개만 읽는다; mistral.rs는 1.3개 코어를 관리하고 순전파마다 256개 전체를 F32로 역양자화하므로 카드는 2%에서 대기한다. 오프로드된 레이어당 토큰당 이는 **442 ms 대비 0.20 ms**이며, 둘 다 오프로드된 레이어 수에 정확히 선형이다. [log/2026-09-17-d](../log/2026-09-17.md#d-what-offloading-costs-each-engine)에서 실측.

이 행들을 다른 곳에서 읽기 전에 알아야 할 두 가지. mistral.rs는 어떤 레이어든 CPU에 있으면 **PagedAttention을 완전히 비활성화**하며, 이는 그 자체로 7%의 가치가 있고(모든 것이 상주하고 PagedAttention을 수동으로 끈 경우 111.2 → 102.7), VRAM을 페어링 축으로 무용지물로 만든다. 그리고 mistral.rs는 [#2430](https://github.com/EricLBuehler/mistral.rs/pull/2430)까지 이를 전혀 할 수 없었다: 모든 요청이 `moe experts forward / dtype mismatch in matmul, lhs: BF16, rhs: F32`로 실패함 ([log/2026-09-17-c](../log/2026-09-17.md#c-what-mistral-rs-can-and-cannot-offload)).

## 컨트롤 모델

MoE와 dense를 분리하고 발견이 한 모델의 특이점이 아님을 확인하기 위해 사용.

| 모델 | 하네스 | 측정 |
|---|---|---|
| DeepSeek-V2-Lite Q3_K_M (MoE, 선형 어텐션 없음) | `llama-batched-bench` 디코드, B = 1/2/4/8 | 202.1 → **156.1** → 229.9 → 317.0 tok/s — 배치 2가 배치 1보다 *총합에서 더 느림* |
| Qwen2.5-7B Q3_K_M (dense) | 동일 하네스, 동일 카드, 동일 분 | 120.7 → 195.5 → 290.7 → 388.5 tok/s — 정상적으로 스케일됨 |
| Qwen2.5-7B Q3_K_M (dense) | mistral.rs, 28개 레이어 중 20개를 호스트에 | 16토큰 버스트에서 17.4 tok/s — 부분 오프로드가 서빙함, 이것이 행이 증거하는 바 |

처음 두 행은 위 동시성 표가 MoE 발견이지 일반적 발견이 아닌 이유다: 동일 가중치 클래스, 동일 카드, 동일 하네스, 그리고 expert matmul의 존재만 다르다.

## 이 페이지 읽는 법

세 문장이면 충분하다면.

**카드에 맞는 모델에서**, ik_llama.cpp가 1명의 사용자에게 더 빠르고(129 대 111), mistral.rs가 여러 명에게 더 빠르며(8개 스트림에서 324 대 152), 이 중 후자는 mistral.rs의 장점이 아니라 ik의 결함이다.

**카드에 맞지 않는 모델에서** — 이 기계이 실제로 살아가는 경우 — 비교가 없다: mistral.rs는 모델을 로드하지 않으며, 로드하는 모델에서 40개 중 1개 블록을 호스트 RAM으로 이동하면 50배 비용이 든다.

**이것을 바꿀 것**은 업스트림 수정 각각 하나이며, 둘 다 식별되었다: ik의 MoE decode가 배치되지 않음(파일링되지 않음, 연산별 타이밍 필요), 그리고 mistral.rs의 expert 스택 전체에 대한 토큰당 역양자화(파일링되지 않음, 동일 이유). 속도가 진단이 아니므로 어느 것도 파일링되지 않았다. 파일링된 것의 기록은 [`docs/upstream-contributions.md`](upstream-contributions.md)에 있다.
