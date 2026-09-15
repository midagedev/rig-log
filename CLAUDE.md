# rig-log — agent context

A build log for one workstation, measured. Start sessions about this machine
here, not in another repo: the machine's facts, the serving configs, and the
record of what was sent upstream all live in this tree.

## What this repo is for

Two purposes, and the second is easy to forget:

1. **Measure what this hardware can actually do** — large language models
   first, then video, images, audio. Every entry carries the exact command
   line, the measured throughput, and the thing that turned out to be wrong.
2. **Find and ship upstream contributions.** Running unreleased models on
   mismatched hardware walks straight into other people's untested paths.
   When a run fails, the question is not only "how do I get past this" but
   "is this a bug someone else will hit, and is it reportable?" A crash with
   a minimal reproducer is worth more than a workaround nobody can check.
   The method is [`docs/upstream-contributions.md`](docs/upstream-contributions.md);
   the record is the table in that file.

Both purposes have the same discipline: **a claim in this repo is something
that was measured on this machine, on a stated date.** If a number is derived
rather than measured, it says so. If a claim turns out to be wrong, the
correction goes in and the old claim is struck — a log that quietly edits its
own history is worth nothing.

## The machine

Facts, contact paths, and the two board gotchas are in
[`README.md`](README.md). It is the canonical summary; keep it current.

Private operational detail — hostnames, systemd units, BIOS to-dos, the
dashboard — lives in `~/repo-mid/vps-infra/hosts/ws.md` and
`hosts/ws-llm-serving.md`, which are **not** public. Nothing from those files
gets copied here verbatim: this repo names the machine by its hardware, never
by its tailnet name or address.

Reaching it: over Tailscale; the node name is in the private host notes, not
here — two lines above is the rule this would otherwise break. It serves an
OpenAI-compatible API on loopback, published over the tailnet. `llm.service` holds both GPUs, so anything that
needs VRAM starts with stopping it and ends with starting it again and
confirming the rate came back.

## Tracking

Work items go to the **WKS** project on the self-hosted tracker (`gadak
--workspace gdk`, project key `WKS`). Findings that outrun an issue go to a
wiki page in the `GDK` space and get linked from the issue by URL. Do not
open a `TODO.md` here. **Experiments carry the label `experiment`** — one
issue per experiment with the measured state so far and what would settle
it (user instruction 2026-09-14); the experiment queue in
`docs/v41-experiment-plan.md` and those issues say the same thing. On the
Mac the PATH `gadak` is a dev build whose home is `~/.gadak-dev`, so the
`gdk` workspace needs `GADAK_HOME=$HOME/.gadak`.

Friction with gadak itself goes to the **GDK** board as its own issue, with
the command and its real output — routing around it destroys the evidence.

## Layout

```
log/        one file per experiment, dated. The measured record.
docs/       longer write-ups: upstream bug dossiers, method, hardware notes
configs/    the scripts actually running on the machine, copied as-is
tools/      recording: VHS tapes and the scripts they drive
assets/     the clips and sheets
```

## Conventions

- **Prose, not bullets, for findings.** An entry explains what was tried, what
  the number was, and what it cost. Tables for measurements, sentences for
  reasoning.
- **Include the failures.** The runs that lost speed are part of the record;
  an entry that only shows the winning configuration is an advertisement.
- **English in this repo** — it is public and the upstream audience reads it.
  Session conversation stays Korean.
- **No private addresses, no hostnames, no passwords.** Check before commit;
  the serving script here has its host generalized on purpose.
- **Every clip that leaves this repo names the recorder with its link**: "recorded
  with [toktape](https://github.com/midagedev/toktape)" in the tweet, the post,
  the PR body, the log line. The clip is also an advertisement for the tool
  (user instruction 2026-09-14).
- Assets: the sheet is `assets/placement-sheet.html`, re-screenshot at
  1280×720. Keep the favicon and title stable across republishes.
- **toktape is a sibling project we feed requirements to.** When a recording
  or serving round here shows something the recorder should do itself (a
  witness it asked us for by hand, a mode it lacks), send the request to the
  toktape session directly rather than working around it (user instruction
  2026-09-14).
- **Model files come down with [`tools/fetch-gguf.sh`](tools/fetch-gguf.sh)** —
  parallel range workers, the expected size read from the API, and a file that
  only appears at its final path when its byte count matches. Measured
  2026-09-15: one connection 28 MB/s against eight at 80 MB/s on the same file
  and link, so a 29 GB model is six minutes rather than seventeen. Do not hand-roll
  a `curl` for a model again; a half-written `.gguf` where a loader can see it is
  the failure this prevents.
- **Benchmarks need a quiet machine, and "quiet" is a protocol**: one lease,
  IO pressure rather than load average, the witness recorded in every row,
  and delegates get the runner script rather than an instruction. The method
  and the incidents behind it are [`docs/quiet-machine.md`](docs/quiet-machine.md).
