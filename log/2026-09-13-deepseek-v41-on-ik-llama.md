# DeepSeek-V4.1이 ik_llama.cpp에 돈다: 빌드 열 개, 틀린 그래프 둘, 맞은 숫자 하나

**2026-09-13.** 어제 기록이 DeepSeek-V4.1-Flash를 mainline `llama.cpp`에 돌렸다. ik_llama.cpp — 이 기계가 `-ser`·`-rtr`·저비트 퀀트 때문에 서빙하는 포크 — 에 `deepseek41`이 없었기 때문이다. 이식은 [v41-serving](../docs/v41-serving.md)에 있다. 이 기록이 맞는 숫자 내기까지고, [README](../README.md) 기계에 CPU only, 이 날짜 측정이다.

전부 mainline이 자기 포트 서빙 중·모델 드라이브 209 GB 다운로드 중에 쟀다. 정확도 gate에 무리 없다 — perplexity가 CPU에 다른 누가 있든 신경 안 쓴다 — 그래서 ~~이 기록 처리량 수치 무엇도 처리량 수치에 읽지 않는다~~ 첫 절 처리량 수치 무엇도 처리량 수치에 읽지 않는다. 처리량 절 끝 조용한 상자 표(같은 날 뒤 추가)가 예외다.

## 순서대로

로더 먼저 끝냈다. 텐서 1046개, engram 텐서 여덟·비전 라우팅 바이어스 마흔 포함. 이어서 그래프 3조각. 일반화 압축-KV 런타임(파일에서 ratio·overlap 가져오는 플랜 슬롯 둘. 하드코드 4-overlapping·128 대신), 소스층 행 풀링·리더 alias V4.1 sparse attention, 호스트쪽 해시 engram lookup.

빌드 6이 처음 그래프에 닿았다. `build_deepseek4()` 안 `ggml_mul_mat`에 assert 없이 segfault 났고, Release 바이너리에 줄 번호 없었다. null 피연산자 조건 `ggml_mul_mat` `gdb` 중단점이 텐서를 지목했을 것이다. mainline 모델 파일 먼저 읽기가 빨랐다. 머리 주석이 V4와 차이 셋을 나열하고, 하나가 이식 노트가 재던 텐서 delta에 없었다. **hyper-connection 계수가 한 sublayer 늦는다.** 그래서 학습 출력 헤드가 없다. null 피연산자가 `output_hc_fn`이었다. 고침이 층 루프에 실어 나르는 mix 텐서다 — 어텐션이 4스트림 복사본을 앞 FFN mix에 접고, FFN이 어텐션 것에, 0층이 one-hot에, 마지막 FFN mix가 출력 접는다.

빌드 7이 디코드했다. raw 프롬프트 temperature 0 48토큰.

```
대한민국의 수도는 서울특별시이다. 대한민국의 인구는 51,000,000명이다. 대한민국의 인구는 …
```

문법 맞고, 사실 맞고, 반복한다 — instruct 모델이 raw 프롬프트 탐욕 샘플링에 하는 것이라서, 그래프 안 깨졌다는 말이지 그 이상 아니다. 뻔히 말한다. 이 텍스트가 다음 절 244점 매기는 그래프에서 나왔다. 잘 읽히는 디코드가 맞는 그래프 증거가 아니다. 정확도 gate가 정확히 그 경우에 있다.

## gate

wikitext-2, 2048 4청크, 양쪽 바이너리 `-ngl 0`에 같은 Q3_K_M 샤드, 페이지 캐시 공유. gate에 FAIL-first 조항이 있다. 포트가 먼저 틀린 숫자를 내야 gate가 무엇을 재는지 안다.

| 빌드 | 청크 1 | 청크 2 | 청크 3 | 청크 4 | 최종 |
|---|---|---|---|---|---|
| mainline `llama.cpp` | 1.7334 | 1.7571 | 1.8354 | 2.2438 | 2.2438 ± 0.0631 |
| ik 빌드 7 그래프(hyper-connection 고침. 빌드 8 바이너리, 로그 고침뿐) | 246.06 | 267.78 | 271.80 | 244.72 | 244.72 ± 12.03 |
| ik 빌드 9 | 1.7229 | 1.7499 | 1.8242 | 2.2258 | 2.2258 ± 0.0622 |

빌드 7이 두 자릿수에 깨져서 gate가 재고 있었다. 결함이 V4 그래프 물려받은 한 줄이다. 쿼리 up 투영 뒤 V4가 헤드마다 다시 RMS 정규화하고, ik 헬퍼가 그 층 가중 없을 때도 한다. V4.1은 low-rank 부분만 정규화한다. mainline이 한 줄 주석에 말한다. ik 그래프가 말할 이유 없었다. V4에는 맞았으니까. 빌드 9가 `deepseek41`에 건너뛰고 매 청크 oracle 오차대 안에 떨어진다. 약간 밑이다. 축하할 무엇이 아니라 다른 Q3_K 커널 둘의 평소 모양이다.

빌드 7·9 사이 번호 없는 교훈 하나. 텐서별 덤프(`llama-eval-callback`)를 갈라지는 층 이분하려고 양쪽에 깔고 한 번도 안 썼다. mainline 덤프가 들어가는 길에 두 번 죽어서다 — 한 번 바이너리 없음에, 한 번 서버가 이미 쥔 GPU에 CUDA 컨텍스트 열기가 `-ngl 0`에도 out-of-memory 에러라서다. `CUDA_VISIBLE_DEVICES=""`가 고침이다. 의심 고친 perplexity 실행이 먼저 끝났다.

## 디코드 경로, oracle 대조

Perplexity가 그래프를 배치에 돌린다. 서버가 토큰 하나씩 돈다. perplexity가 안 밟는 경로(`n_tokens == 1`, shared top-k 행 gather) 통해서다. 마지막 검사가 배치 모양이었다. ik `llama-server` `-ngl 0`에 예비 포트, mainline이 평소 포트, 같은 raw 프롬프트 문자열 양쪽 `/completion`에, 탐욕.

| 프롬프트 | ik | mainline |
|---|---|---|
| BOS + user + assistant + `</think>` | "The capital of South Korea is Seoul. It is a sprawling, vibrant metropolis that blends ancient palaces and temples with cutting-edge technology and modern skyscrapers, while serving as the country's political" | 앞 12토큰 동일, 이어서 "…cutting-edge skyscrapers and technology, serving as the country's political, economic" |
| BOS 없음, `</think>` 있음 | "…It is a bustling metropolis that serves as the country's political, economic, and cultural center…" | "…It is a bustling metropolis known for its blend of ancient temples and modern skyscrapers…" |

앞 토큰 일치·첫 near-tie 뒤 drift가 다른 Q3_K 커널 둘 모양이다. perplexity 숫자가 보이는 같은 drift다. 두 번째 ubatch 크기 실행(`-b 512 -ub 512`, engram history가 ubatch 경계 넘게)이 같은 설정 mainline 2.2537 ± 0.064 상대 2.2320 ± 0.062에 들어왔다.

같은 세션 그래프 아닌 것 둘 나왔다. 둘 다 이 포트가 아니라 ik 서버 것이다. `--jinja`에 ik가 V4.1 채팅 템플릿을 `reasoning_effort` `none`에 `</think>` 없이 렌더해서, mainline이 바로 답하는 채팅 요청이 ik에 thinking 요청에 간다. `n_predict`가 멀티바이트 한글 문자 안에 떨어지는 `/completion`이 500에 돌아온다. "incomplete UTF-8 string". 둘 다 위 명령줄에 재현된다. 후속에 filed, 여기 안 고쳤다.

## draft 모델: 뽑았지, 아직 안 묶었다

V4.1-Flash가 추측 디코딩 draft를 이름 셋에 싣는다. 한 번 풀 가치 있다. DeepSeek가 메커니즘을 **DSpark**라 부른다(신뢰 스케줄 검증 반자기회귀 drafting. 체크포인트 추론 코드에 `dspark_block_size`, `dspark_target_layer_ids`). 텐서가 V3 시절 접두사 **`mtp.*`**를 달고 있다(블록 셋, `mtp.0`–`mtp.2`). 내용은 DSpark다 — `mtp.2`에 `markov_head.embed/head`·`confidence_head.proj` — mainline `--mtp` export가 기대하는 V3식 next-token 헤드가 아니라 못 읽는다. ik_llama.cpp가 이 집안을 **DFlash** companion 아키텍처에 구현하고, 원하는 GGUF가 `arch = dflash`다.

Q3_K_M 업로드에 이 텐서 없다(텐서 1046개, 몸통 블록 정확히 40개). draft가 fp8 원본에서 와야 했다. V4.1 브랜치 컨버터(`vcruz305/llama.cpp`. 이 기록 내내 "mainline"이 그것이다. 업스트림에 V4.1이 open draft 밖에 없어서)가 `--dspark`를 `DeepseekV4ForCausalLM` 아니면 거부한다(`convert_hf_to_gguf.py:269-274`). 동작 복사본이 V4.1 dequantizer 물려받는 `DeepseekV41DSparkModel`에 gate를 넓혔다 — V4에 fp8 블록 [128,128] 상대 V4.1 [32,32]다. 틀리면 에러 없이 garbage가 나온다. 결과 파일 하나, 7.97 GB, 텐서 78개, draft expert MXFP4. 모델 옆 `DSpark` 디렉터리 `DeepSeek-V4.1-Flash-Fp8-128x742M-MXFP4_MOE.gguf`에 있다. 블록 크기 검사가 `mtp.0.attn.wq_a.weight` 왕복이었다. safetensors 직접 fp8 역양자 대 GGUF Q8_0, 상대 RMS 오차 5.4e-3. [128,128] 스케일 레이아웃 강제 같은 비교가 0.144다. 조용한 실패 모양이 그것이었을 것이다.

~~데이터지 동작 draft가 아니다. 파일과 tok/s 숫자 사이 셋이 서 있다.~~ 같은 날 뒤 draft가 묶이고, 로드되고, 쟀다. 아래 문단이 결과고, 목록이 계획으로 남는다. ik DSpark 로더가 `output_hc_{base,fn,scale}`을 요구한다(`llama-load-tensors.cpp:2814-2817`). V4.1에 없다 — 출력 hyper-connection 헤드가 lag이 없앤 정확히 그것이다. draft 그래프(`build_dflash_dsv4`)가 V4 규칙에 쓰여서 몸통에 필요하던 같은 변경 둘, 1-sublayer lag·low-rank-only q norm이 필요하다. 틀리게 든 draft가 틀린 토큰을 내밀고 처리량을 올리는 대신 내린다. 몸통 GPU 경로가 아래 검증됐다. ik 베이스라인이 draft 잴 자리에 이제 있다. 그 순서다.

### draft, 묶음: 로드되고, 돌아가고, 아직 값을 안 한다

로더·그래프 변경이 ik 트리 커밋 하나(`7b79b229`, 파일 넷, 43줄)다. `output_hc_base.weight` 없음에 V4.1 draft를 알아보고, 헤드 텐서 셋 optional, draft 그래프가 헤드별 q norm 건너뛰고 hyper-connection mix를 몸통 정확히 한 sublayer 늦게 넘기고, 마지막 FFN mix가 출력에 복사본을 접는다. draft 파일 자체 정정 하나 필요했다. DeepSeek V4 코드가 타깃 은닉 상태를 각 타깃층 돈 *뒤*에 모은다. V4.1 코드가 *앞*에 모은다(`inference/model.py`. "MTP 헤드가 타깃층 출력이 아니라 어텐션 입력을 읽는다"). 컨버터가 V4의 `config + 1`을 물려받아 `target_layers = [38, 39, 40]`을 썼다. ik가 37–39층 출력을 읽는다. 참조가 36–38층 출력을 읽는다. 메타데이터뿐 복사 `[37, 38, 39]`(`tools/dspark/fix-target-layers.py`, 텐서 바이트 동일)가 정정 파일이다.

양쪽 파일이 같은 gate에 돌았다. ik 서버 `--model-draft … --spec-type dspark:n_max=5`, 탐욕 200토큰 완성 셋, accept가 서버 자체 `draft_n` / `draft_n_accepted`에서, engram 재포장이 모델 드라이브 쓰는 중이라서(tok/s가 경합, accept율이 아니다).

| arm | 디코드 tok/s | draft | accept |
|---|---|---|---|
| draft 없음 | 11.7 / 12.8 / 12.8 | — | — |
| draft, 정정 id [37,38,39] | 8.9 / 12.2 / — | 415 / 317 | 115(28%) / 133(42%) |
| draft, 변환 그대로 [38,39,40] | 9.2 / 8.7 / 11.4 | 413 / 452 / 343 | 115(28%) / 108(24%) / 128(37%) |

둘 따라오고 하나 안 따라온다. draft가 이 상자에 종단 돌았다. 오늘 아침 안 돌았다. ~~손익분기 밑이다. 4분의 1–5분의 2 accept에 5토큰 블록이 아끼는 타깃 일보다 값을 치르고, 디코드가 draft 없이보다 느려진다.~~ (같은 오후 Struck. 프롬프트 스물·작은 블록이 손익분기 위에 올렸다. 아래 표.) 안 따라오는 것이 off-by-one이다. 정정 id가 accept를 3프롬프트 노이즈 밖 안 움직였다. 정정이 맞고 draft 그래프 다른 어딘가도 틀렸거나, 캡처 지점이 주석 말과 달라서 파일이 내내 맞았거나. ~~남는 용의자가 코드 리딩 올린 rope다. 참조 draft 어텐션이 몸통 YaRN 정정 주파수 표를 쓰고, ik DSV4 draft 그래프(V4·V4.1 alike)가 draft를 `freq_scale = 1, ext_factor = 0` plain rope에 건다 — 20토큰 프롬프트 불가시지만 테이블이 다른 것에 학습됐다.~~ gate가 draft·no-draft 출력 토큰 동일도 시도했다. 프롬프트마다 74–237자 뒤 갈린다. Q3 타깃이 엔진 사이 보이는 배치 검증 대 1토큰씩 drift라서다. lossy draft와 맞는 draft를 안 나누니, accept가 이 표 묻는 숫자라서다.

rope 용의자가 틀렸다. 위에 struck이다. 참조 `DSparkAttention`이 `compress_ratio == 0`을 assert한다. 압축 없는 V4.1 어텐션층이 YaRN 끄고 base theta를 쓴다. plain rope가 참조 하는 것이다. ik가 rope 거는 양쪽 — 블록 쿼리·타깃 은닉 짓는 컨텍스트 K/V — 같은 것을 한다. 두 번째 줄별 대조가 다른 조각도 맞다고 찾았다. 캡처가 37–39층 입력이다. `[37,38,39]`가 맞는 파일이다. 블록이 마지막 타깃 토큰 다음 위치에 시작한다. filler 토큰이 128799다. Markov bias가 앞 draft 토큰에 각 위치를 묶는다. 하나가 안 맞는다. 변환 draft에 `dflash.attention.causal` 키가 없어서, ik가 5토큰 블록 안 causal 마스크에 떨어진다. 참조(`get_dspark_topk_idxs`)가 모든 블록 위치에 블록 전체를 보여준다. 다른 마스크에 학습된 draft를 다른 마스크에 돌리면 첫 뒤 모든 블록 위치 은닉 상태가 달라진다. 용의자가 이제 그것이다. 키 false 복사본이 테스트다.

### 프롬프트 셋이 아니라 스물, 블록 크기

위 3프롬프트 표 오차대가 답을 숨길 너비라서, 다음 gate가 정정 draft 한 번 로드하고 프롬프트 스물에 돌렸다. 요청마다 블록 크기 바꿨다(ik 서버에 `speculative.n_max`가 요청별 override다). 기계가 조용하지 않았다 — 옆에 CPU 벤치 돌아서 load average 18–24 — tok/s 열이 하한이지 숫자가 아니다. accept가 로드 의존 안 한다.

| 블록(`n_max`) | draft | accept | 프롬프트별 중앙(최소–최대) | 디코드 tok/s, 중앙 |
|---|---|---|---|---|
| 5 | 5181 | 2128(41.1%) | 45%(13–87) | 13.4 |
| 3 | 3590 | 1968(54.8%) | 61%(20–88) | 18.9 |

둘 바뀐다. 먼저 판정. 로드 24에 18.9 tok/s가 조용한 상자 draft 없는 같은 바이너리 14 tok/s 위다. draft가 값을 한다. 아침 "손익분기 밑"이 프롬프트 셋·5토큰 블록의 산물이었다. 둘째 블록. 5토큰 블록 4·5위치가 accept 드물게 해서 검증 값보다 치른다. 3토큰 블록이 accept 14포인트·5.5 tok/s를 가져간다. 3프롬프트 표 못 보이던 다른 것이 프롬프트별 흩어짐이다 — 산문 continuations 13%·SQL 쿼리 87% — 이 draft 3프롬프트 샘플이 다른 샘플과 안 맞는 이유다.

`causal=false` 복사본 draft가 프롬프트마다 소수까지 원본 동일하게 쟀다. 가설 깨진 게 아니다. 키가 무시된 것이다 — ik가 `attention.causal`을 `dflash2` 아키텍처에만 읽고, 이 draft가 `dflash`다. 두 arm이 control이다. control이 스위치가 안 묶였다 말한다. ik 트리 한 줄 패치가 `dflash` draft에도 키를 읽는다. 그 바이너리 실행이 진짜 테스트다.

그 gate 셋째 마지막 실행이 재는 자 측정도 냈다. gate 스크립트를 도는 중 고쳤고, bash가 새 줄을 읽고, 마지막 arm·서빙 재시작 사이 unbound 변수에 죽었다. 서빙 재시작이 손에 됐다. 스크립트가 돈 대로 `tools/dspark/`에 있다. 고침과 함께.

### 마스크, 읽고 이어서 재고

복사본 답 못 하던 질문에 이어서 두 번 답했다. 먼저 읽고 이어서 돌리고. 읽기가 먼저인 것은 대개 기계가 필요 없어서다. 참조 draft 인덱스 함수(`get_dspark_topk_idxs`)가 제안 블록 모든 위치에 같은 행을 준다. 마지막 128 확정 위치 링 + 5블록 슬롯 전부다. sparse-attention 커널이 `-1` 인덱스 말고 마스크하는 것 없다. draft 어텐션 어디에도 causal 마스크가 없다. ik 마스크 빌더(`llama-dflash.cpp`)가 둘 다르게 했다. 블록 위치 *j*에 블록 위치 *j*까지만 보여주고, 쿼리 행에 128키 창을 밀어서 행 *j*가 참조 모든 행 128 상대 127 − *j* 윈도우 키를 봤다. 둘 다 진짜 빗나감이다. 둘 다 몇 줄이다.

고침 첫 시도가 — `attention.causal` 키 — 틀린 레버였다. 읽기가 그것도 찾았다. 뒤집는 플래그가 `hparams.causal_attn`이다. ik에 그 플래그가 KV 캐시 업데이트도 막는다("non-causal 마스크가 KV 캐시를 안 쓴다"). 배치 크기 clamp·조각모음·임베딩 모델 입력 경로도. 그 바이너리 실행이 마스크·부작용 넷을 같이 쟀을 것이다. 대신 들어간 패치가 draft 로컬 플래그를 더한다. V4.1 draft에 자동 셋된다. 마스크 두 줄만 건드린다. 전체 블록 보임, 최신 확정 위치 고정 창.다른 DFlash draft가 causal·슬라이딩 마스크 유지한다. ik 트리 커밋 `515a94a3`이다.

같은 읽기 패스가 draft 하는 나머지 전부 줄별 참조 대조했다. rope(plain, base theta, YaRN 없음 — 참조가 비압축 경로 assert한다). 캡처 지점(37–39층 입력, 4 hyper-connection 스트림 평균. ik가 1-based id 줄여 36–38 `l_out`을 캡처한다. 같은 텐서다). 블록 기하(샘플 토큰 위치 +1, 뒤 노이즈 토큰). Markov 헤드(앞 draft 토큰 argmax 체인 bias). 공유 헤드·norm, hyper-connection lag 순서, q·kv 투영·norm, 어텐션 출력 역 rope, sink, softmax scale. 전부 맞는다. 코드 빗나감이 마스크 하나였다.

이어서 실행, 같은 프롬프트 스물, 다른 같은 바이너리.

| 블록(`n_max`) | causal 마스크(전) | 참조 마스크(후) | 프롬프트 상승 / 하락 / 동일 |
|---|---|---|---|
| 5 | 41.1%(2128 / 5181) | 41.6%(2139 / 5147) | 6 / 7 / 7 |
| 3, 앞 11 프롬프트 | 59.1%(974 / 1649) | 62.8%(998 / 1588) | 5 / 3 / 3 |

숫자가 움직여서 패치가 live다 — 이른 control 복사본이 전혀 안 움직였다 — 프롬프트별 흩어짐보다 적게 움직였다. 5토큰 블록 0.5포인트, 11프롬프트 3토큰 블록 4 미만이다(500에 요청 하나 깨져서 arm을 건너뛰지 말고 멈춘 하네스. 스크립트 고침). 마스크가 진짜 mismatch였고 원인이 아니었다. 패치가 참조에 맞아서 남지 값을 해서 남지 않는다.

남는 것이 코드에 없다. 다음 실행 둘이 일부를 찾았다. draft가 임베딩·헤드 자체가 없다. 타깃 것을 빌린다. 이 타깃에 `token_embd` Q3_K·`output` Q6_K다. draft가 bf16 복사본 상대 학습됐다. 업로더 Q8_0셋이 둘을 bf16에 둔다. 타깃 변형 둘이 샤드 1에 그 텐서 둘 graft 지었다(`tools/dspark/graft-gguf-tensors.py`. 다른 8샤드 하드링크, 디스크 전부 2 GB 값). bf16 임베딩 하나, 임베딩·헤드 하나. 같은 프롬프트 스물, 같은 패치 바이너리, 양쪽 스물 전부 완료.

| 타깃 샤드 1 | `n_max` 5 | 프롬프트별 중앙(최소–최대) | `n_max` 3 | 프롬프트별 중앙(최소–최대) |
|---|---|---|---|---|
| 업로드(Q3_K 임베딩, Q6_K 헤드), causal 마스크 | 41.1% | 45%(13–87) | 54.8% | 61%(20–88) |
| 업로드, 참조 마스크 | 41.6% | 50%(11–78) | 62.8%\* | 64%(25–85) |
| bf16 임베딩 | **45.5%** | 53%(22–81) | **60.1%** | 63%(30–86) |
| bf16 임베딩·헤드 | 46.2% | 52%(20–80) | 59.9% | 65%(24–84) |

\* 11프롬프트, 500에 멈춘 실행. 같은 11개 causal 마스크 59.1%.

임베딩이 움직이는 것이다. 업로드 샤드 상대 같은 바이너리 5토큰 블록 4포인트다. 프롬프트별 흩어짐 하한이 11%에서 22%에 오른다 — draft 최악 프롬프트가 3비트 임베딩 가장 아프던 것들이다. 그 위 헤드가 안 움직인다. 한 블록 크기 한쪽 0.7포인트, 다른 쪽 0.2포인트. 프롬프트별 6상승·6하락·8동일. 3토큰 블록 둘 변경이 깨끗 분리 안 된다. 마스크뿐 실행이 안 끝났어서다. 프롬프트 스물이 말하는 것은 업로드 샤드 54.8%·bf16 임베딩 60.1%다. 마스크가 둘째에 들어 있다. 이 실행 tok/s 열이 또 하한이다. 로드 19–28.

빌린 임베딩이 간격의 진짜 일부였고 빌린 헤드가 아니었다. 기계 레시피가 graft 샤드 하나다. DSpark draft 도는 타깃에 `token_embd`를 bf16에 둔다. 값이 로드 RAM 1.3 GB다. 업로더에 같은 문장이 권고다. 노이즈원 둘 남고 어느 쪽 graft에도 안 간다. 타깃 은닉 특성이 Q3_K 몸통에서 온다. ~~draft 자체 expert가 fp8 MXFP4 재양자화다. draft 파일 8 GB라 Q8_0 재변환이 싼 다음 테스트다~~ — 같은 저녁 struck이다. 체크포인트가 draft routed expert를 32가중치당 E8M0 스케일 하나 팩 4비트에 저장한다(`mtp.0.ffn.experts.0.w1.weight`가 `I8 [2304, 2560]`, 스케일 `[2304, 160]`). MXFP4 그 자체다. 컨버터가 그 바이트를 다시 싼다. 양자화 안 한다.다른 draft가 fp8 역양자 Q8_0이다. 공유 임베딩이 이제 bf16이다. 변환할 상위 정밀도 draft가 없다. 안 시험한 원천 하나가 Q3_K 타깃 몸통뿐이다. 상위 정밀도 타깃이 이 기계 싸지 않다. 스케일에 draft 발행자 자체 벤치 스텝당 평균 accept 길이 3.57 토큰을 둔다. 45.5% 5토큰 블록이 스텝당 draft 2.3 토큰 accept + 검증 하나다. 다른 workload 같은 근처다.

### 레버, 당김, ik 최종표

위 전부 다른 돌아가는 것 있게 쟀다. 오늘 마지막 창이 조용한 상자 한 순서에 전부 두고, 프로파일 남긴 레버 둘을 당겼다. 핀 메모리와 CPU쪽 엔진 선택.

핀 메모리 레버가 종이 최대로 보였다. `-ot`가 텐서를 CPU에 보내면 ik 로더(`src/llama-load-tensors.cpp`)가 mmap을 떨어서 그 가중치가 핀 호스트 메모리에 떨어진다. CPU쪽 411 GB에 그 할당이 될 수 없다. 문서 탈출 `GGML_CUDA_NO_PINNED=1`이 `ggml_cuda_host_malloc`을 모든 스테이징 버퍼 null에 돌려서, 그래프 호스트-장치 복사 전부가 페이지블 메모리에 간다. 4줄 패치가 `GGML_CUDA_NO_PINNED_WEIGHTS`를 더한다. 가중치가 mmap·언핀에 남고, 스테이징 버퍼가 핀에 남는다. 같은 3프롬프트 draft 없는 bf16 임베딩 타깃 측정. **페이지블 13.63 tok/s, 핀 스테이징 13.60.** 동일 no-draft 구성 로드 둘이 한 시간 간격 13.63·14.13이라 로드-로드 밴드가 약 4%다. 판정이 이 그래프 핀 스테이징이 그 안에 있다는 것이다. 작은 하이브리드 모델에 아니다. DeepSeek-V2-Lite Q3_K_M expert CPU에(`llama-bench`, tg128, 3반복)가 전부 페이지블 60.1 tok/s·핀 스테이징 66.0·ik 기본 다 핀 65.1에 디코드한다 — mainline 같은 파일 같은 배치 68.9. 탈출 hatch가 핀할 가중치 작으면 10%를 값을 치른다. 패치가 그 용도다. 포크 3ded8071에 V4.1 숫자를 메시지에 커밋했다. V4.1 후보가 닫혔다.

스레드 수가 프로파일 가리키던 다른 후보다(OpenMP 배리어 샘플 43%, CUDA 드라이버·HTTP 스레드 다투는 32코어 32스레드). 같은 no-draft 서버 `-t 30`에 14.27 / 13.36 / 13.21 tok/s. `-t 28`에 13.20 / 13.26 / 13.02. `-t 32`에 13.63 / 13.10 / 13.64. 전부 밴드 안이다. 닫혔다.

CPU쪽 엔진 레버가 위 작은 모델 커널 벤치다. 같은 상자 위임 돌림([보고·모든 명령](../docs/throughput-model.md)). dense Qwen2.5-7B Q3_K_M 32스레드 ik 디코드 32.0 tok/s 상대 mainline 30.4, 프리필 217 상대 104. DeepSeek-V2-Lite Q3_K_M(deepseek2 MoE) 73.5 상대 66.2, 447 상대 201. `-rtr`·`-fmoe 0`이 양쪽 기본 5% 안이다. CPU matmul에 ik가 뒤가 아니라 앞이다. V4.1 간격 디코드 20%·프리필 25%가 일반 커널 적자가 아니다. 그 벤치가 다섯째 충돌도 값을 치렀다. gate가 또 load average였고, 마지막 라운드가 이 창 CPU-only V4.1 측정 너머 돌아서 양쪽 버리고 CPU-only 비교 단독 재실행했다. 방법 노트가 [`docs/quiet-machine.md`](../docs/quiet-machine.md)에 있다.

그 재실행이 손실 자리 지목하는 숫자다. V4.1 자체, 같은 bf16 임베딩 파일, `-ngl 0`·보이는 GPU 없음, `llama-bench` tg64 2반복, 상자에 다른 아무것도 없음(시작 IO 압력 0.08, 다른 `llama-*` 프로세스 없음). **ik 디코드 9.80 tok/s, mainline 7.98.** 프리필 숫자(18.9 ± 10.7·16.0 ± 4.1)가 2반복 노이즈 커서 순위 못 매긴다. 바로 이 그래프 전부 CPU에 ik가 23% 앞이다 — 프로덕션 배치 CPU expert 6층·어텐션 전부 GPU에 20% 뒤다. 간격 전부, 더하기, 하이브리드 경로에 있다. ik가 CPU expert·GPU 사이 하는 것 — 토큰당 호스트-장치 트래픽, 그래프 분할, 스케줄러 — matmul이 아니다. 작은 모델 하이브리드 벤치가 작은 스케일 같은 말을 한다(V2-Lite 66 상대 69). 이 벤치가 찾으러 돈 성능 개선 지점이다. 읽던 커널과 다른 읽을 자리다.

최종표가 프로덕션 배치 bf16 임베딩 타깃이다. ik `llama-server`, arm당 탐욕 200토큰 프롬프트 스물, arm당 모델 로드 하나, 상자에 다른 론치한 것 없음. 커널 벤치 명령 로그 16:17 끝난다. 10초마다 live `llama-*` pid 나열 프로세스 샘플러가 16:48 멈출 때까지 이 창 서버만 보여준다. 뒤 증인이 창 스크립트 단독이다. 행 로드 평균 17–31이 서버 자체 32코어 32스레드다. draft 없음, 이어서 3토큰·5토큰 블록.

| arm | draft | accept | 디코드 tok/s, 중앙(최소–최대) | no-draft보다 빠른 프롬프트 |
|---|---|---|---|---|
| draft 없음 | — | — | 14.13(13.19–14.95) | — |
| DSpark, `n_max` 5 | 4808 | 2187(45.5%) | 14.33(8.42–20.89) | 11 / 20 |
| DSpark, `n_max` 3 | 3321 | 1996(60.1%) | **19.86**(11.41–28.89) | 17 / 20 |

accept율이 이른 경합 실행 소수까지 재현된다. accept가 그래야 한다. 출력이 안 그렇다. `n_max` 5에 탐욕 텍스트 스물 중 셋만 no-draft 텍스트 동일하다.다른 17개가 32–493자 뒤 갈린다. draft arm·no-draft arm이 접두사 공유 이어서 달라지는 continuations에 시간 잰 것이다. 오늘 이른 두 draft arm이 문자까지 동일했는데 맞는다. 검증 배치·단일 토큰 디코드가 near-tie argmax를 뒤집는다. tok/s 비교가 선다(텍스트가 몇 % 안 길다). drafting이 탐욕 출력 안 바꾼다는 주장이 안 선다. 숫자가 새 숫자다. 3토큰 블록이 중앙 **no-draft보다 41% 빠르다**. 프롬프트별 1.43배(0.81–1.95). 5토큰 블록이 손익분기다. draft 없는 mainline(17–18 tok/s, 조용한 상자, 위 — 몸통 같지만 graft 아닌 engramQ8 샤드 1 Q3_K 임베딩) 상대, draft 든 포트가 draft 없는 mainline보다 빨리 디코드한다. 오늘이 그 문장 처음 맞은 때다. 간격이 밑에 그대로 있다. draft 없이 14.1 상대 17–18.

### mainline에 같은 draft

맞는 크기 레버가 ik 안에 있은 적 없다. mainline이 8월 DSpark를 머지했다(PR #25173·#25784). 이 기록 내내 재던 V4.1 런타임 브랜치가 그 코드를 싣고 있다. 싣지 않던 것이 V4.1 draft다. mainline 밑 draft 로드가 `output_hc_fn.weight` 없음에 깨진다. mainline DSV4 draft 그래프가 V4 draft다. 학습 출력 헤드, 같은 sublayer 소비 mixes, 헤드별 q 정규화. 셋 차이가 ik 포트 필요하던 같은 셋이다(거기 커밋 7b79b229). mainline 자체 V4.1 몸통 그래프(`src/models/deepseek41.cpp`)가 타깃에 이미 구현한다. 이식이 transcription이다. 파일에 `output_hc_base.weight` 없으면 서는 `dflash_dsv41` 플래그, 그 밑 헤드 텐서 셋 optional, draft 루프가 one-hot 시작 다음 것용 각 sublayer mix를 계산하고 마지막 FFN mix에 접고, q 헤드별 `rms_norm` 건너뛴다. 파일 셋, 추가 52줄·삭제 9줄, 업스트림 master 위 open 추측 PR 둘(#27569, #26575) 무충돌 머지.

로드되고 돌아간다. 같은 타깃 파일, 같은 배치, 같은 프롬프트 스물. mainline `llama-server`에 위 모든 mainline 숫자 같은 `--lazy-mode auto`.

| arm | draft | accept | 디코드 tok/s, 중앙(최소–최대) |
|---|---|---|---|
| draft 없음 | — | — | 17.70(9.41–18.09) |
| DSpark 블록 5, 로드 뒤 첫 패스 | 5022 | 2192(43.6%) | 18.29(9.05–26.65) |
| DSpark 블록 5, 2패스, 같은 서버 | 5022 | 2192(43.6%) | **22.48**(11.09–32.89) |

둘 주의 읽기. accept가 같은 블록 ik 45.5% 상대 43.6%다. 포트가 같은 일 한다는 데 가깝고, 두 검증이 비트 동일하지 않을 데 멀다. 두 패스 draft 수가 같은 것은 mainline이 요청 `speculative.n_max`를 무시해서다. 서버 스키마에 그 필드가 `#if 0` 밑 TODO에 있다("we disable speculative parameter adjustments for now", `tools/server/server-schema.cpp`). 스위프 "n_max 3" 패스가 2번째 블록-5 패스였다 — 첫보다 23% 빨랐다. 같은 draft에. 유력 이유가 fresh 로드 뒤 20프롬프트 너머 expert 아직 페이지인 하는 `--lazy-mode auto`다. no-draft 패스가 첫 행에도 보였다. 그 귀속이 후보다. 측정이 아니다. 모양 자체가 두 번 쟀다(아래). 로드 뒤 첫 패스가 느리고, 셋째가 둘째를 안 이긴다. 2패스 숫자가 비교할 것이다. **같은 draft 블록 5에 mainline 22.5 tok/s 상대 ik 14.3**이다. draft 없는 mainline 17.7 상대 ik 14.1도. 블록-3 실행이 서버 명령줄 크기 박는(요청 필드가 죽어서) 오늘 마지막 숫자다.

| arm | draft | accept | 디코드 tok/s, 중앙(최소–최대) | 25 넘 프롬프트 |
|---|---|---|---|---|
| DSpark 블록 3, 로드 뒤 첫 패스 | 3321 | 1963(59.1%) | 20.27(12.98–25.93) | 3 / 20 |
| DSpark 블록 3, 2패스, 같은 서버 | 3321 | 1963(59.1%) | **22.78**(15.33–29.74) | 8 / 20 |

서빙 포트가 이어서 이 빌드, 타깃·draft 블록 3에 재시작됐다. 같은 프롬프트 스물 두 번 더 그 상대 돌렸다. 그 로드 뒤 첫 패스가 내 채팅 요청 둘이 프롬프트 4·5에 겹쳤다. 프롬프트 6–20이 이른 로드 뒤 첫 패스에 1% 안 맞는다(중앙 비율 1.00). 그 로드 뒤 2패스.

| 패스 | 디코드 tok/s, 중앙(최소–최대) | 위 2패스 상대, 프롬프트별 |
|---|---|---|
| 18:40 로드 뒤 첫 | 19.58(13.14–25.53) | 0.88 |
| 18:40 로드 뒤 둘째 | **22.69**(15.29–29.59) | 0.996 |

22.7–22.8이 고원이지 하한이 아니다. 로드 둘에 재현된다.

ik에 그렇게 중요하던 블록 크기가 mainline에 안 통한다(22.5 상대 22.8). mainline 검증이 싸서 draft 토큰 둘 더가 돌려주는 값을 치른다. accept율이 양쪽 블록 ik 1.5포인트 안 맞는다. 포트가 도는 것이다. 기계 숫자가 draft 든 DeepSeek-V4.1-Flash, 조용한 상자, warm에 **중앙 22.8 tok/s, 최고 29.7**이다. draft 없는 mainline 상대 29%다. ~~ik 든 상대 61%~~ — 한 시간 안 정정이다. draft 없는 ik 상대 61%(14.1)고 자체 블록-3 draft 든 ik 상대 15%(19.9)다. 오늘 겨냥 25가 프롬프트 스물 중 여덟 중앙이지 셋 중앙이 아니다. 22.8–25 사이 있는 것이 mainline no-draft율 자체다. 위 하이브리드 경로 발견이 다음 일 자리라 말한다. 엔진 선택이 측정을 따른다. 서빙 포트가 mainline 빌드 포트·블록 3에 옮긴다.

## 값과 주장 안 하는 것

테스트마다 4분 모델 로드가 값을 치른다. 페이지 캐시에 이미 있는 파일 256 GB 매핑이다. ik 로더가 모든 텐서를 건드려서다. 이 기록이 빌드 열 개·로드 열다섯쯤이다. 로드가 wall clock 대개다.

GPU 경로, 같은 날 뒤. `GGML_CUDA_NO_PINNED=1`에(없으면 `-ot` override가 303 GB CPU 상주 expert를 핀 할당에 바꾸고 로드가 깨진다). `-ngl 99`·프로덕션 배치 — 0–3층 expert 첫 GPU, 4–5층 둘째, 나머지 CPU — 같은 4청크 perplexity가 `-ngl 0` 2.2258 ± 0.0622 상대 **2.2270 ± 0.0625**다. 실행 어림 1.7320 / 1.7486 / 1.8248 / 2.2270, 청크당 87초 대신 39초다. CUDA 경로가 CPU 경로 같은 숫자를 낸다. one-hot mix `ggml_fill`이 스케줄러 둔 데 돌았고 이 그래프 CUDA 커널 필요 없었다. 사용 GPU 메모리가 28.8 GB·15.4 GB였다.

처리량 숫자 하나가 이제 있다. 라벨 든다. ik `llama-server` 같은 배치, 예비 포트 탐욕 200토큰 완성 셋, **14.0 / 14.3 / 14.1 tok/s**다. 모델 드라이브 100 GB 재포장 쓰는 중이었다(load average 28). mainline이 오늘 이른 같은 파일 비슷한 로드 17–19를 쟀다.

이 기록이 처음 그 간격을 ~~ik 속도 기능 전부 꺼짐~~에 설명했다. 틀렸다. 포트에 아첨하는 방향에 틀렸다. 같은 실행 서버 자체 init 줄이 `fused_moe = 1`·`flash_attn = 1`을 읽는다. 둘 다 ik 기본 on이라 플래그 필요 없다. `-mla`가 전혀 안 맞는다 — `src/llama-model.h:656` `is_mla_model()`이 DEEPSEEK2·GLM_DSA·MISTRAL4·BAILINGMOE3를 덮고 dsv4 집안을 안 덮는다. V4.1이 압축-KV 스트림 자체 싣고 있어서다. 진짜 꺼진 것이 `-ser`다. expert 떨어뜨려 사는 것이다. `-rtr`이 로드에 텐서를 다시 깔고 mmap을 내놓는다.어느 쪽도 공짜 아니다. 347 GB 파일·절대 상주 안 하는 테이블 둘 상대 `-rtr`이 자체 실험이다.

간격이 그래서 ik 기본 가속 켠 채 쟀다. 남는 변명이 플래그가 아니라 경합 기계였다. 닫는 비교가 한낮 조용한 상자에 돌았다.다른 perplexity 없음, 재포장 없음, 엔진 시작 전 양쪽 GPU·양쪽 포트 빔. 같은 engramQ8 파일, 같은 배치, 탐욕 200토큰 완성 셋씩, 서버 자체 timings 프리필·디코드.

| 프롬프트 | mainline 프리필 | mainline 디코드 | ik 프리필 | ik 디코드 |
|---|---|---|---|---|
| write-ahead log | 21.7 | 12.10 | 16.3 | 13.80 |
| swapped-out page | 30.7 | 17.80 | 23.1 | 14.06 |
| float addition | 31.0 | 17.30 | 23.1 | 14.18 |

mainline 첫 행이 `--lazy-mode auto` 워밍업이다 — 같은 스크립트 아침 실행이 5.4 / 9.5 / 11.9 같은 램프에 올랐다 — steady 숫자가 17–18 tok/s다. ik가 14다. 기계 로드(오늘 아침 로드 28에 14.0 / 14.3 / 14.1)든 조용(로드 4)든 14다. 경합 변명이 갔다. 포트가 이 그래프 mainline보다 디코드 약 20% 느리다. 프리필 약 25% 느리다. `fused_moe`·`flash_attn` 켠 채다. 20% 가는 곳이 여기 안 쟀다. 후보가 ik fused 커널 안 쓴 dsv4 그래프 경로, 리더층 top-k 재사용, 안 써본 `-rtr`이다.

20%가 아닌 곳, 한 시간 뒤 2창 서빙 정지에 쟀다. fused MoE가 아니다(`-no-fmoe` 디코드 13.2 / 13.8 / 13.6 상대 기본 13.0 / 13.5 / 13.4). 프로파일도 아니다. 디코드 중 각 서버 12초 `perf record`가 포인트 안 같은 그림을 준다. Q3_K 내적 29%, Q4_K 것 18–19%, OpenMP 배리어 스핀 43%, 양쪽 5% 넘 32스레드. ik 커널이 자체 것(`mul_mat_qY_K_q8_K_T<DequantizerQ3K>`)이고, mainline이 `ggml_vec_dot_q3_K_q8_K`인데 시간 몫이 같다 — 포트가 낮은 속도에 같은 일을 한다. flat 프로파일이 설명 못 하고 작은 dense Q3_K 파일 커널별 벤치가 설명할 수 있다. `-rtr`이 안 써봤고 이 상자 못 쓴다. mmap을 내놓고, engramQ8 파일이 RAM 251 상대 472 GB라서다. 그 창 mainline이 15.3 / 15.6 / 16.0에 400토큰 실행 16.6을 쟀다. 첫 A/B 17.8 밑이다. 앞 arm 로드 평균이 아직 20이었다. 위 ik 숫자가 먼저, 로드 10에 잡았다. 양쪽 버리고 CPU-only 비교 단독 재실행했다.

측정 스크립트 자체가 이 표 내기 전 두 번 깨졌다. 두 번째가 한 문장 값어치 있다. 서버 readiness 줄을 기억 쓴 패턴(`server is listening`)에 기다렸다.어느 엔진도 안 찍는다 — mainline이 `listening on http://`, ik가 `HTTP server listening`이라서 — 건강한 로드 15분 뒤 양쪽 절반 "ready 안 됨"을 선언했다. 위 ik 숫자가 죽이려던 서버에 손에 잡았다. mainline 절반이 패턴 고쳐 재실행했다. 스크립트가 고침과 함께 `tools/engine-ab/`에 있다.

mainline draft 포트 주장 안 하는 것. V4 draft가 거기 로드된다는 것(헤드 텐서가 `output_hc_base.weight` 없을 때만 optional이라서 그래야 하는데, V4 draft를 안 돌렸다). accept가 참조 구현에 맞는다는 것 — 증거가 양쪽 블록 크기 ik 포트 1.5포인트 안 맞는 것이고, ik 포트가 `inference/model.py` 대조 감사받은 쪽이다. 빌드가 미머지 업스트림 PR 둘(#27569, #26575)을 싣는다. 서빙 숫자가 그 트리 것이지 master 것이 아니다.

주장 안 하는 것. oracle 상대 배치 하나, 압축 스트림 세션 저장·복원(빈 TODO에 씀), MTP 그래프(assert off), `-rtr`·engram 테이블 prefetch 면제, ~~속도 무엇~~ ~~속도 무엇 너머 위 조용한 상자 A/B 하나 — 20% 원인 없음, `-rtr` 없음, draft 없음~~ — 위 최종표가 조용한 상자 draft를 싣는다. 아직 주장 안 하는 것이 20% 원인(핀 메모리·CPU 커널 둘 제외됐다)·`-rtr`이다. 리더층이 mainline처럼 dense 어텐션 말고 인덱스 소스 top-k를 재사용한다. 4청크 perplexity가 둘을 안 나눈다. 긴 컨텍스트가 나눌 수 있다.

캐시 크기 로그 줄이 빌드 둘에 거짓말했다. alias 뒤 층별 텐서 벡터를 합해서다. 소스 버퍼마다 리더 수만큼 셌다 — 할당 6.28 MiB 상대 보고 72 MiB. 이제 유일 포인터에 센다.

### 토큰 시간 행선지, VRAM 재배분: 24.8 tok/s

포트 뒤 질문이 ik에 가져갈 것 또 있는가였다. 나란히 읽으면 답이 아니다. 하이브리드 경로에 살아남는 ik 유일 이점이 CPU 내적 커널이다. 위 작은 모델 벤치 CPU 몫 5–11% 값어치다. mainline에 ik V4 경로 이어붙인 나머지 이미 있다 — hyper-connection pre/comb/post 커널(`fused_dsv4_hc_*`, 기본 on, CUDA backed), split당 CUDA 그래프, `-ot` 사용 스케줄러 복사 하나, expert마다 스레드 전부 나누고 expert 사이 배리어 없는 `mul_mat_id`. ik `-thp`가 여기 안 돌았다. hugetlbfs 풀이 필요하고 이 기계 없다.

코드가 준 것이 회계였다. GGUF 헤더에서. MoE층 40개, expert 384개, 토큰당 라우팅 6개, expert가 16.85 MB(up·gate Q3_K 각 5.07 MB, down Q4_K/Q5_K 6.71 MB). 카드 6층에 토큰이 시스템 RAM 3.44 GB를 읽는다. 3토큰 draft 4배치가 층당 최대 23.4 distinct expert를 건드린다.

| 경로 | 스텝당 바이트 | 115.8 GB/s(STREAM 실측) | 실측 |
|---|---|---:|---:|
| draft 없음, 토큰 하나 | 3.44 GB | 29.7 ms | 56.5 ms |
| 블록 3, 4배치 | 13.4 GB | 116 ms | ~127 ms |

서빙 경로가 메모리 벽 10% 안이다. 고정 오버헤드(커널 수, 그래프 런치)가 서빙 숫자를 많이 못 움직인다. 4토큰 블록이 스텝당 23% 더 읽고 accept 토큰 23% 미만이니 안 써봤다. 남는 것이 스텝당 바이트다. CPU expert층 더 적게, expert 더 작게.

재시작 둘이 가는 길에 깨졌다. 투명 huge page `always` 든 `--load-mode none`이 로더 자체 경고("tensor overrides to CPU are used with mmap enabled — consider using --load-mode none") 시험 meant였다. 9분 로드에 AnonHugePages가 150 MB 위 안 올라갔다. 서버가 24 GB 카드 515 MiB compute 버퍼 할당에 죽었다. 서빙 구성 slack 600 MB 카드다. 이해 안 됨, 되돌림. `-devd CUDA0` — draft 카드 하나에, 2카드 파이프라인 멈추려고 — 가 `ggml_backend_sched_backend_id_from_cur`에 죽는다. DSpark draft가 타깃 은닉 상태를 읽는데 일부가 CUDA1에 산다.

실패 verbose 로그가 조용한 로그 숨기던 둘을 보였다. 위 모든 mainline 숫자가 fused hyper-connection *pre* 커널 꺼진 채 돌았다. 40층 전부다. 28층이 둘째 카드 첫 층이라 `pre` mix가 첫 카드 27층에서 온다. 스케줄러가 가중 없는 fused 노드를 입력과 함께 둔다. `resolve_fused_ops` probe가 그 배치를 "지원 없음"에 읽고 op를 전역에서 껐다. unfused op가 같은 카드에 떨어져서 틀린 것 없는데 판정만 틀렸다. 고침이 op 믿기 전 층 장치에 지원 묻는다(`ggml_backend_dev_supports_op`) — 10줄, 머지 worktree 커밋 e42d711e5. 로그가 이제 "placed on CUDA0 by the scheduler, CUDA1 supports it, keeping it enabled"에 읽는다. 둘째, draft 컨텍스트에 텐서 override가 없어서 파이프라인 병렬·compute 버퍼 복사 넷에 돌았다. no-op `-otd`가 끈다.

셋째 재시작이 변경 셋·작은 마이크로배치를 같이 묶었다. `-ub 512`(compute 버퍼 CUDA0 4297 MiB·CUDA1 2447 MiB, 실측. `configs/v41-serve.sh` 머리가 4288토큰 프롬프트 값을 치른다). draft `-otd`, resolver 고침, 푼 VRAM expert에 씀 — CUDA0 blk 6 `down`·blk 7 `gate`/`up`, CUDA1 blk 6 `gate`/`up`. CPU가 34 대신 32층 단위를 스트리밍한다. 바이트 5.9% 적게. 로드 뒤 카드 49.1 중 46.8 GB·24.6 중 20.9 GB. 같은 프롬프트 스물, 탐욕, 블록 3, 2패스 모든 행 IO 압력 0.00.

| 패스 | 중앙 tok/s | 최고 | 25 넘 프롬프트 | 22.7 패스 상대 프롬프트별 비율 |
|---|---:|---:|---:|---|
| 1(로드 뒤 첫) | 21.8 | 28.0 | 4/20 | — |
| 2 | **24.75** | 31.5 | 10/20 | 1.070(중앙) |

로드-로드 밴드 약 4 상대 7%다. 첫 패스 패널티가 세 번째 재현(또 12%). 변경 셋이 재시작 하나를 공유해서 쪼개기가 안 쟀다. 위 회계에 expert 이동이 대개 싣는 부분이다. fused-pre 고침이 단독 밴드 밑이다. 서빙 포트가 이 구성에 돈다. 주장 안 하는 것. 이 빌드 긴 프롬프트 프리필 값(`-ub 512` 스크립트 머리 214 상대 343 tok/s 숫자가 이른 빌드 것). 24 GB 카드 남은 3.6 GB가 blk 7 `down`도 받는지.

텐서군 하나 더. 24 GB 카드 3.6 GB 남았으니까. blk 7 `down`(2.58 GB) CUDA1에. CPU가 31층 단위에 떨어진다. 예측 +3%. 같은 프로토콜, 2패스 IO 압력 최대 0.69.

| 패스 | 중앙 tok/s | 최고 | 25 넘 프롬프트 | 24.8 패스 상대 프롬프트별 비율 |
|---|---:|---:|---:|---|
| 1(로드 뒤 첫) | 20.6 | 27.5 | 2/20 | — |
| 2 | **25.6** | 31.8 | 11/20 | 1.011(중앙), 11/20 빠름 |

중앙이 25를 넘었다. 프롬프트별 비율이 밴드 안 단계를 말한다. 예측 3% 상대 실측 1%. slack 말고 값 0에 둔다 — 카드가 이제 49.1 중 47.0 GB·24.6 중 23.2 GB다. 다음 텐서군이 안 맞는다. "카드 expert 더" 레버가 닫힌다. 스텝당 바이트 남는 것이 expert 자체 양자화다.

### 녹음: 테이프 보이는 것·낮은 이유

위 숫자가 예비 포트 탐욕 디코딩, 프롬프트 스물, 로드 뒤 2패스다. 녹음은 다른 문에 간다. 녹음기([toktape](https://github.com/midagedev/toktape))가 서버 기본 샘플링 `/v1/chat/completions`에 말하고, 이 모델 reasoning 블록 켠 채다. 같은 프롬프트 스물 같은 서버 상대, 2.7 GHz 탐욕 패스 상대 프롬프트별 측정.

| 경로 | 중앙 tok/s | 최고 | 탐욕 `/completion` 상대 |
|---|---:|---:|---|
| 탐욕 `/completion`(위 표) | 25.6 | 31.8 | — |
| 서버 기본 샘플링, `/completion` | 24.5 | 31.4 | −4.4% |
| 채팅 엔드포인트, 탐욕, thinking on | 22.4 | 28.5 | −11.6% |

샘플링이 약간 값을 치른다. draft 토큰을 argmax 상대 샘플 타깃에 검사해서다. 채팅 경로가 더 값을 치른다. reasoning 블록이 다른 무엇처럼 초안에 오르고 accept가 나빠서다. 2048토큰 한국어 프롬프트 첫 테이프가 thinking 블록 안 2048토큰 전부를 17.3 tok/s에 썼다. 아래 녹음이 그래서 서빙 스크립트 복사본 `--reasoning-budget 0`에 가져갔다. 포트가 뒤 커밋 스크립트에 돌아왔다.

클립용 레버 하나 더 시도했다. 서빙 구성 도는 CPU 클럭 캡 2.7 GHz를 녹음 길이 3.6 GHz에 올렸다.

| cap | 중앙 tok/s | 최고 | 프롬프트별 | 냉각수 |
|---|---:|---:|---|---|
| 2.7 GHz | 25.6 | 31.8 | — | steady |
| 3.6 GHz | 27.0 | 34.1 | +4.7%, 20 중 20 빠름 | 2분 20초 38.7 → 48.8 °C |

아침 "2.7이 3.6과 같다"가 draft 없이 쟀다. draft 들면 verify 스텝 토큰당 CPU 일이 더 들고 클럭이 보인다. 서빙 설정이 아니다. 가드가 52 °C에 로드를 멈춘다. 3.6 GHz가 약 2분에 50에 닿는다. 아래 4스트림 테이프 넷째에 일어난 일이다(워치독이 캡을 도중 2.7에 떨어뜨렸다).

테이프 전부 25.6 구성, 전부 로드 뒤 2패스.

| 테이프 | 프롬프트 | cap | thinking | 단일 / 합계 tok/s | 토큰당 페이지 폴트 |
|---|---|---|---|---:|---:|
| 영어, 코드 | 최고 단일 프롬프트, 213토큰 | 2.7 | on | 28.6 | 0.4 |
| 영어, 코드 | 4스트림, 각 249토큰 | 2.7 | on | 4 × 7.4 = 29.6 | — |
| 한국어 산문, MoE·오프로드 2048토큰 | 단일 | 3.6 | off | 20.3 | 6.2 |
| 한국어 산문, 주제 넷, 각 768토큰 | 4스트림 | 3.6 | off | 4 × 6.7 = 25.1 | 2.8 |
| 영어 산문, 같은 프롬프트 | 단일 | 3.6 | off | 19.7 | 6.3 |
| 영어 산문, 같은 프롬프트 | 4스트림 | 3.6 → 2.7(워치독) | off | 4 × 5.7 = 22.6 | 5.9 |

코드 테이프가 가장 빠른 것은 잘 알려진 프롬프트 213토큰 답이 draft 잘 돼서다. 긴 산문이 draft 못하고, 2048토큰 답이 accept가 아니라 thinking 끔 패널티에 부딪힌다. 산문 클립이 "설명해 달라" 정직 숫자다. 코드 클립이 최선 정직 숫자다.

**페이지 폴트, 작은 고침 하나.** 오른쪽 열이 녹음기 디코드 중 major 페이지 폴트 수다. engram 테이블(209 GB)이 NVMe에서 토큰당 수십 행 lazy에 읽힌다. 건드린 적 없는 행이 `get_rows` 안 동기 fault다. fresh 텍스트 첫 테이프가 토큰당 fault 41개·캐시 실행 25 상대 약 20 tok/s를 보였다. 행 id가 그래프 돌기 전 `set_input`에 알려지니, 거기 각 행 페이지 `posix_madvise(WILLNEED)`(머지 worktree 커밋 86d01ece1, Linux·macOS뿐)가 같은 텍스트 토큰당 fault 0.9개에 가져왔다. 대충 +1 tok/s다. 위 산문 테이프가 아직 토큰당 3–6개를 보인다. prefetch가 물었는데 그래프 읽을 때 드라이브가 못 낸 행들이다. 공짜도 아니다.

첫 패스 패널티 위 세 번 쟀다에 도로 읽힌다. ~~유력 이유가 `--lazy-mode auto` expert 아직 페이지인 중~~ — expert가 후보다. 안 본 프롬프트 engram 행이 측정된 일부다. 20개 새 프롬프트 첫 패스가 처음 그 행을 건드리고 2패스가 페이지 캐시에 찾는다. 12% 각각 얼마나 싣는지는 안 나눴다.

클립. 영어 코드 쌍·산문 쌍 둘이 공유 드라이브에 있다. 이름 `rig-log-v41-dspark-*`. 카드·테이프 파일이 기계 녹음기 실행 디렉터리에 있다.

ik 14.1 상대 mainline 17.7 자리, 트리 둘에서 읽지 쟀지 않은 것. [`docs/v41-serving.md`](../docs/v41-serving.md)에 있다. 짧게 말하면 ik가 hyper-connection op를 이미 이어붙이고 mainline보다 덜 동기화한다. 없는 것이 절대 안 푸는 CUDA 그래프 래치다.

### fused-pre probe 버그가 mainline 것인가. 측정. 아니다

위 resolver 고침이 일반 코드에 읽힌다. master가 같은 probe·같은 fused HC op를 DeepSeek V4에 싣는다. file 전에 거기 시험했다. 업스트림 master 5f436dddb, unsloth `DeepSeek-V4-Flash-0731-UD-IQ1_S`, 2GPU 층 분할 카드 경계 30층(`-ts 2,1`)·22층(`-ts 1,1`)에, expert CPU, 탐욕 96토큰 `/completion`, master 상대 master+패치.

| 분할 | master | 패치 | 텍스트 |
|---|---:|---:|---|
| 경계 30 | HC pre 켬, 17.4 / 18.0 tok/s | 켬, 17.8 / 17.9 | 동일 |
| 경계 22 | HC pre 켬, 18.0 / 18.4 | 켬, 18.4 / 18.6 | 동일 |

probe가 V4에 op를 절대 안 끈다. V4에 pre 노드 입력이 같은 층에 산다. V4.1에 앞층 lag mix라서 스케줄러가 다른 카드에 노드를 둔다. 고침이 브랜치 PR([vcruz305#2](https://github.com/vcruz305/llama.cpp/pull/2))에 남고 ggml-org에 가는 것 없다. 코드 읽기 "일반이다"가 가설이었고 측정이 닫았다.

같은 창 unsloth V4 DSpark draft(BF16)가 브랜치 빌드 포트·plain master에 돌았다. flavor V4, 양쪽 draft 94 / accept 63, 20.3–20.6 상대 20.7–21.1 tok/s, draft 없이 어느 쪽도 18.0–18.6. 포트가 V4 경로에 손대지 않는다. PR이 이제 "untested" 대신 그렇게 말한다. 버그 주장 안 하는 관찰 하나. 양쪽 빌드 탐욕 텍스트가 draft 없이 텍스트와 20번째 토큰쯤부터 갈린다. draft 든 답이 반복 문장에 퇴화한다. exact 검증기가 탐욕 출력을 바꾸면 안 된다. IQ1_S 타깃이 near-tie에 가까우면 배치 verify가 뒤집을 수 있다. 더 안 쫓았다.

### ik 간격 결정 실험, 실행

[소스 리딩](../docs/v41-serving.md)이 실험 하나에 끝났다. draft 없는 ik, CUDA 그래프 기본 상대 `GGML_CUDA_DISABLE_GRAPHS=1`. 첫 6프롬프트 스물 중, arm당 패스 둘, arm당 로드 하나, 프로덕션 서버 정지. 두 arm이 양쪽 패스 로드-로드 밴드 안이다(2패스 중앙 18.9·18.7). CUDA 그래프 래치가 레버로 닫혔다. 중요한 결과가 다른 것이다. 1패스가 어제 14.13을 프롬프트별 재현한다. 같은 6프롬프트 2패스가 **18.9 tok/s**다. 35% 높다. 위 표 14.1이 그래서 첫 패스 숫자다. mainline 17.7도 비교 행 첫 패스다. 둘 다 첫 패스라 라벨 든다. docs 파일에 이제 있다. ms-층 산수가 그 위에 지어져서 struck이다. 다음 창이 ik쪽 요청당 major 페이지 폴트를 세고 같은 6층 분할 mainline 2패스를 더한다. 로그에 없다.

fault 수 창이 다음 돌았다(05:42–06:01, 같은 6프롬프트, 양쪽 엔진, `/proc` 요청당 major fault). warm 상대 warm 같은 6층 분할 ik 디코드 **18.8**·mainline **19.8**이다. 5% 간격이지 이 기록 쫓던 20%가 아니다. 20%가 양쪽 첫 패스 숫자다. 첫 패스가 mmap 가중치·engram 행 페이지 폴트다. ik가 토큰당 major fault 41–62개에 28%를 잃는다. mainline이 첫 프롬프트 뒤 13–21에 6%를 잃는다. 맞는 차이가 mainline이 86d01ece1에 얻은 engram 행 prefetch, ik에 없는 것이다. 이식이 ik 다음 변경이다. fault 수가 gate다. 상세·프롬프트별 행이 [docs 파일](../docs/v41-serving.md)에 있다.

ik prefetch가 23줄에 이식됐다(포크 커밋 57735010). 같은 창 06:05 재실행했다. 첫 패스 **18.4 tok/s** 상대 전 13.6이다. fault 토큰당 41–62 상대 1–11이다. 2패스 19.0. 이 기록 하루 쓴 20% 간격이 ik compute 스레드 fault인 engram 행이었고, cold·warm 닫혔다. ik·mainline이 이 배치 draft 없이 밴드 안이다.

### 프리필, 1창(06:40–06:50)

서빙 구성 — 카드 expert 8층, `-ub 512`, `--lazy-mode auto`, draft 없음 — 이 4823토큰 코드 프롬프트를 **cold 43.6 tok/s**(110초, 로드 뒤 첫 요청, IO 압력 1.3)·**warm 58.3 tok/s**(83초, 2패스, IO 0.00)에 프리필한다. 양쪽 카드 프리필 중 PCIe gen 4 ×16이었다. 링크가 한계가 아니다. 서빙 스크립트 머리가 이른 빌드 적은 expert층 `-ub 512` 214 tok/s를 인용한다. 이 구성 서술 안 한다. 큰 마이크로배치 셋이 이 배치 로드 안 됐다. expert 든 24 GB 카드에 4.7 GB compute 버퍼 자리 없다. master 새 `--fit` 로직이 `-ngl` 99 고정에 못 낮춘다. 60 KB 소스 프롬프트가 16748토큰에 나왔다. 16384 컨텍스트 넘는다. 숫자 못 냈다. 2창이 프롬프트 ~11k 토큰에 고정한다. `-ub 512` `--no-op-offload`를 더한다(CUDA 백엔드가 32행 이상 배치 CPU 상주 expert 가중치를 장치에 복사한다. 58 tok/s가 512토큰 마이크로배치당 PCIe 259 GB expert 스트리밍 예측 대개라서, 그 플래그가 프리필 PCIe-bound 판정 실험이다). 6층 배치 `-ub 2048`·`4096`을 돈다.

### 프리필, 2창(07:08–07:41)

같은 상자, 프로덕션 서버 정지, 포트 8099, `--lazy-mode auto`, draft 없음, 4823·11186토큰 소스 코드 프롬프트, 각 2패스, 모든 warm 행 IO 압력 0.00–0.05. "8층"이 서빙 배치다. "6층"이 6·7층 expert CPU 복귀다.

| arm | 4.8k cold | 4.8k warm | 11k cold | 11k warm |
|---|---|---|---|---|
| `-ub 512`, 8층(서빙) | 42.8 | 59.5 | 56.4 | 60.2 |
| `-ub 512`, 8층, `--no-op-offload` | 64.2 | 69.7 | 67.8 | 68.6 |
| `-ub 2048`, 6층 | 72.9 | **127.8** | 충돌 | — |
| `-ub 2048`, 6층, `--no-op-offload` | 65.5 | 71.3 | 충돌 | — |
| `-ub 4096`, 6층 | 로드 불가. 24 GB 카드 18.4 GB compute 버퍼 | | | |

읽기 넷. 호스트 op offload 끄면 프리필이 CPU expert 계산이다. 마이크로배치 무관 69–71 tok/s에 앉는다 — CPU 경로 상한이 여기 약 70이다. offload 켜면 CUDA 백엔드가 CPU 상주 expert 가중치를 카드에 마이크로배치마다 복사한다. `-ub 512`에 CPU보다 느리고(70 상대 60), `-ub 2048`에 2배 빠르다(128. 서버 자체 진행 줄이 2048토큰 스텝 149–154 tok/s에 읽힌다. 충돌 전). PCIe 가설이 절반 맞다. offload가 복사 분할하는 전송-bound 경로다. 마이크로배치 커야 복사를 분할한다. 서빙 `-ub 512`가 그 선 틀린 쪽이다. 셋째, 충돌. `-ub 2048` arm 둘 11k 프롬프트 37%에 죽었다. 24 GB 카드 `ggml_cuda_pool_vmm::alloc` 밑 `ggml_cuda_mul_mat_cublas` `CUDA error: out of memory`다 — 프롬프트 처리 중 컨텍스트 따라 자라는 cuBLAS 풀인데 로드 reserve가 안 덮었다. robustness 결함이다(요청 중 메모리 부족이 에러지 중단이어야 한다). 브랜치 저자 후보다. 넷째, 프롬프트 캐시. 11k 프롬프트 한 번 처리 뒤 같은 프롬프트 요청이 516토큰을 재고, 260토큰 붙인 요청이 775를 잰다. 접두사 자라는 코딩 클라이언트가 cold 185초 상대 턴당 8–15초를 낸다. 서빙 프로파일 오늘이 코딩에 쓸모 있는 숫자다. 큰 마이크로배치 여부와 무관하다.

코딩 프로파일이 그래서 필요하다. 24 GB 카드 compute 버퍼·16k 컨텍스트 cuBLAS 풀 빈 VRAM 든 `-ub 2048`이다. 6층 분할 expert 적다는 뜻이다 — 다음 창이 그 배치다. 그 위 `-ub 4096`이 맞으면. WKS-12에 filed.
