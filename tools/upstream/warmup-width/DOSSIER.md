# Dossier — NOT FILED. Draft issue body for ikawrakow/ik_llama.cpp.

Nothing in this file has been posted anywhere. It is written as the issue body would read,
for the lead to review and, with the user's approval, submit.

Target: **ik_llama.cpp**, not mainline. The blocking comparison is now measured (§5) and it
clears the tree of it.

---

## Title

`MoE graphs are silently widened to all experts when a timing counter happens to be zero (n_eval), changing the model's output`

## Symptom, in user terms

On a MoE model whose GGUF says six of sixty-four experts are used per token, the first
sequence a process evaluates can be computed with **all sixty-four** experts, and the answer
it produces is a different token from the one the same prompt gets a moment later. Which of
the two answers you get depends on whether `llama_context::n_eval` — a *statistics* counter,
the one whose only other job is printing `n_eval` in the timing summary — happens to be zero
when the graph is built.

Measured on DeepSeek-V2-Lite-Chat Q3_K_M (`n_expert = 64`, `n_expert_used = 6`,
`expert_gating_func = softmax`, `expert_weights_norm = 0`), CPU, prompt
`"Machine learning models are trained on"` fed one token per `llama_decode`:

* the widened graph answers `" data"` (token 1191) at logit 30.291042
* the honest six-expert graph answers `" a"` (token 245) at logit 29.244007
* the whole 102400-wide logit vector moves by up to **3.65142**

The GGUF asks for six experts, so the widened answer is the wrong one, and it is the one a
program gets by default in the shape below.

This is reachable from a shipped binary with no special tooling:

```bash
llama-cli -m DeepSeek-V2-Lite-Chat.Q3_K_M.gguf -ngl 0 -t 8 -c 512 --temp 0 -n 4 \
          -p "Machine learning models are trained on"
#   -> Machine learning models are trained on a variety of data

llama-cli -m DeepSeek-V2-Lite-Chat.Q3_K_M.gguf -ngl 0 -t 8 -c 512 --temp 0 -n 4 \
          -p "Machine learning models are trained on" -ub 1 -b 1
#   -> Machine learning models are trained on data and they make

llama-cli ... -ub 1 -b 1 --no-warmup
#   -> Machine learning models are trained on data and they make        (unchanged)
```

Both runs are greedy, same binary, same model, same prompt. `--no-warmup` does not help; §4
says why.

## Mechanism

Line numbers are at **`9cba2e38`** (`ikawrakow/ik_llama.cpp`, main, 2026-09-20), verified in
that checkout.

The graph builder infers a warmup graph, per graph, from the batch and a counter:

```c
// src/llama-build-context.cpp:2742
bool is_warming_up = lctx.n_eval == 0 && (batch.n_tokens == 1 && (batch.token[0] == ((bos != -1) ? bos : eos)));
struct llm_build_context llm(lctx, batch, cb, worst_case, is_warming_up, n_outputs);
```

and a warmup graph runs every expert:

```c
// src/llama-build-context.cpp:58
n_expert_used    (warmup ? hparams.n_expert : hparams.n_expert_used),
```

That member is what the MoE aggregation sums, so the widening is not just extra compute — it
changes the result:

```c
// src/llama-build-context.cpp:1708
result = ggml_multi_add(ctx, ggml_view_2d(ctx, experts, n_embd, n_tokens, experts->nb[2], 0), n_expert_used);
```

`n_eval` is a statistics counter. It is incremented in exactly one place, inside
`llama_synchronize`, and only on the single-token branch:

```c
// src/llama.cpp:12505
void llama_synchronize(struct llama_context * ctx) {
    ggml_backend_sched_synchronize(ctx->sched);
    // FIXME: if multiple single tokens are evaluated without a synchronization,
    // the stats will be added to the prompt evaluation stats
    ...
    if (ctx->n_queued_tokens == 1) {
        ctx->t_eval_us += ggml_time_us() - ctx->t_compute_start_us;
        ctx->n_eval++;                       // src/llama.cpp:12515
    } else if (ctx->n_queued_tokens > 1) {
```

and it is zeroed by the timing reset:

```c
// src/llama.cpp:13790
void llama_reset_timings(struct llama_context * ctx) {
    ctx->t_start_us  = ggml_time_us();
    ctx->t_eval_us   = ctx->n_eval   = 0;    // src/llama.cpp:13792
```

Two consequences follow, and both are visible in the measurements:

1. A program that pushes a whole prompt and reads logits once never raises the counter —
   `n_queued_tokens > 1` takes the other branch — so `n_eval` stays 0 for the life of the
   process and **every sequence's first graph is a warmup graph**.
2. `common`'s own warmup block raises the counter and then puts it straight back:

```c
// common/common.cpp:4174-4179
llama_decode(lctx, llama_batch_get_one(tmp.data(), std::min(tmp.size(), (size_t) params.n_batch), 0, 0));
llama_kv_cache_clear(lctx);
llama_synchronize(lctx);        // n_queued_tokens == 1  ->  n_eval = 1
llama_reset_timings(lctx);      // n_eval = 0            <- re-arms the predicate
```

`tmp` holds a single BOS (`common/common.cpp:4154-4163`), so that decode is itself a warmup
graph, which is the intent. The problem is the third line: after it, the first real sequence
is built as a warmup graph too. With `--no-warmup` the block never runs and nothing ever
raises the counter, so both paths leave a normal caller in the widened state.

## Who is exposed

Any caller that submits **single-token batches**, which is the shape `batch.n_tokens == 1`
requires. That is `llama-cli -b 1`, token-at-a-time reference harnesses (which is how this was
found), and any raw-API program that steps a prompt one `llama_decode` at a time — a normal
thing to do when you want per-position logits.

`llama-server` is **not** exposed, and the reason is worth stating because it is an accident
rather than a design: the context clamps a small batch upward —

```c
// src/llama.cpp:8954
if (cparams.n_batch < GGML_KQ_MASK_PAD) {
    LLAMA_LOG_WARN("%s: n_batch is less than GGML_KQ_MASK_PAD - increasing to %d\n", ...);
    cparams.n_batch = GGML_KQ_MASK_PAD;
}
```

so `-b 1` is realized as `n_batch = 16` (the server's own log prints
`n_batch is less than GGML_KQ_MASK_PAD - increasing to 16`). The server chunks the prompt by
`llama_n_batch(ctx)`, the clamped 16 (`examples/server/server-context.cpp:425, 2140`), and so
submits all seven tokens in one decode; `llama-cli` chunks by the *requested* `params.n_batch`
(`examples/main/main.cpp:842-845`) and so submits one. Measured: three identical requests to
one ik server at `-ub 1 -b 1` all answered `" a variety of data"`, the honest answer.

## Reproducer

`probe_mainline.cpp` (mainline half) and `kvclear_probe.cpp` (ik half, 389 lines, no
tokenizer, writes nothing). Each reads its prompt's token ids from a TSV so both engines see
identical ids, decodes the sequence in a context that has seen nothing else, and reports
`max |L1 − L0|` over the whole logit vector. The row used throughout is

```
24	Machine learning models are trained on	100000,27581,4526,4096,418,10986,331
```

— DeepSeek-V2-Lite's BOS followed by the six prompt tokens, so no tokenizer has to agree for
the numbers to be comparable. Five arms flip exactly one conjunct of the predicate above and
nothing else:

| arm | what it changes |
|---|---|
| `warm0_baseline` | nothing — this is L0 |
| `warm1_nosync` | one lone BOS decode, **no** synchronize (`n_eval` stays 0) |
| `warm1_sync` | the same decode **plus one `llama_synchronize`** (`n_eval` = 1) |
| `warm1_sync_reset` | …then `llama_reset_timings` (`n_eval` = 0 again) |
| `prefix2_batch` | `n_eval` still 0, but the first ubatch holds two tokens |

Build and run (the engine tree is only read; nothing in it is rebuilt):

```bash
g++ -std=c++17 -O2 -o kvclear_probe kvclear_probe.cpp \
  -I$IK/ggml/include -I$IK/include -I$IK/common -I$IK/src \
  -L$IK/build/common -L$IK/build/src -L$IK/build/ggml/src -lcommon -lllama -lggml \
  -Wl,-rpath,$IK/build/src -Wl,-rpath,$IK/build/ggml/src

CUDA_VISIBLE_DEVICES="" ./kvclear_probe -m DeepSeek-V2-Lite-Chat.Q3_K_M.gguf \
  --prompts prompts.tsv --seq 24 --prior 5 -ngl 0 -c 512 -t 8
```

## Measured

Both tables: same machine, same day (2026-09-21), same model file, same token ids, CPU only
(`CUDA_VISIBLE_DEVICES=""`, `-ngl 0 -c 512 -t 8`). Two consecutive runs byte-identical on
each side. `max_abs_diff` is against that engine's own L0.

**ik_llama.cpp** (build `c10fbbcc`; the predicate and the three source sites above are
identical at upstream main `9cba2e38`). L0 = **1191** @ 30.291042:

| arm | argmax | max_abs_diff | top-1 logit |
|---|---|---|---|
| `warm0_baseline` | 1191 | 0 | 30.291042 |
| `warm1_nosync` | 1191 | 0 | 30.291042 |
| **`warm1_sync`** | **245** | **3.65142** | 29.244007 |
| `warm1_sync_reset` | 1191 | 0 | 30.291042 |
| `prefix2_batch` | 245 | 3.65142 | 29.244007 |

`warm1_sync` and `warm1_nosync` differ by **one function call** — same tokens, same
positions, same prefill mode, same cache reset. Everything else about them is equal.

**ggml-org/llama.cpp** at `930e2fa5995789efbf249a8bf61325bb626e417b`, same probe ported to
its API. L0 = **245** @ 29.001263:

| arm | argmax | max_abs_diff |
|---|---|---|
| `warm0_baseline` | 245 | 0 |
| `warm1_nosync` | 245 | 0 |
| `warm1_sync` | 245 | **0** |
| `warm1_sync_reset` | 245 | 0 |
| `prefix2_batch` | 1191 | 0.806461 |
| `warm_explicit` — `llama_set_warmup(ctx, true)` | 245 | 0 |

Read honestly: mainline's `prefix2_batch` is **not** the same effect. Batch prefill and step
prefill differ numerically on mainline by about 0.8 here (the `fresh_batch` arm, a virgin
context fed the prompt as one batch, gives 0.856506 with argmax 245), and this prompt's top
two logits are only 0.25 apart, so an ordinary reduction-order difference can flip the
argmax. What separates the two causes is reading the width directly rather than inferring it
from logits.

**The width itself, on mainline**, via an eval callback that prints `ffn_moe_topk`'s `ne[0]`
per graph — the number is `n_expert_used` as the graph was built:

| configuration | layer-1 width, graphs 1..7 | argmax | top-1 |
|---|---|---|---|
| default | `6 6 6 6 6 6 6` | 245 | 29.001263 |
| `llama_set_warmup(ctx, true)` | `64 64 64 64 64 64 64` | 245 | 29.001263 |

So the probe demonstrably observes the widening on mainline — the flag moves it — and none of
the five arms moves it. That is the positive control the null result needs.

## Why mainline is not affected, in its own source

At `930e2fa5`:

* `src/llama-graph.cpp:1472` has the same widening expression, but it reads `cparams.warmup`,
  a caller-set flag — `false` at `src/llama-context.cpp:122`, changed only through
  `llama_context::set_warmup` (`:1207`) and `llama_set_warmup` (`:3847`).
* `grep -rn is_warming_up src/` over mainline is empty. Nothing is inferred from a counter.
* Nothing in `common/`, `tools/` or `examples/` calls `llama_set_warmup`, so `cparams.warmup`
  is false on every context these binaries build. `common/common.cpp:1511-1547` warms up with
  a `[bos, eos]` decode followed by `llama_memory_clear` → `llama_synchronize` →
  `llama_perf_context_reset`, and none of those three can change a graph, because no graph
  reads a counter.
* `include/llama.h:1018` marks `llama_set_warmup` **DEPRECATED**, and
  `src/llama-cparams.h:52` carries `// TODO: remove [TAG_LLAMA_GRAPH_NO_WARMUP]`.
* Even when the flag *is* set, mainline bounds the damage:
  `src/llama-graph.cpp:2331` aggregates `hparams.n_expert_used(il)` views, not the widened
  member — which is why the width table above shows 64-wide graphs producing bit-identical
  logits. ik's `src/llama-build-context.cpp:1708` sums the widened member instead.

## What the fix would look like

**No patch has been applied to any tree, and none is proposed here as a diff.** Two shapes,
smallest first:

1. **Stop re-arming it.** `common/common.cpp:4179`'s `llama_reset_timings(lctx)` puts
   `n_eval` back to 0 two lines after the synchronize raised it. Dropping it fixes the
   default path. It does **not** fix `--no-warmup`, and it leaves graph shape depending on a
   statistics counter, so it is a stopgap.
2. **Make it explicit, as mainline did.** Give the context a caller-set `warmup` flag and
   have `common`'s warmup block set it and clear it around its own decode, so
   `llm_build_context` never consults `n_eval`. This is upstream's own shape
   (`llama_set_warmup`).

Worth pairing with either: ik's `can_reuse_graph` (`src/llama.cpp:663`) compares
`all_seq_id`, `head`, `n_kv`, `n_outputs`, `n_tokens` and the MTP fields but **not** the
graph's expert width, which is why one widened BOS graph gets reused for the rest of a
step prefill. Mainline's equivalent of the second half of this is PR #14753.

## Prior art

Searched issues and pull requests on both trackers plus discussions over GraphQL; queries are
recorded in the round report. Nothing on either tracker reports this symptom.

Three merged mainline pull requests are the relevant lineage, and they read as a decision the
project already made:

| PR | title | merged |
|---|---|---|
| [#11571](https://github.com/ggml-org/llama.cpp/pull/11571) | Load all MoE experts during warmup | 2025-03-14 |
| [#14753](https://github.com/ggml-org/llama.cpp/pull/14753) | graph : avoid huge warm-up graphs for MoE models | 2025-07-18 |
| [#24009](https://github.com/ggml-org/llama.cpp/pull/24009) | llama : deprecate `llama_set_warmup` | 2026-06-02 |

ik carries the first and neither of the other two, and replaced the explicit flag with an
inference. #24009 is the sibling precedent for shape 2 above; #14753 is the sibling precedent
for bounding the aggregation.

## What I did not test

* **One model.** DeepSeek-V2-Lite-Chat Q3_K_M only, `expert_gating_func = softmax` and
  `expert_weights_norm = 0`. On an architecture that renormalizes the routed weights, the
  arithmetic of a widened graph differs again, and I did not measure one.
* **CPU only.** Every number here is `-ngl 0`. A previous round measured the same split on
  the 3090 (1191 @ 30.222145 vs 245 @ 29.230593), but nothing in this round touched a GPU.
* **No timing claims at all.** This is a correctness report; I measured no throughput cost
  for running sixty-four experts instead of six.
* **`llama-server` is not affected**, for the clamp reason given above. I verified the two
  chunking call sites and the realized `n_batch` in the server's own log, but I did not test
  whether some other server configuration (a longer prompt, several slots, a draft model) can
  reach a single-token batch.
* **The mainline shipped-binary control is not the same shape as ik's.** Mainline at this
  HEAD aborts on `-b 1` (`GGML_ASSERT(n_outputs_max <= cparams.n_outputs_max)` in
  `llama-server`, `GGML_ASSERT(n_tokens_all <= cparams.n_batch)` in `llama-cli`), so the
  closest launchable control is `-ub 1` with the default `n_batch`; it answers `" a"` there.
  The like-for-like comparison is the probe, which calls `llama_decode` once per token on
  both engines.
* I did not build a patched ik and measure the fix. Both conjuncts of the predicate are
  flippable from outside the library, which is what the arms do.

## Four objections a maintainer would raise

**"Who feeds a prompt one token at a time?"** Anyone who wants per-position logits, which is
the normal shape for a reference harness, an evaluation script or a logit-level comparison —
it is how this was found. It is also what `llama-cli -b 1` does, and `-b` is a documented
flag, not an internal. The server escapes it only because a KQ-mask padding clamp raises
`n_batch` to 16 behind the caller's back (see "Who is exposed"); nothing about the predicate
is aimed at keeping the server safe, so the next caller that submits a single-token batch is
exposed again.


**"The warmup decode's output is discarded, so who cares."** It is not discarded. The widened
decode writes its token's KV, and under graph reuse the widened graph is reused for the rest
of the prompt — `can_reuse_graph` (`src/llama.cpp:663`) does not compare expert width. With
reuse disabled (`-no-gr`) the divergence shrinks from 3.65142 to 1.1147 but the split stays
and the honest value is bit-identical either way (29.244007), so reuse is an amplifier and
not the cause. And the shipped-binary run at the top of
this report is a user-visible different answer, not an internal detail.

**"That is just batch-vs-batch-size numeric noise; logits are never bit-identical across
batch sizes."** On this engine and this model, batch-vs-step noise is not what you are looking
at: the `fresh_batch` arm (virgin context, whole prompt in one batch) and the `warm1_sync` arm
(step prefill with the counter raised) print the same top-5 logits to every digit shown —
`29.244007, 29.093025, 28.636026, 28.315937, 27.828226` — and the same `max_abs_diff`
`3.65142`. Batch prefill and honest step prefill agree; it is the widened step prefill that is
the outlier. And the `warm1_sync` / `warm1_nosync` pair holds prefill mode, tokens, positions
and cache state fixed and differs by one `llama_synchronize` call, which is not a numeric
knob. A node-by-node hash of the two graphs confirms it directly: nodes 0–60 are
bit-identical, the first differing node is layer 1's router sort (node 61, `ARGSORT` on
`ffn_moe_probs-1`, same shape both ways — its tail past `k` is not defined when `k` is 6),
and the width itself is the next node: `ffn_moe_topk-1` is `64,1` in one arm and `6,1` in the
other. Sixty-four is not a rounding of six.

**"Mainline does the same thing."** Measured, it does not: the same probe ported to
`930e2fa5` returns `max_abs_diff` 0 on every one of the five arms, and a direct readout of
the graph's expert width shows 6 on every graph. When `llama_set_warmup` is called explicitly
the same readout shows 64, so the probe is not blind. A note on the record: an earlier run
here appeared to show mainline behaving like ik, using `llama-eval-callback`. That tool's
binary was built from a checkout of **`ikawrakow/ik_llama.cpp` at `9cba2e38`** that had been
labelled "master" locally — mainline's build does not contain `llama-eval-callback` at all —
so it was ik against ik. That is corrected here rather than dropped.
