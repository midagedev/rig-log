#!/usr/bin/env python3
"""check-glossary.py — did the translation use the words it was told to use?

The third axis, and the one that decides whether fifty translated files can sit next
to each other. Measured 2026-09-18: two runs of the same model on the same file,
differing by 2 % of the prompt, disagreed about the glossary from the first
paragraph -- one wrote 임대 for `lease` throughout and the other left `lease` in
English throughout. Both are fluent and neither is wrong on its own; together they
are a corpus that uses two words for the thing the lease file is.

This is deliberately a document-level count and not a sentence alignment. For each
term the source actually uses, two questions: does the agreed Korean form appear at
all, and does the bare English word still appear in the Korean prose. Code fences
and inline-code spans are stripped first, because `lease.sh` and `--lazy-mode` are
not leakage -- they are supposed to stay exactly as they are.

    check-glossary.py <source.md> <translated.md> [--json report.json]

A term the source never uses is not scored. The denominator is what was applicable,
so a short document and a long one are comparable.
"""

import argparse
import json
import re
import sys

# The same table translate-md.py puts in the prompt. When one changes, both change.
TRANSLATE = [
    ("lease",        r"\blease(s|d)?\b",            ["임대"]),
    ("witness",      r"\bwitness(es)?\b",           ["증인"]),
    ("gate",         r"\bgate(s|d)?\b",             ["게이트"]),
    ("harness",      r"\bharness(es)?\b",           ["하네스"]),
    ("delegate",     r"\bdelegate(s|d)?\b",         ["위임"]),
    ("upstream",     r"\bupstream\b",               ["업스트림"]),
    ("entry",        r"\bentr(y|ies)\b",            ["엔트리"]),
    ("prose",        r"\bprose\b",                  ["산문"]),
    ("card",         r"\bcard(s)?\b",               ["카드"]),
    ("board",        r"\bboard(s)?\b",              ["보드"]),
    ("slot",         r"\bslot(s)?\b",               ["슬롯"]),
    ("run (a run)",  r"\brun(s)?\b",                ["런"]),
    ("claim",        r"\bclaim(s|ed)?\b",           ["주장"]),
    ("measured",     r"\bmeasured\b",               ["실측", "측정"]),
]

# Terms the glossary says to leave in English. Here the failure is the opposite one:
# a translation that helpfully renders them has broken a rule just as surely.
KEEP = [
    ("load average", r"load average",  r"load average"),
    ("prefill",      r"\bprefill\b",   r"prefill"),
    ("decode",       r"\bdecode\b",    r"decode"),
]


def latin_bounded(pat):
    """`\\b` does not do what it looks like it does on a Korean line.

    Measured 2026-09-18, on this file's own first output: the check reported three
    surviving `lease` in a document that leaks it a dozen times, because Hangul is a
    word character to Python's `re`, so `lease는` has no word boundary after `lease`
    and `\\bleaseP\\b` never matched. Every leakage count taken with a trailing `\\b`
    against Korean prose is an undercount. The boundary that is meant here is "not
    another Latin letter", which is what these lookarounds say.
    """
    return "(?<![A-Za-z0-9_])" + pat.replace(r"\b", "") + "(?![A-Za-z0-9_])"


def prose_only(text):
    """Strip fenced blocks and inline-code spans: what is left is what was translated."""
    out, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        m = re.match(r"^\s*(`{3,}|~{3,})", lines[i])
        if m:
            mark = m.group(1)
            i += 1
            while i < len(lines) and not re.match(rf"^\s*{mark[0]}{{{len(mark)},}}\s*$", lines[i]):
                i += 1
            i += 1
            continue
        out.append(lines[i])
        i += 1
    return re.sub(r"`[^`\n]+`", " ", "\n".join(out))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("source")
    p.add_argument("translated")
    p.add_argument("--json")
    a = p.parse_args()

    src = prose_only(open(a.source, encoding="utf-8").read())
    dst = prose_only(open(a.translated, encoding="utf-8").read())

    rows, applicable, passed = [], 0, 0
    for name, pat, korean in TRANSLATE:
        pat = latin_bounded(pat)
        n_src = len(re.findall(pat, src, re.I))
        if not n_src:
            continue
        applicable += 1
        leak = len(re.findall(pat, dst, re.I))
        has = sum(dst.count(k) for k in korean)
        # A fraction, not a flag. Measured 2026-09-18: the binary form scored 80 % for a
        # run that wrote 임대 seventeen times with two parenthetical glosses, and 80 % for
        # a run that left `lease` in English from end to end -- which are the two outcomes
        # this check exists to tell apart. The share of the term's occurrences that came
        # out in the agreed word does tell them apart: 0.89 against 0.00.
        score = has / (has + leak) if (has + leak) else 0.0
        ok = leak == 0 and has > 0
        passed += score
        rows.append({"term": name, "kind": "translate", "in_source": n_src,
                     "korean_hits": has, "english_left": leak,
                     "score": round(score, 3), "ok": ok})

    for name, pat, want in KEEP:
        n_src = len(re.findall(pat, src, re.I))
        if not n_src:
            continue
        applicable += 1
        kept = len(re.findall(want, dst, re.I))
        ok = kept > 0
        passed += 1.0 if ok else 0.0
        rows.append({"term": name, "kind": "keep english", "in_source": n_src,
                     "korean_hits": None, "english_left": kept,
                     "score": 1.0 if ok else 0.0, "ok": ok})

    for r in rows:
        mark = "ok  " if r["ok"] else "MISS"
        if r["kind"] == "translate":
            print(f"{mark} {r['term']:<14} source {r['in_source']:>3}   "
                  f"korean {r['korean_hits']:>3}   english left {r['english_left']:>3}"
                  f"   score {r['score']:.2f}")
        else:
            print(f"{mark} {r['term']:<14} source {r['in_source']:>3}   keep english: "
                  f"{r['english_left']:>3} kept")
    pct = 100.0 * passed / applicable if applicable else 0.0
    clean = sum(1 for r in rows if r["ok"])
    print(f"\nglossary adherence {pct:.0f}%  ({clean}/{applicable} terms with no English left at all)")
    if a.json:
        open(a.json, "w", encoding="utf-8").write(json.dumps(
            {"passed": passed, "applicable": applicable, "pct": round(pct, 1), "terms": rows},
            ensure_ascii=False, indent=2) + "\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
