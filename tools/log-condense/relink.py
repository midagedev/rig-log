#!/usr/bin/env python3
"""Rewrite links to old per-experiment log files -> log/2026-09-DD.md#slug.
usage: relink.py <map.tsv> [--apply]   (dry run by default).
map.tsv: "<old file>\t<new target>" per line (log/moved.tsv has a header row, skipped).
Set CONDENSE_SRC_COMMIT so the `git show <commit>:log/...` source lines are not rewritten.
Skips .git, the old files themselves, and the frozen translation source in assets/."""
import os, re, sys
root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
here = os.path.dirname(os.path.abspath(__file__))
m = dict(l.rstrip("\n").split("\t") for l in open(sys.argv[1]) if l.strip() and not l.startswith("old_file\t"))
src = os.environ.get("CONDENSE_SRC_COMMIT", "c27c3a7")
# configs/ are verbatim copies of machine files (CLAUDE.md), so their comments keep old names.
skip = {"assets/translation-ladder-2026-09-18-source.md", "log/moved.tsv"}
pat = re.compile(r"(?<!" + re.escape(src) + r":log/)(2026-09-\d\d-[a-z0-9][a-z0-9.\-]*?\.md)(#[^)\s\"'>]*)?")
apply = "--apply" in sys.argv
total = 0
for dp, dns, fns in os.walk(root):
    dns[:] = [d for d in dns if d != ".git"]
    for fn in fns:
        p = os.path.join(dp, fn); rel = os.path.relpath(p, root)
        if rel in skip or rel.startswith(("configs/", "tools/log-condense/")) or (rel.startswith("log/") and fn in m): continue
        try: s = open(p, encoding="utf-8").read()
        except Exception: continue
        n = 0
        def rep(mo):
            global n
            old, frag = mo.group(1), mo.group(2)
            if old not in m: return mo.group(0)
            n += 1
            return m[old] if not frag else m[old]  # old fragments pointed inside a file that no longer exists; land on the section
        new = pat.sub(rep, s)
        if n:
            total += n; print(f"{n:4d} {rel}")
            if apply: open(p, "w", encoding="utf-8").write(new)
print("total", total, "(applied)" if apply else "(dry run)")
