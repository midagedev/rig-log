#!/usr/bin/env python3
"""check-translation.py — what a translation is not allowed to change.

A fluent Korean paragraph that inverted a negation reads perfectly and is worth
nothing, and no script can see that; only a reader can. What a script *can* see is
everything a translation had no business touching, and on this repo that list is
exactly the list of things a claim is made of: the numbers, the commands, the file
paths, the links, the shape of the tables. So this gate does not grade Korean. It
asserts that the measured content survived the trip, and leaves the prose to the
reader — which is the same division of labour as every other gate here.

    check-translation.py <source.md> <translated.md>          # 0 pass, 1 fail
    check-translation.py --json report.json <src> <dst>
    check-translation.py --self-test <source.md>              # FAIL-first proof

The self-test is not decoration. A gate that has never been seen to fail is a gate
whose passing means nothing, so `--self-test` mangles a copy of the source six ways
-- drop a table row, change one digit, retitle a link target, edit a line inside a
code fence, delete a paragraph, drop a heading -- and requires a FAIL from each.
Run it whenever this file is touched.
"""

import argparse
import json
import re
import sys
from collections import Counter

FENCE = "\x00FENCE\x00"


def split_fences(text):
    """Return (text with each fenced block replaced by one marker line, [bodies])."""
    out, bodies, i = [], [], 0
    lines = text.split("\n")
    while i < len(lines):
        m = re.match(r"^(\s*)(`{3,}|~{3,})(.*)$", lines[i])
        if m:
            indent, mark = m.group(1), m.group(2)
            body, i = [], i + 1
            while i < len(lines) and not re.match(rf"^\s*{mark[0]}{{{len(mark)},}}\s*$", lines[i]):
                body.append(lines[i])
                i += 1
            i += 1
            bodies.append("\n".join(body))
            out.append(indent + FENCE)
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out), bodies


def headings(text):
    return [len(m.group(1)) for m in re.finditer(r"^(#{1,6})\s", text, re.M)]


def tables(text):
    """(row count, column count) per contiguous run of pipe-leading lines."""
    shapes, run = [], []
    for line in text.split("\n"):
        if line.strip().startswith("|"):
            run.append(line)
        else:
            if run:
                shapes.append((len(run), run[0].count("|")))
            run = []
    if run:
        shapes.append((len(run), run[0].count("|")))
    return shapes


def blocks(text):
    return [b for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]


def inline_code(text):
    return Counter(re.findall(r"`([^`\n]+)`", text))


def link_targets(text):
    inline = re.findall(r"\]\(([^)\s]+)", text)
    refs = re.findall(r"^\s*\[[^\]]+\]:\s*(\S+)", text, re.M)
    return Counter(inline + refs)


def numbers(text):
    """Numeric tokens, with trailing punctuation off.

    Measured 2026-09-18 on the first real output: the raw `\\d[\\d.,:]*` form counted
    `00:00:01,` and `06:27.` as different tokens from `00:00:01` and `06:27`, because
    Korean does not carry the English comma or the sentence period into the same
    position. Those were the gate's own defect, not the translation's.
    """
    return Counter(t.rstrip(".,:") for t in re.findall(r"\d[\d.,:]*", text))


def strikes(text):
    return len(re.findall(r"~~", text))


def compare(src, dst):
    """Every check, as (name, severity, ok, detail)."""
    s_txt, s_fences = split_fences(src)
    d_txt, d_fences = split_fences(dst)
    r = []

    ok = s_fences == d_fences
    detail = ""
    if not ok:
        if len(s_fences) != len(d_fences):
            detail = f"{len(s_fences)} fenced block(s) in the source, {len(d_fences)} in the translation"
        else:
            for n, (a, b) in enumerate(zip(s_fences, d_fences)):
                if a != b:
                    detail = f"block {n + 1} differs; first changed line:\n    - {_firstdiff(a, b)}"
                    break
    r.append(("code fences byte-identical", "FAIL", ok, detail))

    for name, fn in (("link targets", link_targets), ("inline code spans", inline_code)):
        a, b = fn(s_txt), fn(d_txt)
        ok = a == b
        r.append((name, "FAIL", ok, "" if ok else _counter_detail(a, b)))

    # A number the source had and the translation does not is a measurement that fell out,
    # and that is the whole reason this gate exists. A number the translation has and the
    # source does not is usually the opposite of a defect: measured 2026-09-18, the first
    # output turned "a nine-minute load and a fifteen-minute sweep" into "9분 로딩과 15분
    # 스윕", which is how Korean writes it. So the two directions are separate checks and
    # only the losing direction fails. **This does not weaken the digit check**: changing a
    # digit removes the old token as well as adding the new one, so the self-test's "one
    # digit changed" mangle is still caught by the FAIL half -- which is why the self-test
    # is run after this split and not before.
    a, b = numbers(s_txt), numbers(d_txt)
    lost, extra = a - b, b - a
    r.append(("numbers kept", "FAIL", not lost,
              "" if not lost else "lost: " + ", ".join(f"{k!r}\u00d7{v}" for k, v in sorted(lost.items())[:12])))
    r.append(("numbers added", "WARN", not extra,
              "" if not extra else "added: " + ", ".join(f"{k!r}\u00d7{v}" for k, v in sorted(extra.items())[:12])))

    a, b = headings(s_txt), headings(d_txt)
    r.append(("heading levels and order", "FAIL", a == b,
              "" if a == b else f"source {a}\n    translation {b}"))

    a, b = tables(s_txt), tables(d_txt)
    r.append(("table shapes (rows, columns)", "FAIL", a == b,
              "" if a == b else f"source {a}\n    translation {b}"))

    a, b = len(blocks(s_txt)), len(blocks(d_txt))
    r.append(("block count", "FAIL", a == b,
              "" if a == b else f"{a} blocks in the source, {b} in the translation"))

    a, b = strikes(s_txt), strikes(d_txt)
    r.append(("strike markers", "FAIL", a == b,
              "" if a == b else f"{a} '~~' in the source, {b} in the translation"))

    a = len(re.findall(r"\*\*", s_txt))
    b = len(re.findall(r"\*\*", d_txt))
    r.append(("bold markers", "WARN", a == b,
              "" if a == b else f"{a} '**' in the source, {b} in the translation"))
    return r


def _firstdiff(a, b):
    for x, y in zip(a.split("\n"), b.split("\n")):
        if x != y:
            return f"{x!r}\n    + {y!r}"
    return f"length {len(a)} vs {len(b)}"


def _counter_detail(a, b):
    missing = a - b
    extra = b - a
    bits = []
    if missing:
        bits.append("lost: " + ", ".join(f"{k!r}×{v}" for k, v in sorted(missing.items())[:12]))
    if extra:
        bits.append("added: " + ", ".join(f"{k!r}×{v}" for k, v in sorted(extra.items())[:12]))
    return "\n    ".join(bits)


MANGLES = [
    ("a table row dropped", lambda t: _drop_line(t, lambda l: l.strip().startswith("|"))),
    ("one digit changed", lambda t: re.sub(r"(\d)", lambda m: str((int(m.group(1)) + 1) % 10), t, count=1)),
    ("a link target rewritten", lambda t: re.sub(r"\]\(([^)\s]+)", "](CHANGED", t, count=1)),
    ("a line inside a code fence edited", _edit_fence := None),
    ("a paragraph deleted", lambda t: "\n\n".join(blocks(t)[:-2] + blocks(t)[-1:])),
    ("a heading dropped", lambda t: _drop_line(t, lambda l: l.startswith("#") and not l.startswith("# "))),
]


def _drop_line(text, pred):
    lines = text.split("\n")
    for i, l in enumerate(lines):
        if pred(l):
            return "\n".join(lines[:i] + lines[i + 1:])
    return text


def _fence_edit(text):
    t, bodies = split_fences(text)
    if not bodies:
        return text
    first = bodies[0].split("\n")[0]
    return text.replace(first, first + " # edited", 1)


MANGLES[3] = ("a line inside a code fence edited", _fence_edit)


def self_test(path):
    src = open(path, encoding="utf-8").read()
    clean = [c for c in compare(src, src) if c[1] == "FAIL" and not c[2]]
    if clean:
        print(f"SELF-TEST BROKEN: the source does not pass against itself ({clean})")
        return 1
    print(f"self-test on {path}: identical copy passes")
    bad = 0
    for name, fn in MANGLES:
        mangled = fn(src)
        if mangled == src:
            print(f"  ?? {name}: the mangle changed nothing — the gate was not exercised")
            bad += 1
            continue
        failed = [c[0] for c in compare(src, mangled) if c[1] == "FAIL" and not c[2]]
        if failed:
            print(f"  FAIL as required — {name}: caught by {', '.join(failed)}")
        else:
            print(f"  NOT CAUGHT — {name}")
            bad += 1
    print("self-test:", "all mangles caught" if not bad else f"{bad} not caught")
    return 1 if bad else 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("source")
    p.add_argument("translated", nargs="?")
    p.add_argument("--json", help="write the report here")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()

    if a.self_test:
        sys.exit(self_test(a.source))
    if not a.translated:
        p.error("give both files, or --self-test with one")

    src = open(a.source, encoding="utf-8").read()
    dst = open(a.translated, encoding="utf-8").read()
    rows = compare(src, dst)
    failed = 0
    for name, sev, ok, detail in rows:
        mark = "ok  " if ok else (sev + ("" if ok else ""))
        print(f"{mark:5} {name}")
        if not ok:
            if sev == "FAIL":
                failed += 1
            if detail:
                print("    " + detail)
    print(f"\n{len(rows) - sum(1 for r in rows if not r[2])}/{len(rows)} checks clean, {failed} FAIL")
    if a.json:
        open(a.json, "w", encoding="utf-8").write(json.dumps(
            [{"check": n, "severity": s, "ok": o, "detail": d} for n, s, o, d in rows],
            ensure_ascii=False, indent=2) + "\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
