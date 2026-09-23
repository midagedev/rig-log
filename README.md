# rig-log

한 워크스테이션의 빌드 로그다. 이 하드웨어로 실제로 무엇을 할 수 있는지, 측정한 것만 적는다. 대규모 언어 모델이 먼저고 영상·이미지·오디오가 뒤따른다.

숫자는 전부 이 기계에서, 적힌 날짜에 잰 것이다. 도출한 값은 도출했다고 밝히고, 틀린 기록은 지우지 않고 선을 그어 정정한다. 미출시 모델을 맞지 않는 하드웨어에서 돌리면 남이 테스트하지 않은 경로를 밟게 되는데, 그렇게 찾은 결함을 업스트림에 돌려보내는 것이 이 로그의 나머지 절반이다([`docs/upstream-contributions.md`](docs/upstream-contributions.md)).

기록은 하루 한 파일로 [`log/`](log)에 있다. 모델·엔진별 속도표는 [`docs/engine-rates.md`](docs/engine-rates.md)다. 리포 안은 한국어로 쓰고, 리포를 나가는 글(업스트림 이슈·PR 본문, 업스트림이 읽을 코드 주석)은 영어로 쓴다.

![두 카드와 시스템 RAM에 걸쳐 51 tok/s로 디코딩하는 Qwen3.8-Flash-Next](assets/qwen38-flash-next-q4kxl-1stream-tail-0.2.3-5.gif)

*Qwen3.8-Flash-Next UD-Q4_K_XL(103.7 GiB)이 draft 모델 없이 **51.0 tok/s**로 디코딩하는 장면이다. 3090에 20.5 GiB, A6000에 46.6 GiB, 시스템 RAM에 39.7 GiB가 올라가 있다. 실행의 닫는 구간을 앞에서 잘라 냈고 길이를 줄이지 않았다. [toktape](https://github.com/midagedev/toktape) `0.2.3-5-g9bf4e52`로 녹화했다. [기록](log/2026-09-16.md#qwen38-flash-next-and-coder-next)*

## 기계

현재 상태다. 바뀐 이력은 [`docs/machine-changes.md`](docs/machine-changes.md)에 있다.

| | |
|---|---|
| CPU | AMD Ryzen Threadripper PRO 5975WX, 32 cores / 64 threads. Boost disabled, no clock cap |
| Memory | 256 GB DDR4-3600 at DRAM 1.30 V — 32 GB × 8, all 8 channels, Samsung M378A4G43AB2-CWE 2Rx8 UDIMM, **non-ECC** |
| Measured memory read | **147.7 GB/s** (32-thread, 8 GiB read probe); 230.4 GB/s theoretical. A second probe reads 144.8, the one toktape's host percentages use |
| GPU 0 | NVIDIA RTX A6000, 48 GB, bus 61 |
| GPU 1 | NVIDIA GeForce RTX 3090, 24 GB, bus 41 |
| Device order | **By UUID, never by slot.** Runners source [`configs/gpu-order.env`](configs/gpu-order.env) so CUDA0 is the 48 GB card; `nvidia-smi` ignores it and takes `-i <UUID>` |
| Board | ASUS Pro WS WRX80E-SAGE SE WIFI |
| Storage | Samsung 980 PRO 2 TB NVMe (root) + Phison E18 4 TB NVMe (`/models`) |
| Case / Power | 3RSYS T840 / Super Flower Leadex Platinum SF-2000F14HP, 2000 W |
| Cooling | ARCTIC Freezer 4U-M on CPU_FAN. Case fans are wired to the PSU, so all six `CHA_FAN` channels read `Disabled`; fan RPM and slot temperatures only via the BMC (`ipmitool sdr type fan`, `sdr type temperature`) |
| OS | Ubuntu 24.04, kernel parameter `pci=realloc=off` |

지금도 유효한 함정이 넷 있다. `pci=realloc=off`가 없으면 칩셋 USB가 `xhci init -16`으로 죽고 10GbE 포트가 내려간다(`pci=nocrs`는 USB를 살리는 대신 NVIDIA 드라이버를 깨뜨린다). X550 10GbE 포트는 GRO·TSO·GSO·LRO를 끄기 전에는 지속 부하에서 `Tx Unit Hang`을 낸다. 섀시 팬은 커브를 걸 수 없고, 하나가 죽어도 보이지 않는다. PSU 공개 스펙은 ATX12V 2.2 / EPS12V라 네이티브 12V-2x6 커넥터가 없다(벤더 시트에서 읽은 것이다).

~~지속 부하에서 A6000이 86–87 °C를 유지하고 `SW Thermal Slowdown`이 약 100% 시간 켜져 있으니, duty cycle 100%인 작업은 시작하기도 전에 스로틀링 상태다.~~ 2026-09-16 선 그음: 팬 속도를 증인에 넣지 않고 쓴 문장이었다. 87 °C는 카드 자체 목표 84 °C보다 5 °C 위일 뿐이고, 원인은 카드 팬 커브가 100%에 닿기까지 3.7분 걸리는 데 있다. GPU 팬은 NVML로 제어한다([`tools/gpu-fan-curve.py`](tools/gpu-fan-curve.py), [측정](log/2026-09-16.md#diffusion-first-run-and-three-regimes)).

3090은 부하 중 버스에서 떨어진다(`Xid 79`). NCCL DDP로 133초 만에 재현되고 양 카드를 250 W로 묶으면 같은 DDP가 900초 동안 깨끗하지만, 이것은 동작하는 설정이지 원인 규명이 아니다([재현](log/2026-09-18.md#b-the-fault-reproduced)). 2026-09-22에 하루 두 번 떨어져서 그날부터 시간 측정은 A6000에서 하고, 3090은 게이트·빌드용으로 ~~300 W~~ 250 W 캡을 걸어 쓴다(2026-09-23에 바꿨다 — [기록](log/2026-09-23.md#machine-0923))([기록](log/2026-09-22-g-the-3090-fell-twice-so-the-clock-moved-to-the-a6000.md)).

## 속도

전부 이 상자에서 잰 값이다. 전체 표는 [`docs/engine-rates.md`](docs/engine-rates.md).

| 모델 | 조건 | 디코드 | 기록 |
|---|---|---:|---|
| DeepSeek-V4.1-Flash, 서빙 프로파일 + DSpark draft | ik_llama.cpp, warm | 25.05 tok/s | [09-16](log/2026-09-16.md#every-kept-model-re-verified) |
| Qwen3.8-Flash-Next 125B UD-Q4_K_XL, draft 없음 | 양 카드 + 시스템 RAM | 51.1 tok/s | [09-16](log/2026-09-16.md#qwen38-flash-next-and-coder-next) |
| Qwen3-Coder-Next IQ4_XS | A6000 단독, 컨텍스트 32k | 133 tok/s | [09-16](log/2026-09-16.md#qwen38-flash-next-and-coder-next) |
| Qwen3.6-35B-A3B UD-Q6_K, 1스트림 | ik / mistral.rs | 129 / 111 tok/s | [09-17](log/2026-09-17.md#a-rust-engine-on-the-same-card) |
| 같은 모델, 8스트림 합계 | ik / mistral.rs | 152 / 324 tok/s | [09-17](log/2026-09-17.md#b-where-the-four-stream-gap-actually-is) |
| GLM-5.3-Flash | ik, expert 10층 온카드 / ExLlamaV3 `-mcs 195` | 18.7 / 22.2 tok/s | [09-15](log/2026-09-15.md#glm-5.3-flash-first-run) |
| MiMo-V2.6-Flash MXFP4 | mainline, expert 16층 GPU·31층 RAM | 24.0 tok/s | [09-22](log/2026-09-22-l-mimo-v2.6-flash-on-two-cards-and-ram.md) |
| DeepSeek-V4.1-Flash 첫 가동, engram 84 GB는 NVMe에 | mainline llama.cpp | 20 tok/s | [09-12](log/2026-09-12.md#deepseek-v41-first-run) |

## 기록 색인

하루 한 행이다. 상세는 날짜 파일이 진다. 색인이 기록을 요약하려 들면 색인이 자란다 — 이 표는 한 번 2,569자까지 자란 적이 있다.

| 날짜 | 무엇이 판명됐나 |
|---|---|
| [09-11](log/2026-09-11.md) | 284 B 모델을 두 카드와 호스트 RAM에 나눠 **29 tok/s**. 값을 가른 것은 GPU에 올린 expert 층 수가 아니라 추측 디코딩 깊이였다 |
| [09-12](log/2026-09-12.md) | 347 GB 중 84 GB를 드라이브에 둔 채 **20 tok/s**. 10분마다 하드리셋하던 BMC 워치독, 캐시만 재던 디스크 벤치(지속 쓰기 하한 3.70 대 1.47 GB/s), 이사와 SSD가 겹친 20시간 단절 |
| [09-13](log/2026-09-13.md) | V4.1을 ik_llama.cpp에 이식해 PPL **2.2258** 대 오라클 2.2438. CPU only 디코드는 ik 9.80 대 mainline 7.98 tok/s. engram 테이블을 Q8_0로 되돌리면 PPL 6% 개선 |
| [09-14](log/2026-09-14.md) | ik 격차 20%는 engram 행 페이지 폴트였다(첫 패스 13.6 → 18.4 tok/s). 짧은 프롬프트 프리필은 expert 166 GB를 매번 버스로 복사한 탓. 공랭 교체, 메모리 3200 → 3600으로 읽기 **131.2 → 147.7 GB/s** |
| [09-15](log/2026-09-15.md) | `-ub 1024 → 4096`이 11.9k 프리필을 ik에서 2.11배. 한 카드에 드는 모델이 132 tok/s에서 안 움직이는 상한. GLM-5.3-Flash 첫 숫자, V4.1 이식을 PR 둘로 분할 |
| [09-16](log/2026-09-16.md) | 슬롯 이동으로 PCIe 에러 0, 3090을 빼도 디코드 손실 **3% 미만**. Qwen 125B가 draft 없이 51 tok/s. 첫 디퓨전이 드러낸 세 체제, 3.7분 늦게 도착하는 팬 커브, V4.1 tool-call 태그 업스트림 버그 |
| [09-17](log/2026-09-17.md) | 프롬프트 캐시가 13k 접두사에서 깨지던 원인(파서 구분자, 9줄 패치로 턴당 13.8 → 0.8초). mistral.rs는 1스트림에 느리고 4스트림에 두 배, 호스트 오프로드는 층·토큰당 ik 0.20 ms 대 **442 ms** |
| [09-18](log/2026-09-18.md) | 3090 버스 이탈을 133초에 재현하고 드라이버 소스로 기존 주장 셋을 정정. 로컬 모델 번역은 가장 빠른 것이 가장 정확한 것의 네 배로 틀렸다 |
| [09-19](log/2026-09-19.md) | 자체 엔진 bloomery가 첫 토큰을 골랐고(0.0521 tok/s) 밤까지 5.48 tok/s. Rust GPU gemv가 ggml의 **1.86배**. DSpark 검증 비용이 라우팅 expert 바이트 몫과 0.13%p 안에서 일치 — 검증은 공짜가 될 수 없다 |
| [09-20](log/2026-09-20.md) | bloomery CPU 경로의 ik 대비 배수를 18.7배에서 **1.13배**로. 빠진 `#[target_feature]` 하나, 청크 끝마다 잡던 락, 스텝당 14454번의 할당 |
| [09-21](log/2026-09-21.md) | CPU 경로가 깊이 0에서 ik 최속 조합을 여섯 바퀴 전승(85.96 대 84.13)했지만 깊이 4096에서는 ik에 못 미친다. GPU 경로가 첫 토큰을 냈고 3090에서 ik CUDA를 넘었다. 사흘 묵은 HTTP 500 오진 정정 |
| 09-22 | 창을 맞추니 헤드라인이 깊이 4096에서 뒤집혔고([c](log/2026-09-22-c-the-headline-inverted-at-depth-4096.md)), 깊이 비용은 전부 flash였다([f](log/2026-09-22-f-the-depth-cost-is-flash-and-the-meter-lied-twice.md)). 텐서 코어 flash가 깊이 4096에서 ik를 이겼고([j](log/2026-09-22-j-the-mma-kernel-beat-ik-at-depth-4096-and-the-gate-said-no.md)) 참값 자로 검증한 뒤 기본값이 됐다([m](log/2026-09-22-m-the-truth-ruler-caught-ik-too-and-the-extra-error-was-the-activation-block.md), [n](log/2026-09-22-n-the-mma-pass-became-the-default.md)); 새 기본값으로 다시 잰 깊이 표에서는 세 깊이 전부 ik보다 빠르다([o](log/2026-09-22-o-the-depth-table-on-the-new-default-and-the-reversal-is-gone.md)). engram의 NVMe 읽기는 토큰당 0.3 ms이고 그 3분의 2가 syscall 발행이다([p](log/2026-09-22-p-the-engram-path-costs-a-third-of-a-millisecond-and-it-is-syscalls.md)). 3090이 두 번 떨어져 시계를 A6000으로 옮겼다([d](log/2026-09-22-d-the-link-died-60ms-before-the-gpu.md), [e](log/2026-09-22-e-the-link-was-fine-and-this-was-a-fourth-face.md), [g](log/2026-09-22-g-the-3090-fell-twice-so-the-clock-moved-to-the-a6000.md)). MiMo-V2.6-Flash 공개 당일 24 tok/s([l](log/2026-09-22-l-mimo-v2.6-flash-on-two-cards-and-ram.md)). 그 밖에 [a](log/2026-09-22-a-the-instructions-came-out-and-it-got-slower.md) · [b](log/2026-09-22-b-the-barrier-got-a-price.md) · [h](log/2026-09-22-h-the-flash-layer-is-two-load-loops-and-heads-in-one-block-did-not-help.md) · [i](log/2026-09-22-i-qk-on-tensor-cores-was-correct-and-slower.md) · [k](log/2026-09-22-k-a-rulebook-three-reviews-and-four-refactors-in-one-night.md) |
| [09-23](log/2026-09-23.md) | engram 행은 실제 토큰 스트림에서 되풀이된다 — 토큰당 48행 중 새로 읽을 것은 코드 8.38행·산문 25.72행이고, 남는 미스는 전부 처음 보는 n-gram의 강제 미스다([재사용률](log/2026-09-23.md#engram-row-reuse)). CUDA 13.3 툴킷을 13.0 옆에 깔았는데 우리 커널은 `.oxart` md5까지 같고 GPU 게이트 판정 줄 416줄이 그대로였다([전환](log/2026-09-23.md#cuda-13-3)) |

09-21까지는 실험당 한 파일이었고, 09-22는 날짜가 끝나면 같은 방식으로 합친다. 09-11–09-21의 옛 파일명과 새 위치의 대응은 [`log/moved.tsv`](log/moved.tsv)에 있고, 옛 원문은 커밋 `c27c3a7`에 그대로 남아 있다.

## 다음

다음 과제는 이 기계에서 뮤직비디오를 만드는 것이고, 그 비용에 대한 질문이 큐의 대부분이다. 목록은 [`docs/v41-experiment-plan.md`](docs/v41-experiment-plan.md)와 트래커(WKS)에 있다.

## Layout

```
log/        하루 한 파일, 실험은 절. 측정한 기록
configs/    기계에서 실제로 돌아가는 스크립트, 그대로 복사
tools/      기록 수단: 러너, 게이트, VHS 테이프
docs/       긴 글: 업스트림 버그 서류, 방법, 하드웨어 노트
assets/     클립과 시트
CLAUDE.md   이 리포에서 일하는 에이전트용 컨텍스트
```

자주 쓰는 것: 서빙 [`configs/v41-serve.sh`](configs/v41-serve.sh), 모델 내려받기 [`tools/fetch-gguf.sh`](tools/fetch-gguf.sh), 전력 스위프 [`tools/ik/gpu-power-sweep.sh`](tools/ik/gpu-power-sweep.sh), 서빙 배치 시트 [`assets/placement-sheet.html`](assets/placement-sheet.html). 긴 글은 [처리량 모형](docs/throughput-model.md) · [V4.1 서빙](docs/v41-serving.md) · [조용한 기계](docs/quiet-machine.md) · [보드 펌웨어](docs/wrx80e-bios-setup.md) · [도구 인계](docs/tool-handoff.md).

## 이 로그가 낳은 프로젝트

측정하다 도구가 없어서 만든 것이 두 개 있다. 둘 다 MIT이고 포크가 아니다.

- **[toktape](https://github.com/midagedev/toktape)**: 로컬 LLM 서빙용 블랙박스 테이프. 돌고 있는 `llama-server`에 붙어 한 실행을 `.tape`에 담고, 모델 위치와 실제 속도를 카드에 찍는다. 이 README의 클립이 이것으로 녹화됐다. 증인 없는 tok/s는 일주일 뒤 저자 본인도 검증하지 못한다.
- **[exl3-serve](https://github.com/midagedev/exl3-serve)**: [ExLlamaV3](https://github.com/turboderp-org/exllamav3)용 `llama-server` 호환 HTTP 앞단. ExLlamaV3에는 서버가 없어서 `llama-server`용 도구가 EXL3 모델을 못 돌렸다([맞추는 데 든 값](log/2026-09-15.md#exl3-serve-and-tabbyapi-timings)).
