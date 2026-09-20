# rig-log

한 워크스테이션의 빌드 로그: 이 하드웨어로 실제로 무엇을 할 수 있는지, 측정한 것만 적는다.

순서는 생성 워크로드가 로컬 하드웨어에 들어맞는 대로 — 대규모 언어 모델 먼저, 그 다음 영상·이미지·오디오. 모든 기록에는 실행한 명령줄, 측정한 처리량, 그리고 틀렸던 점이 들어간다. 숫자 하나하나는 이 기계에서, 명시된 날짜에 측정된 것이다. 도출된 값이면 도출됐다고 밝히고, 틀린 기록은 지우지 않고 선을 그어 정정한다. 조용히 고쳐 쓰는 로그는 가치가 없다.

미출시 모델을 맞지 않는 하드웨어에서 돌리면 남의 테스트 안 된 경로를 정면으로 밟는다. 그래서 이 로그의 나머지 절반은 업스트림로 돌려보낸 것이다. 방법과 보낸 기록은 [`docs/upstream-contributions.md`](docs/upstream-contributions.md)에 있다.

기록은 날짜순으로 [`log/`](log)에 있다. 다른 보기 — **모델·엔진별 속도표**는 [`docs/engine-rates.md`](docs/engine-rates.md)에서. 이 리포 안은 한국어로 쓴다. 리포를 나가는 글(업스트림 이슈·PR 본문, 업스트림가 읽을 코드 주석)은 계속 영어다.

![두 카드와 시스템 RAM 패널을 곁들여 51 tok/s로 디코딩하는 Qwen3.8-Flash-Next](assets/qwen38-flash-next-q4kxl-1stream-tail-0.2.3-5.gif)

*Qwen3.8-Flash-Next: 125 B 파라미터에 51 B n-gram 테이블, UD-Q4_K_XL 103.7 GiB, **draft 모델 없이 51.0 tok/s** — draft를 쓰는 서빙 중인 DeepSeek-V4.1의 두 배를 4분의 1 바이트로 낸다. 카드에는 다 안 들어간다. 3090에 20.5 GiB, A6000에 46.6 GiB, 시스템 RAM에 39.7 GiB — 오른쪽 패널이 동작 중인 그 분할을 보여준다. [전문](log/2026-09-16-qwen38-flash-next-and-coder-next.md)*

![카드 한 장에서 코딩 프롬프트에 133 tok/s로 답하는 Qwen3-Coder-Next](assets/qwen3-coder-next-iq4xs-1stream-tail-0.2.3-5.gif)

*같은 상자의 다른 끝. Qwen3-Coder-Next IQ4_XS 39.7 GiB는 A6000 한 장에 컨텍스트 32k와 함께 들어가 **133 tok/s**로 디코딩한다. 그 프레임에서 3090은 0.0 GiB다. [전문](log/2026-09-16-qwen38-flash-next-and-coder-next.md)*

두 클립 모두 실행의 **닫는 구간**이다. 프레임 수÷30이 아니라 저장된 프레임별 지연을 합해 잰 길이를 쓴다. 클립을 짧게 할 때는 줄이지 않고 앞에서 잘라낸다. 실행을 짧은 시간에 구겨 넣으면 스톨이 가려져 기계에 대한 거짓말이 된다. [toktape](https://github.com/midagedev/toktape) `0.2.3-5-g9bf4e52`로 녹화·렌더링했고, 파일명이 담는 것은 녹화기 빌드다. 속도와 길이는 정정 가능해야 하니 산문에 둔다.

[![서빙 모델이 앉은 네 티어와 두 번째 카드의 값](assets/placement-sheet.png)](assets/placement-sheet.png)

*서빙 프로파일 한 장 요약: 마흔 레이어의 routed expert가 어느 티어에 있는지, 어디에도 안 올라가는 engram 테이블 두 개, 두 번째 카드의 값을 잰 네 갈래 실행. 원본과 재촬영 방법은 [`assets/placement-sheet.html`](assets/placement-sheet.html).*

## 기계

현재 상태. 바뀌기 전 모습과 바꾼 실행 기록은 [`docs/machine-changes.md`](docs/machine-changes.md)에 있다.

| | |
|---|---|
| CPU | AMD Ryzen Threadripper PRO 5975WX, 32 cores / 64 threads. Boost disabled, no clock cap |
| Memory | 256 GB DDR4-3600 at DRAM 1.30 V — 32 GB × 8, all 8 channels, Samsung M378A4G43AB2-CWE 2Rx8 UDIMM, **non-ECC** |
| Measured memory read | **147.7 GB/s** (32-thread, 8 GiB read probe); 230.4 GB/s theoretical. A second probe reads 144.8, and that is the one toktape's host percentages are derived against |
| GPU 0 | NVIDIA RTX A6000, 48 GB, bus 61 |
| GPU 1 | NVIDIA GeForce RTX 3090, 24 GB, bus 41 |
| Device order | **By UUID, never by slot.** Every runner sources [`configs/gpu-order.env`](configs/gpu-order.env), which pins `CUDA_VISIBLE_DEVICES=<A6000 UUID>,<3090 UUID>` so CUDA0 is the 48 GB card whatever the bus addresses are. `nvidia-smi` does not honour that variable and is addressed with `-i <UUID>` |
| Board | ASUS Pro WS WRX80E-SAGE SE WIFI |
| Storage | Samsung 980 PRO 2 TB NVMe (root) + Phison E18 4 TB NVMe (`/models`) |
| Case | 3RSYS T840 |
| Power | Super Flower Leadex Platinum SF-2000F14HP, 2000 W |
| Cooling | ARCTIC Freezer 4U-M tower air cooler on CPU_FAN. **No chassis fan is on a header** — the case fans are wired to the PSU, so all six `CHA_FAN` channels read `Disabled`. Fan RPM and per-slot temperature are readable only through the BMC (`ipmitool sdr type fan`, `sdr type temperature`; the `PCIE0n` sensors read when the GPU driver cannot) |
| OS | Ubuntu 24.04, kernel parameter `pci=realloc=off` |

하루씩 잡아먹고 아직도 유효한 것 네 가지:

- **`pci=realloc=off` 필수.** 없으면 커널이 PCI 리소스를 재배정하면서 칩셋 USB가 `xhci init -16`으로 죽고 10GbE 포트가 내려간다. `pci=nocrs`는 USB를 살리고 NVIDIA 드라이버를 깨뜨린다.
- **X550 10GbE 포트는 sustained 부하에서 `Tx Unit Hang`.** GRO·TSO·GSO·LRO를 인터페이스에서 끄기 전에는.
- **섀시 팬은 커브 불가.** 케이스 팬이 PSU 직결이라 여섯 `CHA_FAN` 채널이 전부 `Disabled`고, 하나가 죽어도 보이지 않는다. ~~지속 부하에서 A6000이 86–87 °C를 유지하고 `SW Thermal Slowdown`이 약 100% 시간 켜져 있으니, duty cycle 100%인 작업은 시작하기도 전에 스로틀링 상태다.~~ 2026-09-16 선 그음: 증인에 팬 속도를 안 넣고 쓴 문장이다. 87 °C는 카드의 95 °C slowdown 근처도 아니고, **자기 목표 84 °C보다 5 °C 위**일 뿐이며, 그 이유는 팬 커브가 느려서다. GPU 팬은 NVML로 headless 제어 가능([`tools/gpu-fan.py`](tools/gpu-fan.py), 커브 [`tools/gpu-fan-curve.py`](tools/gpu-fan-curve.py)) — 램프 안에 끝나는 작업에 16 °C어치, 수렴할 때까지 도는 작업에는 0이다([측정](log/2026-09-16-diffusion-first-run-and-three-regimes.md)).
- **PSU 공개 스펙은 ATX12V 2.2 / EPS12V** — 네이티브 12V-2x6 커넥터 없음. 벤더 시트에서 읽은 것이지 여기서 측정한 게 아니다. 해당 커넥터를 원하는 카드를 사기 전에 실물 확인.

미해결 질문은 하나로 좁혀졌다. **NCCL DDP에서 3090이 버스에서 떨어지는 이유.** 2026-09-18에 세 번 재현하고 후보를 걷어냈다. 버스 트래픽 아님 — 핀 메모리 DMA가 15분간 **37 GB/s**를 유지해도 멀쩡했고, DDP 실제 이동량의 수백 배다. 지속 전력 아님 — 고장은 384 W에서 났고 419 W 15분은 멀쩡했다. 온도 아님(67 °C). 링크 아님 — 전후 에러 레지스터가 동일하고, A6000의 `Xid 154`는 카드별 고장이 아니라 시스템 전역 플래그다. 남은 것은 집합체만 만드는 것 — 두 카드가 배리어에서 함께 기다렸다가 **같이 끌어당기는** 동기 transient. 양쪽을 250 W로 묶으면 같은 DDP가 900초 깨끗이 돈다(단일 카드 대비 1.51배, 무제한 1.85배). 동작하는 설정이지 증명은 아니다. [재현](log/2026-09-18-b-the-fault-reproduced.md), [조사](log/2026-09-16-the-overclock-and-the-fabric.md), [확정·미확정](docs/machine-changes.md#still-open).

## 속도

한 행도 이 박스에서 측정하지 않은 것은 없다. 전체 표는 [`docs/engine-rates.md`](docs/engine-rates.md).

| 모델 | 조건 | decode | 기록 |
|---|---|---:|---|
| DeepSeek-V4.1-Flash, 서빙 프로파일, draft | ik_llama.cpp | 25.05 tok/s, warm | [log](log/2026-09-16-every-kept-model-re-verified.md) |
| Qwen3.8-Flash-Next 125B, UD-Q4_K_XL, draft 없음 | 양 카드 + 시스템 RAM | 51.1 tok/s | [log](log/2026-09-16-qwen38-flash-next-and-coder-next.md) |
| Qwen3-Coder-Next, IQ4_XS | A6000 단독, 컨텍스트 32k | 133 tok/s | [log](log/2026-09-16-qwen38-flash-next-and-coder-next.md) |
| Qwen3.6-35B-A3B, UD-Q6_K, 1스트림 | ik 129 / mistral.rs 111 tok/s | 129 / 111 | [log](log/2026-09-17-a-rust-engine-on-the-same-card.md) |
| 같은 모델, 8스트림 합계 | ik 152 / mistral.rs 324 tok/s | 152 / 324 | [log](log/2026-09-17-b-where-the-four-stream-gap-actually-is.md) |
| GLM-5.3-Flash, expert 10층 온카드 | ik_llama.cpp | 18.7 tok/s | [log](log/2026-09-15-glm-5.3-flash-first-run.md) |
| GLM-5.3-Flash | ExLlamaV3 `-mcs 195` | 22.2 tok/s | [log](log/2026-09-15-glm-5.3-flash-first-run.md) |
| DeepSeek-V4.1-Flash 첫 가동, engram 84 GB 미적재 | mainline llama.cpp, NVMe에서 행 단위 적재 | 20 tok/s | [log](log/2026-09-12-deepseek-v41-first-run.md) |

## 주요 발견

- **347 GB 모델 중 84 GB를 드라이브에 둔 채 20 tok/s.** DeepSeek-V4.1-Flash의 engram 테이블은 메모리에 전혀 안 올라가고 NVMe에서 수십 행씩 읽어낸다. [전문](log/2026-09-12-deepseek-v41-first-run.md)
- **ik-vs-mainline 20% 격차는 페이지 폴트였다.** engram 행을 `posix_madvise(WILLNEED)`로 예열하자 토큰당 폴트 41–62개→1–11개, 격차는 노이즈로 사라졌다. [전문](log/2026-09-14-v41-gap-closed-prefill-and-queue.md)
- **서빙 프로파일의 프리필은 ubatch가 2.1배, 엔진이 1.15배.** `-ub 1024→4096`이 11.9k 프리필을 ik에서 236→500 tok/s로 올리고, 디코드는 그대로. 같은 날 서빙에 반영(12k 문서 TTFT 50→25초). [전문](log/2026-09-15-prefill-ubatch-ik-vs-mainline.md)
- **3090을 빼는 비용은 디코드의 3% 미만**, warm 행에서는 0.3%. 20 GB는 다른 카드가 아니라 호스트가 흡수한다. [전문](log/2026-09-16-what-the-3090-is-worth.md)
- **프롬프트 캐시는 13k 접두사에서 깨진다.** Hermes 턴 하나가 13,167 토큰 cold prefill(285초)인데, DeepSeek 파서가 user 구분자를 공개하지 않아 그 앞을 고치면 전체를 다시 읽는다. 9줄 패치로 13,145/13,161 토큰 재사용, 13.8초→0.8초. [전문](log/2026-09-17-where-the-prompt-cache-breaks.md)
- **팬 커브는 3.7분 늦게 도착한다.** 카드 자체 커브가 100%에 도달하는 데 그만큼 걸리고, 그 사이 다이는 목표 84 °C보다 최대 5 °C 위에 있다. 처음부터 100%로 고정하면 137초 테이크에서 16 °C, 네 시간짜리에서는 0이다. [전문](log/2026-09-16-diffusion-first-run-and-three-regimes.md)
- **기계번역은 천 단어당 4.7개 문장의 의미를 바꾼다.** 1,711단어 문서에 8건, 전부 유창한 한국어라 구조 게이트는 한 건도 못 잡는다. 번역기는 초안이고, 리드가 읽어야 확정이다. [전문](log/2026-09-18-c-a-local-model-translates-the-log.md)
- **3090 버스 이탈은 133초 만에 재현된다.** 드라이버 소스를 읽어 Xid 79·154에 대한 기존 주장 세 개를 정정했고, 남은 것은 동기 transient 가설과 250 W 캡 회피책이다. [전문](log/2026-09-18-b-the-fault-reproduced.md)

## 기록 색인

실험당 한 파일, 날짜순. 칸 하나는 그날 무엇이 판명됐는지 한 줄과 그것을 대표하는 수치 하나다 — 상세는 항목이 진다. 색인이 항목을 요약하려 들면 색인이 자란다(2026-09-11 47자에서 2026-09-17 2,569자까지 아무도 결정한 적 없이 자랐다).

| 날짜 | 기록 | 무엇이 판명됐나 |
|---|---|---|
| 2026-09-11 | [두 GPU와 256 GB RAM에 걸친 284 B 모델](log/2026-09-11-deepseek-v4-moe-offload.md) | routed expert를 층 단위로 두 카드와 호스트에 나눠 **29 tok/s** |
| 2026-09-12 | [347 GB 모델, 84 GB는 드라이브에 둔 채](log/2026-09-12-deepseek-v41-first-run.md) | engram 테이블 둘이 RAM에 안 올라가고 NVMe에서 읽혀 **20 tok/s**, 토큰당 3.3 ms |
| 2026-09-12 | [10분마다 리셋되던 기계](log/2026-09-12-bmc-watchdog-reset-loop.md) | BIOS가 건 `OS Load` 워치독을 OS가 인계 안 받아 **9분 수명 부팅 넷**. 끄지 않고 인계받았다 |
| 2026-09-12 | [캐시만 재던 디스크 벤치](log/2026-09-12-nvme-sustained-write.md) | 버스트는 동일, 갈리는 건 4분 뒤 하한 **3.70 대 1.47 GB/s**. 벼랑 전에 멈춘 벤치는 캐시 크기를 보고한다 |
| 2026-09-12 | [이사 하나, SSD 하나로 겹친 단절](log/2026-09-12-offline-after-a-move-and-an-ssd.md) | 독립된 고장 둘이 각각 네트워크를 막기에 충분했다. **20시간** 암전 |
| 2026-09-13 | [V4.1을 ik_llama.cpp에 이식](log/2026-09-13-deepseek-v41-on-ik-llama.md) | 빌드 열 개와 틀린 그래프 둘 끝에 PPL **2.2258 대 오라클 2.2438** |
| 2026-09-13 | [engram 테이블만 Q8_0으로 되돌리기](log/2026-09-13-engram-q8-repack.md) | 아무도 안 읽는 **125 GB**를 더 쓰고 PPL 6% — 안 읽히는 바이트는 품질을 안 산다 |
| 2026-09-14 | [AIO가 나가고 공랭이 들어오다](log/2026-09-14-air-cooler-swap.md) | 냉각수 40도 후반에 `warn cpu=89C`가 두 번 찍힌 뒤 교체 |
| 2026-09-14 | [메모리 클럭 3200 → 3600](log/2026-09-14-memory-clock-3600.md) | 읽기 **131 → 148 GB/s**, 3666 위로는 세 번 다 실패 |
| 2026-09-14 | [ik 격차는 페이지 폴트였다](log/2026-09-14-v41-gap-closed-prefill-and-queue.md) | engram 행 prefetch로 첫 패스 **13.6 → 18.4 tok/s**, 토큰당 폴트 41–62 → 1–11 |
| 2026-09-15 | [서빙 모델 프리필: ubatch가 2.1배](log/2026-09-15-prefill-ubatch-ik-vs-mainline.md) | `-ub 1024 → 4096`이 11.9k 프리필을 ik에서 **236 → 500 tok/s**, 디코드는 불변 |
| 2026-09-15 | [서빙 노브 여섯 개 스위프](log/2026-09-15-serving-knob-sweep.md) | 서는 것은 현재 프로파일 하나뿐 — 나머지 다섯은 대역 안이거나 손해 |
| 2026-09-15 | [한 카드에 통째로 드는 모델](log/2026-09-15-a-model-that-fits-one-card.md) | **132 tok/s**, 그리고 어떤 노브로도 안 움직이는 상한 |
| 2026-09-15 | [2.7 GHz 클럭 캡 해제](log/2026-09-15-clock-cap-removed.md) | AIO 루프용 열 대책이었고 루프가 갔다. 캡 없는 히어로 테이크 |
| 2026-09-15 | [GLM-5.3-Flash 첫 숫자](log/2026-09-15-glm-5.3-flash-first-run.md) | 디코드가 대역폭-bound가 아니다 — 스레드 스위프가 평탄 |
| 2026-09-15 | [llama-server 표면 뒤의 ExLlamaV3](log/2026-09-15-exl3-serve-and-tabbyapi-timings.md) | TabbyAPI `time_generate`가 무엇을 재는지 확인하고 exl3 베이스라인 확보 |
| 2026-09-15 | [V4.1 이식을 PR 둘로 나누다](log/2026-09-15-splitting-the-v41-port.md) | 리뷰 가능한 단위로 쪼갠 것이 업스트림 조건이었다 |
| 2026-09-16 | [남긴 모델 전부 재검증](log/2026-09-16-every-kept-model-re-verified.md) | 1.3 TB를 지우고 슬롯·클럭이 바뀐 상자에서 남긴 파일마다 한 번씩 로드 |
| 2026-09-16 | [석 달 된 Qwen 두 모델](log/2026-09-16-qwen38-flash-next-and-coder-next.md) | 125B에 **51 tok/s** — 활성 6B에 n-gram 테이블 51B라 헤드라인 파라미터가 속도를 안 말한다 |
| 2026-09-16 | [4스트림이 서로 다른 행을 원할 때](log/2026-09-16-engram-and-concurrency.md) | engram 행이 fresh 텍스트에 디코드 **6.8%**, 토큰당 major fault 22.1개 |
| 2026-09-16 | [열 부팅의 밤, 마진 밖 슬롯 하나](log/2026-09-16-the-overclock-and-the-fabric.md) | 3090이 Xid 79로 버스에서 떨어지고 드라이버가 양 카드에 Xid 154를 찍었다 |
| 2026-09-16 | [3090을 빼면 잃는 것](log/2026-09-16-what-the-3090-is-worth.md) | expert **20 GB**어치, 디코드 손실 **3% 미만**(warm 0.3%) — 호스트가 흡수한다 |
| 2026-09-16 | [24 GB 카드 단독 서빙, 그리고 시트의 결함](log/2026-09-16-echo-ingredients-and-the-3090-alone.md) | 48 GB 카드를 디퓨전에 비우려고 서빙을 작은 카드로 옮겼다 |
| 2026-09-16 | [같은 크기의 두 거인, 그리지 못한 모델](log/2026-09-16-two-giants-is-a-capability-boundary.md) | 이 기계 첫 이미지 생성. 크기가 같아도 할 수 있는 것이 다르다 |
| 2026-09-16 | [고치지 못한 13.5배, 목표에 닿은 팬](log/2026-09-16-what-guidance-was-not-for.md) | guidance가 살 수 없던 것과, 팬을 100%로 고정해 얻은 것 |
| 2026-09-16 | [한 카드 세 체제, 3.7분 늦는 팬](log/2026-09-16-diffusion-first-run-and-three-regimes.md) | 136초 실행 하나에 체제 셋. 팬 커브 지연이 램프 안 작업에 **16 °C** |
| 2026-09-17 | [24 GB 카드가 기계에서 나오다](log/2026-09-17-the-3090-comes-out.md) | 마지막 검사가 뭐라 했는지와, 전원이 10초 먼저 나가 못 말한 것 |
| 2026-09-17 | [같은 카드 위의 Rust 엔진](log/2026-09-17-a-rust-engine-on-the-same-card.md) | mistral.rs가 단독은 느리고 4스트림에 두 배 — `thinking off`가 꺼진 적 없다는 실행 증명 |
| 2026-09-17 | [4스트림 격차의 실제 자리](log/2026-09-17-b-where-the-four-stream-gap-actually-is.md) | 격차는 엔진이 아니라 배치 경로에 있었다 |
| 2026-09-17 | [mistral.rs의 오프로드 한계](log/2026-09-17-c-what-mistral-rs-can-and-cannot-offload.md) | 텐서 단위 배치가 아예 없고, MoE 한 층을 호스트에 두면 모든 요청이 실패한다 |
| 2026-09-17 | [엔진마다 오프로드가 무엇을 무는가](log/2026-09-17-d-what-offloading-costs-each-engine.md) | 층·토큰당 ik **0.20 ms** 대 mistral.rs **442 ms** — 둘 다 호스트 연산이지 GPU 읽기가 아니다 |
| 2026-09-17 | [프롬프트 캐시는 13k 접두사에서 깨진다](log/2026-09-17-where-the-prompt-cache-breaks.md) | 9줄 패치로 13,145 토큰 재사용, 턴당 **13.8 → 0.8초** |
| 2026-09-18 | [24 GB 카드가 같은 슬롯에 돌아오다](log/2026-09-18-the-3090-goes-back-in.md) | 재장착 검사와 양 카드 상태 복귀 |
| 2026-09-18 | [DDP 버스 이탈을 133초에 재현](log/2026-09-18-b-the-fault-reproduced.md) | 드라이버 소스로 Xid 79·154에 대한 기존 주장 **셋을 정정**했다 |
| 2026-09-18 | [이 기계가 자기 로그를 번역하다](log/2026-09-18-c-a-local-model-translates-the-log.md) | 구조 게이트를 통과한 번역에도 천 단어당 **4.7건**의 의미 변경이 남는다 |
| 2026-09-19 | [Rust로 쓴 첫 커널, 두 모델에 같은 스펙](log/2026-09-19-a-first-rust-kernel-two-arms.md) | cuda-oxide Q3_K gemv가 3090에서 ggml mmvq의 **1.86배**(620 대 333 GB/s, M=8은 1.20배). 네 라운드 열 팔, 하루: 0.40 → 1.05 → 두 팔의 직교 레버를 합쳐 1.86; 4라운드는 CPU AVX2 gemv(ggml의 1.1배 이상, 147.7 GB/s '천장' 정정)와 cuda-oxide ICE 원인 두 줄 |
| 2026-09-19 | [구분자가 콜드 프리필에 물리는 값](log/2026-09-19-b-delimiters-and-cold-prefill.md) | 기본값에서 **1.13배**, `min-step 0`에서 **3.26배** — 값이 막혀 있던 쪽은 설정이었다 |
| 2026-09-19 | [우리 엔진이 처음으로 토큰을 골랐다](log/2026-09-19-c-the-first-forward.md) | V2-Lite 전체 순전파, 프롬프트 **32개 중 31개**가 ik와 같은 토큰. 첫 tok/s 0.0521, 오차는 블록을 따라 누적되지 않는다 |
| 2026-09-19 | [디코드가 평평해졌다](log/2026-09-19-d-the-cache.md) | KV 캐시로 **5.26배**(0.0519 → 0.2730 tok/s), 스텝 폭 84.5 % → 0.5 %, 로짓은 모든 분할에서 **비트 동일** |
| 2026-09-19 | [시간이 어디로 가는지 먼저 잰다](log/2026-09-19-e-where-the-time-goes.md) | 디퀀트가 내적보다 크다(**56 : 44**) — 지렛대는 빠른 f32 내적이 아니라 융합 int8 커널. 토큰과 무관한 가중치 준비가 스텝의 8 %, 병렬화 뒤엔 69 % |
| 2026-09-19 | [15.3배 — 행을 32코어에 나누다](log/2026-09-19-f-fifteen-times.md) | 0.2730 → **4.1639 tok/s**, 스레드 1·3·32의 로짓이 **바이트 동일**. 스레드 수는 32(물리 코어)로 확정 — **SMT 64는 3.7배 느리고 절반이 스핀 탓**이다 |
| 2026-09-19 | [융합 커널이 돈다](log/2026-09-19-g-the-fused-kernel-runs.md) | 커버리지·커널·배선 세 라운드: 4.1639 → **4.5369 tok/s**, Q3_K dequant **0.00**. 게이트가 처음으로 바이트가 아니라 밴드를 지킨다 — 융합 경로가 **더 정확해서** 로짓이 움직인 것을 설계로 받았다. 다음 지렛대는 스텝의 13%를 먹는 디스패치·동기·게더(**~28 ms**) |
| 2026-09-19 | [합류를 분해한다](log/2026-09-19-h-dissecting-the-join.md) | 4.5369 → **4.8046 tok/s**, 로짓 비트 불변(재핀 0). 스핀 스윕이 정책을 못박는다 — 파킹은 실제 비용(spin=0 −9.4%)이는데 더 참으면 대역폭을 훔친다. 워커의 `out` 직접 쓰기로 게더 7.4→2.1 ms, **남은 잔여 41 ms는 디스패치 횟수의 함수** — 다음은 MoE 배칭 |
| 2026-09-19 | [디스패치를 접는다](log/2026-09-19-i-folding-the-dispatches.md) | 4.8046 → **5.4834 tok/s**(+14.1%), 로짓 비트 불변. 전문가당 3번의 풀 디스패치를 층당 2번으로 — 디스패치 1089 → **673/스텝**, 배칭 사이트 잔여 **3.4 ms**로 "잔여는 횟수의 함수"가 측정으로. 관측: 프리필 −27%(원인 미상), 64스레드 6.39(스프레드 53%) |
| 2026-09-19 | [디스패치를 또 접는다](log/2026-09-19-j-the-seventh-fold.md) | wv_b 헤드 16콜을 층당 1번으로 — 디스패치 673 → **268/스텝**, 어텐션 잔여 13.9 → 2.9 ms, 재핀 0 3연속. **그러나 비프로파일 스텝은 안 움직였다**(186.2/186.3 재현) — 워커 파킹 ~930/스텝 불변, 접착부 길이가 파킹을 묶는다. 다음은 Q4_K 융합(17.4 ms) |
| 2026-09-20 | [속성 하나로 73%](log/2026-09-20-a-the-attribute.md) | 융합 커널이 SSE2로 컴파일되고 있었다 — `#[target_feature]` 부재, 인트린식은 **에러 없이 느려진다**. 벤치 0.3 → 10.8 GB/s(코어당 36배), 엔진 **5.37 → 9.28 tok/s**, 남은 배수 8.9배. T=1 회귀와 프리필 회귀의 정체도 이것. 다음: Q4_K·Q5_0 융합, 이번엔 **이식을 넘어서**(벤치가 ik 기준률을 이길 때까지) |
| 2026-09-20 | [측정 단위가 먼저 무너졌다](log/2026-09-20-b-the-thermal-section.md) | 스레드 재판정 — **32 유지**(열 통제 시 32가 다시 앞서고, 64의 스프레드 44.8%가 우위를 삼킴). 발견: ① 러너 **첫 구간이 16~25% 빠르다**(부스트/열) — 같은 섹션 안에서만 비교할 것, ② **스텝이 ctx와 선형 증가**(ctx 6→101에서 103→285ms) — 실서빙 관문 |
| 2026-09-20 | [ctx가 길어도 평탄하다](log/2026-09-20-c-flat-across-context.md) | flash_attn을 (토큰,헤드) 행 공간으로 풀에 병렬 — 재핀 0. **N=96에서 5.74 → 10.10 tok/s(1.76배), 스텝 폭 176.8%→21.2%**(기울기 ~1.9→0.21ms/토큰), N=8은 10.61. 사이트 73.8→**6.9ms/스텝**. 남은 배수 ~7.8배. 다음: **Q4_K 30%·Q5_0 23%**가 스텝의 절반 |
| 2026-09-20 | [진짜 짝을 찾아 배선한다](log/2026-09-20-d-the-real-pairing.md) | Q4_K 융합 — 오라클의 실제 짝 q8_2_x4로(인코더 ik와 **2304바이트 비트 동일**, 미러는 인트린 에뮬레이터, ik 커널과 1 ULP). 재핀 2, 둘 다 A/B 입증: **argmax 31/33→33/33(첫 완전 일치)**, l_out 꼬리 밴드 2.5e-2→7e-2. **N=8 10.61→14.87 tok/s, N=96 10.10→14.06(1.4배)**, 같은 임대 ik 78.07/83.00 — 남은 배수 **5.2/5.9배**. **Q4_K 스테이지 29.8→3.6ms(8.3배)**, 프리필 17.63. 커널 단일코어률은 진다: 14.1 vs **ik 16.3–17.1**(직접 재측정) — 갭은 코드젠, MUL-26 교훈은 피호출 헬퍼에도(누락 시 0.6 GB/s). 새 머리: **Q5_0 23.1ms(32.5%)** |
| 2026-09-20 | [두 트랙를 같은 날에 깐다](log/2026-09-20-e-two-tracks-one-lease.md) | 첫 서브에이전트 병렬 라운드(worktree+BLOOMERY_REMOTE 두 트랙, 측정·통합은 메인). Q6_K(qY 변형, **재핀 0**, 커널률 ik의 95%) · Q5_0(짝=q8_2_x4, **k%256이 아닌 사이트의 계약을 타입별로** — 이 조건이 없으면 스테이지 머리가 발화조차 안 함, 발산 집합 {14}로 1핀). 병합 뒤 **N=8 14.87 → 24.52 tok/s(1.65배), N=96 22.25, 스텝 67 → 40.8ms, 프리필 32.0** — 남은 배수 **3.4배**(ik 82.72 같은 임대). 새 머리: **q_nope2 11.0ms(26.7%)**, 부검 완료(셀 병렬 = 비트 동일) |
| 2026-09-20 | [flash가 무너지고 직렬이 사라졌다](log/2026-09-20-h-three-tracks-one-window.md) | 백그라운드 병렬 3트랙 완주(머지 순서: 재핀 없는 것 먼저, flash 재핀 마지막). MUL-36 **flash SIMD**(kq 8레인 합순서, V는 j축 — 발산 {14}→{24}를 `BLOOMERY_FLASH_SIMD=0` 한 실행으로 A/B 입증, flash 사이트 **6.01→0.40ms/step=15배**) · MUL-37 **직렬 quant 풀 이양+gate/up 이중양자화 제거**(ptr::eq, 비트 불변·재핀 0) · MUL-38 **q_nope2 vpsignb 부호접기 maddubs**(비트 동일·재핀 0, 벽 −0.07ms는 활용도 25% 사이트라 법칙대로). **N=8 37.02, N=96 31.79→39.71(+25%), 스프레드 35.3→6.8%, 프리필 63.65** — ik 82.43/83.27 같은 임대, **잔여 2.10배**, 세션 누적 9.55배. 조사 3트랙(Intel·AMD·광역) 동시 완료 → 다음 축 **패킹**, 그 다음 **스펙 디코딩**(docs/research/cpu-llm-ideas.md) |
| 2026-09-20 | [사이트 포화도 판정](log/2026-09-20-g-the-saturation-verdict.md) | 진단 라운드(병렬 3트랙: 원장 분석 · 커널/디스패치 벤치 · GPU 정찰, 임대 창은 메인 단독 — ef9e579 보강의 첫 실전, 사고 없음). **대역폭 벽은 Q6_K(lm_head) 하나**(119.3 GB/s = STREAM의 81%), flash 1위 사이트(18.8%)는 **스칼라 벽**(0.28 GB/s, 스프레드의 전부), 나머지 내적 사이트는 전부 오케스트레이션(풀 평균 가동 9.1워커) — 커널 MT 상한 122–136 GB/s, 디스패치 세금 1.5ms/step, 둘 다 무죄. 예측 변수는 **디스패치당 바이트**. 다음 축: flash SIMD(재핀) · 직렬 quant 풀 이양(비트 불변) · q_nope2 maddubs(비트 불변) → 유도 ~48 tok/s. MUL-30 판정: **GPU는 cuda-oxide 확정**(박스 완비, Q4_K CUDA 커널 이미 존재), cutile은 13.3 툴킷 뒤 |
| 2026-09-20 | [스테이지 표가 평탄해졌다](log/2026-09-20-f-the-flat-table.md) | 병렬 둘째 라운드. Q5_1(마지막 미융합 타입, 커널률 **ik의 98-99%**, 재핀 0, 사이트 12.6배) · q_nope2 셀 병렬(비트 동일, 8.4배) — 그리고 **첫 판의 무한루프가 에이전트 둘을 '무활동'으로 죽였다**: 매달린 게이트가 조용한 에이전트의 첫 용의자다. **N=8 24.52 → 36.00 tok/s(1.47배), N=96 31.79, 스텝 27.8ms, 프리필 49.3** — 남은 배수 **2.30배**(ik 82.78 같은 임대). 스테이지 표에 지배 사이트 소멸(최대 22%), 모든 양자화 사이트 융합 완료. 다음: 배칭 사이트 포화도(47 GB/s 대 STREAM 147.7) |
| 2026-09-20 | [빨간 게이트가 0으로 끝나고 있었다](log/2026-09-20-i-the-blind-gate-and-the-diet.md) | 하루치 리뷰. 게이트 레시피 13개의 `\|\| echo`가 **4시간 37분 동안 실패를 삼켰다**(그 안에 MUL-36/37/38 병합) — 종료 코드 소유자를 `tools/gate.sh` 하나로, 13게이트 재실행 전부 rc 0(숨은 빨강 없음). 주석 다이어트(qdot 1114→246줄, 이력 주석 137→0을 게이트로) · 디스패치 뼈대 분할. **틀렸던 것**: agy 주석 라운드가 수치 계약을 지움(이후 조사 전용), GLM이 완료 마커를 번역, 그리고 **뼈대 분할이 swiglu 사이트를 두 배로 만든 회귀** — 같은 임대 3-바이너리 A/B와 프로파일 대조로 찾아 닫음(38.49 → 37.49 → 38.33 tok/s). 아침의 39.71은 저녁 창에서 같은 커밋으로도 재현 안 됨(37.56), 원인 미측정. 새 기록 없음 |

## Upstream

미출시 모델을 맞지 않는 하드웨어에서 돌리면 남의 테스트 안 된 경로를 밟는다. 보낸 것과, 조사하고 일부러 보내지 않은 것의 전체 기록 — 다음 세션에게는 보내지 않은 쪽도 값어치가 있다 — 은 [`docs/upstream-contributions.md`](docs/upstream-contributions.md)에 있다.

## 다음 질문

뮤직비디오를 이 기계에서 만드는 것이 다음 과제라, 큐는 그 비용에 대한 질문이 주다. 전부 측정값이 아니라 질문이며, 뒤의 숫자는 이 박스에서 잰 게 아니다. 목록은 [`docs/v41-experiment-plan.md`](docs/v41-experiment-plan.md)와 트래커(WKS)에 있고, 여기에는 두지 않는다.

## Layout

```
log/        실험당 한 파일, 날짜순. 측정한 기록
configs/    기계에서 실제로 돌아가는 스크립트, 그대로 복사
tools/      기록 수단: VHS 테이프와 구동 스크립트
docs/       긴 글: 업스트림 버그 서류, 방법, 하드웨어 노트
assets/     클립과 시트
CLAUDE.md   이 리포에서 일하는 에이전트용 컨텍스트
```

## 재사용 조각

상세 설명은 각 파일 머리말에 있고, 여기서는 이름만 적는다. 서빙 명령 [`configs/v41-serve.sh`](configs/v41-serve.sh) · 구형 V4 서빙 [`configs/llm-serve.sh`](configs/llm-serve.sh) · 처리량 측정 [`configs/tps.py`](configs/tps.py) · 모델별 러너 [`tools/v41/v41-take.sh`](tools/v41/v41-take.sh) [`tools/qwen38/qwen38-take.sh`](tools/qwen38/qwen38-take.sh) [`tools/ik/ik-vram-take.sh`](tools/ik/ik-vram-take.sh) [`tools/exl3/exl3serve-take.sh`](tools/exl3/exl3serve-take.sh) · 모델 내려받기 [`tools/fetch-gguf.sh`](tools/fetch-gguf.sh) [`configs/hf-fetch/`](configs/hf-fetch) · 전력 스위프 [`tools/ik/gpu-power-sweep.sh`](tools/ik/gpu-power-sweep.sh) · 패브릭 부하·판독 [`tools/mem3600-load.sh`](tools/mem3600-load.sh) [`tools/pcie-aer-snapshot.sh`](tools/pcie-aer-snapshot.sh) · GPU 팬 [`tools/gpu-fan.py`](tools/gpu-fan.py) [`tools/gpu-fan-curve.py`](tools/gpu-fan-curve.py) · CUDA 순서 고정 [`configs/gpu-order.env`](configs/gpu-order.env) · 벤치 서빙 [`configs/bench-serve.sh`](configs/bench-serve.sh) · 배치 시트 원본 [`assets/placement-sheet.html`](assets/placement-sheet.html) · GGUF 판독 [`tools/dequant-scan.cpp`](tools/dequant-scan.cpp) [`tools/gguf-region-scan.py`](tools/gguf-region-scan.py) · 온도 감시 [`configs/thermal-guard.sh`](configs/thermal-guard.sh). 긴 글 세 편: [처리량 모형](docs/throughput-model.md) · [V4.1 서빙](docs/v41-serving.md) · [도구 인계](docs/tool-handoff.md) · [엔진별 속도](docs/engine-rates.md) · [조용한 기계](docs/quiet-machine.md) · [보드 펌웨어](docs/wrx80e-bios-setup.md).

## 이 로그가 낳은 프로젝트

측정하다 도구 부재에 부딪혀 두 번은 도구가 리포지토리까지 됐다. 둘 다 MIT, 포크 아님.

- **[toktape](https://github.com/midagedev/toktape)** — 로컬 LLM 서빙용 블랙박스 테이프. 이미 돌아가는 `llama-server`에 붙어 한 실행을 `.tape`에 담고, 모델 위치·프로세스가 실제 건드린 것·실제 속도를 카드에 찍는다. 이 README의 모든 클립이 이것으로 녹음됐다. 존재 이유: 증인 없는 tok/s는 — 배치, 폴트, 카드가 실제 잡은 클럭 — 누구도 검증 못 하고, 일주일 뒤 저자 본인도 못 한다. 이 리포는 공동 관리자가 아니라 까다로운 하류 사용자다. 손으로 모으는 증인이 필요해지면 로컬 우회가 아니라 toktape에 요구사항으로 보낸다.
- **[exl3-serve](https://github.com/midagedev/exl3-serve)** — [ExLlamaV3](https://github.com/turboderp-org/exllamav3)용 `llama-server` 호환 HTTP 앞단. ExLlamaV3는 서버를 안 내놓아서 `llama-server`용으로 쓴 것은 아무것도 EXL3 모델을 못 돌렸고, 녹음기도 마찬가지다. 한 EXL3 모델을 그 표면 — `/props`·`/health`·`/slots`·llama-server `timings`를 exllamav3 자체 작업 결과로 채운 `/v1/chat/completions` — 으로 서빙한 것이 여기서 엔진을 잴 수 있게 했다. [맞추는 데 든 값](log/2026-09-15-exl3-serve-and-tabbyapi-timings.md): 실모델만 드러낸 결함 네 개, 그리고 속도가 의미를 갖기 전에 먼저 측정해야 했던 `time_generate`.

이 로그가 파일하는 트래커와 위키는 로컬 소프트웨어이기도 하지만, 기계보다 먼저 있던 범용 도구라 여기서가 아니라 [`CLAUDE.md`](CLAUDE.md)에 이름을 적는다.
