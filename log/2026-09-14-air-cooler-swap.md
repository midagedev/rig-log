# AIO가 나가고 공랭이 들어오다

**2026-09-14 저녁.** 빌드 때부터 5975WX를 식혀 온 NZXT Kraken AIO를 ARCTIC Freezer 4U-M 타워 공랭으로 교체했다(CPU_FAN 헤더, 모델명은 2026-09-15에 추가). 이유는 세 시간 전 thermal guard 로그에 있다. 17:00, 2.7 GHz 캡 threshold-sweep 창에서 냉각수 40도 후반에 `warn cpu=89C`를 두 번 썼다 — 받아들인 열을 더는 못 옮기는 루프였다. 교체는 사용자가 했다. 이후 측정은 아래다.

## 새 쿨러의 부하 성적

같은 클럭 캡(2.7 GHz, 부팅마다 `cpu-clockcap` 재적용), 같은 방. 온도는 k10temp `Tctl` 10초 샘플, 클럭은 64 스레드 `/proc/cpuinfo` MHz 평균이다.

| 부하 | Tctl | 평균 클럭 | 비고 |
|---|---:|---:|---|
| 부팅 후 idle | 30–33 °C | 1.8 GHz | |
| `yes` × 64, 40초 | 최고 33.6 °C | — | 가벼운 정수 부하 |
| 서빙 프로파일 500토큰 디코드 3동시 (2분) | 최고 39 °C | 2.3–2.5 GHz | 각 21 tok/s, GPU 56 / 49 °C |
| `stress-ng --cpu 64 --cpu-method matrixprod`, 240초 | 41 → 43 °C, 130초부터 평탄 | 내내 2.694 GHz | 스로틀 없음 |
| 스트레스 종료 20초 후 | 37 °C | | 60초에 35 °C |

같은 캡에서 기존 루프의 상한은 위 88–89 °C 경고였다. 오늘 먼저 올린 59 °C 냉각수 가드도 같은 것의 증상이었다. 4분 올코어 스트레스에 43도면 2.7 GHz 캡은 더는 열적 필요가 아니다 — 디코드가 메모리-bound라 캡이 공짜라서 둔다(WKS-22). 3.6 GHz 녹음 전용 모드는 이제 버티는지 여부가 아니라 얼마나 버티는지를 잰다.

## 계측의 변경점

`liquidctl`에 장치 없음. 공랭은 USB 펌프가 아니라 일반 PWM 팬이다. thermal guard는 CPU·GPU 온도로 계속 돈다(liquidctl 블록은 조건부). 다만 모든 창 스크립트의 `cool()` 게이트가 냉각수 온도를 읽어서 이제 매 arm마다 전체 타임아웃을 기다린다. 그 게이트는 `Tctl`로 옮긴다. 팬 RPM은 이 보드에서 Super I/O로 안 나온다 — `nct6798` 일곱 채널이 다섯 개 구동 중에도 0을 읽는다 — BMC 인밴드 IPMI(`ipmitool sdr type fan`)로 나온다. CPU_FAN 2200, SOC_FAN 2700, CHIPSET_FAN 2500 RPM, CPU_FAN lower-critical 1200 RPM. 상세와 이 보드를 커버 못하는 리눅스 드라이버 둘은 [`docs/wrx80e-bios-setup.md`](../docs/wrx80e-bios-setup.md)에 있다.

가는 길에 정정 하나. DIMM은 Samsung M378A4G43AB2-CWE, 2Rx8 UDIMM에 에러 정정 없음(`dmidecode`) — README가 주장한 ECC 모듈이 아니다. README에서 struck.
