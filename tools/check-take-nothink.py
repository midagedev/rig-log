#!/usr/bin/env python3
"""Fail when a take asked the model not to think and the model thought anyway.

    python3 tools/check-take-nothink.py <tape> [<tape> ...]

A tape records the request, not the behaviour: `toktape --no-think` sends
`chat_template_kwargs: {"enable_thinking": false}` and the card prints "thinking off"
whatever comes back. Measured 2026-09-17: llama-server drops those kwargs unless it was
started with `--jinja`, so two hero takes here are labelled "thinking off" and every stream
in them opens with `<think>`. The runner calls this after the take, so the next one cannot
be published with the same wrong label.

Exit 0 when nothing contradicts, 1 when a tape does (or cannot be read). A tape that never
asked for no-think is not judged — that is not this check's business.

**This is a per-take gate, not a repo-wide one.** Run over `assets/*.tape` it will always fail,
because `qwen36-35b-a3b-q6k-4stream-hero-nothink-0.2.4.tape` is the mislabelled take this check
exists because of, and it stays in the tree: the claim about it is struck in the log entry, not
deleted, and a log that quietly removes its own wrong artefacts is worth nothing. So the runners
call this on the tape they just recorded, and nobody should make the repo-wide run green.
"""
import gzip
import json
import sys

# The tags a reasoning model opens a thinking block with, as they appear in the answer text.
# mistral.rs streams reasoning in its own `reasoning_content` field instead, which toktape
# records as a per-request `reasoning_n` (measured 2026-09-17 — there is no such field in
# summary.timings), so a stream that reported reasoning tokens is caught too.
TAGS = ("<think>", "<thinking>", "<|thinking|>", "◁think▷")


def answer_head(req, n=64):
    out = []
    for t in req.get("tokens") or []:
        out.append(t.get("text", "") if isinstance(t, dict) else str(t))
        if sum(map(len, out)) >= n:
            break
    return "".join(out)[:n]


def check(path):
    try:
        tape = json.load(gzip.open(path))
    except Exception as e:  # noqa: BLE001 — an unreadable tape is a failed check, not a crash
        print(f"UNREADABLE {path}: {e}")
        return False
    s = tape.get("summary") or {}
    kw = ((s.get("template") or {}).get("template_kwargs")) or {}
    asked_off = str(kw.get("enable_thinking", "")).lower() == "false"
    if not asked_off:
        return True
    bad = []
    for i, r in enumerate(tape.get("requests") or []):
        head = answer_head(r)
        if any(tag in head for tag in TAGS):
            bad.append((i, head.replace("\n", "\\n")[:48]))
    reasoning = [(i, r.get("reasoning_n") or 0) for i, r in enumerate(tape.get("requests") or [])]
    reasoning = [(i, n) for i, n in reasoning if n]
    if bad:
        print(f"THOUGHT ANYWAY {path}: no-think was requested and {len(bad)} answer(s) open with a "
              f"thinking tag — e.g. stream {bad[0][0]}: {bad[0][1]!r}")
        print("  the server was probably started without --jinja, which drops chat_template_kwargs")
        return False
    if reasoning:
        print(f"THOUGHT ANYWAY {path}: no-think was requested and {len(reasoning)} stream(s) "
              f"reported reasoning tokens — e.g. stream {reasoning[0][0]}: {reasoning[0][1]}")
        return False
    return True


if __name__ == "__main__":
    paths = sys.argv[1:]
    if not paths:
        sys.exit(__doc__)
    ok = all(check(p) for p in paths)
    print("no-think honoured" if ok else "no-think NOT honoured", f"({len(paths)} tape(s))")
    sys.exit(0 if ok else 1)
