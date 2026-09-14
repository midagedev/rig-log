# Dossier: follow-up turns on V4.1 re-prefill 2 600 tokens — a port that forgot one special case

Status 2026-09-15: root cause found and fixed in the V4.1 runtime fork with a
one-line change, measured (turns 2–5: 2 600 → 560 tokens, 21 → 8.8 s, answers
byte-identical); mainline is **not** affected (measured). What goes out is a
patch to the fork branch (`vcruz305/llama.cpp`, `runtime/deepseek41`), not a
mainline issue. With the fix the trace reads `checking checkpoint with [11939, 11939] against
11944` and the n−4 checkpoint is restored on every turn, as on mainline.

## Symptom

A chat over a long document on DeepSeek-V4.1-Flash: turn 1 prefills the
12k-token document, turns 2–5 each add about 550 tokens (the previous answer
plus a 2 500-character passage). With `cache_prompt` on, every follow-up turn
re-prefilled about 2 600 tokens and waited 21 s before the first token.

| build | model | turns 2–5 prompt_n | turns 2–5 TTFT | answers |
|---|---|---|---|---|
| fork, as merged | V4.1-Flash | 2 606 / 2 587 / 2 618 / 2 579 | 20.6 / 21.1 / 21.3 / 21.1 s | reference |
| fork + server-guard patch (first attempt) | V4.1-Flash | 558 / 539 / 570 / 531 | 8.6 / 8.6 / 8.6 / 8.1 s | 5/5 identical |
| fork + `llama_model_n_swa` one-liner (the fix) | V4.1-Flash | 562 / 543 / 574 / 535 | 8.9 / 8.8 / 8.8 / 8.2 s | 5/5 identical |
| mainline master 41abbfd | V4-Flash-0731 | 862 / 843 / 874 / 835 | 5.4 / 5.4 / 5.5 / 5.4 s | reference |
| mainline master + PR #25592 cherry-picked | V4-Flash-0731 | 862 / 843 / 874 / 835 | 5.4 / 5.3 / 5.4 / 5.4 s | 5/5 identical to master |

All on the quiet workstation, 2026-09-15 00:06–00:31, one arm at a time,
each binary built from source immediately before it ran. Fork arms:
V4.1-Flash Q3_K_M (attention Q8_0, bf16 token embedding), `-c 262144 -ub
2048 -ctk q8_0 -ctv q8_0`, four expert layers on the 48 GB card, DSpark draft
n_max 3. Mainline arms: V4-Flash-0731 UD-Q4_K_XL, `-c 32768 -ub 1024`, seven
plus four expert layers on the two cards, no draft, `-ctxcp 32`. Same
document, same five turns (`ckpt-window3.sh`, `ckpt-master.sh`,
`ckpt-window4.sh`).

## Mechanism

The server keeps context checkpoints and, on a follow-up turn, picks the
newest one that is "far enough" behind the resume point:

```cpp
// tools/server/server-context.cpp (master 41abbfd, lines 3297 and 3361)
const auto pos_min_thold = std::max(0, pos_next - n_swa - (has_new_tokens ? 0 : 1));
...
return cur.pos_min < pos_min_thold || cur.pos_min == 0;
```

The `n_swa` margin is right for a sliding-window cache. The DeepSeek V4
memory (`llama_kv_cache_dsv4`) has a 128-token raw window but cannot roll
back inside it, so it reports `seq_pos_min == seq_pos_max` and its
checkpoints are exact states, not windows. Mainline knows this and hides the
window from the server:

```cpp
// src/llama-model.cpp (master 41abbfd, line 2834)
int32_t llama_model_n_swa(const llama_model * model) {
    // dsv4 kv-cache has SWA but it cannot be used as a rollback because of
    // other compression ratios, so we return 0 here
    if (model->arch == LLM_ARCH_DEEPSEEK4) {
        return 0;
    }
    return model->hparams.n_swa;
}
```

The V4.1 port added `LLM_ARCH_DEEPSEEK41` and extended every other
`DEEPSEEK4` special case (graph selection, KV cache construction, the
`is_dsv4` flags in `llama-arch.cpp`, `llama-context.cpp`) — but not this
one. So on V4.1 the server computes its threshold with `n_swa = 128` and
rejects exactly the checkpoint it placed four tokens before the end of the
prompt. The trace from the fork's baseline arm (`-lv 5`, turn 2):

```
checking checkpoint with [11939, 11939] against 11816   ← n-4 checkpoint, rejected: 11939 ≥ 11944 − 128
checking checkpoint with [9895, 9895] against 11816     ← previous user-message checkpoint, accepted
restored context checkpoint (pos_min = 9895, pos_max = 9895, n_tokens = 9896, n_past = 9896)
```

and from mainline with V4-Flash, where the threshold carries no margin:

```
checking checkpoint with [11939, 11939] against 11943   ← accepted
restored context checkpoint (pos_min = 11939, pos_max = 11939, n_tokens = 11940, n_past = 11940)
```

The 862-token `prompt_n` on mainline is the ~550 new tokens plus the four
re-decoded tokens plus the template; 2 606 on the fork is that plus the
2 048 tokens back to the previous checkpoint.

## The fix

```cpp
if (model->arch == LLM_ARCH_DEEPSEEK4 || model->arch == LLM_ARCH_DEEPSEEK41) {
    return 0;
}
```

Fork commit 38f6868e9 (author midagedev) on the local merge branch. It also
reverts the earlier server-side guard patch (ce636d0a5), which fixed the
symptom by teaching the checkpoint search about exact-position checkpoints
— correct in effect, and the same idea as the exact-state branch of
mainline PR #25592, but the wrong layer for this defect: the model already
has a way to say "no usable window", and the port simply did not use it.

## Where it goes

- **To the fork**: a one-line PR against `vcruz305/llama.cpp` branch
  `runtime/deepseek41` (the branch under mainline draft PR #28696, which
  carries only the converter). Small, single-purpose, with the before/after
  table above. The user decides whether and when to open it.
- **Not to mainline**: master behaves correctly for the dsv4 memory it
  ships (V4-Flash). PR #25592 is a different, more general treatment; the
  mainline run above confirms it changes nothing for V4-Flash (identical
  restores and answers), which is a small data point for that PR's "no
  regression" column, not a reason to comment.
- The search record: `gh issue/pr list -R ggml-org/llama.cpp` for
  "checkpoint restore re-prefill dsv4", "checkpoint pos_min", "context
  checkpoint cache_prompt reprocess DeepSeek" (2026-09-15) → #25452 (SWA
  slot exhaustion), #25567 (append-only reuse, fixed), #25592, #24035,
  #21695. None is this.

## What this cost and what it teaches

Two windows were spent on the wrong layer before the right one: the first
A/B was void (both arms loaded the same shared library), the second proved
the server-guard patch worked, and only building mainline to reproduce
showed that mainline did not need it. The rule that a code-reading
diagnosis is a hypothesis until measured on the target held again: the
"mainline has the same code" claim was true of `server-context.cpp` and
false of the program. The general lesson for porting: when a new
architecture is added next to an existing one, `grep` the old arch's enum
across `src/` and account for every hit — here five of six were extended
and the sixth was the bug.

## Separate item: `-ub 4096` aborts instead of failing — fork-specific, closed

On the 256k coding profile of the V4.1 fork, `-ub 4096` ended prefill with
`CUDA error: out of memory` in `ggml_cuda_pool_vmm::alloc` called from
`ggml_cuda_mul_mat_cublas`, i.e. a run-time pool allocation that aborts the
process (WKS-12 window 3, both cards, different sizes). Mainline measured
2026-09-15 with V4-Flash-0731 UD-Q4_K_XL at `-ub 4096`, filling the cards
step by step (`ub4096-master.sh`): 7 and 9 on-card expert layers prefill
11 929 tokens at 435 and 457 tok/s with no abort; 10 layers fail at load
with a clean `cudaMalloc failed: out of memory`. Not reproducible on
mainline with the model it ships.

The reason is in the dispatch: on Ampere every quantized type MMQ supports
goes to MMQ (`ggml_cuda_should_use_mmq` returns true once
`turing_mma_available`), and the cuBLAS path — the one that converts the
whole `src0` to f16 in the pool (`src0_alloc.alloc(ggml_nelements(src0))`)
— is taken only for f32/f16/bf16 weights. The V4.1 serving file carries a
bf16 token embedding and f32 hyper-connection matrices that V4-Flash does
not, so the transient exists only there. The class itself is known
upstream: #28338 (open, 2026-09-03, top_k scratch; maintainer: reduce and
pre-allocate pool temporaries rather than make OOM recoverable) and #28889
(merged 2026-09-14, bounds the top_k scratch for V4 prefill). Nothing to
report from here; if the fork's f32 matmul at large ubatch is ever worth
bounding, that is a fork item.
