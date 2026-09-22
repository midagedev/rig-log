# 도구 인계 — ExLlamaV3 베이스라인과 라이브 칵핏

두 인계 문서의 evergreen 부분만 둔다. 날짜가 박힌 기계 상태·다음 할 일 목록은 버렸다. 측정은 전부 이 기계에서.

## ExLlamaV3 per-expert 오프로드: GLM-5.3-Flash

파일은 expert 3 bpw에 공유 코드북(36,288 모듈, 142 GiB), attention·shared는 5–6 bpw로 5.5 GiB다.

ik에서 18.7 tok/s(expert 10층 온카드)에 막힌 GLM-5.3-Flash에, 직접 배치-자각 양자화를 짓기 전에 재는 경쟁 베이스라인이다. ExLlamaV3 1.4.3+는 런타임에 VRAM·RAM 사이 per-expert 배치를 한다(`-mcs`).

| arm | 배치 | decode ×3 | 11.4k 프리필 | VRAM 48/24 GB |
|---|---|---|---|---|
| ik main, UD-Q4_K_XL, expert 전부 CPU | — | 17.0 | 320 | 15.7 / 10.6 |
| ik main, UD-Q4_K_XL, L7+3 | 10층 온카드 | 18.7 | 353 | 32 / 23 |
| exl3 1.5.0, layer-split | MoE 42층 중 30 CPU | 16.9–17.5 | 241 | 42.8 / 8.6 |
| exl3 `-mcs 195` | 층당 93 expert GPU | 19.1 → 20.5 → **22.2** | **356** | 42.7 / 14.3 |
| exl3 `-mcs 185` | 층당 103 expert 상주 | **23.3** draft-free | 361–373 | 43.5 / 20.5 |
| exl3 `-mtp --draft_n 1` | `-mcs 185` 위 | **25.4** (accept 77%) | — | — |
| exl3 `-mtp` depth 2 | `-mcs 185` 위 | 24.0 | — | — |

읽는 법: layer-split 모드는 ik 리그(AVX2-only CPU에서 17.5 대 17.0–18.7)지만 프리필 3할 느리다. per-expert 모드는 수렴이 느리다(128스텝마다 64 expert 이동). 400토큰 프로브는 미수렴 상태를 잴 수 있어, 부르기 전에 2–4k 토큰 실행이나 PR #315의 precomputed profile이 필요하다. 수렴에 ~1.2k 토큰. `-mtp` 기본 depth 3은 진다(20.6, accept 47%). depth 2는 24.0. `-mct 48`이 32보다 느리다(22.1 대 23.3). 같은 프롬프트 재방문 출력이 배치 이동 따라 달라지는 것은 ik의 near-tie 뒤집기와 같은 부류지 버그가 아니다.

`can_defer_load` 가드 버그는 확정·제출됐다. [exllamav3#376](https://github.com/turboderp-org/exllamav3/pull/376): `-mcs`가 안 쓰는 env를 읽어 라우터가 순열 뒤에 로드하고, 모델이 정상 속도로 깨진 값을 뱉는다. 한 줄 + 미패치 파일에서 깨지는 테스트.

남은 후보: `-mcs 185` 위 precomputed profile이 dynamic 대비 mixed 텍스트에 얼마를 더하는가, 그리고 draft depth upstream 제출(선행기술 조사 뒤, 표 첨부).

도구 위치: `tools/exl3/`(벤치·러너 — `tools/exl3/exl3-run.sh`가 원형. 러너는 GPU 임대 파일을 gate로 삼고, 실행 중인 스크립트를 고치지 말고 새 이름에 복사한다), `tools/tabby/`. 서빙 표면 [exl3-serve](https://github.com/midagedev/exl3-serve)는 llama-server 호환 앞단이다. 상세 실행 기록은 [GLM 로그](../log/2026-09-15.md#glm-5.3-flash-first-run).

## 라이브 칵핏: 저녁마다 층 옮기는 사람을 위한 화면

로컬 LLM 서빙을 튜닝하는 사람이 한 번에 보는 화면이다. 기계 스펙과 모델 형상, 라이브 자원, 프롬프트·디코드 tok/s, 실제 나오는 토큰 — 한 뷰에, 내보낼 수 있게. 이 리포의 `tools/v41-demo.py`가 프로토타입이다(터미널 2분할, VHS 녹화용). 존재하는 것 서베이(2026-09-13, 한 달이면 stale)는 otop·localtok(Ollama-first 지표), llama.cpp-Monitor-Dashboard 계열(브라우저), Prometheus 스택(평균의 관측), nvitop/nvtop(GPU만), llmfit(플래너), LlamaStash(런처) — 한 라이브 실행의 배치 + 실제 메모리 그림 + 요청 자체 속도 + 토큰 텍스트를 터미널에서 녹화 가능하게 합친 것은 없었다. 그게 빈자리다.

이 기계가 가르친 것(잰 것, 재촬영 한 번씩 값 치른 것):

1. **tok/s는 내용 구간으로만 잰다.** 텍스트를 실은 토큰 처음부터 끝까지. 빈 role 청크·finish 청크 포함, 멈춘 뒤에도 도는 wall time 나누기, finish 체크를 건너뛰는 렌더 throttle — 각각 18 tok/s를 기록상 4.5로 끌었다. 서버 자체 `timings`(`predicted_per_second` 등)를 읽고 클라이언트 수치는 교차검증으로.
2. **warm과 cold는 다른 숫자다.** 같은 세션 반복 프롬프트는 캐시를 맞고 fault 0이다. 19토큰 샘플에 "디코드" 라벨을 붙이지 않는다. `cached_tokens`를 속도 옆에 둔다.
3. **RSS는 "적재"가 아니다.** mmap에서 RAM에 있다는 것은 페이지 캐시고, RSS는 프로세스가 건드린 것이며 VRAM에 복사하고 버린 만큼도 모자란다. "한 번도 안 읽힘"(여기서 engram 84.6 GB)은 텐서 헤더에서 왔다. total−RSS는 ~50 GB 부풀렸다. GGUF 헤더(텐서 크기·배치) + `/proc/<pid>/status`(VmRSS·RssFile·RssAnon·RssShmem) + `/proc/<pid>/stat` 12필드(majflt, 토큰당 NVMe) — 그 스파크라인이 클립에서 가장 많이 본 것이다.
4. **채팅 템플릿이 무엇을 재는지 정한다.** `reasoning_effort: none` 대 thinking이 답을 60토큰에서 4,000토큰으로 바꿨다. 보낸 것(effort·template kwargs·렌더 프롬프트의 `</think>`)을 화면에 보인다.
5. **CJK는 두 칸이다.** 박스 우측 패널 정렬에 `east_asian_width` + ANSI 제거 후 측정. 후반을 빼먹어 색 입힌 줄마다 15칸 밀렸다. 녹화용 폰트도 고른다(D2Coding은 한글 advance가 정확히 라틴 2배, 대개 아니다).
6. **바쁜 기계 숫자는 무효다.** 다른 하네스가 재는 효과보다 디코드를 더 움직였다. 로드와 타 GPU 프로세스를 읽고 *contended* 라벨을 찍는다.
7. **녹화도 산술이다.** VHS 10 fps, 2,000토큰에 122초, GIF는 mp4의 10배. 예상 토큰 수·속도에서 프레임·길이를 도출하지 손으로 안 친다.
8. **서버 둘, 파일 하나, 페이지 캐시 하나.** `-ngl 0` 두 번째 서버를 옆에 붙여도 매핑 공유라 RAM 추가 0이다. A/B용으로 서버 복수를 본다.

구현 요구(축약): 실행 중인 OpenAI 호환 서버에 URL로 붙고, 채팅+우측 라이브 패널(배치 요약·RSS 분할·구간 majflt 스파크라인·GPU별 VRAM·프롬프트/디코드·캐시 적중·TTFT), 종료 후 실행 요약 카드(하드웨어·빌드·플래그·모델·컨텍스트·네 속도·contended 한 줄 — 텍스트·SVG/PNG·JSON), VHS 녹화 가능한 결정적 렌더링. 검증은 녹화 스트림 픽스처 단위 셋 + 이 기계 `llama-server` 통합 + 30초 VHS 테이프 하나.
