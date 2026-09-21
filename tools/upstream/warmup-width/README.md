# warmup-width — mainline llama.cpp가 MoE 첫 그래프를 넓히는가

ik_llama.cpp는 그래프마다 워밍업 여부를 **추론**한다. `src/llama-build-context.cpp:2742`
(upstream main `9cba2e38`)의
`is_warming_up = lctx.n_eval == 0 && batch.n_tokens == 1 && batch.token[0] == BOS`가 참이면
`:58`이 `n_expert_used` 대신 전문가를 전부 쓰고 `:1708`의 합산이 그 넓어진 수를 더한다.
`n_eval`은 통계 카운터다 — `llama_synchronize` 안에서만 오르고(`src/llama.cpp:12515`)
`llama_reset_timings`가 0으로 되돌린다(`:13792`). 그래서 답이 바뀐다.

같은 결함이 mainline(`ggml-org/llama.cpp`)에도 있는지가 업스트림 제출을 막고 있었다.
소스는 mainline이 호출자가 세우는 명시 플래그(`cparams.warmup`)를 쓴다고 읽히는데,
`llama-eval-callback` 관측이 양쪽 같아 보였기 때문이다. 이 디렉터리가 그 실행이다.

`probe_mainline.cpp`는 bloomery `tools/ref/kvclear_probe.cpp`(ik 쪽 재현자)를 mainline API로
옮긴 것이다. 토크나이저가 없고 토큰 id를 TSV에서 읽으므로 두 엔진이 같은 id를 본다.
디스크에 아무것도 쓰지 않는다. 엔진 트리는 읽기만 한다 — mainline이 `BUILD_SHARED_LIBS=ON`
빌드라 `g++` 한 번이면 되고 엔진을 다시 짓지 않는다.

## 재는 것

- **기제 5팔** — ik의 술어에서 접속사를 하나씩 뒤집는다(`warm0_baseline`, `warm1_nosync`,
  `warm1_sync`, `warm1_sync_reset`, `prefix2_batch`). ik에서는 `warm1_sync` 하나가
  `llama_synchronize` 한 줄 차이로 답을 뒤집는다.
- **양성 대조** — `warm_explicit`이 `llama_set_warmup(ctx, true)`를 부른다. 다섯 팔이 전부
  0을 내는 것은 "mainline이 안 넓힌다"와 "이 도구가 넓힘을 못 본다"를 구분하지 못하므로,
  넓힘을 실제로 일으킬 수 있는 팔이 하나 필요하다.
- **`--width`** — eval 콜백으로 그래프마다 `ffn_moe_topk`의 `ne[0]`을 찍는다. 그래프가
  지어진 시점의 `n_expert_used` 그 자체라, 로짓에서 추론하지 않고 폭을 직접 읽는다.
  (콜백은 스케줄러를 노드 단위로 돌게 만들어 값을 흔들 수 있다. 모양은 그래프 빌드 시점에
  정해지므로 이 모드는 모양만 보고한다.)

## 실행

```bash
LC=/path/to/llama.cpp WWIDTH_OUT=/path/to/bin ./build-mainline.sh

CUDA_VISIBLE_DEVICES="" $WWIDTH_OUT/probe_mainline \
  -m DeepSeek-V2-Lite-Chat.Q3_K_M.gguf --prompts prompts.tsv --seq 24 --prior 5 \
  -ngl 0 -c 512 -t 8                      # 차등 팔 + 기제 팔
CUDA_VISIBLE_DEVICES="" $WWIDTH_OUT/probe_mainline ... --width          # 폭, 플래그 끔
CUDA_VISIBLE_DEVICES="" $WWIDTH_OUT/probe_mainline ... --width-warmup   # 폭, 플래그 켬
```

`--prompts`는 `id<TAB>텍스트<TAB>쉼표로 이은 토큰 id` 형식의 TSV를 받는다.

## 2026-09-21 이 기계에서 나온 답

mainline `930e2fa5`, DeepSeek-V2-Lite-Chat Q3_K_M(`n_expert` 64, `n_expert_used` 6), CPU.
**mainline은 넓히지 않는다.** 다섯 팔 전부 `max_abs_diff` 0이고, `--width`가 그래프 일곱 개
모두 6을 찍는다. `llama_set_warmup(ctx, true)`를 부르면 같은 자리가 64로 바뀌므로 도구가
눈먼 것이 아니다 — 그런데 로짓은 그래도 같다. mainline은 `src/llama-graph.cpp:2331`에서
합산을 층별 `hparams.n_expert_used(il)`로 묶기 때문이다(PR #14753). ik의 `:1708`은 넓어진
쪽을 더한다.

같은 조건 ik(`c10fbbcc`)에서는 `warm1_sync` 한 팔이 argmax를 1191 → 245로, 로짓을
3.65142만큼 옮긴다. 업스트림 서류 초안은 세션 스크래치의 `wwidth-dossier.md`, 기록은
[`docs/upstream-contributions.md`](../../../docs/upstream-contributions.md)다.
