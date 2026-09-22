#!/usr/bin/env python3
"""Gate for the log condensation round.

usage: check-condense.py <new day file> <old file> [<old file> ...]

env: CONDENSE_SRC_COMMIT (commit that still holds the old files; default c27c3a7),
     CONDENSE_CAP (max new/old byte ratio; default 0.22)

FAIL conditions (exit 1):
  - a number in the new file that appears in none of the old files (invented number)
  - an old file with no <a name="<slug>"></a> anchor + source line in the new file
  - a relative link whose target does not exist (day files log/2026-09-DD.md are allowed)
  - a link to an old per-experiment log filename (must use 2026-09-DD.md#slug)
  - an upstream issue/PR URL present in the old files but missing in the new one
  - an original ~~strikethrough~~ span missing verbatim, or a struck span not in the old files
  - new size > 22% of old total bytes
"""
import os, re, sys

SRC = os.environ.get("CONDENSE_SRC_COMMIT", "c27c3a7")

new_path, olds = sys.argv[1], sys.argv[2:]
new = open(new_path, encoding="utf-8").read()
old_texts = {p: open(p, encoding="utf-8").read() for p in olds}
old_all = "\n".join(old_texts.values())
fails = []

def nums(s):
    out = set()
    for m in re.finditer(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", s):
        out.add(m.group(0).replace(",", ""))
    return out

old_nums = nums(old_all)
# prose numbers only: drop source lines, anchors and link targets before extracting
prose = re.sub(r"git show " + re.escape(SRC) + r":\S+", "", new)
prose = re.sub(r'<a name="[^"]*"></a>', "", prose)
prose = re.sub(r"\]\([^)]*\)", "]", prose)
invented = sorted(n for n in nums(prose) if n not in old_nums)
if invented:
    fails.append(f"numbers not in any old file: {invented[:40]}")

for p in olds:
    slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", os.path.basename(p))[:-3]
    if f'<a name="{slug}"></a>' not in new:
        fails.append(f'missing anchor <a name="{slug}"></a> for {os.path.basename(p)}')
    src = f"git show {SRC}:log/{os.path.basename(p)}"
    if src not in new:
        fails.append(f"missing source line: {src}")

base = os.path.dirname(os.path.abspath(new_path))
for m in re.finditer(r"\]\(([^)\s]+)\)", new):
    t = m.group(1)
    if re.match(r"^[a-z]+:", t) or t.startswith("#"):
        continue
    path = t.split("#")[0]
    if re.search(r"2026-\d\d-\d\d-[^/]*\.md$", path) and os.path.exists(os.path.normpath(os.path.join(base, path))) is False:
        fails.append(f"link to old per-experiment filename: {t}")
        continue
    if re.search(r"(^|/)2026-\d\d-\d\d\.md$", path):
        continue
    if not os.path.exists(os.path.normpath(os.path.join(base, path))):
        fails.append(f"broken relative link: {t}")

up = set(re.findall(r"https://github\.com/[^\s)\]]+/(?:pull|issues)/\d+", old_all))
missing_up = sorted(u for u in up if u not in new)
if missing_up:
    fails.append(f"upstream URLs dropped: {missing_up}")

# strikethrough = the original author's own correction record. Every struck span in the
# old files must survive verbatim, and the new file may not strike anything the old ones did not.
norm = lambda t: re.sub(r"\s+", " ", t).strip()
old_spans = [norm(t) for t in re.findall(r"~~(.+?)~~", old_all, re.S)]
new_spans = [norm(t) for t in re.findall(r"~~(.+?)~~", new, re.S)]
old_strike, new_strike = len(old_spans), len(new_spans)
for t in old_spans:
    if t not in new_spans:
        fails.append(f"original strikethrough missing (must be verbatim): ~~{t[:70]}~~")
for t in new_spans:
    if t not in old_spans:
        fails.append(f"strikethrough not in any old file (do not invent or reword): ~~{t[:70]}~~")

ob, nb = len(old_all.encode()), len(new.encode())
ratio = nb / ob
cap = float(os.environ.get("CONDENSE_CAP", "0.22"))
if ratio > cap:
    fails.append(f"size {nb} B = {ratio:.1%} of old {ob} B (cap {cap:.0%})")

print(f"new {nb} B / old {ob} B = {ratio:.1%}; strikethrough old {old_strike} new {new_strike}; "
      f"anchors {len(olds)}; upstream URLs {len(up)}")
if fails:
    print("FAIL")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("PASS")
