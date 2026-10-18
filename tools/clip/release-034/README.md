# bloomery 0.3.4 릴리스 영상

bloomery 0.3.4를 X 타임라인에 알리는 39.4초 영상(113박, 1080×1080, 60 fps)의 소스다. 전류 한 줄기가 영상 전체를 끌고 간다: 타이틀을 치고, 회로 선을 따라 24 GB 카드로 들어가, 토큰 격자를 한 칸씩 채우고, Spark 두 대를 건너, 임베딩 벡터에 닿는다. 숫자는 전류가 닿는 자리에 떨어지고, 카메라는 전류를 따라 박에서 자르며, 읽을 글이 있는 동안은 아무것도 움직이지 않는다.

설계는 `DESIGN.md`(1단계: 조사, 설계, 스타일 프레임, 음악), 조사는 `research.md`에 있다. 2단계(이 문서)가 `film.html`과 `make_data.py`를 짓고, 렌더는 박스에서 했다. 영상 문구는 영어다. 이 문서는 한국어다.

## 흐름

박 번호는 영상 0초 = 0박이다. 곡은 171.977 BPM(한 박 0.34888초, 20.93프레임)이고, 영상은 곡의 23번째 박에서 시작한다(`timeline.at` 8.357초). 곡의 드롭(곡 67박, 23.71초)이 영상 44박, PROMPT로 넘어가는 컷에 떨어진다. 곡은 135박(47.43초)에서 드럼이 끊기며 끝나고, 그 박이 영상의 마지막 박(113)이다.

| 초 | 박 | 장면 | 무엇이 움직이나 |
|---|---|---|---|
| 0–1.39 | 0–4 | 리더 | 번개의 길이 한 박에 한 마디씩 강철색으로 내려온다(각 마디는 두 프레임 동안 흰색) |
| 1.39–4.53 | 4–13 | TITLE | 4박에 번개가 치고(열 1에서 0.2초 만에 흉터로 식는다) `0.3.4`가 꽂힌다. `bloomery`는 한 박 동안 폭 축 150 → 50으로 좁아지며 제자리에 선다. 전류가 선을 따라 달리고, 5박에 `RELEASE` |
| 4.53–10.46 | 13–30 | BOLT | `74B`가 화면보다 넓게 꽂혀 양끝이 잘린다. 15박에 좁아지며 `-A9B`가 옆에서 자라고 카드가 그려진다. 16박에 `24 GB`, `RTX 3090`, 문장. 전류는 13박에 오른쪽 밖에서 출발해 16박에 카드의 마지막 핀에 닿고, 핀이 한 프레임에 하나씩 켜진다 |
| 10.46–15.34 | 30–44 | DECODE | 24 GB 칸 안으로 0.3초 줌(1 → 12배). DECODE 화면은 그 칸 안에 1/12로 이미 그려져 있다가 줌이 끝날 때 1배가 된다. 31박부터 격자 182칸이 초당 86.69칸으로 켜진다(새 칸은 강조색으로 켜져 0.25초에 강철색으로 식는다) |
| 15.34–18.48 | 44–53 | PROMPT | 드롭. 글자 칸이 바뀌고(옛 글자는 박에서 위로 빠지고 새 글자가 아래에서 들어온다) 격자가 초당 2,047칸으로 한꺼번에 범람한다 |
| 18.48–23.37 | 53–67 | SPARKS | 격자의 마지막 칸에서 나간 선이 45도로 올라가고, 카메라가 0.3초 휩 팬으로 그 선을 따라간다(가로 모션 블러). 54·55박에 노드 둘, 56·57박에 각 노드의 NVMe에서 올라온 전류가 노드에 닿는 박에 그 노드의 전문가 줄이 켜진다 |
| 23.37–26.51 | 67–76 | MODELS | 머리말이 세 모델 이름으로, 68박에 문장이 `over RDMA · by @juliankang4`로 바뀌고, 버스를 따라 전류가 노드 사이를 달린다 |
| 26.51–32.09 | 76–92 | EMBED | 하드 컷. `EMBEDDINGS`가 한 박 동안 좁아진다. 77·78·79박에 TEXT, VIDEO, AUDIO 줄이 하나씩(아이콘은 2.6배에서 0.2초에 제자리로), 80박에 모델 이름과 세 줄의 전류가 출발해 82박에 벡터에 닿고, 벡터가 가운데부터 켜진다. 81박에 `/v1/embeddings` |
| 32.09–36.28 | 92–104 | THANKS | 벡터의 칸들이 미끄러져 한 줄의 선이 되고 `thank you`. 93박에 두 이름과 크레딧, 전류가 선과 가지를 따라 각 이름의 점을 켠다 |
| 36.28–39.42 | 104–113 | END | 하드 컷과 둘째 번개. `bloomery` / `0.3.4`, 105박에 주소. 107박에 전류가 출발해 113박, 곡이 끊기는 박에 끝점에 닿는다 |

## 읽는 시간

규칙은 0.3.1과 같다: 초당 4단어 + 숫자 하나에 1초, 최소 2.5초, 시계는 장의 마지막 요소가 자리 잡은 순간부터, 장은 그 뒤 첫 박에서 끝난다. `make_data.py`가 장마다 이것을 박으로 계산해 길이를 정하고(남는 박은 EMBED와 THANKS에 한 박씩), `film.html`은 그 장의 `still` 시각부터 컷까지 모든 프레임이 정확히 `data.json`의 문자열을 그리고, 그 문자열이 움직이지 않고(0.5 px), 들어오는 중인 것이 없는지 확인한다(hold 검사).

| 장 | 마지막 착지 | 읽기(초) | 단어 / 숫자 |
|---|---|---|---|
| TITLE | 5박 + 0.16초 | 2.5 | 3 / 0 |
| BOLT | 16박 + 0.20초 | 4.5 | 10 / 2 |
| DECODE | 30박 + 0.30초(줌) | 4.25 | 5 / 3 |
| PROMPT | 44박 + 0.26초(바꿈) | 2.75 | 3 / 2 |
| SPARKS | 55박 + 0.16초 | 4.0 | 16 / 0 |
| MODELS | 68박 + 0.26초 | 2.5 | 7 / 0 |
| EMBED | 81박 + 0.16초 | 3.25 | 13 / 0 |
| THANKS | 93박 + 0.16초 | 3.0 | 12 / 0 |
| END | 105박 + 0.16초 | 2.5 | 3 / 0 |

MONTAGE(TEXT / VIDEO FRAMES / AUDIO의 빠른 몽타주)는 리드의 결정(2026-10-18)으로 EMBED 안에 합쳤다: 읽기 바닥 아래의 화면이 없다. SPARKS는 실제로 돈 두 대를 그린다.

## 다시 찍기

Mac에서는 작성, 스틸, 한 장씩의 프로브만 한다(브라우저 하나). 전체 렌더와 전수 검사는 박스에서 한다.

```
cd tools/clip/release-034
ln -s ../release-030/.venv .venv        # 또는 python3 -m venv .venv && .venv/bin/pip install playwright==1.63.0 numpy fonttools
.venv/bin/python make_data.py           # 노트(0.3.4 공개 본문)와 README(9723698f2)의 줄을 확인하고 격자에서 data.json을 쓴다
python3 -m http.server 8795 --bind 127.0.0.1 &   # pid를 적고 그 pid만 끈다
.venv/bin/python render.py probe 3.0 8.0 10.6 13.0 16.5 21.0 30.0 34.0   # probe/main/sheet.png: 1080의 절반과 540 폰 화면
```

`render.py`의 주소와 영상 이름은 환경에서 온다(`FILM_URL`, 기본 `http://127.0.0.1:8795/film.html`; `FILM`, 기본 `release-034`). 페이지가 다른 영상이거나 다른 `T`를 읽으면 이름을 대고 멈춘다.

### 박스에서

환경은 `/root/clip034-render/` 안에만 있다: 시스템 Python 3.12 위의 venv에 playwright 1.63.0, numpy, fonttools, pillow 13.0.0(uv, 캐시도 그 안), 그 안의 `ms-playwright/`에 playwright의 chromium 1243과 headless shell. headless shell은 `ldd`로 빠진 라이브러리가 없어서 시스템 패키지는 하나도 깔지 않았다. 스크립트는 `scratch/box/`에 있다(`scratch/`는 무시 목록이라, 다시 찍으려면 이 세 파일을 꺼내 쓴다).

```
rsync -a scratch/box/setup.sh ../../../../bloomery/tools/ref/lease-probe.sh <box>:/root/clip034-render/   # 박스 별칭
ssh <box> 'bash /root/clip034-render/setup.sh'                     # venv와 chromium, 빠진 라이브러리 목록
rsync -a film.html data.json render.py beats.py fonts scratch/box/{serve,drive,post}.sh <box>:/root/clip034-render/
rsync -a music/volt-s1004.mp3 <box>:/root/clip034-render/music/
ssh <box> 'bash /root/clip034-render/serve.sh'                     # 127.0.0.1:8795, pid는 pids/http.pid
ssh <box> 'cd /root/clip034-render && nohup bash drive.sh check 16 > logs/drive-check.log 2>&1 < /dev/null & echo $! > /root/clip034-render/pids/drive.pid'
ssh <box> 'cd /root/clip034-render && nohup bash drive.sh full 16 > logs/drive-full.log 2>&1 < /dev/null & echo $! > /root/clip034-render/pids/drive.pid'
ssh <box> 'bash /root/clip034-render/post.sh'                      # encode, pops, sync, flash; out/video-music.mp4
```

- `drive.sh check|full N`는 프레임 범위 N개(`F0`/`F1`)로 나눠 `render.py`를 띄운다. 모두 `nice -n 19`, CPU만(`CHROME_ARGS=--disable-gpu`). 청크마다 `$!`(nohup과 nice는 exec하므로 그것이 python 자신이다)를 `pids/<mode>-<i>.pid`에 적고, `kill -0`으로만 기다리며, 종료 코드는 `wait`로 읽는다.
- 타이밍 lease와 hold가 모두 내려가 있을 때만 시작한다(bloomery `tools/ref/lease-probe.sh`의 `lease_free`, 공유 잠금 프로브, 그리고 `lease_holds_up`). 렌더 중에 하나가 올라오면 모든 청크의 python에 SIGSTOP을 보내고(그 chromium은 할 일 없이 기다린다), 내려가면 SIGCONT로 잇는다.
- 잰 값(2026-10-18): 한 하위 프레임 ~0.13초(한 청크, 번개 프레임), 16청크 전체 렌더 320초(하위 프레임 14,190장), 빠른 창의 네 겹 그리기(`FAST_K=4`, 아래)를 넣은 마지막 렌더 485초(`sub/` 3.7 GB), 전수 검사 10초. 페이지 오류는 16청크 모두 0이다.

## 음악

`music/volt-s1004.mp3`: 이 영상을 위해 박스의 RTX A6000에서 [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5)(MIT, 모델 카드가 생성물의 상업적 사용을 허용한다)로 만든 곡이다. XL-sft DiT, 4B 5 Hz LM, 50스텝, guidance 7.0, shift 1.0, 48초, 시드 1004, 프롬프트 `volt`(`musicgen/prompts.json`, 172 BPM):

> instrumental energetic drum and bass, fast breakbeat, deep reese bass, glitchy synth stabs, electric sound design, short riser and sudden drop, stop-time hits, futuristic and bright, clean powerful mix, ends on one hard final hit

프롬프트는 장르만 말한다(작가, 곡 이름, 알려진 리프 없음). 세 프롬프트 × 여덟 시드를 타이밍 lease 아래의 배타 작업으로 만들었고(카드 `musicgen/musicgen-034.card`), 고른 이유와 측정은 `DESIGN.md`의 Music 절에 있다. 잰 값: 171.977 BPM, 첫 박 0.3325초, 드롭 23.71초(+8.44 dB), 소리 끝 47.43초. 브레이크비트라 킥이 격자에 14/40만 있다(중앙값 98.7 ms). 사람이 듣는 확인은 아직이다(1단계의 듣기 검사는 보정 곡에서 통과하지 못해 판정이 아니다). 예비 곡은 `volt-s1006`이다. 다른 곡으로 바꾸면 `MUSIC_ID=<id> make_data.py`가 박에 맞춰 다시 정한다(모든 시각이 박 번호에서 나온다). 곡은 리포에 넣지 않는다(`music/`는 무시 목록).

## 화면의 글자와 출처

모든 문자열은 `data.json`의 `copy`에서만 온다. `make_data.py`가 키마다 출처의 줄을 읽어 그 문자열의 낱말이 줄에 있는지 확인하고(`sources`), `film.html`은 `data.json`에 없는 문자열을 그리면 오류를 낸다. 노트는 0.3.4의 공개 릴리스 본문(`release-notes-0.3.4.md`, 173줄), README는 bloomery `9723698f2`이다.

| 화면 | 출처 | 비고 |
|---|---|---|
| `bloomery`, `0.3.4`, `NEMOTRON 3.5 BOLT`, `74B` `-A9B` | 노트 1 | |
| `RTX 3090`, `24 GB` | README 159 (One RTX 3090 24 GB) | |
| `the whole model on the card` | README 168 (Bolt 행) | |
| `DECODE`, `86.69`, `at depth 4096`, `RTX 3090 · 250 W` | 노트 14 | 리드 결정: 노트의 값(README는 86.9) |
| `TOK/S` | 노트 5 | 표의 단위 |
| `PROMPT`, `2,047`, `a 4096-token prompt` | 노트 12, README 161·168 | 2047.32를 README처럼 토큰 단위로 |
| `SEVERAL DGX SPARKS`, `SERVE ONE MODEL`, `NVMe` | README 41 | 그림은 실제로 돈 두 대 |
| `each node pages its experts from its own NVMe` | README 41, 노트 71 | |
| `Qwen3.8`, `GLM-5.3-Flash`, `DeepSeek-V4.1-Flash` | 노트 73, 76 | |
| `over RDMA · by @juliankang4` | 노트 67 | |
| `EmbeddingGemma 2 · EmbeddingGemma v1`, `VIDEO`, `AUDIO` | 노트 1 | |
| `EMBEDDINGS`, `beside the chat model`, `TEXT`, `/v1/embeddings` | 노트 33 | |
| `thank you`, `@juliankang4`, `@Burntgogi`과 각자의 세 낱말 | 노트 165–173 | |
| `github.com/midagedev/bloomery` | 저장소 | |
| `RELEASE` | 없음 | 주장 없는 표지 |

## 주장하지 않은 것

- 다른 엔진의 이름, 숫자, 비율, 견줌은 없다.
- 여러 노드의 속도는 말하지 않는다(노트도 말하지 않는다). SPARKS는 노드가 제 NVMe에서 전문가를 읽는다는 구조만 그린다.
- 화면의 숫자는 모두 그 카드와 조건을 함께 쓴다(RTX 3090 · 250 W, depth 4096, 4096-token prompt). A6000의 숫자와 릴리스 패스의 숫자는 쓰지 않았다.
- 격자의 채우는 속도는 잰 값(초당 86.69칸, 2,047칸)이지만, 칸 하나가 토큰 하나라는 그림이지 측정의 재생이 아니다.
- 누가 만들었다거나 무엇 때문에 빠르다는 문구는 없다.

## 검사와 결과

| 검사 | 무엇을 보나 | 결과 |
|---|---|---|
| `render.py check` | 모든 프레임과 그 여섯 하위 프레임(2,366프레임, 16,562시각)을 래스터 없이 그려: 자리 잡은 글자 44 px 이상, 여백 안(광학 여유 10 px), 자리 잡은 글자끼리 겹치지 않음, 전류의 머리가 글자에서 빛 반경 + 24 px 밖, 어두운 표시 12 px·강조 표시 24 px 이상, `data.json`에 있는 문자열, 장의 hold, 글리프 | 0건(16청크, 10초). 그린 문자열의 글자 중 글꼴에 없는 것 0 |
| `render.py pops` | 양옆 프레임과 다른 한 프레임 | 0 / 2,365프레임 |
| `render.py sync` | 결과물의 그림 변화 시작이 박에서 1프레임 안, 소리의 킥 위상 | 그레인 0.90단계를 뺀 뒤 변화 시작 23개, 23개 모두 박에서 1프레임 안. 컷과 슬램 30개 중 22개에 시작이 있다. 킥 위상 +2.6 ms(+0.15프레임) |
| `render.py flash` | WCAG 2.3.1 일반 섬광: 상대 휘도 0.10 이상의 반대 방향 변화 쌍이 화면의 1/4 이상에서, 1초에 3번 이하 | 넓은 면적의 변화 0, 섬광 0 |
| 시각 판정 | 새 opus 판정관: 16장 시트(540 px)와 전환 세 개의 6프레임. 고친 뒤에는 또 다른 새 판정관 | 첫 판정: 15장과 전환 셋 SHIP, MODELS 한 장 FIX(모델 이름 묶음이 노드 상자에 붙음). 고친 뒤 두 번째 판정: 16장과 전환 셋 모두 SHIP |

- `sync`는 그레인을 바닥으로 읽는다. 그레인은 짝수 프레임마다 새 판으로 바뀌어 그 프레임들의 변화량을 일정하게 올린다(약 0.66 단계). 옛 규칙은 그것을 16프레임마다 박 밖의 시작으로 읽었다(첫 렌더에서 137개 중 120개). 이제 짝수 프레임의 변화에서 그 몫(짝수 프레임과 뒤의 홀수 프레임 변화 차의 중앙값)을 빼고 읽는다. 그렇게 읽은 첫 렌더에는 박 밖의 시작이 넷 남았고, 각각 원인이 있었다: 슬롯 바꿈이 expo-in으로 천천히 시작해 큰 변화가 박 뒤 3–5프레임에 왔고(MODELS 두 번), SPARKS의 전문가 줄과 EMBED의 벡터가 전류가 닿는 박 밖의 시각에 켜졌다. 바꿈은 박에서 바로 빠지게(expo-out) 고쳤고, 전류는 닿는 순간이 박이 되도록 출발 시각과 속도를 정한다.
- `check`의 hold는 같은 문자열이 한 장에 두 번(SPARKS의 `NVMe`) 있어도 n번째끼리 견준다. `74B`와 `-A9B`는 한 낱말의 두 조각이라 서로의 겹침 검사에서 뺀다.

## 색과 글꼴, 바닥선

바탕 ink `#07080A`, 카드 carbon `#121418`, 선 graphite `#2B2E34`, 보조 steel `#8D929B`, 글자 bone `#F2EFE8`, 강조 volt `#FFD21E` 하나. 글꼴은 google/fonts 저장소의 Anybody(폭 50–150, 굵기 100–900의 가변 글꼴: 좁아지는 움직임이 이 폭 축이다)와 Martian Mono(라벨과 조건 줄), 둘 다 SIL OFL 1.1(`fonts/OFL-anybody.txt`, `fonts/OFL-martianmono.txt`). 영상은 폰에서 약 540 px로 보인다. 1080 기준 글자 44 px 이상(폰 22 px), 어두운 표시 12 px, 강조 표시 24 px. 그레인은 540 px 판 여덟 장을 2배로 깔아(1080에서 알갱이 약 2 px, 폰에서 1 px) 두 프레임마다 판을 바꾼다(불투명도 0.06, overlay). 모션 블러는 프레임마다 하위 프레임 여섯 장을 섞어 만들고, 휩 팬은 속도에 맞춘 가로 가우스 블러를 더한다. 카메라가 빠른 세 창(줌, 휩 팬, THANKS로 접힘; 각 컷에서 0.32초)은 하위 프레임마다 네 시각을 그려 평균한다(`FAST_K=4`, 프레임당 24장, Pillow). 여섯 장으로는 줌 가운데에서 글자가 계단처럼 겹쳐 보였다.

## 파일

- `film.html`: 영상 본체. `data.json`(또는 `?data=`)만 읽는다. `window.seek(t)`는 t의 순수 함수다.
- `make_data.py`: 노트와 README의 줄을 확인하고, 박 격자와 읽기 규칙에서 장의 길이와 모든 착지 시각을 정해 `data.json`을 쓴다.
- `render.py`: `check`(F0/F1로 나눠 돌 수 있다), `probe`, `full`(청크), `encode`, `pops`, `sync`, `flash`.
- `beats.py`, `beats.json`: 곡의 박자 격자. `beatsheet.py`: 1단계의 박 계산기.
- `DESIGN.md`, `research.md`, `styles/`: 1단계의 설계, 조사, 스타일 프레임.
- `musicgen/`: 생성 음악의 스크립트와 카드.
- `fonts/`: Anybody, Martian Mono와 라이선스.

## 만든 방법

`render.py`는 0.3.1 영상의 것을 고친 것이고, 그 머리는 [howseen-ai/claude-motion-design](https://github.com/howseen-ai/claude-motion-design) 템플릿(MIT, 저작권 고지는 파일 머리말)이다. 설계, 코드, 문구는 Claude Code(Opus 5.5)가 썼고, 만든 라운드가 스틸을 1080 px과 540 px으로 열어 보았으며, 따로 띄운 opus 판정관이 결과물의 프레임을 판정했다(고친 뒤에는 새 판정관이 다시).
