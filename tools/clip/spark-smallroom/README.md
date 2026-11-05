# Spark 작은 방 영상

55초 설명 영상(1080×1080, 60 fps)의 소스다. 말하는 것은 하나다. 128 GB 워크스테이션에 DGX Spark 한 대를 붙이면 324 GB 모델(DeepSeek V4.1-Flash Q3_K_M)이 돈다. 같은 방에서 혼자 NVMe 로 페이징할 때보다 decode 1.8 배, prefill 3.6 배 빠르다. 출처는 2026-11-05 사이팅이다([log 11-05](../../../log/2026-11-05.md), 절 "smallroom").

영상 문구는 영어다(리포 밖으로 나가는 것). 이 문서와 [DESIGN.md](DESIGN.md)는 한국어다.

**지금 `data.json` 은 자리표시다** (`"placeholder": true`). 실제 테이프 둘이 아직 없어서 리포의 toktape 자산 둘로 경주를 그렸다. 그래서 모든 프레임에 `PLACEHOLDER TAPES` 도장이 대각선으로 찍힌다. 이 판은 내보내지 않는다.

## 흐름

| 초 | 장면 | 무엇을 보이나 |
|---|---|---|
| 0–5.0 | HOOK | 바이트만큼 높은 324 GB 기둥 옆에 128 GB 유리 상자가 선다. 상자가 기둥으로 가서 씌워지고, 넘치는 부분이 빗금으로 남는다. "It does not fit." |
| 4.95–25.1 | RACE | 두 창이 두 테이프를 각자의 스탬프대로 다시 쓴다. 왼쪽은 128 GB 단독(NVMe), 오른쪽은 + DGX Spark 다. 요청은 5.9 s 에 나가고 테이프 12 s 까지는 실시간이다. 그 뒤는 `speed` 배속이고 라벨이 붙는다. 24.2 s 에 재생이 멈춘다 |
| 25.0–29.4 | HOW 1 | 토큰이 40층을 지나고, 층마다 라우터가 384개 중 6개를 고른다 |
| 29.4–33.6 | HOW 2 | 384칸이 세 집(카드 VRAM, RAM, DGX Spark)으로 날아간다. 고른 6개에 선이 이어진다 |
| 33.6–37.8 | HOW 3 | q8_1 활성이 TCP 링크로 나가고 f32 행이 돌아온다. 호스트가 세 집의 행을 더한다(Σ). 이어서 층이 빠르게 넘어간다 |
| 37.8–41.8 | HOW 4 | 한 스텝 비용. 링크 ~7 ms 는 평평하고, NVMe 는 GB 가 모자랄수록 0.20–0.26 ms/GB 로 오른다 |
| 41.8–45.15 | HOW 5 | prefill. 단독은 페이징 대상 158 GB 를 프롬프트마다 한 번 읽어 17.7 s 다. Spark 는 제 몫을 스스로 계산해 3.6 배다 |
| 45.05–53.05 | NUMBERS | 1.8×, 3.6×, 표 세 행(128 단독, 128 + Spark, 256 참고), 조건 세 줄 |
| 52.9–55 | END | `bloomery`, open source · Rust + CUDA, github.com/midagedev/bloomery |

## 다시 찍기

```
cd tools/clip/spark-smallroom
python3.14 -m venv .venv && .venv/bin/pip install -r requirements.txt \
  && .venv/bin/python -m playwright install chromium-headless-shell
# (a) 실제 테이프로 data.json — 자리표시 도장이 빠진다
.venv/bin/python make_data.py ~/.cache/bloomery/specs/sparkclip/tapes/alone.tape ~/.cache/bloomery/specs/sparkclip/tapes/spark.tape
python3 -m http.server 8767 --bind 127.0.0.1 &      # film.html, data.json, fonts/ 를 서빙한다 (pid 를 잡아 둔다)
.venv/bin/python render.py audit                    # 숫자는 모두 data.json 에, 창의 글자는 제 테이프에. rc 0 이어야 한다
.venv/bin/python render.py probe                    # 2 8 15 22 30 38 48 54 s 스틸 → probe/sheet.png
# (b) 전체 렌더 — 한 프로세스(약 20분) 또는 청크 셋(약 8–10분, 시작을 8초씩 띄운다)
SUB=6 .venv/bin/python render.py full
SUB=6 F0=0 F1=1100 NO_ENCODE=1 .venv/bin/python render.py full   # 청크 하나; 1100–2200, 2200–3300 도 같은 꼴
# (c) 인코딩(청크로 찍었을 때) 과 튐 검사
.venv/bin/python render.py encode                   # sub/ → out/video.mp4, MUSIC=<mp3> MUSIC_AT=<s> 면 음악도
.venv/bin/python render.py pops                     # 한 프레임짜리 튐, 0건이어야 한다(rc 0)
```

자리표시 판은 이렇게 만들었다.

```
.venv/bin/python make_data.py --placeholder ../../../assets/qwen36-35b-a3b-q6k-4stream-ik-sweep-0.2.4.tape \
  ../../../assets/qwen36-35b-a3b-q6k-4stream-mistralrs-sweep-0.2.4.tape
```

Chromium 은 `--disable-gpu --disable-gpu-compositing` 로 띄운다. 캔버스는 소프트웨어로 그리고 Mac 의 GPU 는 열지 않는다. `film.html` 은 모든 프레임을 `window.seek(t)` 하나로 그린다. 같은 t 는 같은 프레임이다. 그레인만 초당 12번 바뀌는데(`floor((60t + 0.5) / 5)`), 계단이라 튐으로 세지 않는다.

### make_data.py 가 거부하는 것(rc 65)

- `requests[0].tokens` 가 빈 테이프. 다시 쓸 것이 없다.
- 스탬프 단위가 ns 도 µs 도 아닌 테이프. `tokens[0].t ÷ timings.ttft_ms` 로 판정한다. 자산 테이프는 ns 다. 단위가 틀리면 경주가 1000 배 틀린 속도로 돈다.
- 스탬프로 다시 잰 속도가 테이프의 `predicted_per_second` 와 10 % 넘게 다른 테이프. 원점이나 단위가 틀렸다는 뜻이다.
- 사용자 프롬프트가 서로 다른 두 테이프. 화면이 "Same prompt" 라고 말하기 때문이다. `--placeholder` 는 경고만 한다.
- 서로 다른 모델 파일의 두 테이프(실제 모드).
- 복사한 글꼴(Geist, Geist Mono, Pretendard)에 없는 글자. 없으면 브라우저가 시스템 글꼴로 조용히 바꾸거나 두부를 그린다.

`render.py audit` 은 `window.hangulCheck()` 로 토큰 글꼴 스택이 한글을 Pretendard 로 그리는지도 잰다. 너비가 다르면 거부한다.

### 경주의 시계

배속 `speed` 는 make_data.py 가 정해서 `data.json` 에 쓴다. 두 테이프가 모두 18.3 s(5.9 → 24.2 s) 안에 끝나면 1 배이고 라벨은 "real time" 하나다. 아니면 앞 12 s 는 실시간, 그 뒤는 `--max-speed`(기본 2, 스펙의 상한) 배속이다. 그래도 끝나지 않는 쪽은 24.2 s 에 쓰던 자리에서 멈추고 "still writing" 이라고 쓴다. 토큰이 나타나는 시각, 실시간 tok/s(그때까지의 토큰 수 − 1 ÷ 첫 토큰부터 지난 시간), 첫 토큰 시각, 끝난 시각은 모두 테이프 스탬프에서 나온다. 화면의 tok/s 는 토큰마다 미리 계산해 `data.json` 에 둔 값만 쓴다. 숫자가 올라가는 애니메이션은 쓰지 않는다. 중간값이 data.json 에 없는 숫자가 되기 때문이다.

창의 글자는 테이프 텍스트를 이어 붙인 문자열의 앞부분이다. 바이트 단위 토큰이 한글 한 글자를 둘로 나눠도 화면은 이어진 문자열을 그린다. 줄은 공백에서 바꾸고 `\n` 에서 끊는다. 생각(`r`) 토큰은 회색, 답 토큰은 흰색이다.

## 화면의 숫자와 출처

`make_data.py` 의 `SITTING`·`ROWS` 가 정본이다. 각 값 옆에 베낀 줄이 있다.

| 화면 | 값 | 출처 |
|---|---|---|
| 표 다섯 행(decode p50, step p50, pp P 512) | 19.35–19.61 · 51.0–51.7 · 28.8–29.2 등 | `log/2026-11-05.md:230-234` |
| 모델, 조건(A6000 stage, P 512, depth 512, n 96, 3 라운드) | | `log/2026-11-05.md:221` |
| 324 GB | 파일 크기 | bloomery `docs/cards/sparkroom-decode.card:2` |
| 페이징 158 GB, arena 64 GB, 너머 94 GB(160G 방 62 GB) | 플랜 줄 | `log/2026-11-05.md:224-225` |
| Spark 팔 RAM 97.7 GB, 노드 ~116 GB | 플랜 줄 | `log/2026-11-05.md:225-226` |
| 카드의 가장 뜨거운 2662 | 플랜 줄 | 스펙(리드가 옮긴 플랜 출력) |
| 링크 왕복 ~7 ms | | `log/2026-11-05.md:130`, `:85` |
| NVMe 0.20–0.26 ms/GB, 스텝 27 → 39 → 51(39.4, 51.2) | | `log/2026-11-05.md:236` |
| prefill 17.7 s, 1.8 배, 3.6 배 | | `log/2026-11-05.md:237`, `:216` |
| CPU 64 코어 그대로 | | `log/2026-11-05.md:246` |
| 경주의 토큰, 스탬프, ttft, tok/s | | 두 테이프 `requests[0]` |

**그림에서 측정값이 아닌 것.** 토큰이 어느 expert 를 고르는지는 해시로 정한 도식이다(세 집에 둘씩). 384칸을 세 집에 나누는 칸 수는 Spark 팔 플랜의 바이트 비(44.8 : 97.7 : 116)로 정했고 화면에 숫자로 쓰지 않는다. HOW 4 의 두 점 높이는 측정한 스텝에서 맞는 방의 27 ms 를 뺀 값(12.4, 24.2)이고, 띠는 측정한 두 기울기를 원점에서 94 GB 까지 그은 것이다. prefill 막대에서 Spark 쪽 길이는 17.7 s ÷ 3.6 이다.

## 쓰지 않은 것

- **expert 하나 19.3 MB, 토큰당 ~4.6 GB.** 스펙 기제 1번의 두 값은 화면에 없다. 같은 스펙의 플랜 줄과 맞지 않는다. 카드 44.8 GB ÷ 2662 = 16.8 MB 이고, 단독 팔 합계 258.3 GB(44.8 + 55.5 + 158) ÷ 15,360(40 × 384) 도 16.8 MB 다. rig-log `docs/bloomery/plan.md:93` 도 16.8 MB 로 계산한다. 어느 쪽이 맞는지 리드가 정하면 `make_data.py` 의 `SITTING` 에 넣고 HOW 1 캡션에 붙인다.
- 160 GB 방의 두 행. 표 카드는 스펙대로 128 단독, 128 + Spark, 256 참고의 세 행이다. 160 GB 방은 HOW 4 의 점 하나로만 나온다.
- 다른 엔진 이름. 영상에 없다.

## 파일

- `film.html`: 영상 본체. `data.json` 만 읽는다.
- `make_data.py`: 두 테이프와 사이팅 리터럴에서 `data.json` 을 만들고, 위의 경우를 거부한다.
- `data.json`: 지금은 자리표시 판이다.
- `render.py`: 스틸, 숫자 감사, 전체 렌더, 청크, 인코딩, 튐 검사.
- `requirements.txt`: 렌더 환경(release-039-v2 와 같다).
- `fonts/`: Geist, Geist Mono(SIL OFL 1.1, `OFL-Geist*.txt`), Pretendard Medium(SIL OFL 1.1, `OFL-Pretendard.txt`, 한글).

## 만든 방법

[howseen-ai/claude-motion-design](https://github.com/howseen-ai/claude-motion-design)의 방식(시간의 함수 하나로 그리는 HTML + Playwright + ffmpeg)을 따랐다. `render.py` 는 [residency](../residency/) 영상의 것을 고쳤고, 그 템플릿(MIT)의 저작권 고지는 파일 머리말에 있다. 팔레트와 글꼴은 [release-039-v2](../release-039-v2/DESIGN.md) 에서 가져왔다. 다만 3D 가 아니라 평면이고, 활자를 중심에 둔다. 코드와 문구는 Claude Code(Opus 5.5)가 썼고, 스틸 판정도 같은 라운드가 직접 했다.

## 결과물 (2026-11-05)

실제 테이프(`alone.tape` 20.87 tok/s · `spark.tape` 35.48 tok/s, 같은 한국어 프롬프트, `cache_prompt=false`)로 `make_data.py` →
`render.py audit`(528 문자열, 거부 0) → `probe`(2, 8, 15, 22, 30, 38, 40.5, 48, 54 s; opus vision 판정 세 라운드, 마지막 SHIP) →
`SUB=6 render.py full`(3,300 프레임, pops 0) → `MUSIC=music/644.mp3 MUSIC_AT=15.24 render.py encode`. 곡은 Mixkit 644
(residency·0.2.6 영상과 같은 트랙, `music/` 은 gitignore 대상): 곡 20.19 s 의 그루브가 레이스 시작 4.95 s 에 떨어진다.
`out/video-music.mp4`(CRF 14 마스터, 139 MB) 와 전달본 `out/video-music-crf20.mp4`(60 MB, pops 0) 둘 다 55.00 s, h264
1080×1080 60 fps + AAC. 전달본이 Drive 의 `bloomery-spark-smallroom-55s.mp4`.

vision 라운드가 고친 것: VRAM 박스 폭(250 px, RAM 258 px), 표의 `34.69, 35.04` → `34.69–35.04`, 레이스 판의 clip 윗변을
구분선 12 px 아래로 내리고 그 위에서 시작하는 줄은 그리지 않음(멈춘 Spark 판이 한 줄을 경계에 걸쳐 남겼다), 차트가 자리
잡은 40.5 s 를 기본 프로브에 추가.
