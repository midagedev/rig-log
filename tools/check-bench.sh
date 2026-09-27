#!/bin/bash
# The bench page's freshness check: fails when docs/bloomery-bench.md is not what
# tools/bench/render.py produces from data/bloomery-bench.tsv and data/bloomery-bench-seed.tsv,
# when a seed value is not stated in its anchored log section (outside strike-through) or that
# section changed since the row was checked, or when a ledger row's anchor is not in log/.
# Mac only; reads nothing outside this repository.
#
#   tools/check-bench.sh               # the check
#   tools/check-bench.sh --self-test   # FAIL-first: a copy of the repository's bench files, mangled
#                                      # five ways, each must fail; the clean copy must pass
set -u
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

if [ "${1:-}" != --self-test ]; then
  [ $# -eq 0 ] || { echo "usage: $0 [--self-test]" >&2; exit 64; }
  exec python3 "$ROOT/tools/bench/render.py" --check --root "$ROOT"
fi

TMP=$(mktemp -d "${TMPDIR:-/tmp}/check-bench.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
fresh() {
  rm -rf "$TMP/r"
  mkdir -p "$TMP/r/docs" "$TMP/r/tools"
  cp -R "$ROOT/log" "$ROOT/data" "$TMP/r/"
  cp -R "$ROOT/tools/bench" "$TMP/r/tools/"
  cp "$ROOT/docs/bloomery-bench.md" "$TMP/r/docs/"
}
check() { python3 "$TMP/r/tools/bench/render.py" --check --root "$TMP/r" > "$TMP/out" 2>&1; }
# mangle NAME: rewrite one file of the copy the named way, found by structure rather than by
# today's values; a mangle that changes nothing is refused, so no case passes unexercised.
mangle() {
  python3 - "$TMP/r" "$1" << 'PY'
import re, sys
root, name = sys.argv[1], sys.argv[2]

def bump(num):  # a number with its last digit changed
    return num[:-1] + str((int(num[-1]) + 1) % 10)

def first_row(path):
    lines = open(path, encoding="utf-8").read().split("\n")
    return lines, lines[0].split("\t"), lines[1].split("\t")

if name == "page":
    path = root + "/docs/bloomery-bench.md"
    s = open(path, encoding="utf-8").read()
    i = s.index("## Latest")
    t = s[:i] + re.sub(r"\| ([0-9][0-9,]*(\.[0-9]+)?) \|", lambda m: f"| {bump(m.group(1))} |", s[i:], count=1)
elif name == "section":
    _, head, row = first_row(root + "/data/bloomery-bench-seed.tsv")
    rel, slug = row[head.index("anchor")].split("#")
    path = root + "/" + rel
    s = open(path, encoding="utf-8").read()
    tag = f'<a name="{slug}"></a>'
    t = s.replace(tag, tag + "\n(edited)", 1)
else:
    path = root + ("/data/bloomery-bench-seed.tsv" if name == "seed-value" else "/data/bloomery-bench.tsv")
    s = open(path, encoding="utf-8").read()
    lines, head, row = first_row(path)
    if name == "ledger-anchor":
        row[head.index("anchor")] += "-gone"
    else:
        k = head.index("value")
        # the seed: a digit the section does not state; the ledger: the leading digit, so the
        # change survives the page's rounding
        row[k] = "|".join(bump(v) if name == "seed-value" else str((int(v[0]) % 9) + 1) + v[1:]
                          for v in row[k].split("|"))
    lines[1] = "\t".join(row)
    t = "\n".join(lines)
if t == s:
    sys.exit(f"mangle {name}: changed nothing")
open(path, "w", encoding="utf-8").write(t)
PY
}

bad=0
fresh
if check; then
  echo "self-test: the repository's bench files pass as they are"
else
  echo "SELF-TEST BROKEN: the unmangled copy fails:"
  cat "$TMP/out"
  exit 1
fi
case_() {
  local name=$1 how=$2 needle=$3
  fresh
  if ! mangle "$how"; then
    echo "  ?? $name: not exercised"
    bad=$((bad + 1))
    return
  fi
  if check; then
    echo "  NOT CAUGHT — $name"
    bad=$((bad + 1))
  elif grep -q -- "$needle" "$TMP/out"; then
    echo "  FAIL as required — $name: $(grep -m1 -- "$needle" "$TMP/out" | cut -c1-170)"
  else
    echo "  CAUGHT FOR ANOTHER REASON — $name: $(head -1 "$TMP/out")"
    bad=$((bad + 1))
  fi
}
case_ "a number in the page edited by hand" page "is not what render.py produces"
case_ "a seed value with a wrong digit" seed-value "is not stated in"
case_ "the section under a seed row edited" section "changed since the row was checked"
case_ "a ledger row whose anchor is not in log/" ledger-anchor 'no `<a name='
case_ "a ledger value changed without rendering again" ledger-value "is not what render.py produces"
echo "self-test: $([ $bad -eq 0 ] && echo 'all mangles caught' || echo "$bad not caught")"
[ $bad -eq 0 ]
