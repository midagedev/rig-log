# 10분마다 리셋되던 기계, 아는 것은 아무도 없었다

**2026-09-12.** 오후 40분간 워크스테이션이 10분마다 하드리셋 네 번, 기록은 한 줄도 안 남겼다. 드러낸 것은 리셋이 아니다. SSH 세션은 짧고 90초면 돌아오니 — 주인이 GPU가 돌아가는 것을 본 것이다. 아무것도 안 돌아야 하는데. 부팅마다 `llm.service`가 다시 올라온 것이었다.

원인은 BIOS가 걸어두고 이 기계 아무것도 풀지 않은 BMC 워치독이다. 같은 날 아침 BIOS 리셋 때부터 걸려 있었다.

## 모양

```
boot  started      ended        uptime
 -3   16:46:31     16:56:14     9m 43s
 -2   16:57:19     17:06:52     9m 33s
 -1   17:08:08     17:17:01     8m 53s
```

1분 안에 규칙적 — 고장이 아니라 타이머의 서명이다. 커널 로그에 아무것도 없다. 패닉·oops·MCE·열 이벤트 없음. CPU 43 °C, NVMe 48·36 °C. 매 부팅 저널이 문장 중간에 끊긴다. 한 부팅의 마지막 줄은 시간별 실행용 `cron` 세션 오픈이다.

## 오독, 그리고 정정

첫 판독은 종료가 정상적이라고 했다. 근거 줄:

```
17:14:36 systemd[8902]: Reached target shutdown.target - Shutdown.
```

시스템 종료가 아니다. 대괄호 숫자는 PID고, 8902는 SSH 세션 끝나며 정리되는 `systemd --user` 인스턴스다. 내 SSH 명령마다 세션을 열고 닫으니 부팅당 네 개가 나온다. PID 1은 그런 말을 한 적이 없다.

판가름은 한 줄이다. 기억할 가치 있다.

| 부팅 | system-shutdown 기록 |
|---|---|
| `systemctl reboot`으로 재부팅한 것 | 1 |
| 이후 매 부팅 | 0 |

clean 종료는 기록을 쓴다. 하드리셋은 쓸 겨를이 없다. 대조가 증거고, 둘 다 한 기계에 있으면 어디서든 된다.

## 타이머를 쥔 것

```
$ ipmitool mc watchdog get
Watchdog Timer Use:     OS Load (0x43)
Watchdog Timer Is:      Started/Running
Watchdog Timer Action:  Hard Reset (0x01)
Initial Countdown:      600.0 sec
Present Countdown:      271.2 sec
```

BMC 자체 이벤트 로그에 리셋당 한 줄씩, 셋이다.

```
2beb | Watchdog2 | Hard reset | Asserted
2bf0 | Watchdog2 | Hard reset | Asserted
2bf5 | Watchdog2 | Hard reset | Asserted
```

`OS Load`는 부트 워치독이다. 펌웨어가 POST 중 걸어두고, 부팅 끝난 OS가 인계받거나 끄기를 기대한다. 걸린 부팅을 잡는 용도다. 여기 우분투는 둘 다 안 해서, POST 10분마다 타이머가 0이 되고 BMC가 시킨 대로 했다. 하드리셋. 고장이 아니다. 일을 했다. 절반짜리 약정의 절반만 있어서고, 없는 절반은 OS 쪽이었다.

BIOS 리셋 뒤 매 부팅 걸렸을 것이다. 안 보인 것은 그 창 대부분 기계에 닿지 않아서다(별건 — [네트워크 단절 기록](2026-09-12-offline-after-a-move-and-an-ssd.md)). 90초 부재는 밖에서 보면 아무것도 아니다.

BMC 시계가 8시간 어긋나서 SEL 타임스탬프와 저널이 산술 없이는 안 맞는다. 조사 중 시간을 먹었다. 고칠 일이다.

## 끄는 대신 인계받는다

끄는 것은 한 줄이고 사건이 닫힌다. 다른 선택은 워치독을 워치독 용도로 쓰는 것이고, 여기가 택했다. 이 기계는 headless에 닿는 길이 네트워크뿐이고, 막 20시간 닿지 않았다. 쐐기 박힌 커널은 걸어가지 않으면 회복 불가다.

IPMI 워치독 타이머는 하나라서, `SMS/OS` 용도로 드라이버가 잡으면 펌웨어 `OS Load` 용도를 밀어낸다. 인계가 끄기를 포함한다.

파일 셋, 전부 [`configs/watchdog/`](../configs/watchdog): 드라이버 로드(`/etc/modules-load.d/ipmi_watchdog.conf`), `action=reset`+panic 유예(`/etc/modprobe.d/ipmi_watchdog.conf`), `RuntimeWatchdogSec=120`(`/etc/systemd/system.conf.d/watchdog.conf`). PID 1이 `/dev/watchdog`을 열어 하드웨어 타임아웃을 박고 60초마다 쓰다듬는다.

120초지 가이드의 10이 아니다. 이 기계는 일부러 메모리 한계에서 돈다 — `llm.service` 상주 ~111 GB에 `OOMPolicy=continue` — 메모리 압박에 PID 1이 멈추는 것을 행으로 읽으면 안 된다. 진짜 쐐기 복구가 최대 2분이지 10초가 아닌 것은 20시간 옆에서 아무것도 아니다.

인계가 됐는지는 타이머에게 묻는다. 용도가 펌웨어의 `OS Load (0x43)`에서 바뀌어 있다.

```
Watchdog Timer Use:     SMS/OS (0x44)
Watchdog Timer Is:      Started/Running
Initial Countdown:      120.0 sec
```

이후 카운트다운을 봐서 쓰다듬음 확인(설정 믿고 말고).

```
17:29:31  120.0 sec
17:29:46  105.2 sec
17:30:01  120.0 sec
17:30:16  105.0 sec
```

90~120초 톱니에 밑으로 안 간다. 이후 1시간 넘게 up. 전에는 9분 수명 셋 연속이었다.

## 잡는 것과 못 잡는 것

잡는 것은 PID 1 스케줄이 멈추는 전부다. 커널 데드락, 리부트 안 하는 패닉, 드라이버 잠금, 메모리 완전 고갈, CPU soft lockup. BMC가 CPU 독립이라 호스트가 통째로 가도 된다.

못 잡는 것은 커널 멀쩡하고 쓸모없는 기계다. 걸린 서비스 하나, 유저스페이스 데드락, 주소 못 받는 NIC — 어제 이 기계의 실제 고장이다 — 전부 systemd가 만족하며 쓰다듬는다. 그걸 잡으려면 상위 조건 참일 때만 쓰다듬는 프로브가 필요한데, 그게 이유 없이 스스로 리부트하는 기계를 짓는 훨씬 쉬운 길이다. 여기서 안 한다.

## 인계는 설치된 게 아니라 수행됐을 뿐이었다

한 시간 뒤 실행 시스템 점검에서 위 절이 커버하는 줄 알았던 구멍이 나왔다.

```
$ journalctl -b _PID=1 | grep -i watchdog
$
```

없다. PID 1이 이번 부팅에 워치독 말을 한 적이 없다. `SMS/OS`로 잡힌 타이머는 그 오후 손으로 모듈 올리고 설정을 다시 읽힌 산물 전부였다. 설정 파일 셋은 디스크에 있어서 다음 부팅에 먹을 것. 아직 한 번도 안 거쳤다.

중요한 이유는 순서 문제다. 같은 날 `llm.service` 4부팅을 날린 것과 같은 종이다. PID 1이 시작할 때 `RuntimeWatchdogSec`을 읽고 `/dev/watchdog`을 연다. `/etc/modules-load.d`는 `systemd-modules-load.service`가 처리하는 유닛이고, 유닛은 PID 1 시작 뒤에 돈다. PID 1이 보는 순간 장치가 없으면 systemd는 재시도 안 한다. 워치독 없이 가고 기본 레벨에 로그도 안 남긴다. 펌웨어 타이머를 차지하는 자가 없고, POST 10분 뒤 BMC가 하드리셋한다. 매 부팅. 이 기록의 사건이 온전하게 복원된다.

`lsinitramfs`로 드라이버가 일찍 없음을 확인했다.

```
$ lsinitramfs /boot/initrd.img-$(uname -r) | grep -c ipmi_watchdog
0
```

그래서 `ipmi_si`·`ipmi_devintf`·`ipmi_watchdog`을 initramfs 모듈 목록에 넣고 재생성했다. 장치가 PID 1이 돌기도 전에 있다. 레이스 이기기에 안 의존하는 유일한 순서다.

## 보라는 말이 아니라 assert하는 체크

[`configs/watchdog/watchdog-armed-check`](../configs/watchdog/watchdog-armed-check)가 부팅에 돌아 타이머가 돌고 우리 것 아니면 0이 아니고 나간다. [`configs/netplan-iface-check`](../configs/netplan-iface-check)과 같은 모양, 같은 이유다. 실패가 조용해서 조용하지 않은 것이 필요하다.

오늘 오후 상태에 실패함을 확인했다. 기록 출력 그대로 먹여서:

```
FAIL: timer is still the firmware's OS Load use — the OS never claimed it; action would be 'Hard Reset (0x01)'
EXIT=1
```

지금 상태에 통과함을 확인했다.

```
watchdog held by the OS: use=SMS/OS (0x44) state=Started/Running action=Hard Reset (0x01) remaining=95.0 sec
EXIT=0
```

실패 케이스의 출력에 주목. 장치 있고 모듈 올라있고, 타이머는 펌웨어 것이다. 손으로 확인하면 그 둘을 보고 끝낼 사실들인데, 불충분하다. 체크가 큰소리로 말할 가치 있다.

## BMC 시계, 드리프트 아님

BMC가 호스트보다 8시간 빠르다. 정확히 8, 대략이 아니다.

```
host  09/12/2026 18:31:15
BMC   09/13/2026 02:31:15 AM KST
```

정확한 오프셋은 타임존 설정이지 빨리 가는 시계가 아니다. `ipmitool sel time set`은 안 먹는다(C 로케일에서도 `Specified time could not be parsed`). BMC 자체 네트워크/NTP 설정 페이지 일이다. 일단 둔다. SEL 타임스탬프는 최소 reliably 변환 가능하다.

## 아직 열림

- 콜드부팅 검증 자체. initramfs 변경·체크 유닛은 설치됐고 이후 부팅이 없다. 한 번 있기 전까지 위 걸림은 추론이지 측정이 아니다. 이 기록은 그렇게 말한다.
- BMC 기본 자격증명 그대로다.
