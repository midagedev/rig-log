# 석 달 된 Qwen 두 모델: 125B에 51 tok/s, 페어의 빠른 절반

*2026-09-16 08:15–09:00.* 요즘 모델이 이 상자에서 뭐 하는지, 빠르고 느린 모델을 같이 서빙할 수 있는지 묻고 다운로드 둘로 답한다. [Qwen3.8-Flash-Next](https://huggingface.co/Qwen/Qwen3.8-Flash-Next)는 125B에 6B 활성 **+ 51B n-gram 임베딩 테이블**과 4B MTP 헤드 — 이 로그 첫 모델로, 헤드라인 파라미터 대부분이 룩업 테이블이다. DeepSeek V4.1 engram 텐서와 같은 아이디어고, 작은 [Qwen3-Coder-Next](https://huggingface.co/Qwen/Qwen3-Coder-Next)(80B-A3B) 대신 고른 이유다. 둘 다 [`tools/fetch-gguf.sh`](../tools/fetch-gguf.sh)로 받았다. 먼저 고쳐야 했다. HF tree API가 디렉터리 하나씩 나열하고 샤딩 unsloth 퀀트가 전부 하위 폴더에 살아서, 크기 조회가 전부 실패했다.

엔진은 `qwen4exp` 아키텍처 담은 mainline `llama.cpp` `930e2fa59`. 배치는 [`tools/qwen38/qwen38-take.sh`](../tools/qwen38/qwen38-take.sh)의 인자지 기본값이 아니고, 매 실행 카드별 VRAM을 UUID로 기록한다.

## 103.7 GiB 파일에 51 tok/s

첫방에 로드된 배치: 26.8 GiB n-gram 테이블 호스트행, expert `blk 0-27` A6000, `blk 28-39` 3090, `blk 40-47` RAM. 48 GB 카드에 47.7 GB, 24 GB 카드에 20.9 GB, 호스트에 39.7 GiB 남는다.

| Qwen3.8-Flash-Next UD-Q4_K_XL, 434토큰 코딩 프롬프트, `-n 2048`, thinking off | 디코드 | 프리필 | 토큰당 major fault |
|---|---:|---:|---:|
| 첫 실행, 테이블 페이지 캐시 찬 상태 | 48.7 tok/s | 278 tok/s | 10.3 |
| 샤드 `cat` 후 1회차 | 49.2 | 300 | 8.9 |
| 2회차 | **51.1** | **414** | **0** |

비교로 같은 상자 DeepSeek V4.1은 draft 달고 warm 25.05 tok/s다. 이 모델은 draft 없이 두 배다. V4.1의 큰 active 셋 대 6B 활성이 사는 값이다.

> ~~at a similar file size.~~ **같은 날 뒤늦게 Struck**, README에 옮기던 중. 두 세션이 독립적으로 두 번씩 검증했다. 두 파일은 비슷한 크기가 아니고 가깝지도 않다. `du --apparent-size`, `du -h`가 `G`로 찍는 GiB다.
>
> | | |
> |---|---:|
> | 위 측정 UD-Q4_K_XL 4샤드 | **103.7 GiB** |
> | `Qwen3.8-Flash-Next` 디렉터리 전체(샤드 + MTP 팩) | 110.1 GiB |
> | 서빙 V4.1 | **444.2 GiB** |
> | engram graft 전 plain `Q3_K_M` | 324 GiB |
>
> 어느 쪽으로 읽어도 4배다. 그 절은 잰 적 없는 것을 이 모델 편으로 주장했다. *같은 크기, 두 배 속도*는 *4분의 1 크기, 두 배 속도*보다 훨씬 강한 주장이고, 일어난 것은 두 번째뿐이다. 속도 비교와 이유는 서고, 크기 동등은 철회다. 문장이 복사 네 개 — 기록, 커밋 메시지, 사용자 보고, 거기서 논거 펴던 peer 메시지 — 를 살아서 두 숫자를 나누기 전에 아무도 안 나눴다는 것도 기록한다.

n-gram 테이블은 engram 테이블이 그랬다(WKS-20). NVMe에서 행 읽기가 디코드 ~5%(48.7 대 51.1) 들고, 비용은 대역폭이 아니라 major fault로 낸다 — 토큰당 8.9 fault, 아키텍처가 읽는 토큰당 16행에 가깝다. 상주는 자동이 아니다. 페이지 캐시 244 GB인데도 fault가 났다. 아침에 잰 다른 모델들이 같은 캐시를 다퉜다. 상주를 구성의 속성으로 만드는 것은 로드 모드다. আগে 돌린 것과 무관하게.

| 같은 배치·프롬프트, `-lm`만 이동 | 디코드 | 프리필 | 호스트 상주 | 토큰당 fault | 로드 |
|---|---:|---:|---|---:|---:|
| `-lm mmap+mlock` | **51.5 tok/s** | 424 tok/s | 39.7 GiB 전부 RAM | 0 | 65초 |
| `-lm none` | 49.7 | 369 | RAM 1.4 / 디스크 38.3 | 4.0 | 15초 |

그래서 전체 흩어짐 48.7–51.5 tok/s, 6% 안. `mlock`이 로드 50초에 그 꼭대기를 산다. 답의 쓸모 모양: 51B 룩업 테이블은 NVMe 서빙이 싸고 핀이 더 싸다. 파라미터 수가 암시하는 반대고, engram 작업이 다른 방향에서 낸 같은 결론이다.

녹음기가 찍은 caveat 하나는 아직 믿으면 안 된다. Decode 행 "≈ 1416 GB/s from RAM, 978% of peak". 카드가 호스트 배치 전부를 토큰당 읽기 바이트로 잡는데, 그중 26.8 GiB는 한 번에 16행씩 읽는 해시 테이블이다. 녹음기 세션에 보고 갔다. RAM의 expert 레이어는 진짜 토큰당 읽기, 테이블은 아니다.

## 빠른 절반: Coder-Next 133 tok/s

Qwen3-Coder-Next IQ4_XS 39.7 GiB는 컨텍스트 32k와 함께 A6000에 통째로 든다. 배치가 필요 없다.

| Qwen3-Coder-Next IQ4_XS, 1스트림, A6000 | 디코드 | 프리필 | TTFT |
|---|---:|---:|---:|
| 403토큰 코딩 프롬프트, `-n 2048` | 133 tok/s | 1013 tok/s | 444 ms |
| 246토큰 설계 프롬프트, `-n 4096` | 131 | 758 | 367 ms |

기계가 실제로 서빙할 수 있는 페어다. 카드에서 131–133 tok/s, 양 카드+RAM 125B 모델에서 51 tok/s. 현재 배치를 둘 다 쥘 수는 없다 — 느린 쪽이 VRAM 72 중 68 GB를 쓴다. 둘 서빙은 빠른 모델에 3090을 주고 느린 쪽 expert 12층을 내리는 것이다. 층 비용 측정상 층당 디코드 ~3%다.

## 깨진 것, 열린 PR이다

MTP draft가 안 오른다.

```
check_tensor_dims: tensor 'token_embd.weight' not found
```

unsloth는 draft-head-only GGUF를 내놓고, master의 `qwen4exp` 로더는 trunk 텐서와 PLE 블록을 무조건 요구한다. [llama.cpp#28097](https://github.com/ggml-org/llama.cpp/pull/28097)("qwen4exp: draft-head-only GGUF 지원 + draft-load 회귀 수정")의 그대로고, 그 PR 열려 있다. 저자는 순수 CPU 상자에서 재현했다. 여기는 CUDA 2카드에 `mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf` 팩으로 같은 실패다. 열린 패치에 두 번째 플랫폼으로 얹을 가치 있다.

## 인덱서 비결정성 negative 결과

[이슈 #28497](https://github.com/ggml-org/llama.cpp/issues/28497): QSA 인덱서 top-k 넘는 컨텍스트에서 탐욕 `qwen4exp` 출력이 CUDA에서 재현 안 된다. `top-k.cu`가 `cub::DeviceTopK::MaxPairs`를 타이 블록 스코어에 `determinism::not_guaranteed`로 부른다. 보고자는 2× RTX 3090(여기 카드 하나와 같은 `sm_86`), CUDA 13.3, CCCL 3.x.

여기서 재현 안 됐다. 탐욕 2회, in 434 / out 2048 — 총 컨텍스트 2482, 2048 인덱서 예산 초과 — 완성본 바이트 동일, 각 8655 바이트. `determinism::not_guaranteed` 호출 든 빌드, CUDA 13.0이다. 2회는 약한 증거고 이슈 자체 재현자는 커널급이라 모델이 필요 없다. 반박이 아니라 CUDA 버전에 대한 데이터포인트다.

*(이 비교 첫 시도는 양쪽 테이프에서 0바이트를 뽑고 "IDENTICAL"을 보고했다. 테이프가 gzip이라서다. 아무것도 안 읽은 파서가 일치처럼 보이는 것이다. 위 체크는 한쪽이라도 비면 시끄럽게 깨진다. 스로틀 플래그 한 번 읽기와 같은 종의 실수, 같은 날 발견.)*

## 클립

둘 다 [toktape](https://github.com/midagedev/toktape) `0.2.3-2-g0f88bd3` 녹음, 테이프 소독 후 `assets/`행.

| 클립 | 내용 |
|---|---|
| `qwen3-coder-next-iq4xs-133tps-1stream-37s.mp4` | 빠른 모델이 133 tok/s에 설계 문서 작성, 37초에 4096토큰 |
| `qwen3.8-flash-next-q4kxl-51tps-mlock-48s.mp4` | 테이블 핀 125B 모델 51.0 tok/s, 48초에 2048토큰 |

둘 다 세 번씩 녹음해서 맞췄다. 이유는 남긴다. **카드에 찍히는 것은 테이프를 렌더한 빌드가 아니라 녹음한 toktape 버전이다.** 새 빌드 재렌더는 카드에 예전 버전을 남긴다. 텐서 분류도 녹음 시점 고정 — 테이프가 텐서명이 아니라 장치·클래스별 바이트 분할을 싣고 있어서, 위 호스트 대역폭 에러도 재렌더로 못 고쳤다. 고친 빌드의 녹음기에서 고치기 전 테이프는 대역폭 절 없이 두 숫자 지목하는 caveat을 찍는다. 분할 틀린 테이프의 정직한 읽기다.

예측 대 측정에 고침을 확인했다. 녹음기 세션이 새 테이프 보기 전에 쓴 예측이라서 — 여기서 값어치 있는 확인은 그 종류뿐이다.

| | 예측 | 실측 |
|---|---|---|
| 토큰당 `other` 바이트 | ~1.4 GB | 1.413 |
| `embeddings` | 안 셈, 상주 ~27.5 GB | 안 셈, 상주 29.476 GB |
| 토큰당 CPU active | 0.26–0.28 GB | 0.256 |
| 호스트 수치 | 13–14 GB/s, 거부 없음 | 13.1 GB/s, 정확 |
| 전모델 기록 | 토큰당 ~6.3 GB | 6.334 |

miss처럼 보이는 한 행은 아니다. 26.8 GiB는 28.78 GB고, 0.675 GB 메인 임베딩 행렬과 29.46 — 27.5 예측이 GiB 숫자를 GB 합에 단위 안 바꾸고 실은 것이다. 예측한 거동은 맞고 확인 산술이 틀렸다. 둘 중 더 위험한 쪽이다. 27.5에 실측이 왔으면 match라 불렀을 것이다.

고치기 전 같은 테이프는 145 GB/s 버스 대비 1033%에 1495 GB/s를 도출했다. 26.8 GiB 테이블이 `other`에 앉아 매 토큰 통째로 셈됐기 때문이다. 디코드 속도는 같은 실행 세 번 — 51.5, 50.7, 51.0 tok/s — 움직인 것은 측정 어디에도 없고 카드 주장뿐이다.
