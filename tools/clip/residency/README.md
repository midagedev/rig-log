# 적응형 residency 영상

2026-09-30에 만든 42초 설명 영상(1080×1080, 60 fps)의 소스다. [오프로딩 대역폭 영상](../offload-bandwidth/)의 후속편이다. bloomery의 적응형 expert residency를 보인다. GPU가 층마다 384개 중 70개의 expert만 들고 있을 때 엔진이 자기 라우팅을 세어 그 자리를 어떻게 바꾸는지, 프롬프트가 고른 expert가 뒤따르는 디코드에 어떻게 남는지를 한 층 무대로 그린다. 완성본은 [`assets/residency-explainer-v5.mp4`](../../../assets/residency-explainer-v5.mp4), 경위는 [log 09-30](../../../log/2026-09-30.md#residency-clip).

영상 문구는 영어다(리포 밖으로 나가는 것). 이 문서는 한국어다.

## 흐름

| 초 | 장면 | 무엇을 보이나 |
|---|---|---|
| 0–4.6 | 40층 한눈에 | 토큰이 층을 차례로 지나고 출력이 써진다. 7층으로 줌인 |
| 4.6–11.6 | fixed seats | 적재 때 정한 좌석(id 앞쪽 69개 + 예비 1). 호출 대부분이 어두운 방(호스트 RAM)에 떨어진다 |
| 11.6–21.6 | it watches itself | 엔진이 호출을 센다. 첫 교체를 슬로모션과 스포트라이트로: 가장 뜨거운 호스트 expert가 뒤에서 복사돼 올라오고, 패스 경계에서 가장 찬 좌석과 바뀐다 |
| 21.6–30.4 | the prompt picks | 되감기. 같은 시작에서 512토큰 프롬프트가 지나며 층당 12개를 한꺼번에 옮긴다(번호 1–12). 그 자리가 디코드에 남는다 |
| 30.4–37 | the race | 세 팔이 같은 출력을 각자의 속도로 쓴다(4배 느리게) |
| 37–42 | 끝 | "run it again → same text." |

## 다시 찍기

```
cd tools/clip/residency
python3 make_data.py pack <bloomery specs/release/resvideo/pack>   # 시팅 기록 → data.json
python3 -m http.server 8766 --bind 127.0.0.1 &                     # film.html, data.json, fonts/를 서빙한다
.venv/bin/python render.py probe 5 13 16 25 36                      # 스틸 몇 장 → probe/sheet.png
SUB=6 MUSIC=<644.mp3> MUSIC_AT=7 .venv/bin/python render.py full    # 한 프로세스로 전부
.venv/bin/python render.py pops                                     # 한 프레임짜리 튐 검사, 0건이어야 한다
```

병렬로 찍을 때는 청크를 넷 이하로, 10초씩 띄워서 연다. 여섯을 동시에 열었다가 넷이 페이지 로드 시간 초과로 죽은 적이 있다. 청크마다 `SUB=6 F0=<시작> F1=<끝> NO_ENCODE=1 render.py full`, 끝나면 `render.py encode`다. venv와 pid 기다리기는 [오프로딩 영상 README](../offload-bandwidth/README.md#다시-찍기)와 같다.

`film.html`은 모든 프레임을 `window.seek(t)` 하나로 그린다. 붓 획, 먹 번짐, 손글씨는 해시 노이즈로 흔들리고 흔들림은 초당 12번 바뀐다(`BF = floor((60t + 0.5) / 5)`). 바뀌는 순간이 프레임 사이에 떨어지므로 같은 t는 같은 프레임이다. `render.py pops`는 계단처럼 바뀌는 흔들림을 튐으로 치지 않고, 앞뒤 프레임이 서로 같은데 가운데만 다를 때만 튐으로 센다. `make_data.py placeholder <toktape>`는 시팅 전의 자리표시 데이터를 만든다. 그때는 모든 프레임에 빨간 PLACEHOLDER 도장이 찍힌다.

## 화면의 숫자와 출처

전부 bloomery 시팅 `resvideo-v41`(2026-09-30 08:53–09:01 UTC, 박스, A6000 한 장, 배치 (a), V4.1-Flash 공개 Q3_K_M, greedy)의 prose P 512 팔이다. 트리는 bloomery 8e13720e이고, 같은 내용이 main 4e77f89b로 들어갔다. residency 기본값은 main `2c49dd6a`다.

| 화면 | 값 | 기록 |
|---|---|---|
| 층당 좌석 70, 고정 40 | pinned 40 + churn 1148/40 + 예비 1 | `residency-host.txt` |
| 스텝별 "calls served by the GPU" | 1 − host_slots / 240 (40층 × 6) | `<arm>-stats-p512-r1.tsv` |
| 큰 % | 최근 8스텝 평균 | 위와 같음 |
| 교체 시점과 개수 | 4패스마다 24개 결정, 4패스 뒤 반영 | `<arm>-p512-r2.residency.txt`의 `made`, `landed` |
| 프롬프트 교체 층당 12 | admitted 480 ÷ 40 | `call stream end` |
| 디코드 tok/s 29.48 / 35.70 / 43.86 | 96스텝 | 시팅 보고 표 |
| 프롬프트 자체 +1.8 % | pp4096 두 바퀴 평균 373.64 ÷ 367.19 | `time prompt` 행 |
| 경주의 토큰 리듬 | 스텝별 wall ms | `<arm>-p512-r2.tsv` |
| 토큰 | 실제 생성 결과, 세 팔 95토큰이 모두 같다 | 위와 같음 |

세 팔은 같은 바이너리다. `fixed seats`는 `BLOOMERY_RESIDENCY=off`, `watches itself`는 `mid-p40-s1` + `BLOOMERY_HOSTSTREAM=off`, `prompt picks`는 `mid-p40-s1` + 스트리밍 켬(기본값)이다. 프롬프트는 bloomery `corpus-prose.ids`의 앞 512개다. 내용은 llama.cpp 문서(MIT)이고 이어쓰기라서 출력이 모델 URL 조각이다. NVMe에서 채운 희생자는 0이다(stats 팔 모든 스텝 majflt 0).

**그림에서 측정값이 아닌 것.** 한 층 안에서 어느 expert가 불리는지, 어느 expert가 뜨거운지, 한 층에 교체가 몇 개 떨어지는지는 도식이다. 기록은 모델 전체의 스텝별 합계(host_slots, made, landed)뿐이다. 그래서 스텝마다 카드에 떨어지는 호출 수를 측정한 적중률에 맞추고(오차 확산), 어느 expert인지는 고정된 인기도 분포와 그때까지의 호출 수로 고른다. 7층에 떨어지는 교체 수는 모델 전체 개수의 1/40을 누적해 정하고, 첫 교체(15스텝에 반영되는 묶음)만 슬로모션으로 보인다. 꼬리표가 호출 횟수 대신 "called a lot"과 "barely called"라고 쓰는 이유다.

## 쓰지 않은 것

- 같은 날 찍은 서버 테이프(RateLimiter 프롬프트, toktape) 셋은 쓰지 않았다. 그 stream 팔의 초반 이점이 prose 시팅보다 작았고(첫 50토큰 31.6 대 rule 27.8), 이유가 아직 열린 질문이다. 한 영상은 한 출처에서만 그린다.
- 09-28 Mac 트레이스 재생 값(18.7 → 39.9 → 77.8 %)은 규칙과 창이 달라 쓰지 않는다.
- 다른 엔진 이름은 영상에 없다. 소스로 확인한 비교는 exllamav3 하나다(생성과 생성 사이에만 sweep).
- "출력이 그대로"라고 쓰지 않는다. 카드와 호스트는 같은 expert에 다른 비트를 낸다. 영상이 말하는 것은 결정성이다. 교체가 고정된 패스 경계에서만 반영되니 같은 이력은 같은 출력을 낸다. 이 창에서는 세 팔의 출력도 같았다.

## 파일

- `film.html`: 영상 본체. `data.json`만 읽는다.
- `make_data.py`: 시팅 묶음(`pack`) 또는 자리표시(`placeholder`)에서 `data.json`을 만든다.
- `data.json`: 이 영상이 쓴 실측 데이터.
- `render.py`: 스틸, 전체 렌더, 청크, 인코딩(`MUSIC`, `MUSIC_AT`로 음악 깔기), 튐 검사.
- `fonts/`: Caveat Brush, Gochi Hand(SIL OFL 1.1, `OFL-*.txt`).

## 만든 방법

붓 획, 번짐, 흔들림은 [@shfred0의 클립](https://x.com/shfred0/status/2102495989194236158)의 먹 느낌을 목표로 이 파일에서 새로 짰다. 렌더러 `render.py`는 [howseen-ai/claude-motion-design](https://github.com/howseen-ai/claude-motion-design) 템플릿(MIT, 저작권 고지는 파일 머리말)을 고친 것이다. 음악은 [Mixkit](https://mixkit.co/free-stock-music/) 644번 트랙(Mixkit 라이선스, 영상·SNS 사용 가능, 표기 불요)이다. 곡은 Gemini가 후보 23곡을 듣고 고른 여섯 중 사용자가 골랐다. 파일은 리포에 넣지 않았다. 스틸 판정은 매번 새 opus 서브에이전트가 했고, 실측 시팅은 bloomery 세션이 돌렸다. 코드와 문구는 Claude Code(Opus 5.5)가 썼다.

만들며 버린 판도 있다. 40층 세계를 카메라로 훑는 판(draft2–3)은 구조가 정확했지만 한 번에 보여 주는 것이 너무 많았다. 그래서 첫 판의 한 층 무대로 돌아가 인트로에서만 40층을 보이기로 했다.
