# bloomery 0.3.6 릴리스 영상

bloomery 0.3.6 릴리스 영상의 소스다. 1080×1080, 60 fps이고, 길이는 `data.json`이 정한다. 지금은 95.63초, 204박이다. 상한은 END까지 합쳐 100초다.

이야기는 하나다. 일반 생성 모델 Qwen3.6-35B-A3B가 RTX A6000 한 장 위의 bloomery-serve에서 SystemOne 엔드포인트(`POST /v1/systemone`)의 결정 요청에 답한다. 학습된 결정 모델(Clef-Flash)이 받는 것과 같은 스키마다.
- 앞 절반(Part A, 0–40.31초)은 원리를 보여 준다. 보통의 구조화 출력(plain structured output)은 토큰마다 엔진을 한 번 부른다. schemajump는 스키마의 고정 문자열을 고르는 자리의 호출에 실어 보내고, 고르는 자리에서만 모델의 점수를 읽는다.
- 뒤 절반(Part B, 40.31–95.63초)은 sitting 3과 V4.1 sitting에서 실제로 돌린 요청과 숫자다.

화면 문법은 "Instrument"다. 검은 바탕, 흰색과 회색 셋을 쓰고, 신호색(주황)은 모델이 고른 것에만 칠한다. 글꼴은 Martian Mono, 한글은 Noto Sans KR 굵은 체다. 영상 문구는 영어, 이 문서는 한국어다.

결과물: `out/video-music.mp4`(gitignore 대상, Drive에 올린다).

## 흐름

박 번호는 영상 0초를 0박으로 센다. 곡 `instrument-s1004`의 박 격자는 128.00 BPM, 한 박 0.46876초다. 영상은 곡의 75박에서 시작한다.

| 초 | 박 | 장면 | 무엇이 움직이나 |
|---|---|---|---|
| 0.00–4.21 | 0–9 | TITLE | 검은 화면. 첫 강박에 `bloomery`, `0.3.6`, 주장 두 줄이 앉는다 |
| 4.21–10.77 | 9–23 | THE REQUEST | `POST /v1/systemone`과 route-01의 요청 글. 2박에 질문 셋과 선택지, `served by Qwen3.6-35B-A3B` |
| 10.77–14.05 | 23–30 | ONE TOKEN, ONE TRIP | 40층을 토큰 하나가 16분음표마다 다섯 층씩 내려간다. `one engine call: all 40 layers` |
| 14.05–22.49 | 30–48 | PLAIN STRUCTURED OUTPUT | 답을 질문 하나에 한 줄씩 쓴다. 토큰은 16분음표에 하나씩, 저마다 상자 안에, 저마다의 막대 위에 앉는다(고르는 호출의 막대는 신호색). 카운터가 20까지 오른다. 그다음 고정 문자열에 조명이 가고 `the schema already says this` |
| 22.49–33.74 | 48–72 | SCHEMAJUMP | 되감기(곡의 쉼 마디). P 타격(영상 52박)부터 한 박에 한 걸음, 엔진이 도는 순서대로 그린다. 앞 고정 4토큰은 프롬프트 호출에 실리고(회색 막대), 그 점수가 `technical`을 고른다. 호출 1이 `technical`과 그 뒤 고정 구간을 넣고(막대 하나, 고른 부분만 신호색) `2`를 고른다. 호출 2도 같은 식으로 `true`를 고른다. 끝 2토큰은 호출 없이 쓴다(테두리 막대). 줄바꿈에 잘린 막대는 여백까지 열어 그린다. 카운터는 2에서 멈춘다. 범례 `one call` / `the model picks` / `in the prompt call` / `no call`, 끝에 `the same text as` / `plain structured output` |
| 33.74–40.31 | 72–86 | A DECISION | 답의 JSON, urgency의 선택지(`Can wait`, `This week`, `Today`, 본문의 legend 순서)와 고른 값의 테두리, `Today 99%`(route-01의 `/v1/systemone` 본문), 라벨 `probability among the options` |
| 40.31–47.34 / –52.96 | 86–101 / –113 | REQUESTS ×2 | tool-03(영어), ko-06(한국어). 요청 글, 2박에 질문마다 10×10 격자가 고른 값의 몫까지 찬다(고른 값 흰색, 두 번째 회색, 나머지 어둡게). 3박에 고른 낱말이 신호색과 그 백분율로 선다. 바닥글 `POST /v1/systemone` / `answer + probabilities` |
| 52.96–55.77 | 113–119 | SAME ANSWERS | `27/27`, 요청 하나에 칸 하나 |
| 55.77–63.74 | 119–136 | HARD QUESTIONS | 많이 맞힌 모델부터 `맞힌 수/29`와 29칸의 자: DeepSeek-V4.1-Flash 27/29, Clef-Flash 21/29, Qwen3.6-35B-A3B 18/29. 바닥글 `V4.1-Flash: Q3_K_M` / `on RTX A6000 + RTX 3090` / `29 questions we wrote, our labels`. V4.1의 시간은 없다 |
| 63.74–82.49 | 136–176 | 예시 셋 | ko-hard-08(접수2: V4.1만 `울산`으로 맞히고 둘은 `부산`), ko-hard-12(강), hard-03(report_1). 한 문항에 한 장면, 질문과 신호색 `our label: <정답>`, 모델마다 같은 크기의 칩에 고른 값과 ✓/✗(백분율 없음) |
| 82.49–91.87 | 176–196 | SHORT REQUESTS | `UNDER 1,000 TOKENS`. Clef-Flash 127.2 ms, Qwen3.6 + schemajump 99.9 ms, Qwen3.6 + plain structured output 169.1 ms를 칸의 자로 그리고 끝에 p50을 쓴다 |
| 91.87–95.62 | 196–204 | END | E 타격이 컷에 온다. `bloomery`, `0.3.6`, 2박에 주소. 3.75초, 마지막 두 박에 페이드 |

LONG REQUESTS는 기본으로 뺐다(`b.long`, 아래 길이 손잡이). SOLAR 장면은 `inputs.json`의 `solar`가 차야 SHORT와 END 사이에 들어가고, "and …" 줄도 `and_line`이 차야 선다.

### 원리 절반이 말하는 것과 말하지 않는 것

- 막대 하나가 엔진 호출 하나다. 두 방식 모두 그렇다. 막대는 장면 끝까지 남아서 어느 정지 화면에서나 셀 수 있다. plain은 20개, schemajump는 프롬프트 호출 뒤 2개다.
- schemajump의 순서는 route-01의 jump 행(`lead` 4, `decisions` 3, `spans` 2, `span_ids` 14, `tail` 2)에서 오고, `make_data_a.py`가 토큰 조각과 이름으로 맞춰 본다. 엔진의 규칙은 bloomery `crates/serve/src/genloop.rs:177-200`(struct Jump)이다. 고르는 자리 하나의 토큰과 그 뒤 고정 구간이 호출 하나로 들어가고(`engine.rs:236`), 앞 고정 구간은 프롬프트 호출에 실리며, 끝 구간은 호출이 없다.
- 프롬프트는 "한 번의 프롬프트 호출"이다. 엔진은 그 안을 ubatch로 나눠 돈다. 그래서 화면에 "one pass"라고 쓰지 않았다.
- ONE TOKEN, ONE TRIP의 켜진 전문가(256개 중 8개와 공유 전문가 하나)는 원리의 그림이다. 시드로 고른 자리(`route(0, 20)`)이고 잰 라우팅이 아니라서, 켜진 칸에 숫자를 쓰지 않았다. 40층은 bloomery `crates/gpu-gates/src/q36_fixture.rs:439`, 256개 중 top-8과 공유 하나는 `crates/gpu-gates/src/bin/gate_qwen35moe_moe.rs:2-4`다.
- 16분음표에 토큰 하나, 한 박에 호출 하나는 설명을 위한 느린 그림이고, 시간을 주장하지 않는다. 시간은 SHORT의 p50에만 있다.
- schemajump의 짧은 고정 구간은 전문가를 거의 나눠 쓰지 않는다. 줄이는 것은 호출 수다. 전문가 하나를 여러 토큰이 나눠 쓰는 것은 긴 프롬프트의 일이고, 그 말은 화면에 없다.

## 숫자와 출처

화면의 숫자는 모두 `make_data.py`(그리고 Part A는 `make_data_a.py`, Part B는 `make_data_b.py`)가 행과 본문에서 계산해 `data.json`에 쓴다. 손으로 친 숫자는 없다. `film.html`은 `data.json`에 없는 문자열을 그리면 오류를 낸다.

- 행: `sources/sit3-1020/`. 2026-10-20 sitting 3의 원본 행과 본문으로, 박스의 sitting 디렉터리에서 복사했다(로그는 넣지 않았다). RTX A6000, Qwen3.6-35B-A3B Q4_K_M 대 Clef-Flash Q5_K_M, 짧은 요청 4라운드, 긴 요청 3라운드, 세트는 en, ko, hard다.
  - `window1/rows.json`은 Clef-Flash(`A`)와 jump 팔, `window2/rows.json`은 Clef-Flash와 step 팔이다(같은 바이너리, 레버 off). 한 번에 한 요청, 클라이언트 벽시계(POST부터 마지막 바이트까지)를 잰다.
  - `bodies/`는 `A`(window 1), `jump`, `step`, 그리고 `jump-systemone`, `step-systemone`이다. 뒤의 둘은 시간을 재지 않은 `/v1/systemone` 응답으로, 선택지마다의 확률이 들어 있다.
  - 이 sitting의 팔 이름은 접두어가 없다(`A`, `jump`, `step`). `make_data_b.py`의 `ARMS`와 `make_data.py`의 `HARD_ARMS`가 `jump`/`step`을 Qwen3.6-35B-A3B의 두 팔로, `BODY_DIRS`가 본문 디렉터리를 잇는다. 모르는 이름은 이름을 대고 멈춘다.
- 러너는 bloomery `tools/ref/sj-vs-clef.sh`, 요청은 `tools/ref/clef/sjcmp.py`가 보냈다.

| 화면 | 값 | 어디서 |
|---|---|---|
| `127.2 ms`, `99.9 ms`, `169.1 ms` | Clef-Flash 127.22(n 200), jump 99.90(n 100), step 169.10 ms(n 100) | short 행의 `wall_ms` 중앙값 |
| SHORT의 판정 줄 | jump의 short p50 < Clef-Flash의 p50이라 `faster` | `inputs.json`의 `verdict`가 비어 있을 때의 규칙 |
| `UNDER 1,000 TOKENS` | short의 최대 프롬프트 598토큰 | Clef 행의 `prompt_n` |
| `27/27` | jump 팔과 step 팔의 답(요청마다 첫 센 라운드의 `tops`)이 같은 요청 수 | 두 창의 en, ko 행 |
| `27/29`, `21/29`, `18/29` | hard 세트 29문항에서 우리 정답 라벨과 같은 수. V4.1-Flash는 jump와 step 모두 27, Qwen3.6은 둘 다 18. V4.1의 행은 `sources/v41h-1020/`(2026-10-20, RTX 3090 + RTX A6000, DeepSeek-V4.1-Flash-1017 Q3_K_M, 12요청 5라운드, jump와 step의 답 12/12 같음) | `make_data.py`의 `hard()`, bloomery `tools/ref/clef/suite-hard.jsonl`과 `suite-hard.gold.jsonl`(md5 `cf8d793d…`) |
| `20`과 `2`(route-01의 호출) | step 20, jump 2 | 행의 `calls`에서 `next_calls + prefill_calls + next_after_calls`(`inputs.json`의 `calls_sum`). 프롬프트 호출은 두 팔 모두 빼고 센다 |
| 백분율(`Today 99%`, `web_search 100%`, `refund 93%`, `yes 73%`) | 고른 값의 확률 × 100, 반올림 | 저장한 `/v1/systemone` 본문의 `answers.<질문>.probabilities`. 예/아니오 답의 `noul`은 P(yes)다. 격자는 정확히 그만큼 칸을 채운다 |
| 예시의 ✓/✗ | 모델마다 고른 값과 우리 정답 라벨 | hard 행의 `tops`, gold |

- 본문이 고른 값은 jump 팔이 기록한 답(행의 `tops`, 첫 센 라운드)과 같아야 한다. 다르면 `make_data_b.py`가 이름을 대고 멈춘다.
- 예시는 모델끼리 답이 갈린 문항 중에서 고른다. 순서는 Clef-Flash가 맞히고 Qwen3.6이 틀린 것 하나, 그 반대 하나, 그다음 다른 갈림이다. 한 요청은 두 번 나오지 않고, 같은 등급 안에서는 읽기 빠른 것을 먼저 고른다. 본문이 고른 값이 채점한 행과 같은 문항만 쓴다(ko-hard-07은 `/v1/systemone` 본문이 132, 채팅 답이 1332라 뺐다).
- 화면에 없는 숫자도 `data.json`의 `measured`에 남는다. step 대비 jump는 −40.95 %(라운드별 짝지은 차이)이고, 긴 요청은 jump 850.66 ms, Clef-Flash 1,741.33 ms이며 그 차이의 92.4 %는 프롬프트 읽기다. jump 팔의 결정 31개 중 26개가 공식 BF16 답과 같다(`sources/reference-tops.json`). LONG 장면을 켜면 이 값들이 화면에 나온다.
- 글자 문자열은 `make_data.py`의 `CITED`가 출처의 줄과 대조한다(낱말이 그 줄에 있는지, 아니면 이유를 적었는지). 문자열마다 `data.json`의 `sources`에 출처가 있다.

## 읽는 시간

규칙은 0.3.4와 같다. 초당 4단어에 숫자 하나마다 1초를 더하고, 최소 2.5초다. 백분율(`96%`)은 낱말이 아니라 숫자로 센다(`make_data.py`의 `QTY`). 시계는 묶음의 마지막 요소가 자리 잡은 순간부터 잰다. 앞 장면에서 같은 자리에 그대로 선 문자열은 다시 세지 않는다. 그래서 두 번째 예시부터는 정답 라벨과 모델 이름을 다시 읽지 않는다. 한국어는 공백으로 나눈 어절을 낱말로 센다.

`make_data.py`가 장마다 읽기 시간과 머무름을 표로 찍는다. 읽는 동안 움직이는 글자가 없는지는 `render.py check`의 hold 검사가 모든 프레임과 하위 프레임에서 본다.

## 길이 손잡이

`inputs.json`의 `b`에서 바꾸고, `make_data.py`를 다시 돌린 뒤 렌더한다. sitting 3에서의 영상 길이:

| 손잡이 | 기본 | 영상 |
|---|---|---|
| (기본) | 요청 2, 예시 3, long 끔 | 95.63초(204박) |
| `requests`, `examples`, `long` | 2, 3, `"off"` | 한 칸마다 마디 단위로 늘거나 준다. V4.1 행을 넣은 뒤로는 다시 재지 않았다(`make_data.py`가 길이를 찍는다) |

`requests`는 `make_data_b.py`의 REQUESTS(tool-03, ko-06, invoice-02, ko-review-04, ko-mail-06) 중 앞의 n개를 보인다. `long`을 `"line"`으로 하면 SHORT에 `long prompts: the gap is almost all prompt reading` 한 줄이, `"shot"`으로 하면 긴 요청 둘의 경주 장면이 들어간다. 손잡이 한 칸은 영상을 마디 단위(4박, 1.875초) 이상으로 옮긴다.

## 다시 찍기 (V4.1 행, Solar)

리드가 고치는 곳은 `inputs.json` 하나다.

| 필드 | 지금 | 넣을 것 |
|---|---|---|
| `rows`, `b.rows`, `b.bodies`, `hard.rows` | `sources/sit3-1020` | 새 sitting의 행과 본문 디렉터리. 박스의 결과를 `sources/<이름>/`으로 복사한다 |
| `hard.arm_map` | 없음(`HARD_ARMS`) | V4.1 행의 팔 이름이 `HARD_ARMS`에 없으면 여기에 `{"<팔>": ["DeepSeek-V4.1-Flash", "jump"]}` 식으로 적는다 |
| `hard.suite`, `hard.gold` | rel036 작업 트리의 파일 | 태그 뒤에는 bloomery main의 `tools/ref/clef/suite-hard(.gold).jsonl`(같은 바이트) |
| `sitting` | `sitting 3, 2026-10-20, RTX A6000` | 새 sitting의 이름(화면에는 없고 `data.json`의 `notes`에 남는다) |
| `verdict` | `""`(행에서 정한다) | `"close"`나 `"faster"`로 강제할 수 있다. 행과 맞지 않는 `"faster"`는 거부된다 |
| `solar` | 비어 있음 | `decode`, `prefill`, `cond`가 다 차야 장면이 생긴다 |
| `and_line` | `""` | 비어 있으면 그리지 않는다 |
| `draft` | `true` | 마지막 숫자를 넣으면 `false` |

```
cd tools/clip/release-036
ln -s ../release-030/.venv .venv        # playwright 1.63.0, numpy, fonttools (없을 때만)
scp -r <box>:<sitting 디렉터리>/window1 <box>:<sitting 디렉터리>/window2 sources/<이름>/   # 행과 본문 복사
.venv/bin/python make_data.py           # 숫자, 문자열, 타임라인을 다시 계산해 data.json을 쓴다. 표를 찍는다
python3 -m http.server 8799 --bind 127.0.0.1 &   # pid를 적어 두고 그 pid만 끈다
PROBE_TAG=main .venv/bin/python render.py probe <초> …   # probe/main/sheet.png
rsync -a film.html parta.js partb.js data.json render.py beats.py splice.py fonts box/{serve,drive,post,run}.sh <box>:/root/clip036-render/
ssh <box> 'cd /root/clip036-render || exit 1; nohup bash run.sh > logs/run.out 2>&1 < /dev/null & echo $! > pids/run.pid'
ssh <box> 'cd /root/clip036-render; p=$(cat pids/run.pid); while kill -0 $p 2>/dev/null; do sleep 5; done; cat logs/run.log'   # 그 pid만 기다린다
ssh <box> 'kill $(cat /root/clip036-render/pids/http.pid)'   # serve.sh가 띄운 서버, 적어 둔 pid로만 끈다
rsync -a <box>:/root/clip036-render/out/video-music.mp4 out/
```

- `cd … && nohup … &`는 목록 전체를 서브셸로 띄워 ssh가 끝까지 붙잡히고 `$!`가 서브셸이 된다. 위처럼 `;`로 쓴다.
- 한글 문구가 바뀌면 `probe/kr_subset.py <NotoSansKR[wght].ttf> fonts/NotoSansKR-subset.ttf data.json`으로 부분집합 글꼴을 다시 만든다(google/fonts `ofl/notosanskr`).
- `make_data.py`는 장면이 곡의 앵커에 맞지 않으면 이름을 대고 멈춘다(rc 5). 그때는 문구를 줄이거나 손잡이를 바꾼다.
- 박스 렌더 한 번은 4분 18초였다(sitting 3, 렌더 5). Mac의 `make_data.py`와 프로브, 오가는 복사까지 15분 안이다.
- `b`가 `probe/bfx/`(`probe/bfx.py`가 만든 가짜 행과 본문)를 가리키면 모든 프레임에 FIXTURE 도장이 찍힌다.

### 박스에서

환경은 `/root/clip036-render/` 안에만 있다. `box/setup.sh`가 `/root/clip034-render/`의 venv(시스템 Python 3.12 위의 playwright 1.63.0, numpy, fonttools, pillow)와 `ms-playwright/`(chromium 1243과 headless shell)를 읽기만 해서 복사했다. 네트워크는 쓰지 않았고, 034의 디렉터리는 고치지 않았다. `lease-probe.sh`는 bloomery main의 `tools/ref/lease-probe.sh`다.

```
ssh <box> 'mkdir -p /root/clip036-render/pids /root/clip036-render/logs'
rsync -a box/setup.sh ../../../../bloomery/tools/ref/lease-probe.sh <box>:/root/clip036-render/
ssh <box> 'cd /root/clip036-render || exit 1; nohup bash setup.sh > logs/setup.log 2>&1 < /dev/null & echo $! > pids/setup.pid'
```

- `run.sh`는 serve, `drive.sh check 16`, `drive.sh full 16`, `post.sh`를 차례로 돌리고 각 rc를 `logs/run.log`에 적는다. 하나가 실패하면 멈춘다.
- `drive.sh check|full N`는 프레임 범위를 N개로 나눠 `render.py`를 띄운다. 모두 `nice -n 19`, CPU만(`--disable-gpu`)이다. 청크마다 `$!`를 `pids/<mode>-<i>.pid`에 적고 `kill -0`으로만 기다린다.
- 타이밍 lease와 hold가 모두 내려가 있을 때만 시작한다(`lease_free`, `lease_holds_up`). 도중에 하나가 올라오면 청크들을 SIGSTOP으로 세웠다가 내려가면 SIGCONT로 잇는다. 카드는 쓰지 않는다.

## 음악

`music/clip036/instrument-s1004.mp3`(gitignore 대상)는 이 영상을 위해 박스의 RTX 3090에서 [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5)로 만들었다(MIT, 모델 카드가 생성물의 상업적 사용을 허용한다).
- 설정: XL-sft DiT, 1.7B 5 Hz LM, 50스텝, guidance 7.0, shift 1.0, 100초, 시드 1004, 프롬프트 `instrument`(128 BPM, `musicgen/prompts.json`).
- 4B LM은 3090에서 초기화 중 메모리가 모자랐다(23.6 GiB 중 23.5). 그래서 1.7B LM과 `PYTORCH_ALLOC_CONF=expandable_segments:True`로 돌렸다.
- 프롬프트 셋(instrument 128, pulse 124, break 136 BPM)에 시드 넷씩, 12곡을 538초에 만들었다. 최대 14.8 GiB를 썼고, Xid 수는 전후 같았다.
- `musicgen/run.sh`는 3090의 게이트 락(`flock`)을 잡고 돌며, 전후 `dmesg`의 Xid 수가 늘면 70으로 끝난다. `musicgen/gen.py`의 `--card`가 카드 이름을 확인한다.
- 잰 값(`beats.json`, `beats.py`): 127.997 BPM, 첫 박 0.0185초, 마디는 3박부터 넷씩, 드롭은 31박(14.55초, +4.0 dB). 킥이 격자에 36/40(중앙값 4.4 ms).
- 타격: P(곡 127박)는 되감기 뒤 프롬프트 호출의 고름(영상 52박), L(곡 191박)은 SHORT의 컷(영상 172박), E(곡 203박)는 END의 컷(영상 192박)에 온다. 앵커가 남긴 박은 Part B의 장면에 돌아가고, SAME ANSWERS가 마지막으로 받는다.
- 이어 붙이기: 곡 147박부터의 고른 그루브(`range(147, 203, 4)`에서 187과 191을 뺀 것)를 쓴다. sitting 3에서 이음매 다섯, 가장 큰 단차는 곡 자체의 박 사이 변화보다 1.2 dB(`splice.py check`)다.
- 듣기 선별(`musicgen/listen.py --screen`, agy gemini-3.8-flash-high): 전자음악, 신스 베이스, 드럼, 목소리 없음, 글리치 없음, 에너지 3. 보정 짝이 맞지 않은 선별이라 판정이 아니다. 후보 `instrument-s1002`, `pulse-s1004`, `break-s1004`도 같은 선별을 지났다. `break-s1001`은 목소리가 들려 뺐다. 곡을 바꾸려면 `MUSIC_ID`와 `make_data.py`의 `TRACKS` 행을 쓴다.

## 검사 (2026-10-20, 박스 렌더 9, sitting 3과 V4.1 sitting)

| 단계 | 결과 |
|---|---|
| `render.py check` | 모든 프레임과 하위 프레임에서 `PAGE ERRORS: 0`. 그린 문자열의 글자가 모두 그 글꼴에 있다(빠진 글리프 0, 한글 110자). hold, 여백, 겹침, 문자열 출처가 모두 이 검사 안에 있다 |
| `render.py full` | rc 0 |
| `encode` | `out/video-music.mp4`: 95.63초, 4,565,506바이트, h264 1080×1080 60 fps, AAC. `draft: false` |
| `pops` | 0 |
| `sync` | 그림의 변화 시작 44개가 모두 박에서 한 프레임 안. 킥 위상 +5.1 ms |
| `flash` | 번쩍임 0(WCAG 2.3.1) |
| `asserts_a.py` | Part A의 문구와 시각 26개 통과. 새 항목은 앞 렌더의 `data.json`에서 실패한다(FAIL-first) |

## 판정

만든 라운드(opus)가 자기 스틸을 1080 px과 540 px(폰)으로 열어 장면마다 SHIP/FIX를 매겼다. 그다음 새 비전 판정관(opus)에게 따로 보냈다.

- 4판(가짜 숫자, 137.8초): 이해도는 통과였다. 원리 장면의 프레임만 보고 "토큰 하나에 호출 하나", "고정 구간은 한 번에", "같은 답"을 읽어 냈다. `urg|ency`처럼 여러 글자가 한 상자라 글자 하나에 호출 하나로 읽히지 않았다. 고칠 점 다섯은 5판에서 고쳤다.
  - schemajump의 막대 수가 "8 calls"와 맞지 않았다. 줄바꿈에서 막대가 둘로 잘렸고, 고르는 호출의 막대가 정지 화면에서 보이지 않았다. 고르는 부분을 신호색으로 칠하고, 줄을 넘는 막대를 하나로 그렸다.
  - 제목 뒤의 흐린 격자(대비 약 1.2:1)가 폰에서 압축 잔상처럼 보여 지웠다.
  - "through all 40 layers"를 "one engine call: all 40 layers"로 바꿔 다음 장면의 단위와 이었다.
  - 숫자 없는 confidence 선의 길이가 어느 백분율과도 맞지 않았다. 질문이 하나인 카드에만 숫자와 함께 둔다.
  - END의 설명 없는 흰 사각형을 지웠다.
- 그 전의 판, 낱말 없는 전문가 행렬로 원리를 그린 판은 사용자가 "알아볼 수 없다"고 해서 버렸다. 2판의 설명 순서(요청, 토큰마다 호출, 되감기, schemajump, 같은 답)로 되돌리고, 예시는 영어 route-01로 바꿨다. 한국어 ko-mail-06은 한 음절이 한 토큰이라 "글자 하나에 호출 하나"로 읽혔다.

## 주장하지 않은 것

- 다른 엔진의 이름, 숫자, 비율, 견줌은 없다. 같은 생각(jump-forward decoding)은 이전에도 있었으므로 "first", "new", "only"를 쓰지 않았다.
- 전문가 라우팅은 그림이다. 켜진 칸에 숫자가 없고, 잰 라우팅이라고 하지 않는다.
- 토큰과 호출이 들어오는 박자는 시간을 주장하지 않는다.
- hard 세트는 우리가 쓴 문항과 우리 라벨이다(바닥글에 그렇게 쓴다). 더 큰 모델이 이긴다고 쓰지 않았다. sitting 3에서는 Clef-Flash가 Qwen3.6보다 많이 맞혔고, 화면은 그 숫자를 그대로 쓴다.
- guard-04(jump의 답이 Clef-Flash의 공식 답과 다른 요청)는 보이지 않는다(사용자 결정). 26/31은 `measured`에 있다.
- V4.1-Flash의 시간은 쓰지 않았다. V4.1에서는 프롬프트 읽기가 시간의 대부분이라 schemajump의 효과가 작고(벽시계 −7 % ±7 %), 이 모델을 보이는 이유는 지식 문제의 정답 수다(사용자 결정).

## 파일

- `film.html`: 영상 본체. `data.json`(또는 `?data=`)만 읽는다. `window.seek(t)`는 t의 순수 함수다. `parta.js`와 `partb.js`를 불러 그린다.
- `make_data.py`: 행에서 숫자를, 출처의 줄에서 문자열을, 박 격자와 읽기 규칙과 곡의 앵커에서 장의 길이와 모든 착지 시각을 정해 `data.json`을 쓴다. `make_data_a.build()`와 `make_data_b.build()`를 부른다.
- `parta.js`, `make_data_a.py`: Part A의 장면(`areq`, `atrip`, `aplain`, `ajump`, `adec`)과 그 블록(`data.json`의 `a`). `--preview OUT.json`은 Part A만 따로 깐다.
- `partb.js`, `make_data_b.py`: Part B의 장면과 그 블록(`data.json`의 `b`). `--preview OUT.json`은 Part B만 따로 깐다.
- `inputs.json`: 행이 모르는 것(앉은 자리 이름, 경로, 손잡이, Solar 칸, "and …" 줄, 판정 강제, draft).
- `tokens.py`, `sources/tokens-qwen36.json`: 답 프로그램의 Qwen3.6 토큰 조각(Qwen3.6의 `tokenizer.json`, sha256 `5f9e4d49…`)과 유도한 호출 계획. 화면의 호출 수는 행의 것을 쓴다.
- `render.py`: 렌더와 검사. `splice.py`: 곡을 이어 붙이고 이음매를 잰다. `beats.py`, `beats.json`: 곡의 박자 격자.
- `sources/`: sitting 3의 행과 본문(`sit3-1020/`), sitting 2의 행(`sit2-1020/`), 공식 답의 요청별 정답(`reference-tops.json`).
- `musicgen/`: 곡을 만든 스크립트(`gen.py`, `run.sh`, `prompts.json`, `listen.py`, `screen.py`).
- `box/`: 박스 스크립트(`setup.sh`, `serve.sh`, `drive.sh`, `post.sh`, `run.sh`).
- `probe/`(gitignore 대상): 미리보기 페이지, 가짜 행(`bfx.py`), 프레임 검사 도구.
- `fonts/`: Martian Mono, Anybody(`film.html`이 아직 불러 둔다), Noto Sans KR의 부분집합(`NotoSansKR-subset.ttf`, 이 영상의 한글만 남긴 가변 글꼴). 모두 SIL OFL 1.1(`fonts/OFL-*.txt`).

## 만든 방법

`render.py`는 0.3.4 3판의 것을 고친 것이고, 그 머리는 [howseen-ai/claude-motion-design](https://github.com/howseen-ai/claude-motion-design) 템플릿(MIT, 저작권 고지는 파일 머리말)이다. 화면 문법은 스타일 조사 라운드가 낸 세 방향 중 사용자가 고른 "Instrument"다. 설계, 코드, 문구는 Claude Code(Opus 5.5)가 썼다. 만든 라운드가 스틸을 1080 px과 540 px으로 열어 보았고, 따로 띄운 비전 판정관이 렌더한 영상을 판정했다.
