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
"""
import gzip
import json
import sys

# The tags a reasoning model opens a thinking block with, as they appear in the answer text.
# mistral.rs streams reasoning in its own `reasoning_content` field instead, which toktape
# counts as thinking tokens, so a tape whose summary reports thinking tokens is caught too.
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
    thinking_n = (s.get("timings") or {}).get("thinking_n") or 0
    if bad:
        print(f"THOUGHT ANYWAY {path}: no-think was requested and {len(bad)} answer(s) open with a "
              f"thinking tag — e.g. stream {bad[0][0]}: {bad[0][1]!r}")
        print("  the server was probably started without --jinja, which drops chat_template_kwargs")
        return False
    if thinking_n:
        print(f"THOUGHT ANYWAY {path}: no-think was requested and the tape reports "
              f"{thinking_n} thinking tokens")
        return False
    return True


if __name__ == "__main__":
    paths = sys.argv[1:]
    if not paths:
        sys.exit(__doc__)
    ok = all(check(p) for p in paths)
    print("no-think honoured" if ok else "no-think NOT honoured", f"({len(paths)} tape(s))")
    sys.exit(0 if ok else 1)
