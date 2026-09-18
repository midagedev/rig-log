# mistral.rs의 오프로드: 되는 것과 안 되는 것

*2026-09-17 18:42–18:59. RTX A6000 48G, 런치마다 임대 1개, 시작마다 io 압력 0. mistral.rs 0.9.3 설치 바이너리, 상자 툴킷 13.0 대 CUDA 빌드 13.2.*

질문은 단순했다. mistral.rs에 이 상자가 의존하는 CPU·NVMe 오프로드가 있는가. 답은 절반 yes다. yes 절반이 이 워크스테이션이 아끼는 모델 부류에 정확히 깨져 있다.

## 바이너리의 제공

`serve --help`와 바이너리 자체 문자열에서 읽었다. 문서가 아니다.

| | |
|---|---|
| `--cpu` | CPU 전용 강제 |
| `-n, --device-layers ORD:NUM` | 층 단위 배치, 이 엔진의 `-ngl` |
| `--topology <YAML>` | 층별 장치 *겸* 층별 양자화 |
| `MISTRALRS_NO_MMAP` | 모델 로드 mmap이 기본. 끄는 스위치 |
| `MISTRALRS_CPU_KV_F32` | CPU 동작 모델의 KV dtype — 설정 없으면 f16. KV 오프로드 스위치 **아님**. 여기 이른 노트가 그랬다. 문자열 오독이었다 |
| 바이너리 문자열 | "No suitable quantization level fits on the available devices. Try a smaller model or enable CPU offload." |

없는 것이 있는 것보다 중요하다. **텐서급 배치가 없다** — 이 상자가 V4.1-Flash 서빙하는 ik의 `-ot exps=CPU`·`-ncmoe N`에 해당하는 것이 없다. 어텐션·dense 몸통은 카드에, expert 가중치는 RAM에. 층은 장치에 통째로 가거나 안 간다. **NVMe·디스크 오프로드도 없다.** 바이너리에 `nvme`, 디스크 오프로드 문자열 없음. mmap은 RAM 넘는 GGUF가 페이지 캐시로 페이징된다는 뜻이지 배치 티어가 아니다 — GPU에 매핑된 것은 어차피 복사된다.

`tune`(양자화·장치맵 추천)은 여기서 전혀 안 돕는다. `Auto-tuning is not supported for pre-quantized GGUF/GGML models.`

## 층 매핑은 돌고, 모델이 안 돈다

Qwen3.6-35B-A3B UD-Q6_K에 `-n 0:8`. help가 답 못 한 질문에 답한다 — 안 나열된 층이 호스트에 간다.

```
INFO mistralrs_quant::utils::log: Layers 0-7: cuda[0] (48 GB)
INFO mistralrs_quant::utils::log: Layers 8-39: cpu (252 GB)
```

서버가 로드되고 `/health`에 답하고, 매 요청을 깨뜨린다.

```
ERROR mistralrs_core::engine: prompt step - Model failed with error: moe experts forward
dtype mismatch in matmul, lhs: BF16, rhs: F32
```

readiness 루프가 9분 묻는 동안 동일 실패 232회. 간헐 아님, 첫 요청 워밍 아님. 매 completion, 1토큰 readiness 프로브 포함.

런치 셋이 범위를 좁힌다. 각각 임대 하나.

| 런치 | 매핑 | 결과 |
|---|---|---|
| `-n 0:40` | `Layers 0-39: cuda[0]` | **동작**, dtype 에러 0 — 플래그 자체는 fine |
| `-n 0:39` | `Layers 0-38: cuda[0]` / `Layers 39-39: cpu` | **깨짐**, dtype 에러 58 — **호스트 1층이면 충분** |
| `-n 0:8`, dense Qwen2.5-7B Q3_K_M | `Layers 0-7: cuda[0]` / `Layers 8-27: cpu` | **동작** — 부분 오프로드가 할 일 한다 |

어느 층인지는 재현자 위해 GGUF 헤더에서 읽었다. 가정 아님. 반복 블록 **마흔 전부** expert 텐서를 든다(`blk.N.ffn_{gate,up,down}_exps.weight`). 호스트행 층마다 expert 블록이 따라간다. 특히 39층은 full-attention 10층 중 하나다 — `full_attention_interval` 4라서 `attn_q`/`attn_k`가 블록 3·7·11 … 39에 살고 나머지 서른은 `ssm`/선형 어텐션 텐서 대신 든다. 깨지는 런치가 호스트에 full-attention + MoE 층을 올린 것이니, 선형 어텐션 경로는 관련 없고 expert FFN이다. 층이 균일 MoE 아닌 모델에 `-n 0:39`는 39 블록에 우연히 있는 것이 간다.

dense 행 속도는 조심 문장 하나 값어치 있다. 오늘 정확히 이 모양에 struck 둘이라서다. 그 런치가 호스트 20/28층에 16토큰 `curl` 버스트 **17.4 tok/s**를 쟀다. 가장 가까운 쌍은 같은 엔진·모델 완전 상주의 스위프 자체 1스트림 테이크 **122.8 tok/s** — 다만 238토큰 프롬프트 toktape 테이크라 16토큰 버스트와 쌍이 아니다. 쌍은 자릿수지 비율이 아니다. 그 행의 증거는 돌았다는 것이다.

그래서 트리거는 CPU에 놓인 MoE expert 블록이다. 하나면 충분하다. 부분 오프로드는 다른 쪽은 멀쩡하다. 에러가 자리를 지목한다 — CPU MoE expert forward가 BF16 활성(로드에 `DType selected is BF16` 찍힘)에 F32로 도착한 expert 가중치를 받는다.

최소 재현자, 두 줄이다.

```
mistralrs serve -f Qwen3.6-35B-A3B-UD-Q6_K.gguf --host 127.0.0.1 --port 8013 \
  --paged-attn on --pa-context-len 4096 --max-seq-len 4096 --max-batch-size 1 -n 0:39
curl -s localhost:8013/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"default","messages":[{"role":"user","content":"hi"}],"max_tokens":1}'
```

## 이 상자 이미 도는 두 엔진과 대조

"mistral.rs에 오프로드가 있는가"는 갈아탈 엔진 옆에서만 뜻이 있다. 기억이 아니라 양쪽 바이너리 자체 `--help`에 물었다(이 상자 빌드 `/home/user/{ik_llama.cpp,llama.cpp}/build/bin/llama-server`).

| | llama.cpp | ik_llama.cpp | mistral.rs 0.9.3 |
|---|---|---|---|
| 호스트행 층 | `-ngl` | `-ngl` | `-n ORD:NUM` |
| 이름별 텐서 배치 | `-ot NAME=buft` | `-ot NAME=buft` | **없음** |
| expert 가중치 전부 호스트 | `-cmoe` | `-cmoe` | **없음** |
| 앞 N층 expert 호스트 | `-ncmoe N` | `-ncmoe N` | **없음** |
| KV 캐시 카드 밖 | `-nkvo` | `-nkvo` | **없음**(`MISTRALRS_CPU_KV_F32`는 dtype) |
| draft 모델 동일 | `-otd`, `-cmoed`, `-ncmoed` | 없음 | 없음 |
| 층별 *양자화* | 없음 | 없음 | `--topology` YAML |
| NVMe·디스크 티어 | 없음 | 없음 | 없음 |

앞 절 읽기에 정정 둘. **NVMe 오프로드 부재는 parity지 결함이 아니다** — 비교 엔진 어디에도 없고, 셋 다 RAM 넘는 파일에 같은 메커니즘(mmap + 페이지 캐시)에 의존한다. mistral.rs에 "NVMe 오프로드 없음"은 맞고 선택에 대해 말하는 것 없다. llama.cpp가 ik보다 이 표면이 넓지 좁지 않다. draft 모델용 `-ot`/`-cmoe`/`-ncmoe` 집안 통째. 추측 디코딩 도는 상자에서 중요하다.

parity 행을 빼면 질문을 정하는 행 하나가 남는다. `-ncmoe N`·`-ot exps=CPU`가 이 워크스테이션 V4.1-Flash 서빙 그 자체고, mistral.rs는 어느 쪽도 표현 못 한다. 값은 같은 날 밤에 잰다. [기록 -d](2026-09-17-d-what-offloading-costs-each-engine.md)다. 답의 큰 절반이다. 오프로드 1층이 ik에 토큰당 **0.20 ms**, mistral.rs에 **442 ms**다. 양쪽이 expert matmul을 호스트에 돌린다 — ik가 26.7코어에 라우팅 256 중 8 expert만 양자화 채로 읽고, mistral.rs가 1.3코어에 256 전부 F32 풀고. 그 기록 첫 버전이 ik가 matmul을 GPU에 둔다고 했다. 거기 struck이다. 그래서 이 표는 각 엔진이 *말할 수 있는 것*을 비교하고, 기록 -d는 각 커널이 그걸로 *하는 것*을 비교한다. 층 단위 오프로드는 대체가 아니다. 층 통째를 호스트에 보내면 어텐션·KV가 expert와 같이 간다. 레시피의 트레이드 반대다. 그래서 mistral.rs 오프로드는 **3티어 중 1티어**다 — `-ngl` 티어 있고, 텐서 티어 통째 없고, 디스크 티어는 아무도 없다.어느 엔진에도 없는 것을 하나 얻는다. 배치용이 아니라 맞춤용 층별 양자화 `--topology`다. 배치보다 맞춤에 재미있다.

## 정직한 범위, 못 묻던 모델 둘

MoE 모델 하나는 하나다. 일반성은 **미측정**이다. 안 만져봐서가 아니다 — 상자의 다른 MoE GGUF 둘이 오프로드 무관 이유로 로드에 거부된다.

- `DeepSeek-V2-Lite-Chat.Q3_K_M.gguf`: `GGUF architecture deepseek2 is missing metadata {arch}.attention.key_length_mla`. 로더 요구 키보다 이전 변환이다.
- `Qwen3-Coder-Next-IQ4_XS.gguf`: `GGUF tensor blk.0.ssm_ba.weight uses dtype IQ4_XS (23) for native binding model.layers.0.linear_attn.in_proj_ba.weight`. 선형 어텐션 투영이 비양자화 기대인데 이 GGUF가 양자화했다.

두 거부 다 따로 알 가치 있는 제한이다 — llama.cpp 집안이 잘 올리는 GGUF가 mistral.rs가 받는 GGUF가 아니다. 오프로드 버그의 두 번째 데이터포인트도 못 된다. 보고는 그래서 "MoE GGUF 하나에 재현, 동작 dense 대조·전체 GPU 대조 동작"이라 말한다. 잰 그대로다.

중복 조사, `EricLBuehler/mistral.rs`에 쿼리 셋. `"dtype mismatch in matmul"`(1적중, [#2072](https://github.com/EricLBuehler/mistral.rs/issues/2072), FP8 *로딩* — 다른 경로), `moe experts forward dtype mismatch`·`device-layers cpu offload gguf moe` 무매치.

## 고침, 테스트가 죽인 주장, 안 싣고 간 테스트

[EricLBuehler/mistral.rs#2430](https://github.com/EricLBuehler/mistral.rs/pull/2430)으로 제출. 한 파일 5줄. 원인은 에러 던지는 곳 한 줄 위다. `GgufMatMul::quantized_act_type`(`mistralrs-quant/src/gguf/mod.rs:560`)이 CPU 가중치에 `None`을 돌린다. 주석 *"cpu handles bf16 activations natively (widened once inside the packed matmul)"* — packed 2D matmul에는 맞고, 그 `None`이 `QuantMethod::gather_forward`의 cast도 끈다. indexed 경로는 widen 안 한다. expert를 F32에 풀고 도착 활성 그대로 곱한다. 그래서 고침은 그 matmul에 F32 cast + 입력 dtype 복원이다. non-indexed 경우 `forward_raw`가 하는 것, CUDA 경로 `quantize_input_q8_1` 안에서 하는 것이다. `indexed_gemv` fast 경로 뒤에 앉는다. 원래 dtype 유지한다.

제출 전 답한 리뷰어 질문 둘. `quantized_act_type`을 고치면 공짜에 넓히는 2D 경로에 형변환이 박힌다. 아래 두 줄 `QMatMul::Tensor` 분기는 같은 모양인데 mismatched dtype에 닿을 수 없다. CPU early return이 `if let QMatMul::QTensor(qt)` 가드라 그냥 텐서는 `Some(DType::F32)`에 떨어지고 trait가 이미 형변환한다.

> ~~`indexed_gemv`는 aarch64 전용이라 x86_64 호스트는 항상 풀기 fallback에 닿는다.~~ **제출 전 Struck. 싣고 가지 않은 테스트에.** 문장이 PR 본문에 있었다. 쓸 때. 버리는 테스트 — `QTensor::quantize(Q4K)`에 BF16 활성, `gather_forward` — 고침 없이 이 Apple Silicon Mac에 통과하고 상자에서만 깨지기를 기대했다. Mac에서 깨졌다. `Error: dtype mismatch in matmul, lhs: BF16, rhs: F32`. `indexed_gemv`도 repacked 커널이 못 내는 레이아웃을 사양해서 aarch64가 같은 fallback에 닿는다. 코드 읽기의 세 번째 틀린 범위 주장. 기계 떠나기 전에 테스트가 잡은 첫 번째다.

그 테스트는 쓰고 쓰고 **안 싣고 갔다.** FAIL-first다 — 변경 없이 `d5ae0f1`에 에러내고 변경에 BF16 돌려준다. GPU 없는 plain `cargo test -p mistralrs-quant`에 돈다. 싣고 가면 리포를 거슬렀다. 세지 말고 읽었다. mistral.rs 최근 머지 `fix` PR 22개 중 테스트 파일 손대는 것 **둘**. 하나는 웹사이트 JS 테스트, 하나는 25파일 정확성 스위프. 인접 단일 목적 고침 넷 — 같은 crate dtype 버그 하나 포함 — 은 각 1파일 테스트 없음이다. 테스트가 착륙할 모듈은 전부 ISQ·UQFF 배관이라 forward-pass dtype 테스트는 원하는 곳에서도 이단아다. `AGENTS.md`가 "add tests"를 말하는데 *새 기능*에다. 고침이 아니다. 그래서 PR은 1파일 +5/−2, 커밋 하나 — 스물 모양 그대로. before-after는 본문 문장 대신이다. FAIL-first는 규율이지 산물이 아니다. 규칙은 이제 [`docs/upstream-contributions.md`](../docs/upstream-contributions.md)에 있다.

리포 gate는 여기 돌렸다. `cargo fmt --all -- --check` 클린, `cargo clippy -p mistralrs-quant --tests -- -D warnings` exit 0, `cargo test -p mistralrs-quant` **361 통과 0 실패**. PR 본문의 서버급 재현은 v0.9.3의 것으로 적는다. `d5ae0f1` CUDA 빌드가 PR 올라갈 때 커널 컴파일 중이었어서다. 숫자는 잰 버전 값만 한다.

그 빌드가 20:58에 끝났다. 36분 25초. 상자 트리가 `d5ae0f1`에 아직 클린 — PR 본문이 서술만 할 수 있던 같은 바이너리가 지목 커밋에 미패치로 잴 수 있었다. 양쪽 절반, 임대 각 하나, 20분 간격. 매핑 동일(`Layers 0-38: cuda[0]` / `Layers 39-39: cpu`, `DType selected is BF16`, 요청 전 상주 28 GB).

| 빌드 | `max_tokens=1` completion 하나 | `dtype mismatch` 줄 |
|---|---|---:|
| `d5ae0f1` 미패치 | **http 500** `model_error`, `Model failed with error: moe experts forward` | 2 |
| `d5ae0f1` + PR 커밋 `b0f26d5c` verbatim 적용 | **http 200**, 토큰 하나 복귀 | **0** |

before-after가 이제 한쪽 릴리스 태그가 아니라 양쪽 같은 커밋이다. PR 본문 증거 문장이 말할 것이다. 두 번째 행의 패치는 PR 커밋 자체 diff를 상자에 파이프해 `git apply`했다. 손 재편집 아님 — 그날의 귀속 사고는 트리 컴파일 중에 고치고 결과를 미패치로 읽은 것이었다. 커밋된 diff 적용이 반복 불가하게 만든다. 재빌드 1분 31초에 CUDA 커널 재컴파일 없음. 두 번째 행이 첫 행 바이너리 + 5줄이다.

러너는 [`tools/mrs/mrs-offload-check.sh`](../tools/mrs/mrs-offload-check.sh)다. 있는 이유는 `mrs-mech-probe.sh`가 이 질문에 우연히 답해서다. 그 프로브 readiness 루프가 *성공 completion*을 요구해서, 로드되고 매 요청 깨지는 서버가 15분간 묻게 둔다 — 위 232 에러의 경위다. 새 러너 readiness는 `/health`다. "가중치가 로드됐다"와 "forward 패스가 돈다"를 나눈다. 구분이 버그 전부다. readiness에 VRAM 수치를 찍는다. 판정이 안 뜬 모델이 아니라 forward 패스에 대한 것임을 증인한다. 상자 트리는 일부러 패치 상태로 둔다. `/home/user/mistral.rs`에서 업스트림 거동을 원하는 세션은 먼저 `git -C … checkout -- mistralrs-quant/src/gguf/cpu.rs` 해야 한다.

걔네 기여 규칙은 기록 값어치 있다. ik 정반대라서다. `CONTRIBUTING.md`가 없다. 관례는 커밋된 `AGENTS.md`와 거의 중복 `CLAUDE.md`에 산다. 에이전트 작성 패치 공개 규칙이 전혀 없다 — 메인테이너가 `Co-Authored-By: Claude` 커밋을 직접 머지한다. 파일이 요구하는 것은 기본 에이전트가 보면 어기는 하우스 스타일이다. 주석 기본 **없음**, 있으면 각 한 줄, ASCII only에 em-dash·`--` 없음, 매직값 named `const`에, 일어날 수 없는 경우 방어 처리 없음, PR 설명에 "Test plan" 절 없음. 이 패치는 주석을 하나도 안 얹는다.

## 이 상자의 의미

자체 엔진 목표가 Rust를 가리킨다. Rust 엔진이 현재 서빙 스택의 일상을 못 하는 첫 번째다. 간격 둘, 값 비싼 순서대로.

1. **expert 전용 배치 없음.** dtype 버그를 고쳐도 층 단위 오프로드는 "expert는 RAM, 어텐션은 카드"를 표현 못 한다. 100 GB급 MoE에 그 레시피가 서빙과 미서빙의 차이 다. 기능 크기 구멍이지 버그 아니다.
2. **MoE 층이 지금 호스트에 아예 못 간다.** 버그. 작아 보이고, 이 워크스테이션이 포크할지도 모를 리포에 처음 보낸 것이다. PR #2430.

측정 발단은 [2026-09-17-b](2026-09-17-b-where-the-four-stream-gap-actually-is.md)에 있다. 위 매 줄의 프로브는 [`tools/mrs/mrs-mech-probe.sh`](../tools/mrs/mrs-mech-probe.sh)다. 거기 CUDA-그래프 카운터도 읽은 것이다.
