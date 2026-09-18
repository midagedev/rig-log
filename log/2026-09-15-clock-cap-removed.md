# 클럭 캡이 벗겨지다, 캡 없는 히어로 테이크

**2026-09-15 16:00.** 2026-09-13부터 이 기계에 걸려 있던 2.7 GHz CPU 캡(`configs/cpu-clockcap.service`, 매 부팅 재적용)과 부스트 잠금(`cpu-noboost.service`, 이미 비활성)을 더는 안 건다. 오늘 사용자 지시는 성능 제한이 더는 필요 없다는 것이다. 캡은 AIO 루프용 열 대책이었고, 루프는 갔다(2026-09-14). `cpu-clockcap.service`는 이제 비활성. 유닛 파일과 스크립트는 돌았던 기록으로 `configs/`에 남는다. `thermal-guard.service`는 남는다 — CPU·GPU 과온에 LLM 부하를 멈추는 안전망이지 제한이 아니다.

"캡 없음"의 뜻에 대한 사실 둘. `acpi-cpufreq`는 P-state 셋(3.6 / 2.7 / 1.8 GHz)을 내놓고 `scaling_max_freq` 3.6 초과를 거부해서, 인터페이스는 어느 쪽도 3.6 GHz로 읽힌다. `boost`가 1이면 코어가 위로 터보를 걸고, 아래 테이크 중 싱글 스레드 4.54 GHz가 목격됐다. 그래서 기존 히어로 레시피의 3.6 GHz "녹음 모드"는 하드 캡이었고, 오늘 실행은 아니다.

## 히어로 테이크, 캡 없음

toktape 세션이 서빙 V4.1 프로파일의 히어로급 테이크를 요청했다(`rig-log-v41-serve-hero64.sh`: DSpark draft block 3, reasoning budget 64, engramQ8 / tokembdBF16 타깃). 녹음기 README용이다. 웜업 500토큰 싱글스트림 5회: 20.5 / 21.7 / 20.7 / 21.7 / 27.1 tok/s. 다음 한 실행, `toktape --sessions 2 --think-budget 64 --for 30s`, [toktape](https://github.com/midagedev/toktape) v0.2.1-3-ga1eafc6으로 녹음. 클립과 카드는 테이프에서 toktape 쪽이 렌더링한다.

| 테이크 16:03:37, 2스트림, 30초 | |
|---|---|
| 디코드 | 스트림당 **12.8 tok/s**, 합계 25.7 (09-14 캡 히어로 3.6 GHz: 스트림당 11.2) |
| draft | 57% accept(331/576), 4.0토큰 verify 스텝 194회, 스텝당 RAM에서 ≈ 119 GB/s |
| 프리필 | 프롬프트 279토큰, TTFT p50 9.47초 |
| VRAM | 45.8 / 20.9 GiB, 호스트 RSS 197.5 GiB, 토큰당 major fault 0.6 |
| CPU, 프리필 창(11초) | 64 스레드 평균 2.7 GHz(2.1–3.6), 싱글 최대 4.54 |
| CPU, 디코드 창(20초) | 평균 3.44 GHz(3.24–3.65), 싱글 최대 4.30 |
| Tctl | 시작 61 °C, 내내 62–65 °C, 이후 61.6 °C. thermal guard 무음, 카드 `throttled: no`, `contended: no` |
| GPU | llama-server만. 시작 시 io pressure avg10 0.01 |

스트림당 숫자가 캡 히어로보다 14% 위다. 이 테이크는 후보 둘 — 클럭과 서빙 프로파일 — 을 분리하지 못한다. 프로파일이 09-14 뒤에 바뀌었다(engram Q8_0, draft용 bf16 토큰 임베딩, 재배분한 expert 배치). 09-13 측정이 2.7과 3.6 GHz 디코드 동일을 말하니 클럭 쪽이 덜 유력하고, 디코드 중 전스레드 평균이 어차피 3.6 이하에 있었다. 정직한 서술은 "캡 없음, 터보 engaged"지 "캡 없어서 빠름"이 아니다. 터보 켠 32스레드 디코드에 Tctl 65 °C는 새 쿨러 캡 부하의 +22 °C, 기존 루프 경고 지점의 −24 °C다.

증인 파일: 테이프와 카드, `runs.tsv`, 2초 클럭/Tctl CSV는 toktape 세션 스크래치로 갔다. 실행 스크립트는 기계의 `hero-ready3.sh`, `hero-take3.sh`, `hero-clock3.sh`다.
