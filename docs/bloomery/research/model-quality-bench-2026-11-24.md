# A quality benchmark for every model bloomery adds (design, 2026-11-24)

The user, 2026-11-24: every model we add should ship with a benchmark, **not only speed**. They prefer to build our own
tools rather than adopt a framework, and are weighing whether some of it belongs in toktape. This page is the survey,
the decision and the plan. Nothing here is measured yet; the first rounds are at the end.

## 1. What the benchmark has to show

bloomery is an engine, not a model. A per-model quality number has to answer two questions, and they need different
instruments:

1. **Does bloomery run this model faithfully?** (an engine claim: our kernels, quant handling, template and sampler do
   not lose quality against a reference). Task scores answer this badly: a few hundred samples move ±2–3 points between
   runs, which hides an engine regression of the same size, and most of the score is the model's own ability.
2. **Does the model work properly behind our server?** (a serving claim: the chat template, tool calls, reasoning split
   and stop ids are right). A broken template can cost tens of points while every kernel is exact.

## 2. Survey (read 2026-11-24, not run)

| Tool | What it is | Fit for us |
|---|---|---|
| [google-deepmind/gbench](https://github.com/google-deepmind/gbench) | Apache-2.0, Python, created 2026-10-30 (174 stars). Any OpenAI-compatible `/v1` (`--remote-endpoint`). Three tiers: 86 academic suites (GSM8K, GPQA, MMLU, BFCL, …), a 16-check **Golden Set** with chat-template sensitivity pairs that separate a broken template from a weak model, and the GemmaClaw agentic QA suite (Docker, some scenarios need the Gemini API). Also a QPS stress sweep with P99 TTFT/ITL SLOs. No paper or blog post ([review issue](https://github.com/8W9aG/openinterpretability/issues/6433)) | The Golden Set idea is the one piece nothing else has. The stress sweep measures concurrent-load serving (vLLM's question), not our single-user headline, and AGENTS.md takes speed numbers only from the lease runners. Young and Gemma/vLLM-centred |
| [EleutherAI/lm-evaluation-harness](https://github.com/eleutherai/lm-evaluation-harness) | MIT, v0.4.13 (2026-08-31). `local-chat-completions` / `local-completions` for OpenAI-compatible servers | The numbers model cards quote. Over the chat API only generative tasks run (no loglikelihood), so multiple-choice needs prompt logprobs from `/completions` |
| Inspect AI + inspect_evals (UK AISI) | MIT, 0.3.291 (2026-11-17). Talks to llama-server as an OpenAI-API provider ([survey notes](https://github.com/a1exk-dev/llm-evals/issues/3)) | The most complete eval set reachable over the API |
| OpenAI simple-evals | deprecated since 2025-07 (same notes) | — |
| llama.cpp `--kl-divergence`, [mlx-quant-fidelity](https://pypi.org/project/mlx-quant-fidelity/), [mlx-kld](https://github.com/TipKnuckle/mlx-kld) | next-token distribution against a reference: KLD, top-1 agreement, PPL | The engine-faithfulness instrument. Quantization studies report KLD tracking downstream accuracy (one reports baseline accuracy held below 0.01; [Fireworks](https://fireworks.ai/research/llm-quantization-quality-kl-divergence) uses < 0.007 as its working line). mlx-quant-fidelity's authors note that short-prose KLD can under-predict task and long-context loss |

What bloomery already has: `crates/refset/src/kld.rs` and `crates/gpu-gates/src/{kld.rs,bin/kld_diff.rs}` read and compare
**ik's** `.kld` base files (full-vocabulary KL in f64, argmax agreement, NLL, bins by position and ubatch boundary);
`ppl_ds41`, `ppl_exaone`, `gate_exaone_kld`; `tools/ref/inkling2-kld.sh` (llama-perplexity bases on an oracle tree);
`exact_ref` (the f64 referee). All of it takes its base from an ik or llama.cpp tree, which the 2026-11-24 "no live
reference trees" decision retires. `bloomery-serve` already returns `logprobs`/`top_logprobs`
(`crates/serve/src/logprobs.rs`).

And an API-level task harness of our own already exists: **modelbench** (rig-log `tools/modelbench/`, written 2026-11-13 for
the EXAONE quant work, never committed; a copy on ws `/root/modelbench/`). KMMLU (450 items, 10 per subject), MMLU-Pro
(420, 30 per category) and HumanEval+ (164, base and plus tests), sampled with a fixed seed into JSONL with a MANIFEST of
dataset revisions and sha256; one user message, temperature 0, seed 0, thinking off by both spellings (and it refuses a
template that cannot turn thinking off, and counts `think_leak`); multiple choice scored by the greedy answer letter, code
by running the extracted function; `summary.py` prints accuracy with its Wilson 95 % interval and, `--paired`, McNemar's
exact test on the items two runs share. Its results on ws (2026-11-13): V4.1 Flash Q3_K_M kmmlu 72.9 % [68.6, 76.8],
mmlupro 74.5 % [70.1, 78.5], HumanEval+ 92.1 %; EXAONE 750B IQ2_XXS kmmlu 61.1 %, mmlupro 47.6 %, HumanEval+ 88.4 %
(the `-p2` rerun of each moved by up to 3.1 points, inside the intervals). Those intervals are ±4 points wide at n ≈ 450:
the measured case of §1's point that task scores cannot see an engine regression of a point or two.

## 3. Decision: build our own, in three layers, split by who can see what

The user prefers our own tools. The survey says what to borrow as ideas, not as code: gBench's template pairs,
lm-eval's task definitions and scoring rules (to check our scorer once against theirs, "doubt the instrument once").

| Layer | Question | Instrument | Owner | Cost per model |
|---|---|---|---|---|
| **Fidelity** | engine faithful? | full-vocabulary KLD, top-1 agreement, PPL against a reference, over a fixed text set (prose, code, a long-context chunk) | **bloomery** (needs the whole logit row, which the API cannot carry: at most ~20 logprobs) | minutes (prompt passes only) |
| **Template** | served right? | ~16 deterministic checks through the API, gBench-style pairs: the same task with and without the template's features (system turn, tool offer, tool result, reasoning on/off, non-ASCII), two-sided presence assertions | **toktape** (engine-agnostic, runs on any server) | minutes |
| **Tasks** | model works? | **modelbench, grown**: its KMMLU / MMLU-Pro / HumanEval+ plus a tool-call set (AST match) and one long-context retrieval; fixed seeds and sample counts; datasets fetched at run time, never bundled; the reference engine on the same items in the same session, judged by McNemar on the paired items | **toktape** (modelbench moves there) | an overnight box job |

Why the split: fidelity needs logits and the reference forward, which only the engine side has (and for a model no other
engine runs, like ERNIE 5.5, the reference is our own `tools/ref/<model>_ref.py`). Template and task checks only need the
API, so they run against llama-server, vLLM or bloomery alike: that is toktape's whole stance ("the black-box tape for
local LLM serving"), and it lets the card put quality next to speed for any engine. A cross-engine agreement check (top-1
and a top-k KL over the API's `top_logprobs`, two servers on the same prompts) is also API-only and fits toktape as an
approximation; the exact number stays bloomery's.

## 4. The pieces

**bloomery: `fidelity` (common, every family).**
- A base writer that does not need ik: the reference's logits over the fixed text set in our own format (or ik's `.kld`
  layout, so `kld_diff` keeps working), written from (a) our f32 reference for a model with no other engine, (b) a BF16
  file run by our own engine at f32 activations (`exact_ref --act f64` exists for the step; it needs a prompt-pass form),
  or (c) a frozen base from before the retirement.
- The engine side writes the same layout from the served quant; `kld_diff` compares. One recipe per family reads the
  family row, so a new model adds one row, not a script (AGENTS.md "common code first"; today each model has its own
  `ppl_*`/`*-kld.sh`).
- Output: mean KLD ± SE, p99, top-1 %, ln(PPL ratio), each with its conditions (file, quant, card, commit, text set).
  Not a gate: the forced_exact pins stay the bug catchers (AGENTS.md "Performance first, accuracy opt-in").

**toktape: `check` and `eval` (proposal, the user decides).**
- `toktape check`: the template set, recorded into the tape; the card gains a line (`Template 16/16`, or which pair
  failed and the request/response bytes).
- `toktape eval --suite kmmlu,mmlupro,humaneval,toolcall,needle`: modelbench's logic ported (its sampling, thinking-off
  handling, scoring, Wilson and McNemar), answers and scores recorded into the tape; the card and the hub show them next
  to the speed rows, with the engine, quant and sampling the tape already records. modelbench is not machine-specific, so
  it does not belong in rig-log either way: toktape (this proposal) or bloomery `tools/`. Code execution (HumanEval) runs
  model-written code: toktape would run it in a sandbox (a container or a no-network user), never in the recorder's process.
- A tape from llama-server and one from bloomery-serve on the same suites in one session give the comparison row.

**Publishing.** Each model's page carries speed (release sitting), fidelity (bloomery) and the template/task rows
(toktape tapes, published as `[recorded on tape]` links the way headline numbers are now). Every number names its machine
and conditions; no ratio against another engine is stated (the README's rule).

## 5. Open decisions (the user's)

1. toktape owns `check` and `eval` (the proposal above), or both live in bloomery's tools and toktape only records.
2. The task list and sample counts (cost: a 280B model at ~30 tok/s with thinking spends hours on GPQA-sized suites).
3. Whether the hub shows task scores at all, or only the template line and fidelity.

## 6. First rounds

1. **fid0** (bloomery, investigation + code): a base writer without ik, the common `fidelity` recipe over one shipped
   family (Qwen3.8-27B or Inkling 2 Mini), and a frozen base from an existing ik `.kld` to prove `kld_diff` reads both
   the same. Prediction card: none (no timing).
2. **tt-check0** (toktape, after decision 1): the template set against llama-server and bloomery-serve on one shipped
   model, recorded in a tape; one intentionally broken template must fail its pair.
3. **tt-eval0**: modelbench into toktape (`eval`), plus the tool-call set, on the same model; its 2026-11-13 V4.1 rows
   reproduced within their intervals, and the scorer cross-checked once against lm-eval's on the same answers.
ERNIE 5.5 is the first new model to carry all three when its body lands.
