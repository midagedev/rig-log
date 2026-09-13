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
| 2026-09-11 | ik_llama.cpp | [#2436](https://github.com/ikawrakow/ik_llama.cpp/pull/2436) — `llama_build_graph()` returns `nullptr` on a DFlash K/V allocation failure and the result is dereferenced, turning a detected out-of-memory condition into a segfault. Four callers passed the value on unchecked. +18/−0. | open |
| 2026-09-11 | ik_llama.cpp | [#2437](https://github.com/ikawrakow/ik_llama.cpp/pull/2437) — the loader checked a tensor's shape and type but never that the GGUF reserved as many bytes as the type requires, so a malformed file loaded silently and read across tensor boundaries. +17/−0. | closed, declined |
| 2026-09-13 | llama.cpp (V4.1 branch) | DeepSeek-V4.1's engram tensors take the body's quantization type, but the tables are never resident — a token reads a few dozen rows of 384 M off NVMe, so their precision costs disk and nothing else. Measured here on wikitext-2: 2.2438 at Q3_K against 2.1090 with the engram tensors at Q8_0, and the two tensor groups are additive, the 0.2 GB `engram_wkv` half worth about 160x more perplexity per byte than the 125 GB table. Upstream has no engram in `llama-quant.cpp` and no V4.1 outside draft [#28696](https://github.com/ggml-org/llama.cpp/pull/28696) (conversion only); [#19654](https://github.com/ggml-org/llama.cpp/pull/19654) closed unmerged. Recipient is the branch author, and the moment is when the C++ half goes up. [Write-up](../log/2026-09-13-engram-q8-repack.md). | candidate, not filed |
| 2026-09-11 | — | The all-NaN logits that started that investigation: a published IQ4_KSS file reserves 4 bytes per row too few in 127 of 129 expert tensors. Not a defect in this engine — the quantizer returns the right size at HEAD and at the commit checked. Nothing filed upstream; the publisher was the right recipient. [Write-up](iq4-kss-short-tensors.md). | investigated, not filed |

Findings that were investigated and deliberately not sent are worth a row
too, once there are any: a negative result that took a day is the same
information as a positive one, and the next session should not redo it.
