# bloomery 0.3.4 릴리스 영상, 3판

bloomery 0.3.4 릴리스 영상의 3판 소스다. 1080×1080, 60 fps, 24.77초(71박)이고, 중심은 RTX 3090 한 장에서 실제로 녹화한 toktape 두 개다. 하나는 bloomery 0.3.4, 하나는 llama.cpp b11668이며, 같은 카드, 같은 GGUF, 같은 프롬프트, greedy로 돌렸다. 두 테이프를 각자의 토큰 시각 그대로 나란히 재생하므로, 보는 사람은 숫자를 읽기 전에 차이를 먼저 본다. 1판(`../out/video-music.mp4`, 39.4초)은 "늘려 놓은 것 같고 인상적이지 않다"는 평을 받았다. 3판은 그 자리에 실제 테이프와 더 뚜렷한 화면 문법을 넣었다. 납작한 색면, 기울어진 상자, 굵은 Anybody, 읽는 동안 멈춘 화면이 그것이다. 1판의 파일은 건드리지 않았다. 영상 문구는 영어, 이 문서는 한국어다.

결과물: `out/video-music.mp4` (6,772,473 바이트). Drive 이름은 `bloomery-0.3.4-release-v3-25s.mp4`다.

## 흐름

박 번호는 영상 0초를 0박으로 센다. 곡 `volt-s1006`의 박 격자는 172.002 BPM, 한 박 0.34883초다. 영상은 곡의 19.88초(곡 56박)에서 시작해 곡의 마지막 박(127박, 44.65초)에서 끝나고, 끝에 0.1초 페이드가 있다. 장면 사이의 컷 셋 가운데 둘(15.34초, 20.92초)이 곡의 크래시 박에 떨어진다.

| 초 | 박 | 장면 | 무엇이 움직이나 |
|---|---|---|---|
| 0–2.78 | 0–8 | TITLE | 기울어진(−7°) 주황 띠가 왼쪽에서 쓸려 들어오고 `bloomery`가 꽂힌다. `0.3.4`는 +4° 기운 뼈색 상자에 담긴다 |
| 2.78–15.34 | 8–44 | RACE | 머리 띠에 모델(`NEMOTRON 3.5 BOLT`, `74B-A9B`)이 들어오고, 9박에 `ONE RTX 3090 24 GB`, 두 레인 태그, 바닥글이 선다. 램프 둘이 컷과 다음 박에 켜지고 10박(3.48초, GO)에 꺼진다. GO부터 두 레인은 각 테이프의 토큰 시각대로 흐른다. 첫 토큰 전에는 레인마다 띠 위로 빛이 두 박에 한 번 지나간다. 진행률을 주장하지 않는 대기 표시이고, 그 레인의 첫 토큰 뒤 0.25초 동안 사라진다. 각 레인의 마지막 토큰에 그 테이프의 decode 속도 도장과 체커 깃발이 앉는다. 깃발은 그 뒤 박마다 칸을 바꾼다. 시계는 느린 레인이 끝나는 순간(7.64초)에 멈춘다 |
| 15.34–20.92 | 44–60 | SPARKS | 크래시 박에 뼈색 면이 오른쪽에서 쓸려 들어온다. `TWO DGX SPARKS`, 두 대의 `128 GB`와 그 사이 링크(링크 위로 반 박마다 펄스가 양방향으로 지나간다), `over RDMA`, 두 모델, `@juliankang4` |
| 20.92–24.77 | 60–71 | END | 크래시 박에 주황 면이 왼쪽에서 쓸려 들어온다. 노(爐) 하나가 서 있다. 띠를 두른 점토 굴뚝, 불 켜진 아치 문, 바닥의 송풍관이 있고, 아궁이 위로 불꽃이 일렁이며 불티가 오른쪽 위로 날린다. `bloomery`, `0.3.4`, 주소 |

### 실시간과 공정성

- 두 레인은 같은 GO 순간에 출발하고, 각 토큰은 그 테이프의 `requests[0].tokens[i].t`(요청을 보낸 뒤 ns) 시각에 그려진다. 자르거나 빠르게 한 것은 없다. 화면 바닥글은 `5,680-token prompt · greedy · real time`다.
- 레인의 터미널 스타일(글꼴, 크기, 색, 줄 간격)은 두 레인이 같다. 레인 색(bloomery 주황, llama.cpp 뼈색)은 태그, 진행 막대, 도장, 깃발, 커서, 대기 띠에만 쓴다. 모델과 카드는 두 레인에 걸친 머리 하나에만 적는다.
- 흐르는 터미널 글자는 움직임이라 읽기 바닥에서 빠진다. 다만 각 조각이 그 테이프의 본문이나 지시문의 일부인지는 매 프레임 검사한다(`streamRun`).

## 출처

화면의 문자열은 모두 `make_data.py`가 테이프나 출처의 줄에서 읽어 `data.json`에 쓴다. 손으로 친 숫자는 없다.

- 테이프: bloomery `specs/toktape/boltclip/tapes/`. 각 레인은 `summary.tag`로 찾는다.
  - bloomery: `ours-3090/20261018-071048-nvidia-nemotron-3-5-bolt.toktape`, `arm=boltclip-ours-3090-p4`, bloomery 0.3.4 (85dd39c2f7f1) 릴리스 tarball.
  - llama.cpp: `lcpp-3090/20261018-071116-nvidia-nemotron-3-5-bolt.toktape`, `arm=boltclip-lcpp-3090-p4`.
  - 두 테이프 모두 GGUF `NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB.gguf`, RTX 3090(250 W 상한) 한 장, 프롬프트 5,680토큰, greedy, thinking off다.
  - 모델 이름은 파일 이름에서 `MODEL_NAMES`로 얻는다. 모르는 파일은 거부한다.
  - 카드와 메모리는 `host.gpus`와 `placement.devices`, 엔진과 빌드는 `summary.server`, 속도는 `timings.predicted_per_second`, 프롬프트 크기는 `timings.prompt_n`에서 온다.
  - 파일, 프롬프트(`template.rendered_prompt_sha256`), 샘플링이 다른 쌍, 한 카드의 단일 스트림이 아닌 테이프, dirty 빌드는 이름과 고유 종료 코드로 거부한다.
- `bloomery`, `0.3.4`, `@juliankang4`: 0.3.4 릴리스 본문 1행과 67행.
- `DeepSeek-V4.1-Flash`, `GLM-5.3-Flash`, `347 GB`, `over RDMA`, 주소: bloomery `README.md` @ 9723698f2의 41, 18, 48행.
- `TWO DGX SPARKS`, `128 GB`: PR #420 본문 105행(`sources/sparks-420.md` 10행). Spark 장면에는 tok/s가 없다. PR이 속도를 주장하지 않기 때문이다. 347 GB 모델이 128 GB 한 대에 들어간다는 주장도 하지 않는다.

## 읽는 시간

규칙은 1판과 같다. 초당 4단어에 숫자 하나마다 1초를 더하고, 최소 2.5초다. 시계는 묶음의 마지막 요소가 자리 잡은 순간부터 잰다. RACE에서는 각 묶음이 자기 착지부터 컷까지 머물고, 모든 묶음의 읽기 시간을 합한 값이 첫 착지와 컷 사이에 들어가야 한다. 달리는 시계는 계기로 보고, 멈춘 값은 끝 묶음의 숫자 하나로 센다.

| 묶음 | 단어 / 숫자 | 읽기(초) | 머무름(초) |
|---|---|---|---|
| TITLE | 2 / 0 | 2.50 | 2.58 |
| RACE 준비(모델, 크기, 카드, 메모리, 두 엔진, 바닥글) | 11 / 4 | 6.75 | 12.05 |
| RACE 끝(두 도장, tok/s, 멈춘 시계) | 1 / 3 | 3.25 | 3.92 |
| SPARKS | 8 / 2 | 4.00 | 4.33 |
| END | 3 / 0 | 2.50 | 2.98 |

`film.html`의 hold 검사는 묶음마다 `still` 시각부터 컷까지 확인한다. 정확히 그 묶음의 문자열을 그리는지, 문자열이 0.5 px 넘게 움직이지 않는지, 들어오는 중인 문자열이 없는지다. 깃발, 대기 띠, 링크 펄스, 불꽃과 불티는 글자가 아닌 표시라서 읽는 동안에도 움직인다.

## 다시 찍기

Mac에서는 작성, 스틸, 프로브만 한다(브라우저 하나). 전수 검사와 전체 렌더는 박스에서 한다.

```
cd tools/clip/release-034/v3
ln -s ../../release-030/.venv .venv       # playwright 1.63.0, numpy, fonttools
.venv/bin/python make_data.py            # 테이프, 노트, README 줄을 읽고 beats.json의 격자에서 data.json을 쓴다
python3 -m http.server 8797 --bind 127.0.0.1 &   # pid를 적어 두고 그 pid만 끈다
PROBE_TAG=main .venv/bin/python render.py probe 1.8 4.6 9.0 12.5 18.6 23.5   # probe/main/sheet.png
```

`render.py`는 1판의 것을 복사해 네 군데를 고쳤다. 기본 주소는 `http://127.0.0.1:8797/film.html`, 기본 이름은 `release-034-v3`다. 글리프 검사에 `AnybodyItalic`을 넣었고, 인코딩 CRF는 환경 변수 `CRF`로 받는다.

### 박스에서

환경은 1판이 만든 `/root/clip034-render/` 안에만 있다. venv, `ms-playwright/`, `lease-probe.sh`가 거기 있고, 3판은 그 아래 `v3/`를 쓴다. 스크립트는 `box/`에 있다.

```
ssh <box> 'mkdir -p /root/clip034-render/v3/music'
rsync -a film.html data.json render.py beats.py beats.json fonts box/drive.sh box/serve.sh box/post.sh <box>:/root/clip034-render/v3/
rsync -a music/volt-s1006.mp3 <box>:/root/clip034-render/v3/music/
ssh <box> 'bash /root/clip034-render/v3/serve.sh'           # 127.0.0.1:8797, pid는 pids/http.pid
ssh <box> 'cd /root/clip034-render/v3 && bash drive.sh check 16'
ssh <box> 'cd /root/clip034-render/v3 && bash drive.sh full 16'
ssh <box> 'bash /root/clip034-render/v3/post.sh'            # encode(CRF 18), pops, sync, flash; out/video-music.mp4
```

- `drive.sh check|full N`는 프레임 범위를 N개로 나눠 `render.py`를 띄운다. 모두 `nice -n 19`, CPU만 쓴다(`--disable-gpu`). 청크마다 `$!`를 `pids/<mode>-<i>.pid`에 적고 `kill -0`으로만 기다린다.
- 타이밍 lease와 hold가 모두 내려가 있을 때만 시작한다(`lease_free`, `lease_holds_up`). 도중에 하나가 올라오면 청크들을 SIGSTOP으로 세웠다가, 내려가면 SIGCONT로 잇는다.
- 잰 값(2026-10-18): 16청크 전수 검사 10초, 전체 렌더 45초(1,486프레임 × 하위 프레임 6장). 16청크 모두 페이지 오류 0이다.

## 음악

`music/volt-s1006.mp3`는 1판의 `volt-s1004`와 같은 배치에서 나왔다(`../music/clip034/manifest.tsv`의 `volt 1006 172 48.0` 행). 생성은 박스의 RTX A6000에서 [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5)로 했다. 라이선스는 MIT이고, 모델 카드가 생성물의 상업적 사용을 허용한다. 프롬프트는 `volt`, 시드는 1006이며, 생성 설정은 `../README.md`의 음악 절에 있다. 사용자가 고른 곡이다. 드롭은 없다.

## 검사 (2026-10-18, 마지막 렌더)

```
check: 16 chunks, PAGE ERRORS: 0 (each), GLYPHS: 0 characters missing from their face
pops:  frames: 1486 pops: 0
sync:  picture: 16 change onsets, 16 within one frame of a beat; 6 of the 7 cut and slam times have an onset
       sound: kick phase -0.9 ms from the picture's beats (-0.05 frames)
flash: 8 large-area transitions, 3 flashes, at most 2 in any 1 s (limit 3)
```

일곱 번째 시각(END 묶음의 마지막 착지인 주소, 21.62초)은 `rise`로 부드럽게 들어와서 바뀜 문턱 0.5 아래(프레임당 0.27–0.36)에 머문다. 박 밖의 바뀜은 없다.

## 판정

새 opus 비전 판정을 두 번 받았다.

- 1차: 레인의 공정성과 540 px 이름 가독성은 SHIP. 성격, 속도감, 끝 카드는 FIX였다. 1판보다는 낫지만 ember보다 덜 강렬하고, 도장이 작고, 프롬프트 대기와 끝난 뒤의 정지가 길고, 노 마크가 종이나 병으로 읽힌다는 것이다. 고친 것은 이렇다.
  - 도장을 96에서 136 px로 키웠다.
  - 깃발이 박마다 바뀐다.
  - 대기 띠를 넣었다.
  - 램프가 GO에 사라진다.
  - 링크 펄스를 넣었다.
  - 노를 다시 그리고 불꽃과 불티를 넣었다.
- 2차: 성격, 가독성, 공정성, 끝 카드 모두 SHIP. 1판보다는 분명히 낫고, ember보다는 근소하게 낫다는 판정이다. 속도감은 FIX로 TITLE을 한 마디 줄이자고 했지만, TITLE은 읽기 바닥(2.5초)에 붙어 있다. 판정문 스스로 "바닥 규칙이 덮으면 SHIP"이라고 했다. 송풍관은 막대처럼 읽힌다는 선택 지적이 있었고, 손대지 않았다.
