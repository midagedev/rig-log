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

## The record

| Date | Project | What | Outcome |
|---|---|---|---|
| 2026-09-11 | ik_llama.cpp | [#2436](https://github.com/ikawrakow/ik_llama.cpp/pull/2436) — `llama_build_graph()` returns `nullptr` on a DFlash K/V allocation failure and the result is dereferenced, turning a detected out-of-memory condition into a segfault. Four callers passed the value on unchecked. +18/−0. | open |
| 2026-09-11 | ik_llama.cpp | IQ4_KSS expert tensors produce all-NaN logits — reproducible CPU-only, cause not established. See [`ik-server-nan-bug.md`](ik-server-nan-bug.md). | issue, not a PR |

Findings that were investigated and deliberately not sent are worth a row
too, once there are any: a negative result that took a day is the same
information as a positive one, and the next session should not redo it.
