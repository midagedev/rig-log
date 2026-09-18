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
| 2026-09-19 | [Rust로 쓴 첫 커널, 두 모델에 같은 스펙](log/2026-09-19-a-first-rust-kernel-two-arms.md) | cuda-oxide Q3_K gemv가 3090에서 ggml mmvq의 **1.05배**(348 대 333 GB/s, q8_1+dp4a). 두 라운드 네 팔: 1라운드 0.40배의 두 원인 보고가 겹친 자리가 2라운드 스펙이 됐다 |

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
