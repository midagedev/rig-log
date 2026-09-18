#!/usr/bin/env python3
"""check-untranslated.py — English left inside a Korean sentence, still inflected.

Neither gate in this repo can see the defect this one is for. `check-translation.py` compares
structure, and an English word inside a paragraph changes no structure. `check-glossary.py`
asks whether the *agreed* terms came out in the agreed Korean, and this word is not on the
list. Measured 2026-09-18, Solar Open 2 on `docs/quiet-machine.md`, block 27:

    EN     A stale lease cost a peer a night
    ko     오래된 임대가 동료에게 하룻밤을 costing했다

Both gates pass that line. One reader found it by reading thirty-three blocks, which does not
scale to a hundred and thirty-four thousand words -- so it becomes a script.

What it looks for is an English run **conjugated as a Korean verb**, and only that. The first
version of this check flagged any Latin word welded to any Hangul and raised 75 findings on
four translations, of which one was real: `bash는`, `pid를` and `Python은` are how this repo
writes those words, and a gate that cries about them is a gate that gets switched off. A
**particle** on an English noun is correct Korean. A **predicate ending** on an English word is
the defect, because it means the model reached for the English verb and inflected it instead of
translating it. So the rule is narrow:

  - the Latin run is 3+ letters, no digits, no `_ - . /` inside;
  - it is followed with no space by 하/했/한/해/함 or 되/된/됐/됨 — verb morphology, not a particle;
  - it is not inside a code span, a fence or a link target;
  - it is not one of the short list of English verbs this repo really does conjugate.

    check-untranslated.py <translated.ko.md> [more.ko.md …]        # 0 clean, 1 findings

The list of exceptions is deliberately short and lives here rather than in a config: every
addition should be argued in a commit message, because a long exception list is how a gate
stops failing.
"""

import re
import sys

# Words that really are written this way in this repo's Korean and are not the defect: they are
# borrowed as verbs the way English borrows "sauté". Each one is here because it appeared in a
# translation the lead accepted, not because it looked plausible.
KEEP = {"exec", "assert", "escalate", "grep", "commit", "push", "merge", "mock", "mount",
        "parsing", "profiling", "pinning", "polling",
        # `spawn된 자식` — Opus wrote this and the lead kept it. It is the same shape as
        # `exec한다`: a verb that Korean engineering prose has borrowed whole, where the
        # Korean word (`생성된`) loses the distinction between spawn and fork that the
        # sentence is about. Added 2026-09-18 with that one example in hand.
        "spawn"}

LATIN = r"[A-Za-z][a-z]{2,}"
VERB = r"[하했한해함되된됐됨]"
PAT = re.compile(rf"(?<![A-Za-z0-9_./-])({LATIN})({VERB})")


def strip_code(text):
    """Blank out fences, inline spans and link targets so they cannot raise a finding."""
    text = re.sub(r"```.*?```", lambda m: " " * len(m.group(0)), text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", lambda m: " " * len(m.group(0)), text)
    text = re.sub(r"\]\([^)]*\)", lambda m: " " * len(m.group(0)), text)
    return text


def findings(text):
    out = []
    for line_no, line in enumerate(strip_code(text).splitlines(), 1):
        for m in PAT.finditer(line):
            word = m.group(1)
            if word.lower() in KEEP:
                continue
            out.append((line_no, word + m.group(2), line.strip()[:110]))
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__.strip().splitlines()[-1])
    bad = 0
    for path in sys.argv[1:]:
        f = findings(open(path, encoding="utf-8").read())
        for line_no, hit, ctx in f:
            print(f"FAIL {path}:{line_no}  an English word conjugated as Korean: {hit!r}\n     {ctx}")
        bad += len(f)
        if not f:
            print(f"ok   {path}")
    print(f"\n{bad} finding(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
