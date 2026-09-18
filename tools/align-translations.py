#!/usr/bin/env python3
"""align-translations.py — one source block, every model's Korean, unlabelled.

Reading four translations end to end, one after another, is four passes over the same
argument and it anchors: by the third the reader knows which model is which and grades
the style rather than the content. Reading them *interleaved* is one pass, and it turns
the comparison into the instrument -- where every model renders a sentence the same way
there is usually nothing to find, and where they disagree is exactly where the source
said something that is easy to get wrong.

The labels are shuffled and the key is written to a separate file, so the reader does
not know which column is the 100 GB model until the scores are in.

    align-translations.py <source.md> <a.ko.md> <b.ko.md> … --out view.md --key key.json

Blocks are aligned by index, which only means anything when check-translation.py's block
count is clean for every file; the script refuses otherwise rather than aligning
paragraphs that are not the same paragraph.
"""

import argparse
import json
import random
import re
import sys

FENCE = "\x00FENCE\x00"


def blocks(text):
    out, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        m = re.match(r"^\s*(`{3,}|~{3,})", lines[i])
        if m:
            mark = m.group(1)
            i += 1
            while i < len(lines) and not re.match(rf"^\s*{mark[0]}{{{len(mark)},}}\s*$", lines[i]):
                i += 1
            i += 1
            out.append(FENCE)
            continue
        out.append(lines[i])
        i += 1
    return [b.strip() for b in re.split(r"\n\s*\n", "\n".join(out).strip()) if b.strip()]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("source")
    p.add_argument("translations", nargs="+")
    p.add_argument("--out", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--seed", type=int, default=None)
    a = p.parse_args()

    src = blocks(open(a.source, encoding="utf-8").read())
    cols = []
    for path in a.translations:
        b = blocks(open(path, encoding="utf-8").read())
        if len(b) != len(src):
            sys.exit(f"{path}: {len(b)} blocks against the source's {len(src)} — "
                     f"run check-translation.py first; these are not the same paragraphs")
        cols.append((path, b))

    # The alphabet used to stop at H, and `zip` truncates without complaining, so asking for ten
    # columns produced eight and a header that said ten. A blind view that quietly omits a model
    # is worse than one that refuses: the reader scores the nine they can see and records a
    # number for the tenth. Measured 2026-09-18, on the sitting that was meant to put GLM
    # alongside the rest of the ladder. Assert rather than truncate.
    ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"        # no I and no O next to a shuffled label
    if len(cols) > len(ALPHABET):
        sys.exit(f"{len(cols)} translations, {len(ALPHABET)} labels available")
    letters = list(ALPHABET)[:len(cols)]
    order = letters[:]
    random.Random(a.seed).shuffle(order)
    key = {letter: path for letter, (path, _) in zip(order, cols)}

    with open(a.out, "w", encoding="utf-8") as f:
        f.write(f"# {len(src)} blocks, {len(cols)} translations, labels shuffled\n\n")
        f.write("Read each block's source, then every version of it. A rendering every "
                "column shares is rarely the defect; a rendering one column alone has is "
                "where to look.\n\n")
        for n, s in enumerate(src, 1):
            if s == FENCE:
                continue
            f.write(f"\n---\n\n## block {n}\n\n**EN** {s}\n\n")
            assert len(order) == len(cols), f"{len(order)} labels for {len(cols)} columns"
            for letter, (_, b) in zip(order, cols):
                f.write(f"**{letter}** {b[n - 1]}\n\n")
    open(a.key, "w", encoding="utf-8").write(json.dumps(key, indent=2) + "\n")
    print(f"{a.out}: {len(src)} blocks, columns {' '.join(sorted(key))}")


if __name__ == "__main__":
    main()
