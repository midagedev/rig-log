#!/usr/bin/env python3
"""gpu-check-aer-gate.py — does the sale check call a link downclock an AER change?

The defect (measured 2026-09-17 on reseat-3090-1): REPORT.md compared the whole
aer-before/after snapshot, which carries `LnkSta:` as well as the error registers.
An idle card links at 2.5 GT/s and a just-finished burn at 16 GT/s — the GPU's own
downclocking, already investigated and struck as a non-finding on 2026-09-16 — so a
card with every error bit clear reported `PCIe AER registers unchanged | CHANGED |
CHECK`. On a sheet another person reads, a row that cries wolf on healthy hardware is
worse than no row: it trains the reader past the one case it exists for.

This asks the shipped source, not a copy: the two functions are lifted out of the
heredoc in tools/gpu-sale-check.sh, so reverting that script fails this gate.

    python3 tools/gpu-check-aer-gate.py

FAIL-first: against the whole-file comparison this replaced, case 1 is CHANGED.
"""
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "gpu-sale-check.sh"
text = SRC.read_text()
m = re.search(r"^def err_lines\(t\):.*?^aer_same = .*?$", text, re.S | re.M)
if not m:
    sys.exit(f"could not find the AER comparison in {SRC} — was it renamed?")
block = m.group(0)
ns = {}
exec(compile(re.sub(r"^aer_(changed|same) = .*$", "", block, flags=re.M), str(SRC), "exec"), ns)
err_lines, link_line = ns["err_lines"], ns["link_line"]


def compare(before, after):
    changed = [f"{b} -> {a}" for b, a in zip(err_lines(before), err_lines(after)) if b != a]
    same = not changed and len(err_lines(before)) == len(err_lines(after))
    return same, changed


CLEAR_U = "\t\tUESta:\tDLP- SDES- TLP- FCP- CmpltTO- CmpltAbrt- UnxCmplt- RxOF- MalfTLP- ECRC- UnsupReq- ACSViol-"
CLEAR_C = "\t\tCESta:\tRxErr- BadTLP- BadDLLP- Rollover- Timeout- AdvNonFatalErr-"
DIRTY_C = "\t\tCESta:\tRxErr- BadTLP+ BadDLLP- Rollover- Timeout- AdvNonFatalErr-"


def snap(speed, cesta=CLEAR_C):
    return f"## 0000:41:00.0\n\t\tLnkSta:\tSpeed {speed}, Width x16\n{CLEAR_U}\n{cesta}\n"


CASES = [
    (snap("2.5GT/s (downgraded)"), snap("16GT/s"), True,
     "the real reseat-3090-1 shape: idle link before, warm link after, every error bit clear"),
    (snap("16GT/s"), snap("16GT/s", DIRTY_C), False,
     "a corrected error actually appears — the case the row exists for"),
    (snap("2.5GT/s (downgraded)"), snap("16GT/s", DIRTY_C), False,
     "link moved AND an error appeared: still a change, and not because of the link"),
    (snap("16GT/s"), snap("16GT/s"), True, "nothing moved at all"),
]

bad = 0
for before, after, want_same, why in CASES:
    same, changed = compare(before, after)
    ok = same == want_same
    bad += not ok
    verdict = "unchanged" if same else "; ".join(changed)
    print(f"{'ok  ' if ok else 'MISS'}  {link_line(before)} -> {link_line(after)}  =>  {verdict}\n      {why}")

# the row must also NAME what moved, or the reader has to ssh in and diff by hand (which is
# exactly what this round had to do)
_, changed = compare(snap("16GT/s"), snap("16GT/s", DIRTY_C))
if not changed or "BadTLP+" not in changed[0]:
    print("MISS  the changed row does not name the bit that moved"); bad += 1
else:
    print("ok    the changed row names the bit that moved")

print(f"\n{len(CASES) + 1 - bad}/{len(CASES) + 1} cases")
sys.exit(1 if bad else 0)
