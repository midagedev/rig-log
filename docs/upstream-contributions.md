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

Read the target's `CONTRIBUTING.md` and follow it exactly. **Its rules do not
transfer between repositories, so read the one you are submitting to.** The
bullets below were written from ik_llama.cpp's, whose CONTRIBUTING calls out AI
slop in descriptions:

- Disclose AI assistance in the body.
- The commit **author** must be a person. No AI co-author trailer, whatever
  your local tooling appends by default.
- No AI-generated comments in the diff. If in doubt, remove all of them.
- Use the project's squashed-commit title format.

That file's wording is "AI usage is not encouraged but it is tolerated", and it
also says: do not submit a PR you do not understand or have never tested
sufficiently. Two consequences worth stating, because a comment is not a PR and
the rules read as if they were only about patches. The disclosure applies to
**anything you post**, so a measurement left on someone else's PR carries the
same sentence. And the "never tested" clause is what forces the verification
boundary into the text: a measurement of the *bug* a PR fixes is not a test of
that PR, so the comment has to say which of the two it is. Measured 2026-09-17
on [#2418](https://github.com/ikawrakow/ik_llama.cpp/pull/2418), where the
numbers were all taken on the unpatched tip and the branch was never built.

mistral.rs is the counter-example, measured 2026-09-17: there is no
`CONTRIBUTING.md` at all, the conventions live in a committed `AGENTS.md` and a
near-duplicate `CLAUDE.md` addressed to agents, there is no disclosure rule of
any kind, and the maintainer merges `Co-Authored-By: Claude` commits of his own
(three of the four such commits in that history are his). Carrying ik's bullets
there would have meant stripping a trailer the maintainer uses himself. What
that repo does demand instead is a house style a default agent breaks on sight:
comments default to **none**, one line each where they exist, ASCII only with no
em-dashes and no `--`, magic values hoisted to named `const`s, no defensive
handling for cases that cannot occur, and no "Test plan" section in a body.

### Whether the patch carries a test: count, do not read

The written rule points the wrong way often enough that reading it is not
enough. mistral.rs's `AGENTS.md` says "Add tests and examples for new
functionality" — and of its twenty-two most recently merged `fix` pull requests,
**two** touched a test file, one of those a website JavaScript test and the
other a twenty-five-file "address recent correctness regressions". The four
adjacent single-purpose fixes, including a dtype bug in the same crate
([#1755](https://github.com/EricLBuehler/mistral.rs/pull/1755)), were each one
file with no test. So the convention there, for a fix, is no test, and the
sentence in `AGENTS.md` is about new functionality.

Counting is one `gh` loop over `gh pr list --search "fix in:title" --state
merged` plus `pulls/<n>/files`, and it answers in a minute what a style
document cannot.

Our own four submissions, which is the same question asked from the other side:

| PR | shipped a test |
|---|---|
| ik_llama.cpp [#2444](https://github.com/ikawrakow/ik_llama.cpp/pull/2444) | no (one file, +5/−1) |
| exllamav3 [#376](https://github.com/turboderp-org/exllamav3/pull/376) | yes (+39, a guard that fails on the unpatched file) |
| llama.cpp [#29008](https://github.com/ggml-org/llama.cpp/pull/29008) | shipped one, **asked to remove it**, merged without |
| mistral.rs [#2430](https://github.com/EricLBuehler/mistral.rs/pull/2430) | no |

The llama.cpp one is the cautionary datapoint and it is worth being precise
about, because it was misread here once. A reviewer wrote "Please remove the
tests and we can get this merged in" and **gave no reason** — the tree is full
of parser tests in `tests/test-chat.cpp`, so it was not a rule about tests. A
second maintainer's remark in the same thread ("the attempt to align something
that won't align was just confusing") was read here as that reason, and it was
not: his commit was `--whitespace`, undoing column alignment in the parser file,
because the full-width `<｜User｜>` never lines up anyway. **A comment is
evidence of what it is about, not of what you need it to be about.**

So: **FAIL-first is a discipline, not necessarily an artifact.** Always measure
the failure and the fix locally; ship the test only when the count says that
repo ships tests for this class of change. Two further filters when it does:

- **Assert only what the fix promises.** The BF16 test drafted for #2430
  asserted that the BF16 path's values equalled the F32 path's exactly. It
  passed, because the fixture was all ones and both sides were exactly
  representable; with realistic values it fails, measured, `-3.859375` against
  `-3.8654757`. The fix promises dtype transparency, not bit-identical results,
  so the assertion was a trap for whoever edited the fixture next.
- **Where it goes matters as much as whether.** That test landed in
  `gguf/mod.rs`'s test module, which is entirely ISQ and UQFF plumbing. A
  forward-pass dtype test is an outlier there even in a repo that wanted one.

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
| 2026-09-15 | ik_llama.cpp | [#2455](https://github.com/ikawrakow/ik_llama.cpp/pull/2455) — DeepSeek-V4.1 (`deepseek41`): shared compressed KV streams, lagged hyper-connections, the low-rank-only query norm, and the engram tables, plus the row prefetch as its own commit. The first of the two PRs the maintainer asked for on #2438; the DSpark draft half is 5 files, +56/−14 on a branch and follows this one, because GitHub cannot base a fork PR on another fork branch. Rebased onto `19dfb71b` and both engines re-measured the same day: wikitext-2 2.2355 ± 0.0626 against the llama.cpp V4.1 branch's 2.2556 ± 0.0641, decode 20.4–20.7 against 21.2 tok/s at the same split. +794/−108 across 13 files, 2 commits. [Write-up](../log/2026-09-15-splitting-the-v41-port.md). | open |
| 2026-09-15 | vcruz305/llama.cpp `runtime/deepseek41` (V4.1 port) | `llama_model_n_swa()` returns 0 for `DEEPSEEK4` so the server does not apply the 128-token SWA margin to a dsv4 memory's exact-position checkpoints; the V4.1 port added `DEEPSEEK41` without extending that case, so every follow-up turn on a long document re-prefilled ~2 600 tokens instead of ~560 (TTFT 21 → 8.8 s, 5/5 identical answers). One line. Mainline master measured unaffected on V4-Flash. Dossier: [`v41-serving.md`](v41-serving.md). [vcruz305/llama.cpp#3](https://github.com/vcruz305/llama.cpp/pull/3), +1/−1, opened 2026-09-15 against `runtime/deepseek41`. | open |
| 2026-09-11 | ik_llama.cpp | [#2436](https://github.com/ikawrakow/ik_llama.cpp/pull/2436) — `llama_build_graph()` returns `nullptr` on a DFlash K/V allocation failure and the result is dereferenced, turning a detected out-of-memory condition into a segfault. Four callers passed the value on unchecked. +18/−0. | merged 2026-09-14 |
| 2026-09-11 | ik_llama.cpp | [#2437](https://github.com/ikawrakow/ik_llama.cpp/pull/2437) — the loader checked a tensor's shape and type but never that the GGUF reserved as many bytes as the type requires, so a malformed file loaded silently and read across tensor boundaries. +17/−0. | closed, declined |
| 2026-09-13 | llama.cpp (V4.1 branch) | DeepSeek-V4.1's engram tensors take the body's quantization type, but the tables are never resident — a token reads a few dozen rows of 384 M off NVMe, so their precision costs disk and nothing else. Measured here on wikitext-2: 2.2438 at Q3_K against 2.1090 with the engram tensors at Q8_0, and the two tensor groups are additive, the 0.2 GB `engram_wkv` half worth about 160x more perplexity per byte than the 125 GB table. Upstream has no engram in `llama-quant.cpp` and no V4.1 outside draft [#28696](https://github.com/ggml-org/llama.cpp/pull/28696) (conversion only); [#19654](https://github.com/ggml-org/llama.cpp/pull/19654) closed unmerged. Recipient is the branch author, and the moment is when the C++ half goes up. [Write-up](../log/2026-09-13-engram-q8-repack.md). | candidate, not filed |
| 2026-09-15 | exllamav3 | MTP drafting with CPU-offloaded experts (`-mcs`/`-mcl`) uses the drafter's `default_draft_size` 3, and on GLM-5.3-Flash at 4 bpw with 103 of 288 experts resident that loses 14 % against no draft (20.6 vs 23.3 tok/s, 47 % acceptance) where depth 1 gains 9 % (25.4, 77 %); the verify step is RAM-bandwidth-bound so only one drafted position pays. Prior-art search and a reproducer on a second placement still to do before filing; there is also no CLI knob for the depth (`model_init` has `-mtp` only; the bench sets `num_draft_tokens` on the `Generator`), so the request is a knob first and a default second. [Write-up](../log/2026-09-15-glm-5.3-flash-first-run.md). | candidate, not filed |
| 2026-09-14 | ik_llama.cpp | [#2438 comment](https://github.com/ikawrakow/ik_llama.cpp/issues/2438#issuecomment-5655462984) — the DSpark draft borrows the target's `token_embd`; a bf16 one lifts acceptance 41.1 → 45.5 % (block 5) and 54.8 → 60.1 % (block 3), the bf16 `output` adds nothing; the block mask is bidirectional in the reference and a dflash-local flag fixes the port's mask with no measurable effect. | posted |
| 2026-09-14 | Hugging Face, JigSawPT/DeepSeek-V4.1-Flash-DSpark-GGUF | [Community post #2](https://huggingface.co/JigSawPT/DeepSeek-V4.1-Flash-DSpark-GGUF/discussions/2) — keep the target's `token_embd` unquantized for this draft: +4–5 points of acceptance, 1.3 GB of RAM. | posted |
| 2026-09-14 | llama.cpp | [#28696 comment](https://github.com/ggml-org/llama.cpp/pull/28696#issuecomment-5655489873) — pointer for branch users: the V4.1 DSpark draft port and the fused-pre probe fix are PRs against `runtime/deepseek41`. | posted |
| 2026-09-14 | llama.cpp | [#26575 comment](https://github.com/ggml-org/llama.cpp/pull/26575#issuecomment-5655463160) — the request-level `speculative.n_max` is under `#if 0` in `server-schema.cpp`, so the per-request cap the PR adds cannot be tested through the request field; measured 5022/2192 both ways. | posted |
| 2026-09-14 | llama.cpp (V4.1 branch) | [vcruz305#1](https://github.com/vcruz305/llama.cpp/pull/1) — `dflash`: accept DeepSeek-V4.1 DSpark drafts (no `output_hc_*` head, lagged mixes, low-rank q norm). +52/−9, clean cherry-pick onto `runtime/deepseek41`, CPU compile there; measured on the merged tree 17.70 → 22.78 tok/s at block 3. V4 draft through the patched path untested, said so. | open |
| 2026-09-14 | llama.cpp (V4.1 branch) | [vcruz305#2](https://github.com/vcruz305/llama.cpp/pull/2) — `resolve_fused_ops` read a layer-boundary placement as missing support and disabled the fused HC pre op on every layer; ask the layer's device `supports_op` first. +10. The `-devd` abort with a DSpark draft noted in the body, not filed. Checked on master with DeepSeek-V4 (UD-IQ1_S, boundary at layer 22 and at 30): the probe keeps HC pre enabled there, so the defect is V4.1-specific (the pre node's inputs are the previous layer's lagged mix); nothing filed on ggml-org. | open |
| 2026-09-11 | — | The all-NaN logits that started that investigation: a published IQ4_KSS file reserves 4 bytes per row too few in 127 of 129 expert tensors. ~~Not a defect in this engine — the quantizer returns the right size at HEAD and at the commit checked. Nothing filed upstream; the publisher was the right recipient.~~ The quantizer is correct, but the cause turned out to be the fork's own gguf-py (next row). [Write-up](v41-serving.md). | superseded |
| 2026-09-14 | ik_llama.cpp | [#2443](https://github.com/ikawrakow/ik_llama.cpp/pull/2443) — gguf-py sizes tensors without the per-row metadata that twenty of the fork's quant types carry, so any read-then-write script (`gguf_new_metadata.py`, which the #2437 publisher had used) writes each IQ4_KSS tensor rows × 4 bytes short. Reproduced from a clean `llama-quantize` output: nan perplexity before, byte-identical data and 1.0027 after. +34/−6, single table plus three call sites. | merged 2026-09-14 |
| 2026-09-14 | Hugging Face, KeinNiemand/DeepSeek-V4-Flash-0731-IK_GGUF | [Discussion 1, follow-up](https://huggingface.co/KeinNiemand/DeepSeek-V4-Flash-0731-IK_GGUF/discussions/1) — after the publisher traced the NaN files to a `gguf_new_metadata.py` rewrite: the defect is in every gguf-py read-then-write script (metadata scripts and the Python split tooling), files straight out of `llama-quantize` and C++ splits are fine, fix is #2443, bake the template into the source model until it lands. | posted |
| 2026-09-14 | ik_llama.cpp | engram row prefetch (fork commit 57735010, port of the V4.1-branch 86d01ece1): the table is memory-mapped and read lazily, so a new prompt's rows are synchronous major faults inside the graph; `posix_madvise(WILLNEED)` in `llama_set_engram_rows` takes the first pass from 13.6 to 18.4 tok/s (faults 41–62 → 1–11 a token), second pass unchanged. +23/−0, one function. ik has no V4.1 on master yet, so the recipient is the fork's V4.1 port; goes upstream with it or as its own PR once the arch lands. [Measurement](v41-serving.md). | filed as the second commit of #2455 |
| 2026-09-14 | ik_llama.cpp | [#2444](https://github.com/ikawrakow/ik_llama.cpp/pull/2444) — `GGML_CUDA_NO_PINNED_WEIGHTS`: `-ot` overrides to the CPU drop mmap so the weights land in pinned memory, which cannot succeed when they exceed RAM; the existing escape also unpins every staging buffer. One condition. V2-Lite hybrid tg128 65.1 / 60.1 / 66.0 (default / old escape / new); V4.1 loads where it did not. +5/−1. | merged 2026-09-15 |
| 2026-09-14 | ik_llama.cpp | [#2438 comment](https://github.com/ikawrakow/ik_llama.cpp/issues/2438#issuecomment-5656281274) — the V4.1 port branch offered as a reference with its verified and unverified scope (PPL 2.2258 vs 2.2438, decode 18.4/19.0 vs 18.6/19.8 at the same split); asks the maintainer whether to split it into PRs or leave it, since the V4 port went in as his own work after an external PR closed. | answered 2026-09-15: two PRs |
| 2026-09-15 | exllamav3 | [#376](https://github.com/turboderp-org/exllamav3/pull/376) — `BlockSparseMLP_CPU.can_defer_load` detected a static expert placement by reading `EXL3_MOE_CPU_SPLIT`, which `-mcs` never sets, so `-mcs` + `EXL3_MOE_CPU_SPLIT_STATS` let the router load after the permutation and the model generated garbage at a normal token rate. One line (read `infer_params.moe_cpu_split`, as the split registration already does) plus a unit test that fails on the unpatched 1.5.0 file. Three-arm reproducer on GLM-5.3-Flash 4.05 bpw; same fix sits inside the open #315, noted there. Base `dev`, AI-assistance disclosed in the #310 form. | open |
| 2026-09-15 | TabbyAPI | #454 (llama.cpp-style `timings` on completion responses) — patch prepared by the toktape session, not by this repo; checked here on the workstation against TabbyAPI main 53da791 with the same exllamav3 1.5.0 build: main has no `timings` on any of six requests, the patch places it on the last streamed chunk or top level and returns null for n=2, its unit tests fail to import on main and pass 23 on the patch. Measured along the way that exllamav3's `time_generate` spans n decode passes (one token = one pass), so the rate is n / time, and that TabbyAPI rounds its times to 0.01 s. [Log](../log/2026-09-15-exl3-serve-and-tabbyapi-timings.md). | candidate, not filed (the toktape session files it) |
| 2026-09-17 | ik_llama.cpp | [#2418](https://github.com/ikawrakow/ik_llama.cpp/pull/2418) comment - not our PR. Thireus had already fixed the Qwen3Next mixed-sequence prefill cliff; what this box had that the PR body did not was the size of it. Posted the `llama-batched-bench -npp 238 -ntg 256 -npl 1,2,4` table (prefill 2581.9 / 119.7 / 119.0 tok/s, decode flat at 133.8 / 137.9 / 157.2, so the 21x is confined to prefill), the warning the engine prints itself, and the server-level TTFT p50 of 248 ms / 4516 ms / 12529 ms at one, four and eight streams. Says in the text that the branch was never built, so it is the unpatched behaviour and not a verification; AI assistance disclosed in prose, no trailer, per that repo's CONTRIBUTING. | posted |
| 2026-09-17 | mistral.rs | [#2430](https://github.com/EricLBuehler/mistral.rs/pull/2430) — a GGUF MoE with any layer mapped to host memory fails every forward with `moe experts forward / dtype mismatch in matmul, lhs: BF16, rhs: F32`. `GgufMatMul::quantized_act_type` returns `None` for CPU weights so the packed 2D matmul can widen BF16 itself, which also switches off the cast `QuantMethod::gather_forward` applies; the indexed path dequantizes experts to F32 instead of widening. Five lines in `gguf/cpu.rs`, placed after the `indexed_gemv` fast path so that path keeps its dtype. One file, no test, because that is what twenty of the repo's twenty-two most recent merged `fix` PRs are; the regression test was written, used as the FAIL-first, and dropped. Scoped in three launches: `-n 0:40` clean, a dense GGUF on the same split serves, one layer is enough to break a MoE one. `fmt`, `clippy -D warnings`, 361 crate tests clean — 362 with the dropped test, and the row said 362 until this was checked. The body's first version claimed the bug was x86-only; the test failed on aarch64 too and the claim was struck before submission. Evidence upgraded the same night: the CUDA build of `d5ae0f1` finished with the box tree still clean, so the server-level pair is one commit on both sides — unpatched http 500 with two `dtype mismatch` lines, the PR commit applied verbatim http 200 with none. The body still attributes its server repro to v0.9.3 and is worth one edit. | open |
| 2026-09-17 | ik_llama.cpp | Qwen3Next concurrent prefill collapses from 2 582 to 119 tok/s because `src/llama.cpp:7051` chunks a mixed-sequence ubatch one token at a time — the 3.4 s to 10 s TTFTs measured on every four-stream take here. Already fixed by open PR [#2418](https://github.com/ikawrakow/ik_llama.cpp/pull/2418), so **nothing to file**: the contribution is the measurement as a comment there. [Log](../log/2026-09-17-b-where-the-four-stream-gap-actually-is.md). | duplicate of [#2418](https://github.com/ikawrakow/ik_llama.cpp/pull/2418); our measurement posted there 2026-09-17 |
| 2026-09-17 | ik_llama.cpp | MoE decode barely batches: `llama-batched-bench -npp 238 -ntg 256 -npl 1,2,4,8` on DeepSeek-V2-Lite Q3_K_M gives decode 202.1 / **156.1** / 229.9 / 317.0 tok/s, so two sequences are slower in total than one, while dense Qwen2.5-7B in the same harness gives 120.7 / 195.5 / 290.7 / 388.5. CUDA graphs ruled out (`GGML_CUDA_DISABLE_GRAPHS=1` costs 7 %, the collapse survives) and `-no-fmoe` is worse. Three duplicate searches found nothing. **Held, not filed** — a reproducer without a cause is a symptom report; needs per-op timing (nsys or a timing build, ik has no profiler env var). | candidate, held |
| 2026-09-17 | mistral.rs | **not filed** - the CPU GGUF MoE path dequantizes a block's entire expert stack to F32 and rebuilds an `UnquantLinear` on every forward, one line above where #2430 landed, so an offloaded layer costs a flat **442 ms per token** (measured 443.7 / 442.2 / 441.5 ms per layer at 1, 4 and 10 blocks on the host) against 0.20 ms for ik_llama.cpp, which runs the same matmul on the host across 26.7 cores (measured, `utime+stime`) and reads only the 8 of 256 routed experts in quantized form, where mistral.rs manages 1.3 cores. ik is therefore the existence proof to quote: a quantized sparse CPU expert path costs 0.20 ms per layer per token on this exact model and hardware. Nothing in the path uses the sparsity. Two candidate shapes: cache the dequantized stack, or gather the routed experts before dequantizing. Held because a rate is not a diagnosis - 442 ms is consistent with the dequantize and with other things, and the next step is a profile of one offloaded layer that attributes the milliseconds. Same rule that holds ik's batch-2 decode finding. | unfiled |
| 2026-09-19 | cuda-oxide | **candidate, held** — `#[unroll]` on a `while` loop with a `usize` counter fails device codegen with `APInt::shl: bitwidth mismatch (64 vs 32)` (cargo-oxide 0.2.1, git deps b9847e95, nightly-2026-08-28, sm_86); the same tree compiles `#[unroll]` on `u32`-counter loops, so the counter width is the working hypothesis, unverified. Needs a minimal repro in their examples layout, the counter-type intervention, and a duplicate search before filing. Found in the bloomery stage-0 muse arm; tracked as MUL-7. [Log](../log/2026-09-19-a-first-rust-kernel-two-arms.md). | unfiled |

Findings that were investigated and deliberately not sent are worth a row
too, once there are any: a negative result that took a day is the same
information as a positive one, and the next session should not redo it.
