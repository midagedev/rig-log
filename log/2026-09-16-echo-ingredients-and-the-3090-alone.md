# 나라 제외 라이선스, 얼굴 못 잡는 모델, 분할 화면에 복사된 시트, 작은 카드 단독 서빙

*2026-09-16, 15:30–19:40.* 한 오후 네 갈래, 같은 기계 전부 측정. 앞 둘이 이 상자 돌릴 비디오 모델에 대한 것, 셋째가 참조 시트 그리는 법의 결함과 이제 잡는 gate, 넷째가 서빙 LLM을 24 GB 카드에 옮겨 48 GB 카드를 디퓨전 작업에 비우는 것이다.

## MiniMax-H3는 받기 전에 읽었고, 읽기가 끝냈다

오후 계획이 오디오 든 최대 오픈 비디오 모델이었다. MiniMax-H3, 33 B dense omni-transformer에 Qwen3-VL-32B 텍스트 인코더, 프롬프트 native 멀티샷, CFG 증류, diffusers 0.40 파이프라인이 상자에 있다. 가중치 받기 전에 라이선스 파일을 읽었다. IV조가 *Excluded Territories* — EU·영국·미국·**대한민국** — 를 나열하고, IV.4가 허용 지역 밖 사용과 출력 사용 둘을 금한다. 허브의 `apache-2.0` 재라벨 커뮤니티 파생이 그대로 싣고 있다. 받은 것 없다. 결정이 사용자 것이고, 질문이 다시 안 나오게 여기 기록한다.

## JoyAI-Echo 1.5: 세우고, 재고, 내려놓다

대안 서베이가 JD의 JoyAI-Echo 1.5(LTX-2.3 베이스, 8스텝 DMD 증류, Gemma-3-12b-it 인코더, 메모리 오디오 든 참조 슬롯 최대 일곱, 프롬프트 내부 컷, 25 fps에 9.6초). 2단이다. 컨디셔닝 인코더(Gemma + VAE + 보이스 필터 → 요청당 `.safetensors` 하나)와 DiT. 러너 [`tools/echo/echo-take.sh`](../tools/echo/echo-take.sh). LTX 러너와 임대·idle·증인·센티널 계약 동일.

| 단, consumer bf16 구성, resident 0, prefetch 1 | wall | VRAM 피크 | 호스트 RSS |
|---|---:|---:|---:|
| encode, 예제 요청 66 | 71초 | 23.6 GB | 32.8 GB |
| encode, 1요청 | 12초 | — | 8.4 GB |
| generate, 로드 | 22초 | | |
| generate, denoise | 136–158초 | **14.8 GB** | **74.4 GB**(34.6 GiB 핀 블록 가중치) |
| generate, 디코드 | 15초 | | |
| generate, 합계 | 156–213초 | | |

둘 둔다. 14.8 GB 피크가 트랜스포머 블록 전부를 핀 호스트 메모리에 오프로드해 하나씩 스트리밍한 것이라 24 GB 카드에 9 GB 남기고 든다 — `resident_blocks` 노브를 안 돌렸고 48 GB 카드의 33 GB가 매 테이크 idle이었다. 프롬프트가 요청 로더 안 가드에 **1,500자**에 잘린다. 2,534자 샷 목록이 첫 시도에 첫 막에 잘렸다. 조용히.

내려놓은 이유는 품질이다. 클립 보고 사용자가 판정(이 리포가 자기 비디오에 자기 모델 등급을 안 매긴다). 컷 따라 스타일 붕괴, 고양이 얼굴이 다른 만화 고양이에 drift, 액션 비트 미착. LTX-2.3 베이스와 8스텝 증류 탓이지 노브가 아니다. 같은 컨셉 첫 LTX-2.5 테이크가 훨씬 낫다고 해서 오후가 LTX-2.5에 돌아왔다.

판정 내린 Echo 클립 둘, 올린 그대로: [결투, 컨셉 슬롯](https://drive.google.com/file/d/1sSN_pkisoXmD8MxiVCta1DkSM11B3jXi/view)(1.83 MB), [괴수 대치](https://drive.google.com/file/d/1zxd1JwfVGTjEz6q-RSp0ejGGGqPAiheN/view)(3.82 MB).

지나며 찾은 구멍 하나. **상자에 ffmpeg이 없었다.** Echo 오디오 합치기가 조용히 깨지고 wav를 무음 mp4 옆에 썼다. apt에 6.1.1 설치하고 첫 클립 손으로 합쳤다.

## LTX-2.5 Ingredients IC-LoRA: 컨디셔닝용 참조 시트

Lightricks가 2026-09-10에 `LTX-2.5-22b-IC-LoRA-Ingredients`를 냈다. 참조 시트(캐릭터 얼굴·턴어라운드·소품·장소 패널당 하나, 검정 바탕, 텍스트 없음)를 출력 지오메트리 121프레임 이상 **정적 비디오**에 주고, 2부 프롬프트 — `Reference sheet: … / Generated video: …`. 러너가 `PIPE=ic_lora`, `LORAS="PATH STRENGTH"`, `VIDCOND="PATH STRENGTH"`를 얻었다([`tools/ltx/ltx-take.sh`](../tools/ltx/ltx-take.sh)). 시트 자체는 Krea-2 Turbo 프롬프트 렌더를 ffmpeg에 121프레임 루프했다. `ic_lora.py`가 2단 증류 파이프라인이라 `WH="1536 896"`이 stage 1을 LoRA 학습 768×448 버킷에 둔다.

| 테이크 | 로드 포함 wall, `--offload disk` | VRAM 피크 | 호스트 RSS | 출력 | 시트 · 클립 |
|---|---:|---:|---:|---|---|
| 첫 시트, 빌딩 사이 회색 고양이 | 145초 | 29.2 GB | 43.6 GB | 1536×896, 5.04초, 오디오 있음 — 한 장면 | [시트](https://drive.google.com/file/d/14-s6UHCkcMJdRqlOseBX4w_BKO9a_yVP/view) · [클립](https://drive.google.com/file/d/1kf7x_8WZngmZqgcdsq-i16UY47u3V_3X/view) |
| 울트라맨급 시트, 회색 고양이 | 130초 | | | 판정: **4분할 화면** | [시트](https://drive.google.com/file/d/1kxHgZwdpndAImDUaXbBV9hB3v3GZeDfq/view) · [클립](https://drive.google.com/file/d/1wbb5CzZOgKle4OpYI6luDIIxt24nV67K/view) |
| 같은 시트 스타일, 주황 고양이 | 131초 | | | **4분할 화면** | [시트](https://drive.google.com/file/d/1dHxTSpkXk7z8hO8wfAOxbgi6ZS5YYtC5/view) · [클립](https://drive.google.com/file/d/1PvTO3fhPlDG6MngTzDfk4CPMc-tfq3m2/view) |
| 카탈로그 시트, 주황 고양이, ref 1.0 | 147초 | | | ~~단일 프레임~~ 4분할(아래 struck) | [시트](https://drive.google.com/file/d/1zTlEeUIfU5jX-lWa5ZlTcbkeBnp7QzFN/view) · [클립](https://drive.google.com/file/d/1PvTO3fhPlDG6MngTzDfk4CPMc-tfq3m2/view) |
| 카탈로그 시트, 주황 고양이, ref 0.75 | 132초 | | | ~~단일 프레임~~ 4분할(아래 struck) | 같은 시트 · [클립](https://drive.google.com/file/d/1UC54djC20-aNxKE1D21EBG-gpQlMhfFi/view) |

이 절 모든 클립이 러너 붙인 이름에 사용자 Drive에 있다. 시트는 Krea-2 낸 4후보 컨택트 시트다.

### 시트가 분할 화면에 복사됐고, 이유

둘째·셋째 클립이 4패널에 나왔다 — 시트 레이아웃을 그 자리에 애니메이트, 고양이·메카 같은 프레임 없음. 비전 판정(별도 에이전트, 시트 셋과 클립당 중간 프레임 하나씩, 레이아웃만 질문)이 클립 거터 지오메트리가 시트와 **픽셀 단위** 일치함을 찾았다. 된 시트와 안 된 둘의 차이를 지목했다. 검정 양이 아니다 — 된 시트가 순검정 32%, 안 된 것들이 13–17%다. 검정이 프레임을 그리는가다. 된 시트 4패널 중 둘이 순검정에 잘린 피사체(엣지 링 값 0, 거터와 무구분)라 보이는 직사각형 둘, 대각 배치다. 시트가 애셋 보드에 읽히고 모델이 장면을 구성한다. 안 된 시트 모든 패널이 직사각형 채우는 완성 필름 프레임(엣지 링 13–155)이다 — 결정적으로 우상 패널이 *거대 고양이의 도시 기립* 프롬프트였는데, 비디오가 구성해야 할 장면 그 자체였다. 목표가 이미 4매트 프레임 중 하나라 구성할 것이 없고, 모델이 그리드를 애니메이트했다.

고침이 클립 프롬프트가 아니라 시트 단계에 있다. 캐릭터·메카 패널이 순검정 잘라내기에 돌아갔고, "빌딩이 무릎에 닿는" 스케일이 `Generated video:` 텍스트에만 갔다. 재발 층이 [`tools/img/ref-sheet-gate.py`](../tools/img/ref-sheet-gate.py)다. 사분면마다 안쪽 엣지 링 밝기 중앙값에 bounded 프레임 읽기 패널을 센다. 실제 파일 FAIL-first:

| 시트 | 순검정 | 엣지 링 TL TR BL BR | 프레임 읽기 패널 | gate(최대 2) |
|---|---:|---|---:|---|
| 첫(됨) | 32.1% | 60 · 0 · 0 · 67 | 2 | pass |
| 울트라맨 회색(분할) | 16.6% | 26 · 37 · 155 · 50 | 4 | **refused** |
| 울트라맨 주황(분할) | 13.4% | 43 · 30 · 14 · 56 | 4 | **refused** |
| 카탈로그 주황, 4후보 전부 | 39–41% | 0–1 · 0 · 0 · 52–59 | 1 | pass |

체인([`tools/ltx/ingredients-chain-example.sh`](../tools/ltx/ingredients-chain-example.sh))이 4후보에 gate 돌리고 통과 첫 것을 취한다. ~~클립의 두 번째 기계 체크 — 중간 프레임 완전 검정 안쪽 열·행 — 이 분할 클립 26열 20행, 카탈로그 시트 클립 둘 0·0에 읽는다.~~ **2026-09-16 20:15 Struck.** 사용자가 카탈로그 시트 클립 둘을 보고 4분할이었다. 열 체크가 놓친 것은 경계가 내용 엣지(불 켜진 거리 위 검정 void, 밝은 옆 어두운 패널)라 검정 줄이 아니라서다. 검정 줄 검출기가 아무것도 안 쏜다. gate 뒤 패널 수 이론도 안 선다. 카탈로그 시트가 bounded 프레임 하나로 읽히고 gate 통과하고도 그리드에 복사됐고, *된* 테이크 프롬프트 그대로 고양이 색만 바꾼 새 시트(gate: 2패널, 된 시트와 같)가 샘플 3프레임 전부 검정 거터 2×2 분할을 냈다. gate가 트리에 남는 것은 시트 측정이지 클립 예측이 아니다.

이어서 분리 arm이 말했다(분할 카탈로그 시트 클립 상대 변경 하나씩, 각 5/60/115프레임 비전 판정).

| arm | 변경 | 레이아웃 | 두 거인 |
|---|---|---|---|
| stage 1만(768×448 출력) | stage 2 스킵 | 끝까지 분할 | 분리 |
| 된 테이크 *프롬프트*([클립](https://drive.google.com/file/d/16EosVn0AyhLczgVbLFUCN1UkR9nfR95t/view)) | 프롬프트 텍스트 | f5 분할, f60 한 거리 | 같은 공간, 고양이 너무 작음 |
| 된 테이크 *시트*(회색 고양이, [클립](https://drive.google.com/file/d/1PKD8Lxe-4w_gxHHs0qFbTe1A0s4nt_C3/view)) | 참조 시트 | 한 장면(f5 inset, f60 소멸) | 같은 공간, 고양이가 메카에 다가감 |
| 참조 어텐션 0.5 | 어텐션 스케일 | 한 장면 | **한 몸**: 메카에 고양이 머리 |
| 참조 어텐션 0.25 | 어텐션 스케일 | 한 장면 | f5 뒤 고양이 소멸 |

그리드가 stage 1에 LoRA 자체 학습 버킷에 만들어진다. 푸는 레버 둘이 프롬프트와 시트다. 도움 될 것 같은 노브 — 참조 토큰 어텐션 스케일 — 하나가 분할을 둘 정체성 융합에 맞바꾼다. 낮을수록 나쁘다. 참조 *strength*가 이름 반대로 돈다. 1.0이 참조 latent를 깨끗하게 두고, 낮은 값이 타깃에 노이즈를 걷고, 0.75가 1.0보다 시트의 더 문자적 복사였다. 어느 시트가 복사되고 어느 시트가 구성되는지는 이 로그가 아직 말할 규칙이 아니다. 첫 된 테이크가 지금까지 증거상 outlier다 — 측정했다. 된 테이크의 시트 프롬프트·비디오 프롬프트 그대로 고양이 색만, 시드 23·24·25·26에 분할 / 분할 / 한 몸(분할 첫 프레임 뒤 고양이 머리 메카) / 분할. **넷 중 0 구성**이다([시트](https://drive.google.com/file/d/1vlNHlRkMJ4naBewMe9EcVfn-8vZEq5Ov/view), [시드 23 클립](https://drive.google.com/file/d/1SWUZ6HbjUG4kLnu1YhPhJFGe_i1zRlT4/view)).

구성한 것은 매 샘플 프레임 frame 0 고정이었고, 레시피가 시트 옆에 `IMAGE="<구성 키프레임> 0 1.0"`이다(키프레임이 Echo 시도용 만든 거리 둘 거인 Krea-2 스틸). 끊김 없는 거리 레벨 샷 하나, 둘 거인 6–10층 파사드 상대, 5프레임 메카 가슴 고양이 발, 60 반동, 115 그래플([클립](https://drive.google.com/file/d/1Uwan0irUgPxlUuLcXZBGcbNdna7mUvF3/view)). 고양이가 회색에 나온 것은 키프레임이 회색이라서다 — frame 0 생김새는 프롬프트가 아니라 고정 이미지가 정한다. 시트 일이 움직임 중 정체성 유지에 줄어든다. 앞으로 레시피다. **키프레임에 구성하고, 시트에 정체성을 잡는다.** 주황 키프레임에 확인했다(같은 키프레임 프롬프트 색만, Krea-2, 4중 후보 1). 매 샘플 프레임 끊김 없는 샷 하나, 둘 거인 8–9층, 5프레임 어깨 발, 60 가드, 115 웅크린 클린치, 고양이 주황 내내 같은 고양이, 메카 내내 같은 설계. 132초([키프레임 후보](https://drive.google.com/file/d/1sSN_pkisoXmD8MxiVCta1DkSM11B3jXi/view), [클립](https://drive.google.com/file/d/107s9bm6W4MIbEHioIe1yfGqgSSR2V6w5Z/view)). `IMAGE=` 첫 프레임 컨디셔닝과 `EXTRA=` passthrough가 [`tools/ltx/ltx-take.sh`](../tools/ltx/ltx-take.sh)에 있다.

같은 라운드 앞 17분 날린 chain 스크립트 실수 하나. 시트 러너가 안 쓰는 센티널 파일행 `until grep … take.log` 대기(stdout 로그)와 `run.log`에 없는 fallback 구절. 카드 둘 빈 상자가 idle에 있었다. 로그가 아니라 산물을 기다린다(출력 디렉터리 이미지 수). 다른 프로세스가 쓸 수도 안 쓸 수도 있는 로그가 아니다.

## 24 GB 카드 단독 서빙 모델

아침 기록이 3090 빼는 서빙 V4.1 프로파일 값을 디코드 3% 미만이라 쟀다. 오후가 역을 물었다. **3090 단독에 서빙 가능한가.** A6000을 하루 종일 디퓨전 작업에 비우려고. 러너 [`tools/v41/v41-3090-only.sh`](../tools/v41/v41-3090-only.sh), 한 카드 러너 파생이다. `CUDA_VISIBLE_DEVICES=<3090>`, `-ot "exps=CPU"`(호스트에 expert 40층 전부), 어텐션·hyper-connection·KV·DSpark draft 카드에, `GGML_CUDA_NO_PINNED_WEIGHTS=1`, 같은 다섯 프롬프트 `n_predict` 200, temperature 0, 프롬프트 캐시 없음. 컨텍스트 arm 둘.

| arm | 3090 VRAM | 로드 | cold 디코드(3) | warm 디코드(2) | draft accept |
|---|---:|---:|---|---|---|
| 3090 단독, 16k | 19.7 GB | 199초 | 14.5 / 21.0 / 19.8 | 19.9 / 25.5 | 39–59% |
| 3090 단독, **64k** | **22.5 GB** | 179초 | 12.5 / 20.7 / 19.9 | **19.8 / 25.4** | 같은 토큰 |
| A6000 단독, 카드에 expert 4.5층(아침) | 47.3 GB | — | 16.1 / 22.4 / 20.1 | 21.6 / 25.9 | |

warm 디코드가 GPU에 expert 0층 A6000 arm 2% 안이다. 64k 컨텍스트가 16k 대비 2.8 GB 들고 카드에 1.5 GB 남는다. 첫 cold 프롬프트가 리부트 뒤 NVMe 첫 engram 행이다. 그 주 모든 기록과 같다. 두 번째 패스에 없다. draft 통계가 두 arm 바이트 동일(같은 장치·같은 수치)이라서, 아침 2카드/1카드 비교와 달리 draft-accept 채널 교란이 여기 없다.

이제 서빙 구성이다. [`configs/v41-3090-serve.sh`](../configs/v41-3090-serve.sh), [`configs/llm-3090.service`](../configs/llm-3090.service) 뒤(`Conflicts=llm.service`라 두 프로파일이 카드 동시 점유 불가). 첫 시작이 `203/EXEC` 8연패했다. 스크립트가 상자에 mode 644에 떨어졌다. 4 디퓨전 러너(`ltx`·`img`·`echo`·`music`)가 "모든 GPU 2 GB 미만"에 걸리는데, 3090이 서빙 모델 쥐면 매 테이크 거부했을 것이다. `maxgpu`가 이제 A6000만 UUID에 읽는다. 쓰는 카드 idle이 필요한 카드라서다.

엔드포인트 첫 클라이언트가 [Hermes Agent](https://github.com/nousresearch/hermes-agent)다. 상자 사용자 계정 설치(`~/.hermes/config.yaml`: `provider: custom`, `base_url: http://127.0.0.1:8001/v1`, `context_length: 65536` — 도구 사용에 64k 미만 거부가 64k arm이 문제던 이유다). 설치가 `Failed to write to the distribution cache`에 한 번 깨졌다. root ssh 위 이른 `uv` 실행의 root 소유 `~/.cache/uv/builds-v0`와 아카이브 항목들. `chown -R user:user`에 재실행 고쳤다. Hermes가 로드 중 서버에 닿았다(`HTTP 503: Loading model`) — 배선이 맞았다. 첫 도구 사용 턴이 아니었다. **모든 tool call이 plain text에 돌아왔다.** 이유가 업스트림 결함, 아래다.

## DeepSeek V4.1이 tool-call 마크업을 바꿨고, llama.cpp가 못 봤다

도구 든 요청에 모델이 답했다.

```
<｜DSML｜ calls>
<｜DSML｜ invoke name="get_weather">
<｜DSML｜ parameter name="city" string="true">Seoul</｜DSML｜ parameter>
```

서버가 전부 `content`에 돌려주고 `tool_calls: null`을 냈다. `tool_choice: required`에도. Hermes가 tool call 0에 봤다. 순서대로 측정에 배제한 것. DSpark draft(draft on/off 토큰 id 동일), GGUF 어휘(id 10699/34756/10767이 릴리스 `tokenizer.json`에도 `Ġcalls`·`Ġinvoke`·`Ġparameter`), 토크나이저(문자열 다섯, HF `tokenizers` 대 `/tokenize` id 동일), 프리토크나이저 프리셋(`joyai-llm` 정규식 셋이 릴리스와 바이트 동일). 모델이 맞았다. 릴리스가 `encoding/encoding.py`에 `tool_calls_block_name = " calls"`를 싣고, README 첫 줄에 말한다. *"DSML 태그명이 leading space를 쓴다 … V4 포맷은 공백 없이 `<｜DSML｜tool_calls>`를 썼다."* GGUF 내장 채팅 템플릿이 V4 것이다(릴리스 `models/templates/deepseek-ai-DeepSeek-V4.jinja`와 1바이트 차이). `common/parsers/deepseek.cpp`가 V4 이름을 하드코드한다. 포크·`ggml-org/llama.cpp` master 어느 쪽도. 이슈·PR 언급 없음.

고침이 엔진 포크 브랜치 파일 셋이다. 바뀐 태그명 셋 V4 템플릿(`models/templates/deepseek-ai-DeepSeek-V4.1-Flash.jinja`), 템플릿이 짓는 `' calls>` 리터럴 키 V4.1 파서 분기, V4 블록 거울 테스트 넷. FAIL-first 섰다. 템플릿·테스트 들고 파서 안 손대면 `test-chat`이 V4.1 tool-call 케이스에 죽는다. 파서 패치에 `test-chat` 통과. 업스트림 master(포크 베이스 앞 59커밋)에 충돌 없이 cherry-pick. 서버가 템플릿을 파일에 받는다(`--chat-template-file`). GGUF 내장 것이 틀려서다. 내장 템플릿 고칠 자리가 convert PR(#28696)이다.

| 패치 뒤 | 결과 | tok/s |
|---|---|---:|
| `tool_choice` auto, 날씨 질문 | `get_weather({"city":"Seoul"})` 파싱 | 26.6 |
| `tool_choice` required, 터미널 | `terminal({"command":"ls -la /tmp"})` | 27.7 |
| 도구 불필요 | `391`, 호출 없음 | 17.1 |
| 히스토리에 tool result | 쓰는 산문 답 | 16.2 |

Hermes가 진짜 턴을 돌렸다. 7분 8초 tool call 여덟. `nvidia-smi`·프로세스 목록·`/v1/models`·서버 명령줄 읽고, 자기 모델이 GPU 0·3090에 앉는다고 답했다. caveat 정확 — expert 텐서가 `-ot exps=CPU` 밑 호스트에 있고 카드 22.6 GB가 어텐션·dense 가중치·64k KV 캐시. DSML 보일러플레이트에 디코드 27 tok/s(draft가 거의 전부 accept), 산문 16–17.

### 에이전트가 맞고 못 써서, 빠른 모델이 카드를 가져갔다

V4.1 Hermes 턴이 프리필·reasoning 지배지 디코드가 아니다. 위 여덟 도구 턴이 7분 8초. 에이전트 너머 warm "17×23이 뭐냐" — 시스템 프롬프트·tool 스키마·메모리·스킬 수만 토큰 앞에 — **5분 3초**가 걸렸다. 같은 카드 빠른 절반 서빙이 대신한다([`configs/qwen36-3090-serve.sh`](../configs/qwen36-3090-serve.sh). Qwen3.6-35B-A3B UD-Q4_K_XL 3090 통째, q8_0 KV 64k 컨텍스트, 템플릿 kwarg thinking off, `llm-qwen-3090.service`).

| 3090 단독 | V4.1(Q3, 호스트 expert, draft) | Qwen3.6-35B-A3B Q4_K_XL |
|---|---:|---:|
| VRAM | 22.5 GB | 22.3 GB |
| 디코드, tool call / 산문 | 27 / 16–17 tok/s | **140 / 150 tok/s** |
| 프리필(331토큰 tool 프롬프트) | ~60 tok/s(서빙 프로파일) | **1,172 tok/s** |
| Hermes: 여덟 도구 GPU 질문 | 7분 8초 | **10초**(tool call 둘) |

tool call이 native 파싱(Qwen3 포맷, 템플릿 작업 없음). 24 GB 카드 140 tok/s가 09-15 48 GB 카드 140에 맞는다 — 그 기록 찾은 ~390 GB/s 상한이 어느 카드 대역폭도 아니다. 두 프로파일이 systemd 충돌한다. 3090 쥐는 것이 이제 선택이다. 폰 앞 봇에는 이것이다. V4.1은 A6000이 비디오에 안 바쁠 때 느리고 꼼꼼한 모델 자리 유지한다.

미확정: *틀린* 템플릿에 `tool_choice: required`가 샘플링도 안 묶었다. GBNF 문법과 `/completion` JSON 스키마가 같은 서버에 잘 묶는데. PEG-native 파서 문법이 dflash draft 경로 밑 샘플러에 닿는가는 별개 질문으로 남는다.

## 48 GB 카드 200만 원, 조사하고 거절

Quadro RTX 8000 중고가 200만 원에 나왔다(Turing TU102, 48 GB GDDR6 672 GB/s, 260 W 블로워, fp16/int8 텐서 코어, **bf16 없음**). 미국 중고 $1,975 대, 중고 A6000 $2,600–4,370. 여기서 안 쟀다. 공개 측정과 이 상자 자체 숫자에 읽기다. 짧은 컨텍스트 dense 디코드가 대역폭을 탄다(외부 8–14 B 벤치: RTX 8000 52.5 tok/s 대 A5000 57.1). 32k 컨텍스트에 같은 출처가 Qwen 32B Q4를 **RTX 8000 11 tok/s 대 3090 하나 35**에 쟀다 — 대역폭 72%에 3배 느리다. 긴 컨텍스트 어텐션이 Turing에 연산-bound라서다. llama.cpp가 Turing MMA 플래시어텐션 커널을 싣는데도. 64k 컨텍스트 에이전트가 정확히 그 체제고, 3090이 V4.1을 거기 25 tok/s에 서빙한다(위 표). 디퓨전 일꾼으로는 이 상자 bf16 모델을 native에 못 돌린다(LTX-2.5 허브 fp16 파일 요청이 2026-08-12부터 무응답, Z-Image에 open fp16 NaN 이슈). ExLlamaV3 양자화가 안 돌아서 09-15 재는 exl3 길이 닫힌다. 거절. 두 번째 3090이나 중고 A6000이 이 상자 하는 일에 맞는 카드다.
