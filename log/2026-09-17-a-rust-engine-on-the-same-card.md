# 같은 카드의 Rust 엔진: 단독 느리고 4스트림 두 배 — "thinking off"가 꺼진 적 없다는 실행 증명

**2026-09-17 14:07–14:31, A6000 1장, Qwen3.6-35B-A3B UD-Q6_K, 테이크 일곱.** 아침에 밝힌 장기 목표는 이 기계용 엔진이다. Rust가 방향이다(NVIDIA CUDA Rust 글 이후). 첫 걸음이 리포가 될 리 없었다. 숫자다. Rust 서빙 엔진이 이 카드에서 실제 어디 서는지, 여기 모든 것과 같은 재기. mistral.rs 0.9.3 대 ik c10fbbcc. 같은 GGUF·프롬프트 넷·토큰 cap·임대.

둘이 나왔다. 4스트림 합계가 거의 두 배 — ik 149 tok/s, mistral.rs 283. 싱글스트림은 반대, 130 대 111. 두 실행 모양을 맞추다 이 리포의 한 카드 벤치 러너 `--no-think` 테이크가 어차피 thinking이었다는 것이 나왔다. 그 러너가 `--jinja`를 안 넘겼기 때문이다. 처음 쓴 설명이 틀렸고 아래 struck이다. 정정한 실행이 40초 걸렸다.

## 녹음기가 못 붙었고, 고친 것은 우리다

mistral.rs는 OpenAI 호환 API뿐이다. `GET /props` 404, `/v1/models` 200. toktape는 `/props`에 붙고 llama-server가 매 스트림 청크에 붙이는 `timings` 객체에서 속도를 읽는다. 정면 거부(`cannot attach: HTTP 404`). 일반 고침은 녹음기에 TTP-99로 filed, 아직 To Do. 같은 문제를 2026-09-15 ExLlamaV3에 llama-server 프로토콜 앞단 써서 풀었으니, 기다리지 않고 또 썼다.

쓰기 전에 서버 로드 한 번이 앞단이 실제 번역할 것을 답했다(`curl`, 요청 모양 넷, 캡처 `/home/user/mrs-take/probe`).

| 질문 | 측정 답 |
|---|---|
| toktape 미지 필드(`timings_per_token`, `return_progress`) | 무시, 200 |
| `stream_options.include_usage` | 존중. `usage`가 `[DONE]` 앞 `finish_reason` 청크에 탐 |
| usage 필드 | `prompt_tokens`, `completion_tokens`, `total_prompt_time_sec`, `total_completion_time_sec`, `avg_*_tok_per_sec` |
| `chat_template_kwargs: {enable_thinking: false}` | 존중 — 스트림에 `reasoning_content` 없음 |
| thinking 언급 없음 | 생각한다. 48 중 48토큰이 `reasoning_content`에 도착 |
| `/props`, `/health`, `/apply-template` | 404, 200, 404 |

그래서 [`tools/mrs/mrs-shim.py`](../tools/mrs/mrs-shim.py)는 일부러 얇다. 채팅 본문을 바이트 그대로 전달한다. toktape가 보내는 것을 엔진이 이미 다 받기 때문이다. `/props`는 `exl3-serve`처럼 답한다 — 모델 경로·슬롯 수·`n_ctx`, mistral.rs 지목 `engine` 블록. **`build_info` 없음.** 있으면 카드에 "llama-server"가 찍힌다. 아키·expert 수·파라미터 합은 GGUF 헤더를 직접 읽는다. 보고하는 서버 경로가 없어서다. `/apply-template`에 GGUF 자체 채팅 템플릿을 jinja2 렌더 — 카드가 `prompt unknown` 경고 대신 프롬프트 해시를 갖는 경위다. 매 청크에 `timings` 객체를 붙인다. 스트림 중에는 자체 시계 잠정, `usage` 든 청크에 엔진 자체 수치 — `prompt_tokens`·`total_prompt_time_sec`에서 `prompt_n`/`prompt_ms`, 완성 쌍에서 `predicted_n`/`predicted_ms`. 카드의 속도는 엔진 측정이지 프록시가 아니다.

stdlib only다. 상자에 aiohttp가 없다. 설정은 환경으로만, argv 아님. 프록시 명령줄의 GGUF 경로가 녹음기가 프록시를 서버로 착각하는 정확한 경위라서다.

## 테이크 일곱

파일 동일, 같은 ~234토큰 프롬프트 넷(`hl1..hl4`), `-n 512`, temperature 0, warm 페이지 캐시, UUID GPU 1개, 임대 잡고, 시작마다 `io avg10 0.00`. 엔진 자체 숫자가 `srv`, toktape 클라이언트 셈이 `cli`. 합계는 양쪽 엔진 토큰 ÷ (마지막 토큰 − 첫 토큰) — 표 양쪽에 같은 계산인 유일한 숫자다.

| 14:07–14:31 | 스트림 | thinking | 서버 각 | 클라 각 | 합계 | TTFT p50 | GPU W | 출력 토큰 |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| ik c10fbbcc | 1 | on | 130.1 | 129.9 | **130** | 252 ms | 298 | 512 |
| mistral.rs 0.9.3 | 1 | on | 111.2 | 104.5 | **105** | 160 ms | 248 | 512 |
| ik c10fbbcc | 4 | on | 37.5 | 37.4 | **149** | 4,475 ms | 293 | 4 × 512 |
| mistral.rs 0.9.3 | 4 | on | 76.9 | 73.1 | **283** | 451 ms | 299 | 4 × 512 |
| mistral.rs 0.9.3 | 4 | off | 79.1 | 73.8 | 237 | 465 ms | 260 | 234–345(EOS) |
| ik, `--jinja` | 4 | off | 41.2 | 40.9 | **146** | 5,448 ms | 285 | 157–248(EOS) |
| ik, `--jinja` | 1 | off | 131.4 | 130.8 | **132** | 250 ms | 298 | 244(EOS) |
| ik, `--jinja`, `-c 32768` | 4 | off | 42.1 | 41.8 | **144** | 5,704 ms | 281 | 152–279(EOS) |

thinking on/off가 어느 엔진 속도도 2% 넘게 안 움직인다 — ik 합계 149 대 146, 단독 130 대 132, mistral.rs 1스트림 105 대 105. 표 양쪽이 같은 말을 하고, 아래 라벨 실수에도 비교가 산다.

단독에 ik가 클라이언트 시계 **24% 빠르다.** 도출 읽기 386 GB/s. 09-15 이후 이 로그가 재는 카드 절반 상한 그대로다. 4스트림에 mistral.rs가 합계 **90% 앞**이다. 스트림당 속도가 거의 안 움직인다(111→77). ik는 무너진다(130→37.5). 프리필이 나머지 절반이다. 같은 ~235토큰 프롬프트 넷에 ik 자체 회계가 thinking on 엔진 프리필 **3,357 ms**, off **5,393 ms**. mistral.rs **104 ms** 대. 10배 TTFT 간격 거의 전부고, 디코드 간격보다 큰 불일치다. ik에 260토큰 프롬프트 하나가 1,206–1,314 tok/s에 프리필되니, 그 초들을 쓰는 무엇이든 프롬프트 넷이 4슬롯에 몰릴 때만 나타난다. mistral.rs no-think 두 행이 cap이 아니라 EOS에 끝난다. 낮은 합계는 끝난 스트림 꼬리지 느린 엔진이 아니다.

## 이 숫자들이 아닌 것

Rust 커널 측정이 아니고, 이 문단 첫 버전이 이유를 틀렸다.

> ~~cuTile 모듈 — 진짜 Rust 작성 커널 — 은 CUDA ≥ 13.2를 요구하고 이 상자는 13.0이라 설치자가 뺐다.~~ **같은 날 Struck.** 설치 툴킷 13.0 맞지만 바이너리가 자체 런타임을 싣고 있고 `mistralrs doctor`가 `CUDA: build 13.2`와 `Build features: cuda, flash-attn, cutile`을 보고한다 — 모듈이 컴파일돼 있다. 놀는 이유도 같이 보고한다. `cuTile runtime tooling is unavailable; native CUDA and CUTLASS fallbacks remain active`. NVIDIA `tileiras` 설치 힌트와 함께, 이 상자에 없다. 버전 질문이 가릴 두 번째 gate도 있다. 바이너리 자체 문자열에 cuTile MoE 백엔드가 *blockwise FP8* grouped GEMM이고 `MISTRALRS_MOE_BACKEND=fused`가 F16·BF16 가중치를 요구한단다. Q6_K GGUF는 어셈블러 있어도 어느 경로에 안 닿는다.

돌린 커널이 무엇인지는 4시간 추론이었다가 이제 측정이다. `-v` 기동 서버가 `Preloaded 698 Candle CUDA PTX functions`를 찍는다. 이 숫자 밑 커널이 코드 리딩대로 candle 것이다. 같은 로그 줄이 안 묻던 질문에 답한다 — `Qwen3Next: 10 full attention layers, 30 linear attention (GDN) layers`. 이 모델 스택 4분의 3이 KV 읽기가 아니라 recurrent 상태 갱신이라는 뜻이다. 잰 것은 그래서 커널 위 Rust 호스트·스케줄러다. ik가 직접 컴파일하는 같은 부류 커널 위. 발견은 배치·스케줄링이지 Rust가 빠른 GEMM을 쓸 수 있는지 아니다.

그래서 4스트림 격차가 재미있는 것이고 열린 질문이 중요한 것이다.

> ~~09-16 ExLlamaV3 arm이 동시성이 sparse MoE에 보통 무익한 이유를 쟀다. 2스트림 두 토큰이 다른 expert에 라우팅되니 스텝당 읽기 바이트가 스트림에 비례하고 합계가 평탄하다. ik의 4스트림 +13%가 그 산술에 맞는다. mistral.rs +170%는 안 맞는다. 후보 설명 둘은 잴 수 있다. 싱글스트림이 고정비 bound라 배치가 분할하거나, indexed-MoE 경로가 expert 합집합을 스텝당 한 번 모으는데 ik가 시퀀스마다 다시 읽는다.~~ **같은 날 Struck.** 묻던 스위프에. 둘 다 빠른 엔진에 대한 추측이었고, 격차는 반대편이다. 2스트림 비용이 mistral.rs 11%·ik 50%. ik 디코드는 MoE 모델에 배치를 안 한다(선형 어텐션 없는 두 번째 MoE 모델에 측정, 같은 하네스 정상 스케일 dense 대조). 동시 프리필은 명명된 자리에 싱글토큰 청킹에 떨어진다. CUDA 그래프·fused-MoE 경로 어느 쪽도 개입에 살아남지 못했다. 측정·재현자·업스트림 처분은 [2026-09-17-b](2026-09-17-b-where-the-four-stream-gap-actually-is.md).

## 꺼진 적 없는 `--no-think`, 설명하는 플래그

테이크를 맞춰야 해서 첫 4스트림 mistral.rs 실행이 짝 지을 ik 히어로 테이크처럼 `--no-think`를 썼다. 이어서 답을 읽었다. mistral.rs 4스트림이 첫 토큰부터 content에 돌아왔다. ik는 `<think>\nHere's a thinking process:`에 돌아왔다 — 넷 전부, 카드에 `thinking off`라 쓴 테이크에서.

여기 커밋된 Qwen3.6 테이프 전수 확인:

| 테이프 | `enable_thinking` 요청 | 출력이 think 블록에 열림 |
|---|---|---|
| `qwen36-35b-a3b-q6k-4stream-hero-nothink-0.2.4` | false | **yes** |
| `qwen36-35b-a3b-q6k-4stream-hero-nothink` | false | **yes** |
| `qwen36-35b-a3b-q6k-4stream-mistralrs-nothink-0.2.4` | false | no |
| `qwen36-35b-a3b-q6k-1stream`, `-4stream`, `-4stream-hero`, `-4stream-short-prompts`, `q4kxl-1stream` | 미요청 | yes |

> ~~09-17 히어로 테이크가 thinking off에 4스트림을 녹음했다.~~ **같은 날 Struck.** 요청이 `chat_template_kwargs: {enable_thinking: false}`를 실었고, 서버가 버렸고, 모델이 매 스트림 512토큰 내내 생각했다. 카드의 `thinking off`는 물은 것에 정직하다 — 테이프가 요청을 서술한다 — 일어난 것에 틀렸다. 이 기록 다른 것은 안 바뀐다. 스트림당 37.5 tok/s·합계 149가 thinking 토큰에 기계가 한 것이다.
>
> 14:41 재녹음. 히어로 클립을 물은 세션의 요청에. 같은 프롬프트 넷, `--jinja`, `--no-think`, `-np 4`, `-c 32768`. 모델이 안 생각했다. 매 스트림 152–279토큰에 EOS로 끝났다. 합계 **144 tok/s** — thinking 토큰 149의 4% 안이라서, 오라벨이 기록에 라벨만 값 치르고 숫자는 안 치렀다. 러너 gate가 live 테이크에 처음 `no-think honoured`를 찍었다. 테이프 `assets/qwen36-35b-a3b-q6k-4stream-ik-jinja-nothink-c32k-0.2.4.tape`다.
>
> ~~ik에 `chat_template_kwargs` 지원이 없고, mainline llama-server에 있고, 격차가 기여감이다.~~ **30분 안에 Struck. 어디 보내기 전에.** 포크에 그 필드 있다(`common/chat.cpp:546`, `common/chat.h:181`). 원인은 이쪽이었다. [`tools/ik/ik-vram-take.sh`](../tools/ik/ik-vram-take.sh)이 `--jinja`를 안 넘겨서, 서버가 레거시 템플릿 경로를 탔다. kwargs를 거기서 안 읽고, 안 읽는다는 말도 없다. 프로덕션 서빙 구성은 내내 맞았다([`configs/qwen36-3090-serve.sh`](../configs/qwen36-3090-serve.sh)이 `--jinja --chat-template-kwargs`를 넘긴다). Qwen3.8 러너도 맞다. 한 카드 벤치 러너만 빠져 있었다. 즉시 쟀다. 같은 프롬프트·플래그에 `--jinja` 추가, `--no-think` 전송 — think 블록 없음, 244토큰에 EOS, 131.4 tok/s. **코드를 읽었으면 틀린 업스트림 보고가 나갔다. 40초 실행이 막았다.**

프롬프트 해시는 부산물이자 진단 증거다. toktape가 `/apply-template`에서 받은 렌더 프롬프트를 해시한다. shim의 jinja 렌더(GGUF 템플릿)와 ik 자체 `--jinja` 렌더가 정확히 일치한다 — `--jinja`·mistral.rs 테이크 다섯 전부 `0304d4f3…`. 두 엔진에 바이트 동일 텍스트를 먹인 행들이지, 제각각 템플릿한 행이 아니다. 레거시 경로 ik 테이크 둘은 대신 `4d74d304…`에 해시한다. 프롬프트 토큰 236 대 234. kwargs를 버린 경로가 다른 프롬프트를 렌더했다. 조용히 다른 템플릿이 밖에서 보이는 모양이다.

세 겹으로 둔다. 측정 아닌 요청 파라미터가 또 일어날 것이기 때문이다.

- **원천에 닫음.** ik 벤치 러너에 `--jinja` 무조건. 벤치 경로가 프로덕션 서빙 템플릿 경로와 같아지기도 한다.
- **gate, FAIL-first.** [`tools/check-take-nothink.py`](../tools/check-take-nothink.py)가 테이프를 읽는다. no-think 요청에 답이 thinking 태그에 열리면 — mistral.rs가 thinking을 실는 `reasoning_n` 토큰 보고 스트림도 — 스트림·텍스트 지목에 떨어뜨린다. 히어로 테이프에 깨진다(`THOUGHT ANYWAY … 4 answer(s)`).다른 0.2.4 테이프 일곱에 통과한다. 안 물은 테이크는 판단 안 한다. 양쪽 러너가 테이크 뒤 호출하고 실행을 떨어뜨린다. 첫 배선 버전이 안 돌았다. 테이프 경로를 `$RUNS/…`에 찾는데 toktape는 `~/toktape-runs/…`를 찍는다. 변수가 비어 돌아오고 가드가 말없이 체크를 건너뛰었다. 이제 경로 없으면 에러다. 러너의 20초 테이크가 `no-think honoured (1 tape(s))`를 찍는다 — 손으로만 증명한 gate는 증명 안 된 gate다.
- **다음에 더 보이게.** 녹음기에 같은 모순을 카드에 올려달라 했다. 테이프가 모순 양쪽 절반을 다 쥐고 있어서다.

## mistral.rs 카드의 틀린 것, 이유

그 카드들을 읽을 때 네 행이 프록시·llama.cpp 이야기임을 알고 읽는다.

- **ENGINE `?`** — 테이프가 mistral.rs 0.9.3 지목 engine 블록을 싣는데, toktape 0.2.4가 그 블록에서 kind를 찍는 것은 `exllamav3`뿐이다. 탐지가 "answered `/props` and did not say what it is"에 떨어진다. engine 블록 무엇이든 찍으라는 요구는 보냈다. 버전은 어느 쪽도 테이프에 있다.
- **FLAGS** — `-fa default -b default …`는 argv 안 뜯어서 찍히는 llama.cpp 플래그셋이다. mistral.rs 진짜 argv는 테이프 engine 블록에 있다.
- **`contended: yes`와 "1 other GPU compute process"** — 그 프로세스가 mistral.rs다. toktape가 서버 pid를 모델 경로의 명령줄 매칭 *and* llama.cpp 집안 명령명 요구에 찾는다. `mistralrs`가 탈락하고 탐색이 리스닝 포트 쥔 자 — shim — 에 떨어진다. 이 카드의 모든 메모리·페이지폴트 행이 파이썬 프록시의 것이다. 호스트 RSS가 0.0 GiB인 이유다.
- **컨텍스트 `8192`** — mistral.rs는 4스트림 공유 8,160토큰 paged pool 하나다. 스트림당 8,192가 아니다. ik 카드의 2,048은 `-c 8192 -np 4`가 나눈 것이다.

측정에 대한 측정 하나. mistral.rs의 `total_completion_time_sec`이 토큰 도착 wall time보다 일관되게 **4–10% 짧다**(512토큰: 관측 4,892 ms 대 보고 4,606 ms). shim 자체 시계와 toktape 클라이언트 셈이 1% 안에 일치해서, 간격은 프록시가 아니라 엔진 회계 안에 있다. ik 서버·클라이언트 수치는 0.2% 일치한다. like-for-like 행에 숫자 하나를 골라야 해서 클라이언트 것을 골랐다.

## 상태

`tools/mrs/mrs-shim.py`, 러너 `tools/mrs/mrs-take.sh`, 고친 `tools/ik/ik-vram-take.sh`와 `tools/check-take-nothink.py`가 상자 `/home/user/`에 있다. 소유자 `user`. 테이프 일곱과 카드가 `assets/`에 있다. `…-mistralrs-…`, `…-ik-think-…`, `…-ik-jinja-nothink-…` 밑. 커밋 전 전부 `tools/tape-sanitize.py`·`tools/check-tapes-sanitized.sh` 통과했다. 프로브 캡처·서버 로그는 상자 `/home/user/mrs-take/`에 둔다. A6000 idle, 임대 해제. [toktape](https://github.com/midagedev/toktape) 0.2.4에 녹음.

이 기록의 열린 질문은 같은 저녁에 판정됐다. 필요한 도구는 shim 옆 트리에 있다. [`tools/engine-ab/stream-sweep.sh`](../tools/engine-ab/stream-sweep.sh)이 스트림 수 순서에 테이크를 놓고, [`tools/ik/ik-batch-scaling.sh`](../tools/ik/ik-batch-scaling.sh)이 `llama-batched-bench`를 임대 뒤에 감싸고, [`tools/mrs/mrs-mech-probe.sh`](../tools/mrs/mrs-mech-probe.sh)이 mistral.rs 자체 CUDA-그래프 카운터를 읽고, [`tools/tape-row.py`](../tools/tape-row.py)가 테이프에서 표 행을 지어서 여기 숫자가 다시는 진행 줄에서 복사되지 않는다. 다섯째 [`tools/mrs/mrs-offload-check.sh`](../tools/mrs/mrs-offload-check.sh)는 같은 밤 늦게 왔다. "이 빌드가 모델 일부를 호스트에 두고 서빙하는가"를 boolean에 답한다. `/health`를 readiness에 써서, 로드되고 매 요청 깨지는 서버를 안 뜬 서버로 착각하지 않는다. 측정은 [2026-09-17-b](2026-09-17-b-where-the-four-stream-gap-actually-is.md)와 [2026-09-17-c](2026-09-17-c-what-mistral-rs-can-and-cannot-offload.md)다.
