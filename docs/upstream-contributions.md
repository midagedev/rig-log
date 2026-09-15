# Sending things upstream

Running unreleased models on mismatched hardware is a good way to find other
people's untested paths. This is how a failure on this machine becomes
something a maintainer can act on — and how it gets decided whether that is a
pull request, an issue, or nothing at all.

The pipeline is adapted from a general one; every step below is here because
skipping it cost something on this machine, and the cost is named.

## 0. Decide what the contribution is

Three outcomes, and picking the wrong one wastes the maintainer's time as
well as yours:

| You have | Send |
|---|---|
| A defect **and** its cause, small diff, measured before/after | a pull request |
| A defect, reproducible, cause unknown | an issue with the reproducer |
| A defect that turns out to be your own configuration | nothing |

A fix whose cause you inferred from reading source is not the first category.
It is a hypothesis, and it goes nowhere until step 2 turns it into an
observation.

## 1. Prior art, before writing any code

Search **issues, pull requests, and discussions**, and record the queries
verbatim so the absence is checkable by someone else.

GitHub's REST search does not see discussions; use GraphQL:

```bash
gh api graphql -f query='query{ search(query: "repo:OWNER/REPO <terms>",
  type: DISCUSSION, first: 5){ discussionCount nodes{ ... on Discussion { number title } } } }'
```

Then find the **closest merged pull requests of the same class** — not the
same subject, the same *shape*. What they looked like, how big they were, who
reviewed them, what evidence they carried. A taste argument loses; "same
class as #X, already merged" wins. For the null-deref fix below, the
precedents were an unchecked-value crash fix and a null-buffer crash fix,
both one file and under ten lines, both bodies a paragraph of mechanism plus
a measured repro. That told us the shape before we wrote a line.

Also look for the adjacent thing that is *not* the same, and say so in the
body. There was a closed issue about the same allocation failing, correctly
closed as a configuration problem; naming it and explaining the difference is
cheaper than having a maintainer find it and assume you did not look.

## 2. Measured FAIL-first

**Observe the bad behaviour on the target's current tip before drafting
anything.** Not on your build from last week — fetch and check, because a
stale assumption here invalidates everything after it.

Two things this step caught in one afternoon:

- A dossier item read "rebuild with PR #2432 included and re-test; if it
  resolves, there is nothing to report." One `gh pr view` showed #2432 was
  **closed, not merged**, and `git ls-remote` showed the local build already
  *was* `origin/main` tip. The whole item was void, and a day of rebuilding
  would have produced no information.
- A claim that a bug was `llama-server`-only, with `llama-cli` as the working
  control. It was wrong. The control had been run at `--temp 0`, which takes
  an argmax and so never reaches the code that aborts — it produced empty
  output that looked like success. At `--temp 0.7`, `llama-cli` aborts
  identically. **A control that does not exercise the failing path is not a
  control**, and a report built on it would have sent a maintainer looking in
  the wrong binary.

Get a backtrace if it crashes. `gdb -batch -ex run -ex bt --args <cmd>` on
the unpatched binary is thirty seconds and it turns "somewhere in this
function" into a frame.

## 3. Reduce the reproducer

Strip every flag that is not required, and keep stripping until removing one
more makes the failure go away. What you want to hand over is something a
maintainer can paste.

Worth the effort in both directions: dropping `--jinja`, the template flags,
the tensor overrides, the attention mode and most of the context turned a
nine-flag serving command into

```bash
llama-server -m <file> -ngl 0 -c 8192 -t 32
curl .../completion -d '{"prompt":"Hello","n_predict":64,"temperature":0.7}'
```

which needs no GPU at all — so anyone with the file and enough RAM can run
it. A reproducer that requires two specific GPUs will sit unreproduced.

Then localize. `llama-eval-callback` prints every tensor with its sum, so the
first `nan` in that log names the operation and its inputs. One flag
(`-no-fmoe`) moved the NaN from the fused kernel to a plain matmul over the
same tensor, which exonerated the fused path in a single run. Narrowing like
that is what separates an issue a maintainer can act on from a bug report
that says "it crashes".

## 4. The patch: minimal, single-purpose, local conventions

One fix per pull request. Match what the surrounding code already does,
including which error value each function returns — divergence is what gets
flagged, parity is what makes review instant.

Where a fix is wider than the one line that breaks, say why in the body,
per site. The null-deref fix touched five places: the producer, which stopped
dereferencing, and four callers, which would otherwise have received the
`nullptr` and crashed one frame later. That needed three sentences, not a
defence.

Read the target's `CONTRIBUTING.md` and follow it exactly, including the
parts about AI:

- Disclose AI assistance in the body.
- The commit **author** must be a person. No AI co-author trailer, whatever
  your local tooling appends by default.
- No AI-generated comments in the diff. If in doubt, remove all of them.
- Use the project's squashed-commit title format.

## 5. Pre-flight: predict the objections

Before submitting, read the final diff and body cold and ask what a tired
maintainer or an automated reviewer flags. The predictable classes: scope
wider than the title, a value returned that does not match the function's
convention, unchecked "tested" boxes with no explanation, and claims the diff
does not support.

For each: fix it, or pre-empt it in one sentence. A pre-empted objection
costs a sentence; an unanswered one costs a round trip and makes the
submission look unconsidered.

State the boundary of the testing honestly. "The project's backend op tests
do not reach this code, so I did not treat them as coverage" invites the
maintainer to run the step you could not. An overclaim they discover poisons
everything else in the body.

## 6. After submitting

Answer findings with things the reader can check themselves — file paths,
line numbers, pull request numbers — not opinions. Offer the follow-up
instead of arguing scope. Do not push a commit to answer what a sentence
answers; every push re-triggers review.

## What a refusal taught, since one happened

[#2437](https://github.com/ikawrakow/ik_llama.cpp/pull/2437) was declined and
closed. It was correct, seventeen lines, no false positives on six good files.
It failed on value, not on quality, and the failure is instructive enough to
change the steps above.

**Their code being wrong beats other people's input being wrong.** That is the
line the two submissions fell on either side of. A crash in the target's own
code is theirs to want fixed. A check that defends against a third party's
malformed output costs them permanent maintenance and pays someone else. The
maintainer's words were that it is "a very minor improvement to the user
experience", and on his side of the ledger that is right.

**No prior art of the same shape is a stop sign, not a green light.** The
crash fix had merged siblings to point at. The loader check had none, and that
absence was read as novelty. In a mature repository it more often means the
class has already been decided against.

**Ask in a paragraph before building.** For a class you are not sure is wanted,
an issue costs a paragraph and a refusal costs nothing. Here the patch, the
build, the false-positive run across six files and the body were all written
before the question was asked.

**Lead with what it saves the maintainer, not with what it fixes.** The real
argument for that check was that without it the symptom is NaN logits rather
than a bad file, so the reports arrive in his tracker — one user was already
composing exactly that report. That belonged in the first paragraph; it was in
the last line.

So step 0 gains a question: would the maintainer pay for these lines forever?
If the answer needs a paragraph of persuasion, it is an issue, not a pull
request.

## The record

| Date | Project | What | Outcome |
|---|---|---|---|
| 2026-09-15 | vcruz305/llama.cpp `runtime/deepseek41` (V4.1 port) | `llama_model_n_swa()` returns 0 for `DEEPSEEK4` so the server does not apply the 128-token SWA margin to a dsv4 memory's exact-position checkpoints; the V4.1 port added `DEEPSEEK41` without extending that case, so every follow-up turn on a long document re-prefilled ~2 600 tokens instead of ~560 (TTFT 21 → 8.8 s, 5/5 identical answers). One line. Mainline master measured unaffected on V4-Flash. Dossier: [`checkpoint-restore-dsv4.md`](checkpoint-restore-dsv4.md). [vcruz305/llama.cpp#3](https://github.com/vcruz305/llama.cpp/pull/3), +1/−1, opened 2026-09-15 against `runtime/deepseek41`. | open |
| 2026-09-11 | ik_llama.cpp | [#2436](https://github.com/ikawrakow/ik_llama.cpp/pull/2436) — `llama_build_graph()` returns `nullptr` on a DFlash K/V allocation failure and the result is dereferenced, turning a detected out-of-memory condition into a segfault. Four callers passed the value on unchecked. +18/−0. | open |
| 2026-09-11 | ik_llama.cpp | [#2437](https://github.com/ikawrakow/ik_llama.cpp/pull/2437) — the loader checked a tensor's shape and type but never that the GGUF reserved as many bytes as the type requires, so a malformed file loaded silently and read across tensor boundaries. +17/−0. | closed, declined |
| 2026-09-13 | llama.cpp (V4.1 branch) | DeepSeek-V4.1's engram tensors take the body's quantization type, but the tables are never resident — a token reads a few dozen rows of 384 M off NVMe, so their precision costs disk and nothing else. Measured here on wikitext-2: 2.2438 at Q3_K against 2.1090 with the engram tensors at Q8_0, and the two tensor groups are additive, the 0.2 GB `engram_wkv` half worth about 160x more perplexity per byte than the 125 GB table. Upstream has no engram in `llama-quant.cpp` and no V4.1 outside draft [#28696](https://github.com/ggml-org/llama.cpp/pull/28696) (conversion only); [#19654](https://github.com/ggml-org/llama.cpp/pull/19654) closed unmerged. Recipient is the branch author, and the moment is when the C++ half goes up. [Write-up](../log/2026-09-13-engram-q8-repack.md). | candidate, not filed |
| 2026-09-15 | exllamav3 | MTP drafting with CPU-offloaded experts (`-mcs`/`-mcl`) uses the drafter's `default_draft_size` 3, and on GLM-5.3-Flash at 4 bpw with 103 of 288 experts resident that loses 14 % against no draft (20.6 vs 23.3 tok/s, 47 % acceptance) where depth 1 gains 9 % (25.4, 77 %); the verify step is RAM-bandwidth-bound so only one drafted position pays. Prior-art search and a reproducer on a second placement still to do before filing; there is also no CLI knob for the depth (`model_init` has `-mtp` only; the bench sets `num_draft_tokens` on the `Generator`), so the request is a knob first and a default second. [Write-up](../log/2026-09-15-glm-5.3-flash-first-run.md). | candidate, not filed |
| 2026-09-14 | ik_llama.cpp | [#2438 comment](https://github.com/ikawrakow/ik_llama.cpp/issues/2438#issuecomment-5655462984) — the DSpark draft borrows the target's `token_embd`; a bf16 one lifts acceptance 41.1 → 45.5 % (block 5) and 54.8 → 60.1 % (block 3), the bf16 `output` adds nothing; the block mask is bidirectional in the reference and a dflash-local flag fixes the port's mask with no measurable effect. | posted |
| 2026-09-14 | Hugging Face, JigSawPT/DeepSeek-V4.1-Flash-DSpark-GGUF | [Community post #2](https://huggingface.co/JigSawPT/DeepSeek-V4.1-Flash-DSpark-GGUF/discussions/2) — keep the target's `token_embd` unquantized for this draft: +4–5 points of acceptance, 1.3 GB of RAM. | posted |
| 2026-09-14 | llama.cpp | [#28696 comment](https://github.com/ggml-org/llama.cpp/pull/28696#issuecomment-5655489873) — pointer for branch users: the V4.1 DSpark draft port and the fused-pre probe fix are PRs against `runtime/deepseek41`. | posted |
| 2026-09-14 | llama.cpp | [#26575 comment](https://github.com/ggml-org/llama.cpp/pull/26575#issuecomment-5655463160) — the request-level `speculative.n_max` is under `#if 0` in `server-schema.cpp`, so the per-request cap the PR adds cannot be tested through the request field; measured 5022/2192 both ways. | posted |
| 2026-09-14 | llama.cpp (V4.1 branch) | [vcruz305#1](https://github.com/vcruz305/llama.cpp/pull/1) — `dflash`: accept DeepSeek-V4.1 DSpark drafts (no `output_hc_*` head, lagged mixes, low-rank q norm). +52/−9, clean cherry-pick onto `runtime/deepseek41`, CPU compile there; measured on the merged tree 17.70 → 22.78 tok/s at block 3. V4 draft through the patched path untested, said so. | open |
| 2026-09-14 | llama.cpp (V4.1 branch) | [vcruz305#2](https://github.com/vcruz305/llama.cpp/pull/2) — `resolve_fused_ops` read a layer-boundary placement as missing support and disabled the fused HC pre op on every layer; ask the layer's device `supports_op` first. +10. The `-devd` abort with a DSpark draft noted in the body, not filed. Checked on master with DeepSeek-V4 (UD-IQ1_S, boundary at layer 22 and at 30): the probe keeps HC pre enabled there, so the defect is V4.1-specific (the pre node's inputs are the previous layer's lagged mix); nothing filed on ggml-org. | open |
| 2026-09-11 | — | The all-NaN logits that started that investigation: a published IQ4_KSS file reserves 4 bytes per row too few in 127 of 129 expert tensors. ~~Not a defect in this engine — the quantizer returns the right size at HEAD and at the commit checked. Nothing filed upstream; the publisher was the right recipient.~~ The quantizer is correct, but the cause turned out to be the fork's own gguf-py (next row). [Write-up](iq4-kss-short-tensors.md). | superseded |
| 2026-09-14 | ik_llama.cpp | [#2443](https://github.com/ikawrakow/ik_llama.cpp/pull/2443) — gguf-py sizes tensors without the per-row metadata that twenty of the fork's quant types carry, so any read-then-write script (`gguf_new_metadata.py`, which the #2437 publisher had used) writes each IQ4_KSS tensor rows × 4 bytes short. Reproduced from a clean `llama-quantize` output: nan perplexity before, byte-identical data and 1.0027 after. +34/−6, single table plus three call sites. | open |
| 2026-09-14 | Hugging Face, KeinNiemand/DeepSeek-V4-Flash-0731-IK_GGUF | [Discussion 1, follow-up](https://huggingface.co/KeinNiemand/DeepSeek-V4-Flash-0731-IK_GGUF/discussions/1) — after the publisher traced the NaN files to a `gguf_new_metadata.py` rewrite: the defect is in every gguf-py read-then-write script (metadata scripts and the Python split tooling), files straight out of `llama-quantize` and C++ splits are fine, fix is #2443, bake the template into the source model until it lands. | posted |
| 2026-09-14 | ik_llama.cpp | engram row prefetch (fork commit 57735010, port of the V4.1-branch 86d01ece1): the table is memory-mapped and read lazily, so a new prompt's rows are synchronous major faults inside the graph; `posix_madvise(WILLNEED)` in `llama_set_engram_rows` takes the first pass from 13.6 to 18.4 tok/s (faults 41–62 → 1–11 a token), second pass unchanged. +23/−0, one function. ik has no V4.1 on master yet, so the recipient is the fork's V4.1 port; goes upstream with it or as its own PR once the arch lands. [Measurement](ik-vs-mainline-v41-gap.md). | candidate, not filed |
| 2026-09-14 | ik_llama.cpp | [#2444](https://github.com/ikawrakow/ik_llama.cpp/pull/2444) — `GGML_CUDA_NO_PINNED_WEIGHTS`: `-ot` overrides to the CPU drop mmap so the weights land in pinned memory, which cannot succeed when they exceed RAM; the existing escape also unpins every staging buffer. One condition. V2-Lite hybrid tg128 65.1 / 60.1 / 66.0 (default / old escape / new); V4.1 loads where it did not. +5/−1. | open |
| 2026-09-14 | ik_llama.cpp | [#2438 comment](https://github.com/ikawrakow/ik_llama.cpp/issues/2438#issuecomment-5656281274) — the V4.1 port branch offered as a reference with its verified and unverified scope (PPL 2.2258 vs 2.2438, decode 18.4/19.0 vs 18.6/19.8 at the same split); asks the maintainer whether to split it into PRs or leave it, since the V4 port went in as his own work after an external PR closed. | posted, awaiting maintainer |
| 2026-09-15 | exllamav3 | [#376](https://github.com/turboderp-org/exllamav3/pull/376) — `BlockSparseMLP_CPU.can_defer_load` detected a static expert placement by reading `EXL3_MOE_CPU_SPLIT`, which `-mcs` never sets, so `-mcs` + `EXL3_MOE_CPU_SPLIT_STATS` let the router load after the permutation and the model generated garbage at a normal token rate. One line (read `infer_params.moe_cpu_split`, as the split registration already does) plus a unit test that fails on the unpatched 1.5.0 file. Three-arm reproducer on GLM-5.3-Flash 4.05 bpw; same fix sits inside the open #315, noted there. Base `dev`, AI-assistance disclosed in the #310 form. | open |
| 2026-09-15 | TabbyAPI | #454 (llama.cpp-style `timings` on completion responses) — patch prepared by the toktape session, not by this repo; checked here on the workstation against TabbyAPI main 53da791 with the same exllamav3 1.5.0 build: main has no `timings` on any of six requests, the patch places it on the last streamed chunk or top level and returns null for n=2, its unit tests fail to import on main and pass 23 on the patch. Measured along the way that exllamav3's `time_generate` spans n decode passes (one token = one pass), so the rate is n / time, and that TabbyAPI rounds its times to 0.01 s. [Log](../log/2026-09-15-exl3-serve-and-tabbyapi-timings.md). | candidate, not filed (the toktape session files it) |

Findings that were investigated and deliberately not sent are worth a row
too, once there are any: a negative result that took a day is the same
information as a positive one, and the next session should not redo it.
