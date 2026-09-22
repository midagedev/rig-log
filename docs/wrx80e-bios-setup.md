# WRX80E 워크스테이션의 BIOS 설정

보드는 ASUS Pro WS WRX80E-SAGE SE WIFI (WRX80, Threadripper PRO 5975WX, GPU 2개, DDR4 256 GB)이다. 이 문서는 무인 LLM 호스트로 운영할 때의 펌웨어 측면, 즉 무엇을 설정해야 하는지, 각 항목이 어디에 숨어 있는지, 그리고 그 이유를 다룬다. 메뉴 경로와 페이지 번호는 공식 [BIOS 매뉴얼 (E18120)](https://dlcdnets.asus.com/pub/ASUS/mb/SocketTRX4/Pro_WS_WRX80E-SAGE_SE_WIFI/E18120_PRO_WS_WRX80E-SAGE_SE_WIFI_BIOS_Manual_EM_WEB.pdf) 기준이다.

이 보드의 두 가지 설정은 데스크톱 BIOS에서 일반적으로 찾는 위치에 있지 않으며, 둘 다 찾는 데 시간이 걸린다. CPU 전력 제한은 AMD CBS 내에서 "power limit"이 아닌 이름 아래에 묻혀 있고, 문서화된 메뉴에는 팬 커브 페이지가 전혀 없다. 둘 다 아래에서 해결한다.

## 각 항목의 위치

| 항목 | 메뉴 경로 | 매뉴얼 |
|---|---|---|
| CPU 전력 제한 (PPT / cTDP) | Advanced → AMD CBS → NBIO Common Options → SMU Common Options | p.53 |
| 펌웨어에서 부스트 끄기 | Advanced → AMD CBS → CPU Common Options → Core Performance Boost | p.39 |
| GPU 2개용 대용량 VRAM 매핑 | Advanced → PCI Subsystem Settings → Above 4G Decoding | p.25 |
| 4G 이상 MMIO 애퍼처 | Advanced → AMD PBS → Mmio Above 4G Limit | p.35 |
| 정전 후 자동 전원 켜기 | Advanced → APM Configuration → Restore AC Power Loss | p.34 |
| Wake-on-LAN | Advanced → APM Configuration → Power On By PCI-E | p.34 |
| BMC / 원격 KVM | Server Mgmt → BMC Support, BMC network configuration | p.67, 69 |
| 부트 워치독 (**hung-OS 체크 아님** — 아래 참조) | Server Mgmt → OS Watchdog Timer | p.68 |
| 메모리 클럭 | Advanced → AMD CBS → UMC Common Options → DDR4 Common Options → DRAM Timing Configuration → Accept → Overclock [Enabled] → Memory Clock Speed (MEMCLK, DDR 수치의 절반) | p.42 |
| DRAM 전압 (Auto에서 클럭을 따라가지 **않음**) | Ai Tweaker → DRAM ABCD Voltage / DRAM EFGH Voltage, 값 직접 입력 | p.18 |
| Infinity Fabric 클럭 | **이 펌웨어에는 항목 없음** — 메모리 클럭을 1:1로 따라가며 1800 MHz까지 자체 동작 | — |
| 팬 커브 | 이 보드의 BIOS에 없음; BMC가 헤더를 구동함 (CPU_FAN은 상수 2200 rpm으로 읽힘) | — |
| 읽기 전용 팬/온도/전압 | Tool → IPMI Hardware Monitor | p.63 |

## CPU 전력 제한 — "power limit"이라 불리지 않는 항목

AMD는 "Power Limit" 필드를 노출하지 않는다. 패키지 전력 상한은 PPT이며, 이는 Ai Tweaker가 아닌 **Advanced → AMD CBS → NBIO Common Options → SMU Common Options** (p.53)에 있다:

- **Power Package Limit Control** — `Auto`는 퓨즈된 PPT(5975WX 기준 280 W)를 사용한다. 더 낮은 상한을 설정하려면 `Manual`로 설정하여 **Power Package Limit**을 노출한다.
- **cTDP Control** / **cTDP** — 열 설계 전력 상한, 동일한 패턴: 값을 설정하려면 `Manual`.

PPT를 낮추면 올코어 클럭이 약간 줄어드는 대신 온도와 팬 소음이 크게 감소한다. 이 워크로드에서는 그 트레이드오프가 유리하다. CPU 측 디코드은 메모리 대역폭에 종속적이다. expert는 DDR4에서 실측 ~116 GB/s로 읽어내며, 이것이 병목이지 코어 클럭이 아니다. 따라서 PPT를 제한해도 처리량 손실은 거의 없으면서 패키지를 첫 [로그 엔트리](../log/2026-09-11.md#deepseek-v4-moe-offload)의 실측 81 °C 지속 / 91 °C 프리필-burst 수치에서 크게 멀어지게 할 수 있다. 주어진 제한에서의 정확한 tok/s 비용은 **아직 실측되지 않았다**; 이것이 다음 벤치이다.

**Core Performance Boost → `Disabled`** (AMD CBS → CPU Common Options, p.39)와 함께 사용하여 모든 코어를 베이스 클럭에 고정한다. 이는 Linux에서 `cpufreq/boost=0`으로 설정하던 것의 펌웨어 영구 버전이다.

## GPU 2개: 주소 공간

- **Above 4G Decoding → `Enabled`** (p.25). 48 GB 카드와 24 GB 카드는 4 GB 라인 위에 매핑되어야 한다. 이것이 없으면 BAR가 맞지 않는다.
- **Re-Size BAR Support → `Auto`** (p.25).
- **Mmio Above 4G Limit → `Auto`** (AMD PBS, p.35; Above 4G Decoding이 활성화된 후에만 나타남). PCIe 열거가 잘못 동작하면 `43`이 폴백이다.
- **SR-IOV → `Disabled`** (GPU SR-IOV를 수행하지 않는 한).

이것의 Linux 대응 항목은 커널 명령 줄의 `pci=realloc=off`이며, 이 보드는 이것이 없으면 10 GbE 포트가 떨어진다. 이는 개인 호스트 노트에 보관되어 있으며 여기에는 없다. 디스크의 GRUB 설정에 있으므로 BIOS 설정 변경이 이를 위협하지 않으며, 먼저 의심하지 않을 가치가 있다. 2026-09-11에는 이 보드와 무관한 정전의 설명으로 남아 있었다.

이 기계을 열 때 실제로 존재하는 위험은 **PCI 리넘버링**이다. 장치를 추가하면 무엇이 무엇 앞에 오는지가 바뀐다. 2026-09-12에 설치된 4 TB NVMe 드라이브는 버스 `0x23`을 차지했고, 그 뒤의 10 GbE 컨트롤러는 `0x24`에서 `0x25`로 이동했다. 해당 주소에서 파생된 모든 이름이 함께 이동한다. `enp36s0f1`이 `enp37s0f1`이 되었고, netplan 파일은 이전 이름을 계속 참조했으며, 기계는 네트워크 없이 부팅되었고 로그도 남지 않았다. 존재하지 않는 인터페이스를 명명하는 netplan 스탠자는 오류가 아니라 조용히 무효화되기 때문이다. **인터페이스를 버스 기반 이름이 아닌 MAC 주소로 매칭하라.** 설정과 이를 검증하는 검사는 [`configs/01-lan.yaml`](../configs/01-lan.yaml) 및 [`configs/netplan-iface-check`](../configs/netplan-iface-check)에 있으며, 전체 설명은 [로그 엔트리](../log/2026-09-12.md#offline-after-a-move-and-an-ssd)에 있다.

## 전원 및 무인 동작 (APM, p.34)

| 항목 | 값 | 이유 |
|---|---|---|
| Restore AC Power Loss | `Power On` | 전원 깜빡임 후 자동으로 복귀 |
| Power On By PCI-E | `Enabled` | Wake-on-LAN |
| ErP Ready | `Disabled` | Enabled는 S5 대기 전원을 차단하여 WoL과 BMC를 죽임 |

## 원격 복구: BMC (Server Mgmt, p.67–70)

이 보드에는 ASMB9-iKVM (ASPEED AST2500) 베이스보드 컨트롤러가 있다. 추가 카드 없이 보드 자체에 완전한 원격 KVM이 탑재되어 있다. 호스트가 전원 꺼진 상태에서도 응답하므로, 다른 방에 있는 헤드리스 박스에 정확히 필요한 기능이다.

- **BMC Support → `Enabled`** (p.67).
- **BMC network configuration → Configure IPV4 support → Lan channel 1** (p.69): DHCP 주소를 위해 **Configuration Address source → `DynamicBmcDhcp`**로 설정하거나, `Static`으로 설정하고 IP를 입력한다. 보드에는 두 개의 LAN 채널이 있다. 케이블이 하나만 연결되어 있다면 DHCP 설정은 해당 포트를 소유한 채널에 있어야 하므로, 둘 다 설정하는 것이 가장 안전하다.
- **OS Watchdog Timer → `Enabled`**, **OS Wtd Timer Policy → `Reset`** (p.68), *단, OS 측 설정이 갖춰진 경우에만* — 아래 수정 사항 참조.

  > **2026-09-12 수정.** 이 항목은 이전에 "OS가 응답을 멈추면 BMC가 자동으로 박스를 리셋한다"로 읽혔다. 틀린 설명이고, 그걸 믿은 탓에 오후 한나절을 날렸다. `OS Watchdog Timer`는 **부트** 워치독을 아밍한다. IPMI 타이머는 `OS Load`를 사용하며, POST에서 시작된 600초 카운트다운으로, 운영 체제는 부트가 완료된 후 이를 인수하거나 꺼야 한다. 실행 중인 시스템의 활성도 체크가 아니다. OS가 여전히 응답하는지는 아무것도 감지하지 못한다. 설정을 활성화하고 OS 측 대응 항목이 없으면, 완벽하게 건강한 기계가 매 부트 후 10분마다 하드 리셋되며, 하드 리셋은 종료 기록을 쓸 기회가 없으므로 로그도 남지 않는다. 이것이 이 가이드의 BIOS 리셋 후 네 번 발생한 일이다.
  >
  > OS가 타이머를 인수하는 경우에만 활성화 상태를 유지하라. Ubuntu에서는 `ipmi_watchdog`을 로드하고 systemd가 이를 펫하도록 `RuntimeWatchdogSec`을 설정하는 것을 의미한다. 파일은 [`configs/watchdog/`](../configs/watchdog)에 있으며, 전체 설명은 [로그 엔트리](../log/2026-09-12.md#bmc-watchdog-reset-loop)에 있다. 이렇게 하면 이전 문장이 약속한 것을 얻는다. 쐐기 박힌 커널을 리셋하는 진정한 런타임 워치독이다. 이것이 없으면 이 항목을 `Disabled`로 설정하라.

그 안에서 BMC의 시계를 설정하거나, 적어도 잘못되었을 수 있음을 인지하라. 이 보드에서는 호스트와 8시간 차이가 나는 것으로 확인되었으며, 이는 워치독 리셋을 명명하는 유일한 도구인 BMC 이벤트 로그를 시스템 저널과 정확히 맞춰야 할 때 가장 중요한 순간에 맞추기 어렵게 만든다.

첫 부트 후: `https://<its IP>`에서 BMC에 도달하며, 기본 로그인 `admin` / `admin`으로 접속 후 **즉시 비밀번호를 변경하라**. 기본값으로 남겨진 구성되지 않은 AMI BMC는 LAN 상의 개방형 원격 전원 및 콘솔 인터페이스이다. 여기서 전원 켜기/끄기/리셋, 라이브 화면(POST 코드, 부트, 커널 패닉), 가상 미디어를 모두 원격으로 수행할 수 있다.

### Linux에서 팬 읽기 (2026-09-14)

팬 헤더는 BMC만 볼 수 있다. Super I/O (`nct6798`, 드라이버 `nct6775`)는 전압과 자체 온도 입력을 잘 읽지만, 7개 팬 채널 모두 PWM 1–5를 60 %로 구동 중임에도 0 RPM을 보고한다. 타크 라인은 ASPEED BMC로 간다. `asus_ec_sensors`는 이 보드를 나열하지 않으며 DSDT에는 필요한 `ASMX` 뮤텍스나 `BREC` 영역이 없고, `asus_wmi_sensors`는 hwmon 장치를 생성하지 않고 로드된다. 호스트에서 인밴드 IPMI 인터페이스를 통해 작동하는 방법:

```
sudo ipmitool sdr type fan          # CPU_FAN 2200 RPM, SOC_FAN 2700, CHIPSET_FAN 2500
sudo ipmitool sdr type temperature  # CPU Temp., LAN Temp., PCIE01 Temp.
sudo ipmitool sensor get CPU_FAN    # lower critical threshold 1200 RPM
```

BMC의 CPU_FAN 하한 임계값은 1200 RPM이므로, 멈추거나 뽑힌 CPU 팬은 BMC 이벤트 로그에 자동으로 나타난다. 호스트 측 열 가드는 k10temp `Tctl`을 직접 읽는다.

### PCIe 슬롯당 온도 센서 (2026-09-16)

`sdr type temperature`는 슬롯당 하나씩 `PCIE01`부터 `PCIE07`까지 내놓고, 카드가 꽂힌 슬롯만 값을 읽는다. 5번 슬롯의 A6000에서 1시간 미만 훈련 중이고 3090이 유휴 상태일 때:

```
PCIE01 Temp. | 34 degrees C      CPU Temp. | 43 degrees C
PCIE05 Temp. | 86 degrees C      LAN Temp. | 51 degrees C
```

두 가지 용도. 슬롯 읽기는 카드와 독립적이므로, 카드의 `nvidia-smi` 다이 온도 87 °C에 대한 슬롯 온도 86 °C는 카드 주변 공기가 그 온도라는 확인이지, 한 센서가 핫스팟을 찾은 것이 아니다. 그리고 드라이버가 할 수 없을 때 답을 제공한다. 2026-09-16에 두 GPU 모두 Xid 154 이후 CUDA 초기화에 실패했고 `nvidia-smi`는 어느 카드도 열 수 없었지만, 이 채널은 계속 보고했을 것이다.

### 팬 헤더에서 `Disabled`의 의미

이 기계의 6개 `CHA_FAN` 헤더 모두 `Disabled`로 읽힌다. 이는 BMC가 헤더에서 타코미터를 보지 못한다는 의미이지, 케이스에 공기 흐름이 없다는 뜻이 아니다. 이곳의 섀시 팬은 전원 공급 장치에 직접 배선되어 있어 커브 없이 상수 속도로 돌아가며, 아무것도 보고하지 않는다. BMC가 이 보드에서 팬을 볼 수 있는 유일한 것이므로, PSU 배선 팬은 머신의 모든 도구에서 보이지 않는다. `Disabled`를 "이 헤더에 아무것도 꽂혀 있지 않음"으로 읽어라.

## 팬: 문서화된 메뉴에 없음

Tool → IPMI Hardware Monitor 페이지 (p.63)는 **읽기 전용**이다. 팬 RPM, 온도, 전압을 보여주지만 커브 편집기는 없다. 매뉴얼에는 Monitor 메뉴가 전혀 문서화되어 있지 않지만, 펌웨어에는 있다. 팬 커브는 **Monitor** 메뉴 / **`F6` Qfan Control** 핫키 아래에 있다. 이것이 Linux에서 이 보드의 팬을 구동할 수 없는 이유이다. 헤더는 ASUS 컨트롤러에 응답하며, OS가 쓸 수 있는 hwmon이 아니다. 펌웨어에서 커브를 설정해야 한다.

- ~~라디에이터 / 섀시 팬 (CHA_FAN): 코어 온도에 일찍 반응하는 공격적인 커브, AIO 냉각수가 정체되기 전 열적 여유가 거의 없기 때문.~~
- ~~크라켄 펌프는 USB이며 팬 헤더가 아님 — Linux에서 liquidctl로 100 % 고정, 이 커브와 무관.~~

  **둘 다 2026-09-14 이후 오래됨**, AIO가 `CPU_FAN`에 ARCTIC Freezer 4U-M으로 교체되었고 liquidctl이 장치를 잃음 ([로그](../log/2026-09-14.md#air-cooler-swap)). 이제 커브할 라디에이터가 없으며, 2026-09-16 현재 섀시 팬도 헤더에 없으므로 CHA_FAN 커브는 아무것도 구동하지 않는다.

정확한 커브 포인트는 머신의 라이브 그래프를 기준으로 설정되었으며 아직 여기에 전사되지 않았다.

## 메모리 클럭 (2026-09-14)

대역폭 프로브, 검증 메모리 스트레스, 탐욕적 아이덴티티 체크 및 각 정지점에서 3회 디코드으로 3200 → 3400 → 3600 → 3666을 진행했으며, 기록은 [`log/2026-09-14.md#memory-clock-3600`](../log/2026-09-14.md#memory-clock-3600)에 있다. 현재 구성은 **Memory Clock Speed 1800 MHz (DDR4-3600), DRAM ABCD/EFGH Voltage 1.30**이다. 결정된 이유:

- 3600은 Auto 1.2 V에서 `stress-ng --vm --verify` 10분을 통과함; 1.3 V에서 3666은 MCE 0으로 139개의 잘못된 리드백을 반환했고(비 ECC이므로 다른 것은 알아차리지 못했을 것임), 패브릭이 1800 MHz에 머물러 대역폭의 3 %를 잃음. 3733, 3766, 3800은 POST되지 않음.
- Auto DRAM 전압은 AMD CBS에서 선택한 클럭과 관계없이 SPD 1.2 V이며, 부하에 따라 움직이지 않음. BMC는 유휴 및 스트레스 상태에서 1.22 V를 읽음. 매뉴얼 항목이 적용됨: 1.30은 1.29/1.28 V로 읽힘.
- 3600은 마지막으로 동작하는 단계이므로 0.1 V의 여유를 가짐.

## Setup 진입 및 잘못된 클럭에서 복구

`sudo systemctl reboot --firmware-setup` 또는 `sudo ipmitool chassis bootdev bios` (한 부트만; 외부에서 `lanplus`로도 작동)는 다음 부트에 Setup으로 진입한다. 트레이닝되지 않는 클럭은 케이스의 **CLR CMOS 버튼**으로 복구한다. BMC 웹 UI에는 원격 CMOS 클리어 또는 BIOS-기본값 동작이 없다.

### CMOS 클리어 후

모든 것이 리셋된다. 2026-09-14에 유용하다고 판단된 순서대로 다시 입력한 목록:

1. AMD CBS → UMC Common Options → DDR4 Common Options → DRAM Timing Configuration → Accept → Overclock Enabled → Memory Clock Speed 1800 MHz
2. Ai Tweaker → DRAM ABCD Voltage 1.30, DRAM EFGH Voltage 1.30
3. Advanced → APM Configuration → Restore AC Power Loss = Power On, ErP Ready = Disabled
4. Advanced → PCI Subsystem Settings → Above 4G Decoding = Enabled, Re-Size BAR Support = Auto (이후 두 GPU가 `nvidia-smi`에 표시되어야 함)
5. AMD CBS → DF Common Options → Memory Addressing → NUMA nodes per socket = NPS1 (`lscpu`가 하나의 노드를 표시함)
6. Server Mgmt → OS Watchdog Timer = Disabled
7. 의도적으로 기본값으로 둠: PPT (280 W), Core Performance Boost (Auto), Global C-state (Auto), SMT, CSM (Disabled)

## 아직 실측할 것

- 퓨즈된 280 W 대비 제한된 PPT에서의 tok/s, 제한값 선택을 위해.
- 3200 → 3600 디코드 델타를 닫기 위한 깨끗한 DDR4-3200 디코드 행 (3회 단일 스트림 400-토큰 런); 대역폭은 +12.6 %이나, 디코드은 아직 동일 기준선에 대해 실측되지 않음.
