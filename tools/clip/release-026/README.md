# bloomery 0.2.6 릴리즈 영상

bloomery 0.2.6을 소개하는 47.5초 영상(1080×1080, 60 fps)의 소스다. [residency 영상](../residency/)과 같은 먹과 종이 그림체, 같은 음악을 쓴다. 성능 이야기가 중심이고, 주인공은 서버 기본값에서 Qwen3.8-Flash-Next가 받는 프롬프트다.

비교는 세 팔이다. 모두 A6000, `--place a`, 서버가 고르는 기본값이고 MTP 초안도 기본값(켬)이다. 숫자는 벤치 바이너리(`generate_qwen3moe`)로 쟀다. 화면에는 바이너리 이름을 쓰지 않고, `data.json`의 `source`가 그것을 적는다.
1. `0.2.5 · UD-Q4_K_XL`: 0.2.5의 서버. 서버가 프롬프트 스트림을 켜지 않았다(`BLOOMERY_HOSTSTREAM=off`와 같다). pick도 링도 없다.
2. `0.2.6 · UD-Q4_K_XL`: 같은 파일, 0.2.6의 서버. 프롬프트 스트림이 기본으로 켜진다(pick + 링).
3. `0.2.6 · UD-Q3_K_XL (i-quant)`: 더 작은 파일. 0.2.5에서는 이 파일의 라우팅 expert가 전부 CPU로 갔고, 0.2.6은 GPU에서 돌린다.

2 대 1은 같은 파일에서의 엔진 이득이다. 3은 새 양자화 지원이다. 3이 2보다 빠르다고 가정하지 않는다. 3의 문구는 데이터 문자열(`arm3_caption`)이다. 시팅에서 3은 4,096 프롬프트와 디코드에서 2보다 빨랐고 512 프롬프트에서는 느렸다(775.0 대 943.0). 막대 장면은 그대로 보이고, 어느 문구도 3이 어디서나 빠르다고 하지 않는다.

한 층 무대(1–2막)는 팔 1과 팔 2의 한 층을 그린다. 0.2.5 서버에서는 GPU가 CPU를 기다렸다. 0.2.6 서버에서는 층마다 pick이 일이 가장 많은 호스트 expert를 PCIe로 GPU 좌석에 앉힌다(시팅의 기능 실행에서 층당 122개). 앉은 것은 디코드까지 남고, 작은 나머지만 CPU가 한다(층당 20,729 → 2,598열). 이것이 주된 항이다. 링은 이 프롬프트에만 쓰는 칸인데, 기본값에서는 48층 중 9층에서만 돈다(그 층마다 19개). 그래서 무대의 링은 비어 있고 흐리게 그려지며 "ring · 9 of 48 · layers"라는 이름표만 단다. 몽타주 자막이 "the ring adds 19 more in 9 of 48"이라고 말한다.

영상 문구는 영어다(리포 밖으로 나가는 것). 이 문서는 한국어다.

**`data.json`은 2026-10-07 릴리즈 시팅 값으로 채워져 있다**(`"placeholder": false`, 도장 없음). `make_data.py placeholder`로 되돌리면 모든 프레임 아래에 빨간 PLACEHOLDER NUMBERS 도장이 찍힌다. 새 시팅은 `sitting.json`을 만들어 `make_data.py fill`로 채운다(아래 「채우기」).

## 흐름

음악 박자는 이 트랙의 그루브가 들어오는 곡 20.19초다. `MUSIC_AT=7.9`이면 그 박자가 영상 12.29초(DROP)에 떨어진다. 그 뒤 장면 경계는 곡의 점4분음표 0.82초 격자 위에 있다. 곡 7.92초의 악구 시작이 영상 0초다.

| 초 | 장면 | 무엇을 보이나 | 읽는 키 |
|---|---|---|---|
| 0–3.3 | 제목 | 화덕 속 블룸(먹 번짐 + 호박색 심)과 `bloomery 0.2.6`, 불씨가 오른다. `title`("Qwen3.8-Flash-Next in bloomery 0.2.6"), 비율이 1.02 이상일 때만 ": faster prompts"가 붙는다 | `version`, `title`, `pp_ratio` |
| 3.3–12.29 | 0.2.5 (stream off) | 한 층 무대. 위는 GPU 방, 아래는 호스트 RAM의 어두운 방(CPU 칩과 호스트 expert). 4,096토큰 프롬프트 카드가 작업 점으로 흩어진다(4.85 악구). GPU 좌석이 한 번 훑고 끝나면 8.6에 등이 꺼지고 "waiting…". CPU는 호스트 expert를 차례로 비운다 | `before_label`, `host_cols_before`, `topk`, `experts_per_layer`, `layers`, `prompt_tokens` |
| 12.29–20.49 | 0.2.6 · the prompt path | DROP에 되감기("same layer, again"). 링이 흐리게, 비어서 그려지고 안에 "ring / N of 48 / layers"(`streamed_layers`). 일이 가장 많은 호스트 expert에 호박색 동그라미(pick). 14.4부터 PCIe 관을 타고 올라가 좌석의 옛 주인과 바뀌고 호박색 테로 남는다("+N seated · they stay"). CPU는 남은 작은 몫만 하고 먼저 끝난다. 다 내려앉으면 GPU가 돌린다. 18.44부터 층 2–5는 관에 호박색 복사가 오르고, 20.08부터 48층까지 빨리 감는다. 자막 "each layer picks its own; the ring adds M more in N of 48" | `after_label`, `admit_per_layer`, `streamed_per_layer`, `streamed_layers`, `ring_half`, `host_cols_after`, `card_experts_per_layer`, `arms[1].file` |
| 20.49–25.41 | one layer, side by side | 두 줄의 시간 막대(GPU / PCIe / CPU)가 같은 속도로 그려지고 0.2.6 줄이 먼저 끝난다. 0.2.5 서버는 "the GPU waits", 0.2.6 서버는 복사·계산·CPU 몫이 "at the same time" | `arms[0].pp4096`, `arms[1].pp4096`, `host_cols_*` |
| 25.41–32.79 | the prompt | 세 팔이 4,096토큰 띠를 경주한다(머리줄 "a 4,096-token prompt · real time"). 가장 느린 팔이 예산 5.68초의 1.08배 안이면 실시간, 넘으면 "played N× faster than real". 끝난 팔마다 tok/s와 그 팔의 한 줄 | `arms[i].label/file_gb/pp4096`, `arm1_caption`–`arm3_caption` |
| 32.79–38.53 | the numbers | 범례(팔 이름 · GB)와 막대 세 묶음: 프롬프트 512, 프롬프트 4,096, 프롬프트 뒤 디코드. 묶음마다 제일 큰 팔에 맞춘 0 기준선 막대. 아래에 "same file: 4,096-token prompts N× · answers +M%"(뒤에 `answers_tag`), 비교 대상, 이유 한 줄 | `arms[i].pp512/pp4096/decode`, `pp_ratio`, `decode_note`, `decode_conditions` |
| 38.53–42.63 | also in 0.2.6 | 카드 두 장: MTP 드래프트 폭을 잰 비용으로 고른다, PLE 표를 둘 자리가 없는 호스트는 4 GiB 캐시로 디스크에서 읽는다 | `side1`, `side2` |
| 42.63–47.5 | 끝 | 먹이 번져 화면을 덮고 `bloomery 0.2.6`, "prompts N× · answers +M%"(뒤에 `answers_tag`), 비교 대상과 "same file", 팔 3의 이름과 한 줄, 조건, 디코드 조건, 잰 방법, 리포 주소. 음악은 마지막 2초에 줄어든다 | `version`, `pp_ratio`, `answers_tag`, `arms`, `arm3_caption`, `conditions`, `decode_conditions`, `method_line`, `repo` |

## 다시 찍기

```
cd tools/clip/release-026
python3 -m venv .venv && .venv/bin/pip install playwright numpy && .venv/bin/python -m playwright install chromium
mkdir -p music && curl -sSL -o music/644.mp3 https://assets.mixkit.co/music/644/644.mp3   # music/는 .gitignore에 있다
python3 make_data.py fill sitting.json                               # 또는 placeholder
python3 -m http.server 8781 --bind 127.0.0.1 &                        # film.html, data.json, fonts/를 서빙한다
.venv/bin/python render.py probe 2.5 10.5 17.4 24.9 31.6 37.6 40.5 47.3   # probe/main/sheet.png, 600 px 스틸 m_NN.png
SUB=6 MUSIC=music/644.mp3 MUSIC_AT=7.9 .venv/bin/python render.py full    # 한 프로세스로 전부
.venv/bin/python render.py pops out/video-music.mp4                   # 한 프레임짜리 튐 검사, 0건이어야 한다
```

병렬로 찍을 때는 청크를 넷 이하로, 10초씩 띄워서 연다. 청크마다 `SUB=6 F0=<시작> F1=<끝> NO_ENCODE=1 render.py full &`을 띄우고 `$!`을 파일에 한 줄씩 적는다. `while read p; do while kill -0 $p; do sleep 5; done; done < pids.txt`로 기다린 뒤 `SUB=6 MUSIC=… render.py encode`를 돈다. 프레임은 2,850개이고 경계는 0, 713, 1426, 2139, 2850이다. M 계열 Mac에서 청크 넷이 약 6분 30초, 인코딩과 튐 검사가 약 1분 20초 걸렸다(2026-10-07). `sub/`는 약 5.8 GB의 JPG로 차니 끝나면 지워도 된다. zsh의 `for p in $pids`는 낱말로 나뉘지 않으니 쓰지 않는다. `PROBE_TAG=<이름>`은 스틸을 `probe/<이름>/`에 따로 남긴다.

`film.html`은 모든 프레임을 `window.seek(t)` 하나로 그린다. 붓 획, 먹 번짐, 손글씨는 해시 노이즈로 흔들리고, 흔들림은 초당 12번 바뀐다(`BF = floor((60t + 0.5) / 5)`). 같은 t는 같은 프레임이다.

**스스로 거르는 것 셋.**
- 34 px(글꼴 크기, em) 미만 글자는 그려지되 콘솔 오류가 된다. `render.py`는 프로브와 렌더 뒤에 PAGE ERRORS로 찍는다. 0줄이어야 한다. 긴 문구는 줄이지 않고 감싼다.
- `data.json`에 필수 키가 없거나 형이 틀리면 화면에 이유가 찍힌다. `render.py`는 그 이름을 대고 멈춘다.
- `make_data.py variant <out> 키=x배|값 …`(팔 안의 키는 `arms[1].pp4096=x2`)로 수치를 바꾼 사본을 만들고 `FILM_URL='http://127.0.0.1:8781/film.html?data=<out>'`로 찍는다. 확인한 변형(자리표시 판 다섯, 채운 판 셋)은 아래와 같다. 비율을 바꾸는 변형은 `pp_ratio`도 같은 배수로 바꾼다(`fill`이 계산해 넣은 값이 남아 있기 때문이다).
  - `arms[1].pp4096` 절반: 비율 0.88×, 제목에서 "faster"가 빠진다.
  - `arms[1].pp4096` 두 배: 3.50×, 0.2.6 줄이 짧아진다.
  - 팔 3이 가장 느린 경우(500 tok/s): 경주가 "played 1.4× faster than real"로 바뀌고, 문구는 "the same speed from a smaller file" 같은 `arm3_caption`.
  - 긴 라벨(`0.2.5 server (BLOOMERY_HOSTSTREAM=off)`): 모든 줄이 제 글자로 맞춰지거나 감싸진다.
  - 일반 머신 모양(링 반쪽 398칸, 층당 링행 300).
  - 채운 판에서 `arms[1].pp4096`와 `pp_ratio` 절반(0.83×, 제목에서 "faster prompts"가 빠지고 경주가 "played 1.1× faster than real"), 두 배(3.33×), `streamed_layers=0`(링이 무대에서 빠지고 자막이 "each layer picks its own").

## 채우기: `sitting.json`

JSON 하나다. 팔은 `arms` 목록에 세 개(팔 1, 팔 2, 팔 3 순서)를 넣고, 나머지는 평평한 키다. 단위는 아래 표와 `data.json`의 `units`에 있다. `make_data.py fill`은 모르는 키(팔 안의 키 포함), 빠진 필수 키, null, 숫자가 아닌 값, 0 이하의 tok/s, 셋이 아닌 `arms`를 이름을 대고 거부한다. `pp_ratio`가 없으면 `arms[1].pp4096 / arms[0].pp4096`로 계산하고 그렇다고 출력한다.

```json
{"arms": [
  {"label": "0.2.5 · UD-Q4_K_XL", "file": "UD-Q4_K_XL", "file_gb": 111, "pp512": 0, "pp4096": 0, "decode": 0},
  {"label": "0.2.6 · UD-Q4_K_XL", "file": "UD-Q4_K_XL", "file_gb": 111, "pp512": 0, "pp4096": 0, "decode": 0},
  {"label": "0.2.6 · UD-Q3_K_XL (i-quant)", "file": "UD-Q3_K_XL", "file_gb": 90, "pp512": 0, "pp4096": 0, "decode": 0}],
 "arm3_caption": "…",
 "host_cols_before": 0, "host_cols_after": 0, "streamed_per_layer": 0, "streamed_layers": 0, "admit_per_layer": 0, "ring_half": 0,
 "conditions": "Qwen3.8-Flash-Next · A6000 48 GB · --place a · MTP on",
 "decode_conditions": "decode: 96 tokens after the 4,096-token prose prompt, MTP draft on",
 "answers_tag": "", "method_line": ""}
```

위의 0은 자리다. `fill`은 tok/s와 `file_gb`, `ring_half`, `host_cols_before`의 0을 거부한다.

**전제.** 1–2막의 before 무대는 pick이 없는 층을 그린다(좌석 교체 없음, CPU가 층당 약 19,000개, GPU가 기다림). 팔 1이 0.2.5의 서버 동작(프롬프트 경로 끔)일 때만 맞는다. pick을 하는 팔을 팔 1로 넣으면 무대와 시간 막대가 틀린다.

| 키 | 필수 | 단위 | 어디서 |
|---|---|---|---|
| `arms[i].label` (i = 0, 1, 2 → 팔 1, 2, 3) | 예 | 글 | 화면의 팔 이름, 예: `0.2.5 · UD-Q4_K_XL` |
| `arms[i].file` | 예 | 글 | 파일 짧은 이름, 예: `UD-Q4_K_XL`. 팔 2의 것이 무대 조건 줄에 들어간다 |
| `arms[i].file_gb` | 예 | GB = 10⁹ 바이트 | 파일의 바이트 수 ÷ 10⁹(HF가 보여 주는 크기). `du -h`·`ls -lh`의 `G`는 GiB라 약 7 % 작게 읽힌다: 89.99 GB가 `84G`로 나온다. 세 팔을 같은 단위로 |
| `arms[i].pp512` | 예 | tok/s, 512토큰 프롬프트 | 그 팔의 `mean pp … tok/s(pp)` 행, P 512 |
| `arms[i].pp4096` | 예 | tok/s, `prompt_tokens` 토큰 프롬프트 | 같은 행, P 4096 |
| `arms[i].decode` | 예 | tok/s, 프롬프트 뒤 디코드 | 그 팔 `ROW` 행들의 `tok/s(mean)` 평균 |
| `arm3_caption` | 예 | 글 | 팔 3의 한 줄(경주와 끝 카드). 예: "a smaller file: its i-quant experts now run on the GPU", "the same speed from a smaller file" |
| `arm1_caption`, `arm2_caption` | 아니오 | 글 | 기본값 "the prompt stream off", "the same file, the prompt stream on" |
| `pp_ratio` | 아니오 | 배 | 팔 2 / 팔 1, 러너의 짝 비율(라운드별) |
| `host_cols_before` | 예 | 층당 호스트 열(토큰 × expert 쌍), 층 평균 | 팔 1의 `stat prompt host`의 `host_slots` ÷ `services` |
| `host_cols_after` | 예 | 같음 | 팔 2의 같은 행 |
| `streamed_per_layer` | 예 | 스트림한 층 하나당 expert, 스트림한 층의 평균 | 팔 2 기능 실행의 `xstream end`의 `streamed` ÷ `layers`(스트림한 층 수) |
| `streamed_layers` | 예 | 층 | 팔 2 기능 실행에서 링이 돈 층 수(`xstream end`의 `layers`). 화면에 "N of 48"로 찍힌다. 0이면 링을 무대에서 뺀다 |
| `admit_per_layer` | 예 | 층당 expert | 팔 2 기능 실행의 `call stream end`의 `admitted` ÷ `picks`. 0이면 좌석행 경로를 그리지 않는다 |
| `ring_half` | 예 | 칸 | 팔 2의 `xstream end`의 `half_slots`(또는 시작 줄의 `xstream_half=`) |
| `card_experts_per_layer` | 아니오 | 층당 expert, 그림에만 쓰고 화면에 찍지 않는다 | 계획 줄의 카드 expert 수 ÷ 층 수. 기본값 300 |
| `before_label`, `after_label` | 아니오 | 글 | 무대, 시간 막대, 끝 카드의 이름. 기본값 `0.2.5 (stream off)`, `0.2.6`. 숫자에 "0.2.5에 비해"를 붙이는 곳은 모두 이 이름을 쓴다 |
| `title` | 아니오 | 글 | 제목 줄. 기본값 "Qwen3.8-Flash-Next in bloomery 0.2.6". 바이너리 이름(서버, 벤치)은 화면에 쓰지 않는다 |
| `answers_tag` | 아니오 | 글 | 숫자 장면과 끝 카드의 "answers +M%" 뒤에 붙는 말. 디코드를 MTP 초안 없이 쟀으면 "(MTP off)", 켜고 쟀으면 빈 문자열(기본값) |
| `method_line` | 아니오 | 글 | 끝 카드의 잰 방법 한 줄. 빈 문자열(기본값)이면 찍지 않는다 |
| `conditions` | 예 | 글 | 모델, 카드, 배치, 서버. 프롬프트 길이는 장면이 붙인다. 모든 수치 장면 아래에 34 px로 감싸 찍힌다. 약 64자 안이면 한 줄이다 |
| `decode_conditions` | 아니오 | 글 | 디코드 막대의 조건. 토큰 수와 MTP 초안(draft)이 켜졌는지 꺼졌는지를 꼭 쓴다. 서버 기본값은 켜짐이다 |
| `decode_note` | 아니오 | 글 | 디코드가 왜 빨라졌는지 한 줄 |
| `side1`, `side2` | 아니오 | 글 | 곁줄 둘. `side2`를 빈 문자열로 두면 카드 한 장만 나온다 |
| `prompt_tokens`, `layers`, `experts_per_layer`, `topk` | 아니오 | 모델 사실 | 기본값 4096, 48, 512, 10 |
| `model`, `version`, `repo`, `source` | 아니오 | 글 | 기본값 그대로 두면 된다 |

## 화면의 숫자와 출처

시팅: 2026-10-07, A6000 한 장, 한 리스, 팔마다 4라운드, 카드 `docs/cards/vid026-3arm.card`(bloomery 리포). 바이너리는 `generate_qwen3moe`이고 0.2.6 서버가 고르는 기본값(`BLOOMERY_XSTREAM` 미설정 → `--place a`에서 split, residency 켬), MTP 초안도 기본값(켬). 팔 1은 0.2.5 빌드에 `BLOOMERY_HOSTSTREAM=off`(0.2.5 서버의 동작). 층당 수는 같은 바이너리와 기본값으로 돈 팔 2의 기능 실행(step stats)과 시팅의 stat 줄에서 나왔다. 앞서 MTP 초안을 끄고 잰 창은 리드가 `sitting-draftoff.json`으로 따로 갖고 있다.

| 화면 | 값 | 출처 |
|---|---|---|
| "every token picks 10 of 512 experts, in each of 48 layers" | `topk`, `experts_per_layer`, `layers` | 모델 사실(GGUF 메타) |
| CPU jobs a layer 20,729 → 2,598 | `host_cols_before`(팔 1) → `host_cols_after`(팔 2) | 시팅, `stat prompt host`의 `host_slots` ÷ `services` |
| "+122 seated · they stay" | `admit_per_layer`(팔 2) | 기능 실행, `call stream end`의 `admitted` ÷ `picks` |
| 링 "9 of 48 layers", 자막 "the ring adds 19 more in 9 of 48" | `streamed_layers`, `streamed_per_layer`(팔 2) | 기능 실행, `xstream end` |
| 링의 칸 벽(숫자 없음), GPU 좌석 수(숫자 없음) | `ring_half` 96, `card_experts_per_layer` 243(팔 2) | 기능 실행. 초안이 카드 바이트를 쥐어 좌석이 줄었다 |
| 시간 막대 두 줄의 길이 | `prompt_tokens / arms[i].pp4096 / layers`(팔 1, 2) | 시팅 [유도] |
| 경주의 초시계 5.6 / 3.3 / 2.8 s | `prompt_tokens / arms[i].pp4096` | 시팅 [유도: tok/s를 초로 바꾼 것] |
| 팔마다 tok/s: 512 프롬프트 686 / 943 / 775, 4,096 프롬프트 733 / 1,258 / 1,438, 디코드 73.6 / 89.1 / 98.4 | `arms[i].pp512`, `arms[i].pp4096`, `arms[i].decode` | 시팅(685.5, 732.6 등을 반올림해 찍는다) |
| 111 GB / 90 GB | `arms[i].file_gb` | 파일 크기, 10⁹ 바이트(111.3, 90.0) |
| "prompts 1.72×", "answers +21%" | `pp_ratio`(= 1,257.7 / 732.6 = 1.717, `fill`이 계산), `arms[1].decode / arms[0].decode` | 시팅 [유도] |

## 그림에서 측정값이 아닌 것

- 어느 expert가 어느 좌석에 앉는지, 호스트 expert마다 일이 몇 개인지(덩어리 크기)는 도식이다. 화면에 "blot size = its jobs (schematic)"이라고 쓴다. 크기 분포는 순위 1/(i+3)^s 모양이다. s는 pick이 앉힌 것을 뺀 나머지가 `host_cols_after / host_cols_before` 몫을 갖도록 맞춘다(평균 층은 링으로 거의 아무것도 보내지 않는다). 그래서 덩어리의 합은 데이터와 맞지만 하나하나는 아니다. 순서(일이 많은 것부터)는 규칙의 순서와 같다.
- 라우팅 점(빨간 점)은 "일이 expert로 간다"를 보이는 도식이고 개수가 아니다.
- GPU 좌석 수는 `card_experts_per_layer`로 그리되 화면에 숫자로 쓰지 않는다.
- 시간 막대는 줄 길이만 데이터(프롬프트 시간 ÷ 48)다. 줄 안의 나눔은 도식이고, 화면에 "inside: schematic"이라고 쓴다. 그 도식도 한 규칙에 묶였다. CPU 몫은 일의 수에 비례하고(같은 스레드, 같은 속도), 층의 앞(attention, 라우팅)과 뒤(합치기)는 두 줄에서 같은 시간이다. 비율은 스트림을 만든 라운드의 기능 실행(측정 아님)에서 나온 층당 분해(카드의 층 앞부분 19–30 ms, 호스트 몫 95 → 15.5 ms)를 따랐다.
- 슬로모션의 GPU와 CPU 작업 시간은 설명용이다. CPU만은 두 층에서 같은 속도로 비운다. 그래서 0.2.6 층의 CPU 몫은 `host_cols_after / host_cols_before`만큼의 시간에 끝난다.
- 몽타주(층 2–5)는 같은 무대를 다시 쓴다. 층마다 다른 expert가 앉는다는 것은 그리지 않았다. 링이 어느 4층에서 도는지는 그리지 않는다. 개수만 이름표와 자막으로 말한다.
- 무대는 팔 1과 팔 2의 층이다. 팔 3(Q3 파일)의 층은 그리지 않는다.

## 주장하지 않은 것

- 다른 엔진의 이름, 수치, 비율은 없다. 비교는 우리 팔끼리뿐이다.
- 비교는 서버의 기본 동작끼리다. 0.2.5에서 프롬프트 스트림을 기본으로 켠 것은 벤치 바이너리뿐이었고, 서버는 끈 채로 돌았다. 그래서 팔 1은 스트림을 끄고 쟀다. 숫자는 벤치 바이너리에 서버 기본값을 줘서 쟀다. 그래서 화면에는 바이너리 이름(`bloomery-serve`, "server")을 쓰지 않는다. 제목은 `title`, 경주 머리줄은 "a 4,096-token prompt", 끝 카드는 "prompts N×"다. 어느 바이너리로 쟀는지는 `data.json`의 `source`에 남는다. "0.2.5에 비해"를 붙이는 숫자에는 언제나 `before_label`("0.2.5 (stream off)")이 함께 찍힌다.
- MTP 초안은 모든 팔에서 기본값(켬)이다. 조건 줄과 디코드 조건 줄에 쓴다. 숫자 장면의 `decode_note`는 좌석에 남은 pick을 말하지만, +21% 전부가 pick 몫은 아니다. 0.2.6은 초안 폭을 고르는 방법도 바꿨고(`side1`), 초안을 끈 창에서는 +9%였다.
- "출력이 같다"고 쓰지 않는다. 카드와 호스트는 같은 expert에 다른 비트를 낸다.
- 비율이 1.02 미만이면 "faster"를 쓰지 않는다. 제목은 비율로 낱말을 고르고, 막대 장면과 끝 카드는 형용사 없이 비율만 쓴다.
- 0.2.6 서버의 프롬프트 이득을 링 하나의 공으로 돌리지 않는다. 2026-10-07 오전 창에서 좌석행만 켠 팔(`BLOOMERY_XSTREAM=admit`)이 둘 다 켠 팔(`split`)과 거의 같았다(1,342 대 1,350 tok/s). 그리고 기본값의 링은 48층 중 9층에서만 돈다. 그래서 영상은 pick을 주된 움직임으로 그리고 링은 이름표만 단 채 비워 둔다. 장면 이름은 "the prompt path"다. `decode_note`는 좌석에 남은 pick을 말한다.
- 팔 3이 어디서나 빠르다고 하지 않는다. 시팅에서 팔 3은 512 프롬프트에서 팔 2보다 느렸고(858.9 대 988.7), 막대가 그대로 보인다. 문구는 "a smaller file: more of it fits on the GPU"뿐이다.

## 파일

- `film.html`: 영상 본체. `data.json`(또는 `?data=`)만 읽는다.
- `make_data.py`: `placeholder`, `fill <sitting.json>`, `variant`.
- `data.json`: 2026-10-07 시팅 값으로 채운 판.
- `render.py`: 스틸(`probe`, 600 px 축소본 함께), 전체 렌더, 청크, 인코딩(`MUSIC`, `MUSIC_AT`), 튐 검사.
- `fonts/`: Caveat Brush, Gochi Hand(SIL OFL 1.1, `OFL-*.txt`).

## 만든 방법

그림체(붓 획, 번짐, 흔들림, 종이)와 렌더러는 [residency 영상](../residency/)에서 가져왔다. `render.py`는 [howseen-ai/claude-motion-design](https://github.com/howseen-ai/claude-motion-design) 템플릿(MIT, 저작권 고지는 파일 머리말)을 고친 것이다. 음악은 [Mixkit](https://mixkit.co/free-stock-music/) 644번 트랙(Mixkit 라이선스, 영상·SNS 사용 가능, 표기 불요)이고 리포에 넣지 않는다. 장면 설계, 코드, 문구는 Claude Code(Opus 5.5)가 썼다. 스틸은 만든 라운드가 스스로 600 px 축소본까지 열어 확인했다. 채운 판은 리드가 따로 비전 판정을 받는다.
