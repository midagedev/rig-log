# "master"라고 이름 붙은 트리가 ik였다 — 본가는 넓히지 않는다

*2026-09-21 밤.* 낮에 확정한 결함 — ik가 그래프마다 워밍업 여부를 통계 카운터로 **추론**하고, 그렇게 추론된 그래프가 전문가를 전부 돌려 답을 바꾼다 — 은 제출 앞에서 한 가지에 막혀 있었다. 본가(`ggml-org/llama.cpp`)도 같은가. 소스는 본가가 호출자가 세우는 명시 플래그를 쓴다고 읽히는데, `llama-eval-callback`으로 본 관측은 양쪽이 같아 보였다. 코드 리딩과 관측이 어긋나면 제출하지 않는다는 것이 이 리포의 파이프라인 ②다.

## 관측이 틀렸다

`llama-eval-callback`을 낸 트리는 `/root/ik-prefill-probe/master`였다. 그 `.git/config`의 origin은 `https://github.com/ikawrakow/ik_llama.cpp`다. 디렉터리 이름만 "master"였고, 본가 빌드에는 그 바이너리가 아예 없다. **ik를 ik에 대고 "양쪽이 같다"고 읽고 있었다.** 이름이 라운드 하나를 먹었다.

## 본가는 넓히지 않는다

ik 쪽 재현자를 본가 API로 이식해(`tools/upstream/warmup-width/`) `930e2fa5`에서 돌렸다. 토크나이저가 없고 토큰 id를 TSV에서 읽으므로 두 엔진이 같은 id를 본다. CPU, `-ngl 0 -c 512 -t 8`, DeepSeek-V2-Lite-Chat Q3_K_M(전문가 64, top-6).

| 팔 | ik `c10fbbcc` | 본가 `930e2fa5` |
|---|---|---|
| `warm0_baseline` | 1191, 0 | 245, 0 |
| `warm1_nosync` | 1191, 0 | 245, 0 |
| **`warm1_sync`** | **245, 3.65142** | 245, **0** |
| `warm1_sync_reset` | 1191, 0 | 245, 0 |

각 칸은 argmax와 자기 L0 대비 `max_abs_diff`다. ik에서 답을 뒤집는 `llama_synchronize` 한 줄이 본가에서는 아무것도 하지 않는다.

**널 결과는 양성 대조가 있어야 값을 한다.** 다섯 팔이 전부 0인 것은 "본가가 안 넓힌다"와 "이 도구가 넓힘을 못 본다"를 구분하지 못한다. 그래서 eval 콜백으로 `ffn_moe_topk`의 `ne[0]`을 그래프마다 찍었다 — 그래프가 지어진 시점의 `n_expert_used` 그 자체다. 기본값은 일곱 그래프 모두 **6**이고, `llama_set_warmup(ctx, true)`를 부르면 같은 자리가 모두 **64**가 된다. 도구는 넓힘을 본다. 본가가 안 할 뿐이다.

그리고 플래그를 세워 64로 지어도 **로짓은 그대로다**(245 @ 29.001263, 차이 0). 본가는 합산을 층별 `hparams.n_expert_used(il)` 뷰로 묶어서(`src/llama-graph.cpp:2331`) 넓어진 멤버를 더하지 않는다 — PR [#14753](https://github.com/ggml-org/llama.cpp/pull/14753)이 그 일을 했다. ik의 `src/llama-build-context.cpp:1708`은 넓어진 쪽을 더한다. 본가는 이 결정을 두 번 했다: 2025-07에 워밍업 그래프의 크기를 묶었고, 2026-06에 [#24009](https://github.com/ggml-org/llama.cpp/pull/24009)로 플래그 자체를 deprecated로 표시했다. ik는 셋 중 첫 PR([#11571](https://github.com/ggml-org/llama.cpp/pull/11571), 넓히기를 도입한 것)만 들고 있고, 명시 플래그를 카운터 추론으로 바꿔 놓았다.

## 출하 바이너리에서 보인다

도구 없이도 보인다. ik의 `llama-cli`, `--temp 0`, 같은 프롬프트, 문서화된 플래그 하나 차이:

```
llama-cli … --temp 0 -n 4 -p "Machine learning models are trained on"
  → Machine learning models are trained on a variety of data
llama-cli … --temp 0 -n 4 -p "…" -ub 1 -b 1
  → Machine learning models are trained on data and they make
llama-cli … -ub 1 -b 1 --no-warmup
  → Machine learning models are trained on data and they make        (그대로)
```

GGUF가 말하는 `n_expert_used`는 6이니 아래 둘이 틀린 답이다. `--no-warmup`은 구제가 아니다 — 워밍업 블록이 안 돌면 카운터를 올릴 것이 아무것도 없어서 술어가 계속 참이다.

서버는 걸리지 않는데, 설계가 아니라 **우연**이다. `cparams.n_batch`가 `GGML_KQ_MASK_PAD`보다 작으면 컨텍스트가 16으로 올려 버리고(`src/llama.cpp:8954`), 서버는 그 올려진 값으로 프롬프트를 쪼개 일곱 토큰을 한 번에 낸다. `llama-cli`는 요청한 값으로 쪼갠다. 술어는 서버를 지키려고 만들어진 것이 아니므로, 단일 토큰 배치를 내는 다음 호출자는 다시 걸린다.

## 정직하게 적어 둘 것

모델 하나(softmax 게이팅, 가중치 재정규화 없음), CPU만, 성능 주장 없음. 본가의 출하 바이너리 대조는 같은 모양이 아니다 — 본가는 이 HEAD에서 `-b 1`에 `GGML_ASSERT`로 죽어서(`llama-cli`는 `n_tokens_all <= cparams.n_batch`, 서버는 `n_outputs_max <= cparams.n_outputs_max`) 같은 명령을 못 돌린다. 그것대로 별도 후보다. 엔진을 고친 빌드로 재보지는 않았다 — 술어의 두 접속사 모두 라이브러리 밖에서 뒤집을 수 있어서 팔들이 그 자리를 대신한다.

서류는 썼고 아직 아무 데도 내지 않았다.
