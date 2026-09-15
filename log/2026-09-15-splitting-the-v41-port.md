# Splitting the DeepSeek-V4.1 port into two PRs

2026-09-15, evening. ik_llama.cpp at `19dfb71b`, the port branch rebased onto
it, the same Q3_K_M shards as every earlier run on this machine.

## Why

The port went up in [#2438](https://github.com/ikawrakow/ik_llama.cpp/issues/2438#issuecomment-5656281274)
as a branch rather than a PR, with the question attached: split it into
reviewable pieces, or leave it as a reference? The answer arrived this
morning — "I think it would be easier if split in 2 PRs."

A branch that works is not a PR. The branch had eight commits, three of them
"fix what the first commit did", one of them already merged upstream, and
comments written to explain the model to myself. None of that survives
contact with a reviewer.

## The rebase

The branch was based on `3bb386eb`; main had moved eighteen commits. Three
conflicts, all of them small, and all three interesting for the same reason —
they are places where someone else's work arrived in the same lines:

- `exp_probs_b_vl` is now created by the loader on main. The V4-Flash vision
  PR (#2431, merged 2026-09-15) added the same tensor for its own reason, so
  the port's line was a duplicate and the port's comment described it wrongly
  ("unused by text inference" — on main it routes image tokens).
- `LLM_TENSOR_FFN_EXP_PROBS_B_VL` had to be kept in the tensor-name table.
- The swiglu-limits guard grew `LLM_ARCH_GLM5NEXT` on main while the port
  replaced its `DEEPSEEK4` test with `llm_arch_is_dsv4()`. The merge keeps
  both.

The fourth resolution was a deletion: `GGML_CUDA_NO_PINNED_WEIGHTS` was on the
branch and is now on main as [#2444](https://github.com/ikawrakow/ik_llama.cpp/pull/2444),
so the rebase dropped it as already applied.

## The split

`llm_arch_is_dsv4()` is the seam. Everything the model needs to load and run
is one PR; everything the DSpark draft needs is the other.

| | files | commits | diff |
| --- | --- | --- | --- |
| PR 1, the model | 13 | 2 | +794 / −108 |
| PR 2, the draft | 5 | 2 | +56 / −14 |

The three follow-up commits were folded into the commit they fix, so the
reviewer reads the code as it stands and not as it was arrived at. The engram
row prefetch stays its own commit: it is a separate claim with its own
measurement, and it can be reverted without taking the architecture with it.

GitHub does not stack cross-fork PRs — the base of a PR from a fork has to be
a branch of the upstream repo — so PR 2 waits for PR 1 to land rather than
carrying its 794 lines as review noise. The branch comparison is linked from
PR 1 for anyone who wants to see the draft half now.

## Comments

`CONTRIBUTING.md` is explicit: "Minimize as much as possible the AI slop. Both
in the PR description and in the endless comments left behind in the code by
the LLM. If in doubt, just remove all AI generated comments."

The branch added 101 comment lines to 870 of code. The rule applied was: a
comment stays if breaking it breaks the code — the table must stay mmapped,
the hash constants index straight into it, readers alias their source's
storage, a shared token has no unambiguous history. A comment goes if it
teaches: every "V4 does X, V4.1 does Y" pair that restated the two lines
underneath it, and every sentence explaining what the next call does. 101
lines became 66.

## Re-measuring

The Saturday numbers were measured against `3bb386eb`. Eighteen commits later
they are no longer the port's numbers, and two of those commits are CPU GEMM
work, so the whole pair was run again today — both engines, same file, same
box, nothing else running.

wikitext-2, four chunks of 2048, CPU only:

| build | [1] | [2] | [3] | [4] | final |
| --- | --- | --- | --- | --- | --- |
| the port, on `19dfb71b` | 1.7393 | 1.7633 | 1.8389 | 2.2355 | 2.2355 ± 0.0626 |
| llama.cpp V4.1 branch `38f6868e` | 1.7352 | 1.7666 | 1.8493 | 2.2556 | 2.2556 ± 0.0641 |
| the port on `3bb386eb`, 2026-09-13 | 1.7229 | 1.7499 | 1.8242 | 2.2258 | 2.2258 ± 0.0622 |

Both sides moved by about the width of a chunk-to-chunk wobble, in the same
direction, and the port stays a hair under the reference. The point is not the
0.01: it is that a two-day-old number measured against a moved base is not
evidence of anything, and the PR would have carried it as if it were.

Decode at the published split — experts of six layers on the cards, the rest on
the CPU, `-c 16384 -ngl 99 -t 32 -b 2048 -ub 512`, 200-token greedy completions,
three on cold engram rows and two with the rows in page cache:

| build | new prompts | rows cached |
| --- | --- | --- |
| the port | 20.41, 20.55, 20.73 | 21.21, 21.22 |
| llama.cpp V4.1 branch | 21.27, 21.21, 21.20 | 21.35, 21.91 |

Mainline is about 3 % ahead, which is where it was on Saturday (18.6 against
18.4). Both engines decode faster than they did then.

## What the runner caught

The measurement script was written for this round and caught four things, in
the order they happen to a person doing it by hand:

1. `--lazy-mode auto` is a mainline flag. ik's server printed its help and
   exited, and the session-leader assertion fired against a pid that was
   already gone — so it reported "not a session leader" for a process that had
   died. The assertion now distinguishes the two.
2. `-ot` to the CPU asks for 283 GiB of pinned host memory on a 251 GB box.
   This is the path [#2444](https://github.com/ikawrakow/ik_llama.cpp/pull/2444)
   was written for; the runner now sets `GGML_CUDA_NO_PINNED_WEIGHTS=1`.
3. mainline's `/health` answers 200 while the model is still loading. The
   readiness check was a health code, so five requests went out against a
   loading server, came back without `timings`, and the run still printed
   `IK_V41_DONE`. Readiness is now a completion that actually returns timings.
4. A response without `timings` is now a failed run rather than a line of
   output. The third defect was only visible because a Python `KeyError`
   happened to be loud; the next one would not have been.

The script is [`tools/ik/ik-v41-verify.sh`](../tools/ik/ik-v41-verify.sh). It
takes a branch and a tag, gates on the clock, the cards and the lease, and runs
either engine through the same measurement path — which is the only reason the
two rows above are comparable.

## Where it stands

[#2455](https://github.com/ikawrakow/ik_llama.cpp/pull/2455) is open with the
two tables above and its own list of what is not implemented: session save of
the shared streams, the MTP graph, the quantizer exemption for the engram gate
scales, vision, and a batch that shares a token between sequences (the n-gram
history is ambiguous there, so it asserts rather than guessing). The draft PR
follows it.
