# llama-server 표면 뒤 ExLlamaV3: exl3-serve, TabbyAPI timings, `time_generate`의 측정 대상

2026-09-15 저녁. 워크스테이션, GLM-5.3-Flash EXL3 4.05 bpw(`/models/GLM-5.3-Flash-exl3-4.05`), exllamav3 1.5.0(GitHub 휠 `+cu128.torch2.10.0`, torch 2.10.0+cu128). 매 로드 `-gs 44,21 -mcs 185 -mct 32 -cs 32768 -mtp`, draft depth 1 — `log/2026-09-15-glm-5.3-flash-first-run.md`의 서빙 프로파일.

## 이유

녹음기 [toktape](https://github.com/midagedev/toktape)는 llama-server에 붙는다. `/props`를 읽고 `/v1/chat/completions`을 스트리밍하고 서버 `timings`를 자체 토큰 수에 대조한다. ExLlamaV3에 그런 서버가 없어서, 그날 per-expert 배치 숫자를 녹음할 수 없었다. 병렬 두 길. 한 exllamav3 모델 위에 그 표면을 내는 작은 파이썬 앞단(exl3-serve, 미공개), 그리고 TabbyAPI — exllama 프로젝트 자체 OpenAI 호환 서버 — 에 없는 필드 하나(이슈 #454, toktape 세션이 패치 준비, 여기서 검증) 패치. TabbyAPI는 llama-server식 `/props`·`/apply-template`을 이미 달고 있었다(2026-09-07 추가). 녹음기에 없는 것은 `timings`, `/slots`, `prompt_progress`, 배치 정보다.

## 엔진 블록, 파일 대조 측정

녹음기 카드가 `/props`의 `engine` 객체에서 모델·배치를 찍는다. 규칙은 잰 값 아니면 생략이다. 기준값은 safetensors 헤더에서 계산, 서빙 블록을 로드 시점에 대조했다.

| 필드 | 기준(디스크) | 서빙 |
|---|---|---|
| 파일/바이트(히든 제외 최상위) | 30 / 165,151,541,665 | 동일 |
| 파라미터(텍스트 모델, MTP·vision 제외) | 313,326,811,966 | 동일 |
| 토큰당 active 바이트(dense 전부, 임베딩 1행, top-8 expert) | 10,979,084,996 | 동일 |
| 퀀트 | `quantization_config.json`: bits 4.05, head_bits 6 | "EXL3 4.05 bpw · head 6.0" |
| CPU 워커 expert(185 × 12,619,788 B × 42층) | 98,055,752,760 | CPU에 포함 |
| 카드 KV 캐시(캐시 + draft 캐시) | 419,430,400 + 157,286,400 + 52,428,800 | 629,145,600 |

`model.get_storage_info()`가 이 분할에 평균 4.15 bpw를 보고한다 — CPU tail이 평균에서 빠진다. 퀀트 문자열이 그래서 파일에서 온다.

400토큰 스트리밍 답이 `predicted_n` 400 대 텍스트 delta 399(`</think>` 토큰 하나가 텍스트를 안 낸다). reasoning은 `reasoning_content`에. draft 211 / accept 189.

## 실모델이 잡은 결함 넷, 테스트가 아니라

첫 구현이 자체 suite를 통과했다. 각각 디스크 모델·실제 답에 숫자를 대조해야 나왔다.

- **reasoning 분리가 안 걸렸다.** GLM-5.3 채팅 템플릿이 프롬프트를 `<think>`에 끝내서, 답이 블록을 열지 않고 닫는다. `<think>`를 기다리는 splitter가 reasoning 전부를 content에 보냈다.
- **턴이 안 멈췄다.** `generation_config.json`에 종료 id 셋(154820, 154827 `<|user|>`, 154829 `<|observation|>`). 토크나이저 것 하나만 job에 넘겼다.
- **active 바이트가 expert 전부를 셌다. 10,979,084,996 대 159,387,791,876.** 실제 배치는 `experts.<e>.<proj>.<quad>`라 테스트용 합성 fixture보다 한 단 깊다. expert 패턴이 안 맞았다.
- **클래스 분할이 walk 순서를 따랐다.** 로더가 가중치를 128 MiB 청크에 싣는다. 저장 크기를 저장 중복 제거에 세니 처음 만난 텐서에 청크 통째를 얹었다 — 8 KB RMSNorm 가중치 27개가 개당 0.125 GiB에 잡혀서 48 GB 카드의 "other"가 4.45 GB를 읽었다. 장치 바이트는 이제 각 텐서 자체 바이트를 센다. 겹침·slack 체크는 아래 진행 중이다.

## exllamav3 `time_generate`의 커버

llama-server 보고 생성 속도가 디코드 스텝 수에 나눈다. 그게 n인지 n−1인지는 엔진이 시계를 언제 시작하는지에 달렸다. 같은 소스 두 읽기가 갈렸다(이 세션이 먼저 n−1에 읽고 exl3-serve를 고쳤다. toktape 세션은 n에 읽었다). 쟀다. 정확히 n토큰, 정지 조건 없음, 탐욕, 각 2회 반복.

| n | `time_generate`, draft 없음(초) | / n | / (n−1) | wall, 첫 텍스트→끝(초) |
|---|---|---|---|---|
| 1 | 0.0628, 0.0618 | 0.062 | — | 0.0000 |
| 2 | 0.1047, 0.1048 | 0.052 | 0.105 | 0.0520, 0.0526 |
| 3 | 0.1566, 0.1573 | 0.052 | 0.078 | 0.1042, 0.1032 |
| 8 | 0.4138, 0.4163 | 0.052 | 0.059 | 0.3606, 0.3628 |

토큰 하나가 1패스 시간을 쓰고 0이 아니다. 토큰당 수치는 n에 평탄하지 n−1에 평탄하지 않다. 첫 텍스트 결과부터 wall 시계는 (n−1)패스다. 시계가 첫 토큰 내는 패스 전에 시작해서, `time_generate`가 n패스에 걸치고 n / time이 llama-server 일치 속도다. exl3-serve 변경을 되돌리고 TabbyAPI 패치를 n−1에서 n에 옮겼다. MTP draft 켜고 같은 실행이 1토큰 0.09–0.15초·8토큰 0.41초(accept 3, reject 2)를 냈다. 패스와 토큰이 거기 1:1이 아니라서, 판정은 draft 없는 행에서 읽는다. 스텝별 delta·prefix 캐시 적중을 찍을 개정 프로브가 개정 도달 전에 출발했다. 그 열이 없다.

## TabbyAPI #454: main 대 패치

TabbyAPI main(53da791)과 같은 트리+패치, 로드 각 하나, 요청 여섯. 위와 같은 torch·exllamav3 빌드의 별도 venv에 설치(TabbyAPI 자체 extra가 torch 2.9.0용 exllamav3 휠을 고정한다).

| 요청 | main | 패치 |
|---|---|---|
| chat, stream, `include_usage` | `timings` 없음 | 마지막 청크에만 `timings` |
| chat, stream | `timings` 없음 | `finish_reason` 청크에만 |
| chat, 비스트림 | `timings` 없음, `usage` null | 최상위 `timings`, `usage` 여전히 null |
| chat, 비스트림, n=2 | choice 둘 | choice 둘, `timings` null |
| text, stream, `include_usage` | `timings` 없음 | 마지막 청크만 |
| text, 비스트림 | `timings` 없음 | 최상위 `timings` |

양쪽 전부 200. 모든 `timings`가 draft 카운터를 실었다(chat 51/45, text 33/31). 패치 단위 테스트 파일이 main에 import 실패, 패치에 23 테스트 통과. PR용 관찰 셋. TabbyAPI가 finish 청크 짓기 전에 `prompt_time`·`gen_time`을 0.01초에 반올림한다(`backends/exllamav3/model.py:1229`, `:1255`). `timings` 해상도 10 ms다. 비스트림 응답이 `stream_options.include_usage` 박을 때만 `usage`를 실었다. 마지막 스트림 청크가 `finish_reason`·`usage`를 같이 싣는다. 양쪽 트리.

## 테이크: llama-server 녹음기에 녹음된 ExLlamaV3

20:56, llama.cpp 아닌 엔진의 첫 toktape 테이크. exl3-serve 6a7358d가 서빙 프로파일(`-gs 44,21 -mcs 185 -mct 32 -cs 32768 -mtp`, 121초 ready)에 `/models/GLM-5.3-Flash-exl3-4.05` 로드. 테이크 밖 warm 요청 하나. toktape v0.2.1-5-g0719fec가 `/props` 너머 붙어 탐욕 1스트림 녹음. 프롬프트가 13:08 ik graft B 테이크 쓴 것이다. 그 테이프에서 되읽어서 두 클립이 같은 축에 있다. `reasoning_effort: low`의 merge-two-sorted-lists 요청, in 32토큰.

| 20:56 테이크, `contended: no` | exl3-serve + ExLlamaV3 | ik graft B + MTP(13:08) |
|---|---|---|
| 파일 | EXL3 4.05 bpw, 153.8 GiB | Q6_K graft, 184.3 GiB |
| 배치 | per-expert, `-mcs 185` | 카드에 통층 10층 |
| 디코드 | **22.0 tok/s** | 24.2 tok/s |
| draft | mtp n_max 1, 96% accept(116/121) | mtp n_max 2, 97%(153/157) |
| TTFT, 32 프롬프트 토큰 | 3551 ms | 768 ms |
| VRAM | 43.5 / 19.4 GiB | 29.5 / 20.9 GiB |
| 호스트 RSS | 99.1 GiB | 156.4 GiB |
| major fault | 토큰당 0.0 | 토큰당 0.0 |
| 컨텍스트 | in 32 / out 237 | in 32 / out 238 |

두 행이 그날 산술의 귀환이다. 디코드 22.0 대 24.2는 파일 30 GiB 덜 읽고 이 상자 ik에 9% 뒤진다. `-mcs 195` 배치 스위프 자리와 같은 트레이드(ik 18.7 대 19.1–22.2)지 새 사실이 아니다. 호스트 RSS가: per-expert 배치가 CPU 워커에 92.5 GiB를 두고 나머지 전체가 아니라서, 프로세스가 GGUF 서빙 것보다 57 GiB 작다.

TTFT가 실험감 행이다. 32토큰 프롬프트 첫 토큰에 3551 ms는 프리필 측정이 아니다 — 카드가 스스로 말한다. 같은 프롬프트 ik가 768 ms에 답하는데, 요청당 2.8초 시동이 붙으면 대화형 무엇을 지배한다. 어디 가는지는 안 쟀다. 새 시퀀스의 CPU 워커 첫 손댐, 엔진 스레드의 토크나이저·템플릿 렌더(exl3-serve가 하나라 인코딩이 디코드 스텝 뒤에 기다린다), job enqueue 자체가 후보다. 개정 프로브의 스텝별 delta가 아직 없다. 별도 실험으로 filed.

클립이 1스트림인 이유는 해야 해서다. `--parallel 2`가 아직 슬롯 둘을 안 낸다(exllamav3가 발전기 배치를 캐시 슬롯 수에 맞추는데 `-ambs` 기본 1). 2스트림 테이크가 직렬화를 녹음하고 동시성이라 부른다.

[toktape](https://github.com/midagedev/toktape)에 녹음. 테이프 `assets/glm53-flash-exl3-mcs185-mtp.tape`(공개 전 [`tools/tape-sanitize.py`](../tools/tape-sanitize.py)에 호스트명 "workstation" 치환). 카드 `assets/glm53-flash-exl3-mcs185-mtp.card.png`, mp4 [Drive](https://drive.google.com/file/d/1XsINW_aOqHPCsafa4d2ITu6T_hFoTBPO/view?usp=drivesdk). 러너 [`tools/exl3/exl3serve-take.sh`](../tools/exl3/exl3serve-take.sh). 체크 러너의 gate·teardown에 프로브 대신 녹음.

## 2스트림: 고정, 고침, 동시성의 실제 값

위 1스트림 테이크가 1스트림인 이유는 `--parallel 2`가 슬롯 둘을 안 냈다. exllamav3가 모든 캐시를 `max_batch_size = args.autosplit_max_batch_size`에 짓는다 — `-ambs` 플래그, 기본 **1** — `Generator.__init__`이 자체 배치를 `cache.num_slots`에 맞춘다(v1.5.0 `model_init.py:292`, `cache.py:161`, `generator.py:233`). exl3-serve가 둘을 물어 하나를 받았다. `/slots`은 정직하게 빈 둘을 보고했다. exl3-serve가 이제 `model_init` 전에 `-ambs`를 최소 `--parallel`에 올리고 뒤에 서빙 배치를 assert한다. 그래도 안 맞으면 로드가 두 숫자를 달고 깨진다. 큐에 넣고 동시성이라 부르는 대신이다.

두 상태 다 녹음했다. 같은 프롬프트·배치, toktape v0.2.2.

| `-mcs 185 -mtp`, toktape v0.2.2 | 프롬프트 | 스트림당 | 합계 | wall | `peak_decoding_streams` | TTFT p50 |
|---|---:|---:|---:|---:|---:|---:|
| 1스트림(20:56) | 32 | 21.96 | 22.1 | 14.3초 | — | 3551 ms |
| 2, 고치기 전(21:10) | 32 / 26 | 22.04 / 22.41 | 21.4 | 26.0초 | **1** | 893 ms |
| 2, 고치고(21:44) | 32 / 26 | 10.64 / 11.57 | 20.3 | 27.0초 | **2** | 759 ms |
| 2, 고치고, 진짜 프롬프트(22:03) | 274 / 274 | 11.49 / 11.58 | **23.5** | 29.9초 | **2** | 11652 ms |

고친 것이 먹었다. 녹음기 자체 caveat `the 2 streams decoded one at a time: the aggregate is one stream behind a queue, not 2 at once`가 21:10 테이프에 울리고 21:44에 없다. `peak_decoding_streams` 1→2. 두 번째 요청 대기가 12.3초→4.6초.

동시성이 처리량에 하는 것은 거의 없고, 부호가 창에 달렸다. ~~합계가 안 움직였다 — 20.3 대 22.0.~~ 너무 셌다. 같은 시간 struck. 21:44 테이크가 20.3, 22:03 테이크(30초 창에 진짜 274토큰 프롬프트 둘)가 싱글 22.1 대 23.5를 말한다. 셋 안정량은 스트림당 속도다. 매번 solo 정확히 절반. 2토큰 스텝이 87 ms 대 1토큰 스텝 45.5 ms라서다. 합치면 2스트림이 21.96 대 23.1 tok/s — **5%**. 합계 숫자가 20.3과 23.5를 오가는 것은 창 중 두 스트림이 실제로 함께 디코드하는 분량이다.

5%는 산술이 맞아떨어진 것이지 실망이 아니다. 여기 디코드가 CPU 상주 expert 98.1 GB 읽기다. 2스트림 두 토큰이 다른 expert에 라우팅되니 바이트가 토큰과 함께 2배가 되고 바이트당 토큰이 거의 안 오른다. MTP draft가 97% accept에 +12%를 산 같은 이유다. compute-bound 엔진의 2스트림 배치가 2배 근처를 보일 곳에, 여기는 1.05배를 보인다. 진짜 사는 것은 클라이언트 둘에 한 번에 답하는 것이다. 하나가 다른 쪽 12.3초를 기다리는 대신.

대조로 카드 위 통 expert 층의 ik/llama.cpp V4.1-Flash가 각 12.8 tok/s·합계 25.7 대 solo ~22를 기록한다 — 같은 움직임에 더 큰 이득. draft·모델이 다르니 비교가 아니라 포인터다. 여기 행당 테이크 하나지 평균이 아니다.

### 프리필 비용이 고정이라 앞 질문이 닫힌다

두 테이크 뒤 프리필 행이 측정이 됐다. 32토큰 프롬프트의 3.5초 TTFT가 무엇이었는지 답한다. 프롬프트 길이 32·213·274토큰이 전부 같은 wall 시계를 낸다 — 엔진 프리필 3.47초·3.19초·3.52초. 이 배치의 프리필 비용은 토큰당이 전혀 아니다. fan-out이다. 어떤 프롬프트든 층마다 top-8 expert를 실은 토큰 수만큼 그린다. 288슬롯에 essentially CPU tail 98.1 GB 전체를 건드린다. 토큰당 속도가 그래서 프롬프트 따라 오른다(32토큰 9.2 tok/s, 244에 72.4). 고정 읽기가 토큰에 분할돼서다. 짧은 프롬프트의 대화형 비용이 그 고정 3.4초다. [WKS-27](../docs/upstream-contributions.md)이 고정 fan-out과 토큰당 비용을 나누는 스위프를 원했다. 같은 배치 3점이 고정이라 말한다.

네 번째 점이 클립 테이크와 함께 닿았다. 252토큰, 3046 ms. 그날의 깨끗한 테이크다 — caveat 둘, 실행 이야기가 아니다(exllamav3 CPU 워커가 메모리 수치를 4프로세스 합에 만들고, Tctl이 54→68 °C에 흘렀다). 답 둘 완성. 스트림당 디코드 11.6 tok/s·합계 19.4. 꼬리에 스트림 하나 남은 창의. 스트림당 프리필 82.5 tok/s에 `engine prefill 3046 ms · queue 1558 ms` — 큐가 첫 프리필을 기다리는 두 번째 스트림이다. exl3-serve 엔진 스레드가 하나라서다. 테이프 `assets/glm53-flash-exl3-2stream-complete.tape`, 클립 [Drive](https://drive.google.com/file/d/1nxcZKbgU_A82Cf2940cYY0n0soqgnKEL/view?usp=drivesdk), 48.3초. 답 자르기를 멈춘 것은 프롬프트 둘을 200단어에 묶은 것이다. 11.6 tok/s에 45초 창이 약 520토큰인데, 무제한 답이 더 원했다.

거기 가는 데 재녹음 셋, 둘이 내 몫이다. `--prompts FILE`이 스트림이 아니라 *라운드*다 — 라운드의 매 스트림이 그 줄 프롬프트를 받는다. 22:03 테이크가 같은 프롬프트를 두 번 돌리고 두 번째 줄에 안 닿았다. 반복 `--prompt`가 동시 스트림에 프롬프트를 돌린다. 그 테이크가 양쪽 스트림 `prompt_ms` 0을 보고했다. exl3-serve 결함인데 녹음기가 드러냈다. 엔진이 프리필 시간을 eos 결과에만 보고해서, 녹음기 시계에 잘린 실행이 0을 하드코드한 잠정 timings에 떨어졌다. 이제 제출부터 첫 토큰의 서버 자체 span을 싣는다. llama-server가 같은 경로에 보고하는 것이다.

고친 값에 이 고정이 왜 안 보였는지 설명하는 가격이 있다. 슬롯 둘이 하나보다 VRAM을 더 먹는다. `-gs 44,21 -mcs 185`에 `-cs 32768`·`-cs 16384` 둘 다 `Insufficient VRAM in split for model and cache`에 로드 실패했다. `-cs 8192`에만 든다. exllamav3가 장치 `-gs` 분율 안에 모듈별로 로드하고 OOM에 다음 장치로 넘어간다(`model_ls.py:274`). 배치-2 로드가 배치-1 드는 같은 분할에 자리가 없다. 테이프가 `assets/glm53-flash-exl3-2stream-serialized.tape`·`assets/glm53-flash-exl3-2stream-batched.tape`에 있다. 긴 프롬프트 테이크 둘이 `assets/glm53-flash-exl3-2stream-real-prompts.tape`(프롬프트 하나 두 번)와 `assets/glm53-flash-exl3-2stream-two-prompts.tape`(프롬프트 둘, 진짜 프리필 행)에 있다. 클립 둘이 Drive에 — [직렬](https://drive.google.com/file/d/1Mc6uivfsJc6Q4PZP99nv3bWD4IvxEEm-/view?usp=drivesdk)·[동시](https://drive.google.com/file/d/1juhIz_HBheswUJ4Ql7csnMKSssFLibtB/view?usp=drivesdk). 둘 다 [toktape](https://github.com/midagedev/toktape) v0.2.2에 테이프 렌더.

러너가 가는 길에 자기 고침을 벌었다. 실패 로드가 HTTP 앞단을 살려 503에 사유를 답하게 둔다. readiness가 전부 900초를 두 번 기다렸다. readiness가 이제 200 아니면 지목된 실패다 — 두 번째 시도가 VRAM 메시지를 화면에 40초에 죽었다.

## 가는 길의 고장

TabbyAPI 러너가 서버가 아니라 서브셸 pid를 기록했다. teardown이 서버를 놓치고 GPU 임대를 풀었다. 카드 둘 잡힌 채로. 백그라운드 job이 SIGINT 무시 시작도 함께다. 둘 다 고친 launch·teardown과 함께 [`docs/quiet-machine.md`](../docs/quiet-machine.md)에 썼다. 클래스 프로브가 처음에 root 작업 디렉터리에서 출발해 죽었다. exllamav3 CPU 워커(spawn 프로세스)가 못 들어가는 곳이다.
