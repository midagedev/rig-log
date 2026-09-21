# NOT FILED — draft issue body for ikawrakow/ik_llama.cpp

Nothing here has been posted. The long internal record, including the arms that were tried
and the mainline comparison in full, is [`DOSSIER.md`](DOSSIER.md).

---

**Title:** `MoE graphs are silently widened to all experts when n_eval happens to be 0, changing the output`

## What happens

On a MoE model whose GGUF says 6 of 64 experts are used per token, a sequence can be computed
with all 64, and it answers differently. Same binary, same model, same prompt, greedy, one
documented flag apart:

```bash
llama-cli -m DeepSeek-V2-Lite-Chat.Q3_K_M.gguf -ngl 0 -t 8 -c 512 --temp 0 -n 4 \
          -p "Machine learning models are trained on"
#  -> Machine learning models are trained on a variety of data

llama-cli … -p "Machine learning models are trained on" -ub 1 -b 1
#  -> Machine learning models are trained on data and they make

llama-cli … -ub 1 -b 1 --no-warmup
#  -> Machine learning models are trained on data and they make        (unchanged)
```

The GGUF asks for 6 experts, so the second answer is the wrong one.

## Why

The graph builder infers, per graph, whether it is building a warmup graph, and a warmup graph
runs every expert (line numbers at `9cba2e38`):

```c
// src/llama-build-context.cpp:2742
bool is_warming_up = lctx.n_eval == 0 && (batch.n_tokens == 1 && (batch.token[0] == ((bos != -1) ? bos : eos)));

// src/llama-build-context.cpp:58
n_expert_used    (warmup ? hparams.n_expert : hparams.n_expert_used),

// src/llama-build-context.cpp:1708  — the widened member is what MoE aggregation sums
result = ggml_multi_add(ctx, ggml_view_2d(ctx, experts, n_embd, n_tokens, experts->nb[2], 0), n_expert_used);
```

`n_eval` is a statistics counter. It has exactly two writers: `llama_synchronize` raises it on
the single-token branch (`src/llama.cpp:12515`), and `llama_reset_timings` sets it to 0
(`:13792`). So a caller that pushes a whole prompt and reads logits once never raises it —
`n_queued_tokens > 1` takes the other branch — and every sequence's first graph is widened.

`common`'s own warmup block then re-arms the predicate (`common/common.cpp:4174-4179`):

```c
if (llama_model_has_decoder(model)) {
    llama_decode(lctx, llama_batch_get_one(tmp.data(), std::min(tmp.size(), (size_t) params.n_batch), 0, 0));
}
llama_kv_cache_clear(lctx);
llama_synchronize(lctx);        // n_queued_tokens == 1  ->  n_eval = 1
llama_reset_timings(lctx);      // n_eval = 0            <- predicate true again
```

`tmp` holds exactly one token — BOS, or EOS if the model has none (`:4154-4164`) — so that
decode is deliberately a warmup graph, matching the predicate's third conjunct. That is
the intent. The third line is the problem: after it, the next real sequence is built as a
warmup graph too. With `--no-warmup` the block never runs, so nothing ever raises the counter
and the predicate is true from the start. Both paths leave a normal caller widened.

`is_warming_up` arrived in `a2676d59`, "Load all MoE experts during warmup and make warmup 1
token" (#198, 2025-02-10).

## Measured

DeepSeek-V2-Lite-Chat Q3_K_M (`n_expert` 64, `n_expert_used` 6, softmax gating, no weight
renorm), CPU, `-ngl 0 -c 512 -t 8`, prompt fed one token per `llama_decode` by a probe that
reads token ids from a TSV so no tokenizer has to agree. `max_abs_diff` is over the whole
102400-wide logit vector against the baseline. Build `c10fbbcc`; the three sites above are
identical at `9cba2e38`.

| arm | argmax | max_abs_diff |
|---|---|---|
| `warm0_baseline` — nothing | 1191 | 0 |
| `warm1_nosync` — one lone BOS decode, no synchronize | 1191 | 0 |
| **`warm1_sync`** — the same decode **plus one `llama_synchronize`** | **245** | **3.65142** |
| `warm1_sync_reset` — …then `llama_reset_timings` | 1191 | 0 |

`warm1_sync` and `warm1_nosync` differ by one function call, with tokens, positions, prefill
mode and cache state held fixed.

This is not batch-size numeric noise. A virgin context fed the whole prompt in one batch
prints the same top-5 logits as `warm1_sync` to every digit (`29.244007, 29.093025, 28.636026,
28.315937, 27.828226`): batch prefill and honest step prefill agree, and the widened step
prefill is the outlier. Hashing the two graphs node by node, nodes 0–60 are bit-identical and
the first difference is layer 1's `ffn_moe_topk`, `64,1` in one arm and `6,1` in the other.

Graph reuse amplifies it but is not the cause: `can_reuse_graph` (`src/llama.cpp:663`) compares
`all_seq_id`, `head`, `n_kv`, `n_outputs`, `n_tokens` and the MTP fields, not expert width, so
one widened BOS graph is reused for the rest of a step prefill. With `-no-gr` the divergence
falls from 3.65142 to 1.1147 and the honest value is bit-identical either way.

## Mainline is not affected

The same probe ported to `ggml-org/llama.cpp` API and run at `930e2fa5` returns `max_abs_diff`
0 on every arm, and an eval callback reading `ffn_moe_topk`'s `ne[0]` per graph reports width 6
on all seven graphs. Calling `llama_set_warmup(ctx, true)` moves that readout to 64, so the
probe is not blind to widening — mainline simply does not infer it. Mainline's equivalent
expression (`src/llama-graph.cpp:1472`) reads `cparams.warmup`, a caller-set flag that nothing
in `common/`, `tools/` or `examples/` sets; `grep -rn is_warming_up src/` there is empty. Even
with the flag set the logits do not move, because the aggregation sums per-layer
`hparams.n_expert_used(il)` views (`src/llama-graph.cpp:2331`, #14753).

## Who is exposed

Any caller that submits single-token batches: `llama-cli -b 1`, token-at-a-time reference
harnesses (which is how this was found), and any program that steps a prompt one
`llama_decode` at a time for per-position logits.

`llama-server` is not exposed, by accident rather than design: `src/llama.cpp:8954` raises
`cparams.n_batch` to `GGML_KQ_MASK_PAD` (16) when it is smaller, the server chunks by
`llama_n_batch(ctx)` (`examples/server/server-context.cpp:425, 2140`) and so submits the whole
prompt in one decode, while `llama-cli` chunks by the requested `params.n_batch`
(`examples/main/main.cpp:842-845`). Three identical requests to a server at `-ub 1 -b 1` all
gave the honest answer.

## Two possible shapes

1. Drop the `llama_reset_timings(lctx)` in `common`'s warmup block. Fixes the default path
   only; `--no-warmup` stays broken and graph shape still depends on a statistics counter.
2. Give the context an explicit caller-set `warmup` flag and have the warmup block set and
   clear it, so `llm_build_context` never reads `n_eval`. This is upstream's shape
   (`llama_set_warmup`, deprecated there in #24009). Pairing `can_reuse_graph` with expert
   width, or bounding the aggregation as #14753 did, would close the reuse half.

No patch has been applied to any tree and none is proposed here as a diff.

## Not tested

One model, CPU only, no timing claims. I did not build a patched ik and measure the fix — both
conjuncts of the predicate are flippable from outside the library, which is what the arms do. I
did not test whether some other server configuration can reach a single-token batch.

The probe was written and this text drafted with AI assistance; every number above was re-run
by hand on the machine named, and every line citation was checked in the `9cba2e38` and
`930e2fa5` checkouts.
