# DGX Spark 엔진 비교 — 아침 보고 (2026-11-04)

2026-11-04 03:30 KST 기준. GB10 한 대, 드라이버 580.178.04. 클라이언트 시계, tok/s, 세 번의 중앙값. 엔진은 한 번에 하나씩 돌렸고, 모델을 로드하기 전마다 drop_caches를 했다. 측정 방법과 긴 근거는 [spark-engines.md](spark-engines.md)에 있다.

> 이해관계 공개: 우리 커밋 넷이 Strata에 들어가 있다. #1004(/props의 total_slots), #1663(잘못된 타입의 sampling 값), #1664(chat의 file · input_audio · document 블록), #1700(spec 생성이 컨텍스트 끝에서 여는 창)이다. 그래서 Strata 행은 같은 IQ3_S 파일로 llama.cpp와도 재서, 엔진에서 오는 차이와 튜닝에서 오는 차이를 갈랐다.

## 요약

- **소스 빌드로 제안 둘을 실측했다.** bloomery를 CUDA 13.3 devel 컨테이너에서 빌드했다. 13.3 바이너리는 호스트 드라이버 580에서 그대로 돌았다. 드라이버와 커널은 건드리지 않았고, 패치는 스크래치 클론에만 했다.
- **② Qwen3.8 검증 행 4→6, 폭 5는 부분 확인이다.** 코드 디코드가 +8.6 %로, 추정한 +30 %에 못 미쳤다. 무패치 소스 빌드의 63.5가 69.0 tok/s가 됐고, 두 번 재서 재현됐다. 산문은 −2.5 %다. 검증 행이 하나 늘 때마다 창 비용이 약 6.5 ms 늘어 이득이 줄었다. TensorFold 74.4까지는 7 %가 남는다.
- **⑦ Qwen3.8 MTP_STORE_ROWS 64→512는 확인됐다.** pp4096이 2,440에서 2,504 tok/s로 +2.6 % 올랐고(추정 +3.5 %), 디코드는 그대로다.
- **③ 대신 Atlas를 nsys로 재서 원인을 확인했다.** Qwen3.6 체인 폭 2–3은 상수가 아니어서 이번에는 뺐다. Atlas의 폭 1 창은 한 스텝의 1.36배이고, bloomery는 1.63배다. 차이는 헤드에서 난다. Atlas는 4비트 lm_head를 두 행에 한 번 읽는다. bloomery는 Q6_K 검증 헤드와 드래프트 헤드를 따로 읽고, 이 둘이 창 시간의 24 %를 차지한다.

## 보드 1: Qwen3.8-Flash-Next

디코드는 코드·산문 각 256토큰이고, pp는 479 / 4,200 id 프롬프트다. 같은 칸에 여러 행을 쟀으면 값을 `/`로 나눠 행 이름과 같은 순서로 적었다.

| 파일 | 엔진 · 행 | 디코드 코드 | 디코드 산문 | pp512 | pp4096 |
|---|---|---:|---:|---:|---:|
| FP4-Local | bloomery 0.3.12 rec | 63.9 | 42.9 | 1243 | 2330 |
| FP4-Local | bloomery 소스 빌드 base / w5(제안 ②) | 63.5 / 69.0 | 44.4 / 43.2 | 1243 / 1242 | 2440 / 2449 |
| FP4-Local | bloomery 기본 / nomtp | 62.5 / 29.6 | 42.9 / 29.8 | 1241 / 1285 | 2268 / 2452 |
| FP4-Local | Flare 기본 / nomtp | 47.5 / 26.7 | 36.8 / 27.0 | 1112 / 1122 | 2232 / 2353 |
| FP4-Local | vLLM rec / nomtp | 56.8 / 26.9 | 35.5 / 26.9 | 998 / 1110 | 2002 / 2146 |
| TF MLX 4-bit MTP | TensorFold 기본 / no-drafts | 74.4 / 29.3 | 44.0 / 28.1 | 978 / 1052 | 1503 / 1584 |
| NVIDIA NVFP4 | SGLang MTP / 없음 | 30.2 / 15.2 | 21.5 / 14.9 | 560 / 633 | 1598 / 1561 |
| UD-Q4_K_XL | bloomery 공유 드래프트 / nomtp | 52.1 / 28.8 | 36.9 / 29.0 | 816 / 842 | 1524 / 1558 |
| UD-Q4_K_XL | llama.cpp | 27.5 | 27.4 | 672 | 767 |
| GSQ-RCO IQ3_S | Strata MTP / nomtp | 66.8 / 31.7 | 49.6 / 34.5 | 450 / 388 | 1577 / 1585 |
| GSQ-RCO IQ3_S | llama.cpp | 30.9 | 31.1 | 655 | 752 |
| GSQ-RCO IQ3_S | bloomery | 거절(iq4_nl) | — | — | — |

## 보드 2: Qwen3.6-35B-A3B

| 파일 | 엔진 · 행 | 디코드 코드 | 디코드 산문 | pp512 | pp4096 |
|---|---|---:|---:|---:|---:|
| lmstudio Q4_K_M | bloomery 기본 | 92.0 | 92.7 | 2582 | 4549 |
| lmstudio Q4_K_M | llama.cpp 기본 | 76.7 | 77.5 | 1919 | 2415 |
| UD-Q4_K_M(MTP 판) | bloomery rec / nomtp | 73.7 / 66.4 | 69.3 / 66.6 | 1754 / 2553 | 2484 / 4296 |
| UD-Q4_K_M(MTP 판) | llama.cpp rec(폭 3) / 폭 1 / 기본 | 96.9 / 83.1 / 66.5 | 74.7 / 76.6 / 66.9 | 1746 / 1748 / 1895 | 2263 / 2287 / 2425 |
| UD-Q4_K_XL(MTP 판) | bloomery rec / nomtp | 68.2 / 63.9 | 64.0 / 64.2 | 1757 / 2563 | 2487 / 4306 |
| UD-Q4_K_XL(MTP 판) | llama.cpp rec / 기본 | 94.4 / 65.5 | 71.3 / 65.8 | 1718 / 1898 | 2253 / 2429 |
| UD-Q4_K_XL(MTP 판) | Strata 기본 / nomtp | 58.0 / 58.6 | 64.4 / 64.4 | 2048 / 2114 | 2782 / 2896 |
| NVIDIA NVFP4 | SGLang MTP / rec | 120.1 / 79.7 | 91.4 / 79.9 | 3467 / 3874 | 4179 / 6742 |
| NVIDIA NVFP4 | TensorFold 기본 / nomtp | 64.1 / 64.0 | 63.9 / 64.1 | 3489 / 3484 | 5188 / 5175 |
| NVIDIA NVFP4 | Atlas nvfp4 레시피(MTP K=1) / nomtp | 141.2 / 95.8 | 123.6 / 96.4 | 1505 / 1591 | 2628 / 2788 |
| TF MLX 4-bit MTP | TensorFold 기본 / nomtp | 82.0 / 82.4 | 82.4 / 82.5 | 3584 / 3587 | 5514 / 5509 |
| Qwen FP8 | SGLang MTP / 기본 | 68.0 / 53.0 | 51.6 / 53.1 | 2267 / 1537 | 5805 / 4643 |
| Qwen FP8 | Atlas 기본 / rec / nomtp | 66.8 / 64.8 / 55.3 | 67.3 / 58.6 / 55.0 | 521 / 427 / 433 | 1017 / 962 / 982 |
| NVFP4 · FP8 · MLX | bloomery | 거절(폴더 형식) | — | — | — |

## bloomery가 뒤지는 곳과 증거

| # | 어디서 | 차이 | 증거 |
|---|---|---|---|
| 1 | Qwen3.6 MTP 켠 프리필 | pp4096 −42 %(4,296 → 2,484) | 저장 걷기가 행마다 디코드 모양 gemv로 돈다. nsys로 보면 `q8_0_gemv`가 16,800회 더 돌고 470 ms가 더 든다. |
| 2 | Qwen3.6 MTP 디코드 | 코드 73.7 대 llama.cpp 96.9 | llama.cpp는 폭 1에서 창 비용으로 +13 %, 폭 1→3에서 +17 %를 더 얻는다. bloomery 창은 한 스텝의 1.63배, Atlas는 1.36배다(nsys). bloomery는 헤드를 따로 두 번 읽고, 그게 창 시간의 24 %다. |
| 3 | Qwen3.8 코드 디코드 | 63.9 대 TensorFold 74.4 | 수락률이 0.95인데도 검증 4행 상한 때문에 폭 3에서 멈춘다. 상한을 풀면 69.0(실측)이 된다. |
| 4 | Qwen3.6 NVFP4 · FP8 · MLX 폴더 | 못 연다 | config.dtype, lm_head FP8, seat qwen35에서 거절된다. 이 칸의 최고는 디코드 Atlas 141.2, pp4096 SGLang 6,742다. |
| 5 | unsloth UD 파일의 Q8_0 밀집 텐서 | llama.cpp와 비김 | 실효 대역폭이 174 대 176 GB/s다. split-K 마이크로벤치는 +2 %뿐이라 주된 레버가 아니다. |
| 6 | Strata의 IQ3_S 파일 | 못 연다 | 공유 전문가가 IQ4_NL이다. |
| 7 | juliankang4 테이프와의 차이(86.9 대 80.6–81.1) | 토큰당 +0.93 ms | 클록은 우리가 더 높은데, GPU가 노는 시간이 0.68 ms에서 1.22 ms로 늘었다. 드라이버(595 대 580)와 호스트 커널이 다르고, 둘 다 하드 스톱이라 더 가를 수 없다. |

## 제안 순위: 추정 대 실측

| 순위 | 제안 | 코드 위치 | 추정 | 실측 |
|---|---|---|---|---|
| ① | Qwen3.6 저장 걷기를 ubatch GEMM으로 | qwen35moe MTP store walk | pp4096(MTP) +65 % | 미측정 |
| ② | Qwen3.8 검증 4→6행, 폭 5 | `runtime/stores.rs` DELTA_VERIFY_ROWS, `place.rs` 아레나 상수 | 코드 +30 % | 코드 +8.6 %, 산문 −2.5 % |
| ③ | Qwen3.6 체인 폭 2–3, 걷기 그래프 캡처 | app `mtp35.rs` WIDTH, gpu `mtp_chain` | 코드 +15–30 % | 상수가 아니라 이번에 뺐다 |
| ④ | Qwen3.6 창: 헤드 한 번 읽기, 줄인 드래프트 헤드, mcol f32 | `qwen3moe_head_q6k_argmax_prefetch`, `q6k_gemv_prefetch`, `f32_tile_gemm` | 창당 −4 ms, +15–20 % | Atlas nsys로 근거 확인. 창이 1.63배에서 1.36배가 되면 73.7 → 약 88(계산값) |
| ⑤ | Qwen3.6 NVFP4 폴더 열기 | 모델 로더(형식) | 새 칸 | 미측정 |
| ⑥ | Q5_K sel | `q5k_gemv_sel` | +3 % | 미측정 |
| ⑦ | Qwen3.8 MTP_STORE_ROWS 64→512 | `qwen35moe/place.rs` | pp4096 +3.5 % | pp4096 +2.6 % |
| ⑧ | Q8_0 gemv split-K | `q8_0_gemv` | +1 % | 마이크로벤치 +2 % |

덤으로, 같은 소스라도 컨테이너(CUDA 13.3)에서 빌드하면 릴리스 바이너리보다 Qwen3.8 pp4096이 +4.7 % 빠르다(2,330 → 2,440). 디코드는 같고, 원인은 아직 가르지 않았다.

## 실패와 못 한 것

- **SGLang Qwen3.6 NVFP4 기본 행은 실패했다.** `'FusedMoE' object has no attribute 'g1_scale_c'` 오류가 났다.
- **vLLM Qwen3.8 기본 행은 실패했다.** PLE nvfp4 형식은 b12x 백엔드가 있어야 뜬다.
- **Strata와 TensorFold의 Qwen3.6 MTP는 효과가 없었다.** TensorFold는 드래프트 수락이 0/0이었다.
- **bloomery가 열지 못하는 형식이 있다.** Qwen3.6 NVFP4(config.dtype), FP8(lm_head), MLX(seat qwen35), Qwen3.8 IQ3_S(iq4_nl)다.
- **패치 빌드의 첫 로드가 거절됐다가 해결됐다.** `place.rs` 아레나 상수가 gpu 크레이트의 검사와 어긋났고, 상수를 고쳐 해결했다.
- **Atlas nsys는 세 번째 시도에 성공했다.** 첫 번째는 빌드와 겹쳐 watchdog이 MemAvailable 2.7 GB에서 서버를 죽였다. 두 번째는 프로브 요청에 model 필드가 빠졌다.
- **제안 ①③④⑤⑥은 미측정이다.** 코드 변경이 커서 이번 밤에는 계산값만 있다.

## 정리된 결정 (2026-11-04 아침)

- **푸시:** 로컬 커밋은 승인을 받아 푸시했다.
- **Flare 서명 키:** 무인 첫 실행에서 Flare가 패키지 키 승인을 요구했다. 우리 로컬 개발 키의 지문(8eac4304…)을 확인한 뒤 `--dangerously-approve-key`와 `--dangerously-accept-publisher local-development`로 승인했고, 이 승인은 그대로 둔다.
- **bloomery 소스 빌드와 제안:** 스크래치 빌드는 남겨 둔다. 제안 ①②④⑦과 형식 공백은 bloomery 쪽에 넘겼다. 채택 여부는 그쪽이 정한다.
