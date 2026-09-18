# 네트워크 단절 두 겹: 이사 하나, SSD 하나

**2026-09-12.** 워크스테이션이 09-11 저녁 — 사무실에서 집으로 옮긴 날 — 어두워졌고 약 20시간 어두웠다. 콘솔에 내내 로그인 프롬프트라 OS는 문제가 아니었다. 고장 둘이 독립적으로 하루 간격이었고, 하나씩 단독으로 네트워크를 막기에 충분했다. 하나만 고치면 정확히 같은 죽음이다. 첫날 추측이 빈손인 이유 대개가 그것이다.

아래 전부 이 기계·이 날짜, 관련 부팅 저널을 읽어서다.

## 고장 하나: 이사, 내놓지 않은 임대

설치자가 쓴 netplan 스탠자에 `critical: true`가 들어 있었다. `systemd-networkd`에 동작 구성을 뜯지 말고 붙들라는 뜻이다 — 루트 파일시스템이 네트워크에 있는 기계용이다. 임대 떨어지면 디스크가 떨어지니.

이 기계에 사무실 임대 있었다. 이사가 무슨 짓을 했는지 본다. 사무실 마지막 부팅 끝자락, 케이블 빠질 때:

```
20:24:40  enp36s0f1: Lost carrier
20:24:40  enp36s0f1: DHCPv4 connection considered critical,
                     ignoring request to reconfigure it.
20:24:44  enp36s0f1: Gained carrier
```

이어서 집 첫 부팅, 30분 뒤:

```
20:52:53  ixgbe 0000:24:00.1 enp36s0f1: renamed from eth1
20:52:54  enp36s0f1: Configuring with …10-netplan-enp36s0f1.network
20:52:58  enp36s0f1: Gained carrier
20:52:58  ixgbe … enp36s0f1: NIC Link is Up 1 Gbps, Flow Control: RX/TX
20:52:59  enp36s0f1: Gained IPv6LL
```

인터페이스 발견·구성·1 Gbps carrier. 링크로컬 IPv6를 받고 **DHCPv4는 한 번도** — 그 부팅 어디에도 `DHCPv4 address … acquired` 줄이 없다. 전 부팅 `12:56:42`에 있는 것과 대조다. `critical`이 말한 대로 했다. 재구성 요청 무시. 집 네트워크에 앉아 사무실 임대 개념을 붙들었다.

하류 전부 거기서 왔다. `tailscaled`가 `v4=false`에 `LinkChange: all links down; pausing`을 찍었다. tailnet에서 노드가 내려가고 `ssh`가 타임아웃난 이유다.

같은 부팅 각주 하나. 다음 날 새벽 04:58:

```
ixgbe … enp36s0f1: NETDEV WATCHDOG: CPU: 22: transmit queue 3 timed out 5685 ms
ixgbe … enp36s0f1: initiating reset due to tx timeout
ixgbe … enp36s0f1: Reset adapter
...
DHCPv4 connection considered critical, ignoring request to reconfigure it.
```

README가 이미 경고하는 X550 `Tx Unit Hang`이다. 임대를 물을 두 번째 기회를 줬다. `critical`이 그것도 거부했다.

## 고장 둘: 새 SSD가 네트워크 카드를 옮겼다

수리 시작할 때는 Phison E18 4 TB가 들어가 있었고 BIOS가 리셋돼 있었다. 추가 드라이브가 곁다리가 아니라 두 번째 고장의 원인이다.

```
23:00.0  Non-Volatile memory controller  Phison E18 PCIe4 NVMe Controller
24:00.0  USB controller                  ASMedia ASM3242
25:00.0  Ethernet controller             Intel X550
25:00.1  Ethernet controller             Intel X550
```

새 드라이브가 버스 `0x23`을 먹고 뒤 전부 한 칸 밀렸다. 부팅 너머 측정, 내내 같은 카드·MAC:

| 부팅 | 시기 | X550 위치 | 인터페이스명 |
|---|---|---|---|
| −5, −4 | 09-11 | `0000:24:00.x` | `enp36s0f1` |
| −3 | 09-12 08:47–13:36 | `0000:24:00.x` | `enp36s0f1` |
| −2 이후 | 09-12 15:30 → | `0000:25:00.x` | `enp37s0f1` |

`enp36s0f1`은 오래 가는 이름이 아니다. PCI 버스 번호의 렌더링이다 — `0x24`=36, `0x25`=37. 펌웨어가 열거 때 붙인다. 앞에 장치를 끼우면 이름이 움직인다.

netplan 파일이 계속 `enp36s0f1`을 지목했다. 없는 인터페이스 지목 스탠자는 에러 조건이 아니다. 경고 없음, 실패 유닛 없음, 저널 줄 없음. 링크가 절대 안 올라오고, DHCP가 안 돌고, 기계가 주소 없이 로그인 프롬프트에 앉는다 — 콘솔에서 죽은 NIC과 구분 불가다.

하드웨어·케이블 고장이 아니라 그 상태였다는 증거는 명령 하나다. `ip link set … up`이 유선 포트에 즉시 `LOWER_UP`을 올렸다. 링크는 내내 있었다. 올릴 구성이 없었다.

## 아니었던 것

유력 용의자는 `pci=realloc=off`였다. 이 보드는 없으면 10 GbE 포트가 떨어지고, BIOS 리셋이 커널 파라미터를 잃는 종류의 사건처럼 보인다. 틀렸다.

```
$ cat /proc/cmdline
BOOT_IMAGE=/boot/vmlinuz-6.8.0-139-generic root=UUID=… ro pci=realloc=off
```

파라미터는 디스크 GRUB 설정에 살아서 펌웨어 변경이 위협한 적 없다. 적어둔다. 이 기계가 계속 내놓을 가설이라서다.

## 수정

[`configs/01-lan.yaml`](../configs/01-lan.yaml), `/etc/netplan/01-lan.yaml` 모드 600에 설치. 셋 변경, 고장당 하나 + 밑의 함정 하나:

- **MAC 주소에 매칭.** 펌웨어가 안 바꾼다. 버스 파생 이름 대신. X550 포트 둘 다 선언해서 케이블이 어느 포트에 꽂혀도 된다.
- **`critical` 없음.** 이 기계 루트는 로컬이다. 오래된 임대 붙들어서 지킬 것이 없고, 붙든 것이 첫날 값이다.
- **cloud-init이 파일을 더는 안 소유한다.** `50-cloud-init.yaml`은 생성물이고, `/etc/cloud/cloud.cfg.d/90-installer-network.cfg`에 같은 오래된 `enp36s0f1`이 있었다 — netplan 파일만 고치면 다음 부팅 재생성까지만 먹는다. `network: {config: disabled}` drop-in이 소유자를 하나로 만든다.기존 파일은 삭제 말고 `/root/netplan-backup/`행.

`optional: true` 양 포트 deliberate고 값 치르는 것 명시한다. 없으면 `systemd-networkd-wait-online`이 케이블 없는 포트에 부팅을 120초 묶는다. 있으면 `network-online.target`이 즉시 통과하는데, 여기만 안전한 이유는 그것이 필요한 것이 없어서다 — LLM 서버는 loopback에 묶고 tailscaled는 자체 재시도한다.

## 체크

결함 부류는 "없는 하드웨어를 서술하는 netplan, 조용히"라서, 계약은 선언 인터페이스마다 실제 링크에 닿는 것이다. [`configs/netplan-iface-check`](../configs/netplan-iface-check)가 assert하고, [oneshot 유닛](../configs/netplan-iface-check.service)이 매 부팅 돌아서 다음 mismatch가 닿을 수 없는 기계 대신 `systemctl --failed`에 나온다.

고장 구성에 수정 전:

```
FAIL /etc/netplan/50-cloud-init.yaml: enp36s0f1 names a link that does not exist
0/1 declared interfaces present
EXIT=1
```

새 구성에:

```
ok   lan-f0: MAC …:86 -> enp37s0f0
ok   lan-f1: MAC …:87 -> enp37s0f1
2/2 declared interfaces present
EXIT=0
```

FAIL이 요점이고, 수정 들어가기 전에 기록했다 — 뒤에는 일부러 기계를 깨야 재현된다.

## DNS, 가정 말고 측정

기존 구성에 공개 리졸버 둘이 지명돼 있었다. 기존 ISP용 선정이다. 네트워크 바뀌며 들고 가는 것은 버스 번호 바뀌며 인터페이스명 들고 가는 것과 같은 종의 실수라 쟀다.

| 리졸버 | 결과 |
|---|---|
| 구성 지명 둘 | 둘 다 응답 |
| 집 라우터 | `connection refused` — DNS 안 한다 |

그래서 둔다. 깨졌으면 블록 삭제하고 DHCP 주는 대로 받는 것이 맞았다 — 다만 여기 DHCP 답에 그 라우터가 들어 있고, 그 라우터가 53번을 거부한다.

## 유일한 출입구를 안 잃고 적용

revert·apply 둘 다 transient systemd 유닛에 돌렸다. `netplan apply`를 날리는 SSH 세션이 재구성되는 인터페이스를 타서, 중간에 죽는 apply는 어느쪽 결과보다 나쁘다.

```bash
# dead man's switch: 180초에 손구성 주소를 복원한다
systemd-run --on-active=180 --unit=lan-revert /bin/bash -c \
  "ip addr add <addr>/24 dev enp37s0f1 2>/dev/null; \
   ip route replace default via <router> dev enp37s0f1"

systemd-run --unit=lan-apply --collect /usr/sbin/netplan apply
```

revert 목표는 이전 구성이 아니라 *동작하는* 손구성 상태다 — `50-cloud-init.yaml`로 돌아가면 단절이 복원된다. 세션 돌아오고 타이머를 멈췄다. 결과: 유선 포트 DHCP 임대, 손으로 넣은 주소는 netplan이 직접 치웠다, DNS resolve, Tailscale 스스로 복귀.

## 리부트

`netplan apply` 성공과 부팅 생존은 다른 주장이다. 이 단절은 전적으로 두 번째 이야기였다.

| | |
|---|---|
| cloud-init이 구성 재생성 안 함 | `/etc/netplan/`에 `01-lan.yaml`뿐 |
| 유선 포트 주소 획득 | 리부트 전 같은 DHCP 임대, 그 경유 default route |
| DNS | resolve |
| Tailscale | 스스로 복귀 |

넷 중 셋. 네 번째는 LLM 서버였고, 안 돌고 있었다.

## 리부트가 드러낸 것

막 고친 기계 리부트가 이미 깨져 있던 다음 것을 찾는 법이다. 둘 있었고, 둘 다 네트워크와 무관하다.

**LLM 서버가 최소 4부팅 자동 시작 안 됐다.** `enabled` 맞고, `multi-user.target`이 원하고, 지목 의존성 전부 active, 자체 저널 비어 있다 — systemd가 시도한 적 없다. 원인은 다른 곳 한 줄이다.

```
multi-user.target: Found ordering cycle on llm.service/start
multi-user.target: Job llm.service/start deleted to break ordering cycle
                   starting with multi-user.target/start
```

`thermal-guard.service`가 `WantedBy=multi-user.target`이면서 `After=multi-user.target`이었다. 타깃에 끌리는 유닛이 그 뒤 순서를 걸면 고리가 닫힌다. `multi-user.target` → `llm.service`(`After=thermal-guard.service`) → `thermal-guard.service` → `multi-user.target`. systemd가 아는 유일한 대로 고리를 끊었고, 끊은 job이 모델 서버 시작 job이었다. stray `After=` 제거가 수정이다.

16:57 부팅에 검증했다. 저널에 `ordering cycle` 없고, `llm.service` 16:57:22부터 active, `NRestarts=0`, systemd 말고 시작한 것 없음. 사이클은 `multi-user.target` 트랜잭션 지을 때만 존재해서 부팅만이 판가름할 수 있었다.

(한 grep이 먼저 반대라 했다. `journalctl | grep -c 'ordering cycle'`이 1을 돌려줬는데, 매치가 grep하는 SSH 명령 본문이었다. 들어오는 길에 `tailscaled`가 로그 남긴 것이다. 자기 질문을 답으로 세기 쉽다, SSH 너머에서.)

겉에서 그 실패 모양: enabled 서비스, failed 상태 없음, 로그 없음, 안 돈다. `systemctl status`에 `inactive (dead)` — 일부러 멈춘 것과 같은 말이다. `systemd-analyze verify llm.service`가 0에 나간다. 순서 사이클은 유닛 파싱이 아니라 트랜잭션 지을 때 해소돼서다. 부팅 저널에만 증거 있다.

**`cpu-noboost.service`가 노골적으로 실패 중이었다.** `echo 0 > /sys/devices/system/cpu/cpufreq/boost`를 하는데, BIOS 리셋 뒤 그 노드가 없다. 펌웨어가 Core Performance Boost를 직접 끄기 때문이다.

| | |
|---|---|
| `cpb` | `0` |
| `scaling_max_freq` | `3600000` |
| `bios_limit` | `3600000` — 5975WX 베이스 클럭 |

그래서 기계의 진짜 계약 — 부스트 끔. 쿨러가 sWRX8 IHS를 안 커버해서 — 은 지켜지는데, 강제 유닛이 실패를 보고했다. 들리는 것보다 나쁘다. `systemctl --failed`의 영구 빨간 줄이 진짜 실패 숨는 자리다. [`configs/cpu-noboost`](../configs/cpu-noboost)가 대체하고 메커니즘이 아니라 결과를 assert한다 — 노브 있는 곳마다 부스트 끄고, 꺼졌음을 증거 지목에 확인하고, 켜 있는데 못 끌 때만 실패한다. 이제 `boost off: cpb reads 0 (firmware or driver)`을 보고한다.

## 같은 실수, 네 번

뻔히 말할 가치 있다. 여기 유일한 일반 교훈이라서다. 이 기계의 별개 실패 넷, 전부 같은 모양이다. 아끼던 *불변*이 아니라 휘발 *메커니즘*에 묶었다.

| 원한 것 | 묶인 것 |
|---|---|
| 이 네트워크 카드 | PCI 버스 번호의 렌더링 이름 |
| 동작하는 임대 | 이미 가진 임대 |
| 부스트 끔 | sysfs 파일 하나의 존재 |
| 가드 뒤 시작 | 자기를 기다리는 타깃 |

다섯 번째는 수년 전 누군가 맞혀서 값 0이다. NVMe 컨트롤러 둘에 `nvme0` 결정은 프로브 먼저 끝나는 쪽이다. 프로브는 비동기다. 하드 손대지 않고 40분 간격 부팅 둘에 측정:

| 부팅 | `nvme0n1` | 루트 위치 |
|---|---|---|
| 16:46 | 2 TB 삼성 | `nvme0n1p2` |
| 16:57 | 4 TB Phison | `nvme1n1p2` |

둘 다 루트가 마운트됐다. `/etc/fstab`과 커널 명령줄이 UUID로 지목해서다. `nvme0`에 디스크 사실은 하나도 없었다 — 파괴 명령에 그 이름 치기 전에 붙들 것이다.

## 서빙, 그 전부 뒤에

```
decode    28.9 tok/s   (400 tokens generated)
prompt      178 tokens in 1.9s
draft        62% accepted   (DSpark, depth 2)
```
