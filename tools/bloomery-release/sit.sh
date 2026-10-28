#!/usr/bin/env bash
# One bloomery release sitting, driven from the lead's Mac: the cells go to the box, `just release-sitting` runs them in
# one hold on one binary, and the verdict and the tapes come back with the two tables the release notes carry.
#
#   sit.sh <version> [--binary tree|portable] [--cells FILE] [--tree DIR] [--keep-going] [--dry-run]
#
#   <version>      the release, e.g. 0.3.11: names the tarball (bloomery-<version>-linux-x86_64-cuda-sm86.tar.gz in the
#                  box tree's target/release-dist/), the prediction card (docs/cards/rel0311-headline.card, kind
#                  baseline, written before the sitting: the version without its dots, as the earlier cards are) and
#                  the output directory (~/.cache/bloomery/rel0311/)
#   --binary       portable (default): the release's verdict, the tarball's own bloomery-serve. tree: an iteration's,
#                  the tree's target/release build, marked stage=tree, never a release number
#   --cells FILE   default: cells.tsv beside this script; copy and edit it per release (its header names the columns)
#   --tree DIR     the release tree on this Mac (default: the current directory); it must be synced by `tools/box.sh`
#                  to the box's directory of the same name, where `just release-build` made the tarball
#   --keep-going   run the round's other cells after a red one (tools/release/sitting.sh's flag)
#   --dry-run      the sitting's plan and predicted wall (the cells are sent; no hold goes up, nothing is fetched)
#
# The box is BLOOMERY_BOX (a ssh name, as tools/release/publish.sh reads it; required: no host is named here) and its
# directory BLOOMERY_REMOTE (default ~/repo/<the tree's name>). BLOOMERY_HOLD_OWNER (default rel) owns the hold on both
# sides: this call passes it, and nothing else on the box starts until the sitting ends.
#
# Output, in ~/.cache/bloomery/rel<version without dots>/: sitting-<binary>.log (the sitting's whole output), <verdict>.sitting
# (the verdict tools/release/publish.sh reads from the box) and <verdict>.sitting.d/ (each call's log and every
# server's session directory, the tapes among them). Exit: the sitting's (0 green, 1 red, 75 the box is busy).
set -uo pipefail

usage() {
  echo "usage: sit.sh <version> [--binary tree|portable] [--cells FILE] [--tree DIR] [--keep-going] [--dry-run]" >&2
}
die() {
  echo "sit.sh: $2" >&2
  exit "$1"
}

VERSION=${1:-}
[ $# -eq 0 ] || shift
STAGE=portable CELLS=$(cd "$(dirname "$0")" && pwd)/cells.tsv TREE=$PWD DRY=0 EXTRA=()
while [ $# -gt 0 ]; do
  case $1 in
    --binary | --cells | --tree)
      [ $# -ge 2 ] || { usage; die 64 "$1 needs a value"; }
      case $1 in
        --binary) STAGE=$2 ;;
        --cells) CELLS=$2 ;;
        --tree) TREE=$2 ;;
      esac
      shift 2
      ;;
    --keep-going) EXTRA+=(--keep-going); shift ;;
    --dry-run) DRY=1; EXTRA+=(--dry-run); shift ;;
    *) usage; die 64 "unknown argument '$1'" ;;
  esac
done
[[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { usage; die 64 "the version is MAJOR.MINOR.PATCH, got '$VERSION'"; }
case $STAGE in tree | portable) ;; *) die 64 "--binary is tree or portable, got '$STAGE'" ;; esac
[ -r "$CELLS" ] || die 66 "no cells file at $CELLS"
[ -f "$TREE/tools/release/sitting.sh" ] || die 66 "$TREE holds no tools/release/sitting.sh: run this in the release tree or name it with --tree"
[ -n "${BLOOMERY_BOX:-}" ] || die 64 "BLOOMERY_BOX is unset: it names the box, as for tools/release/publish.sh"
BOX=$BLOOMERY_BOX
TREE=$(cd "$TREE" && pwd)
REMOTE=${BLOOMERY_REMOTE:-"~/repo/$(basename "$TREE")"}
NAME=bloomery-$VERSION-linux-x86_64-cuda-sm86
TAG=rel${VERSION//./}
CARD=docs/cards/$TAG-headline.card
[ -f "$TREE/$CARD" ] || die 66 "no $CARD in $TREE: the sitting's prediction card (kind baseline) is written before the sitting"
OUT=$HOME/.cache/bloomery/$TAG
mkdir -p "$OUT" || die 73 "cannot make $OUT"
export BLOOMERY_HOLD_OWNER=${BLOOMERY_HOLD_OWNER:-rel}
case " ${BLOOMERY_BOX_ENV:-} " in
  *" BLOOMERY_LEASE_CARD="*) ;;
  *) export BLOOMERY_BOX_ENV="${BLOOMERY_BOX_ENV:+$BLOOMERY_BOX_ENV }BLOOMERY_LEASE_CARD=$CARD" ;;
esac

RCELLS=target/release-dist/cells-$VERSION.tsv
# The directory exists after `just release-build`; a tree stage may be the first call. The cells go beside the tarball.
(cd "$TREE" && bash tools/box.sh 'mkdir -p target/release-dist') || die $? "tools/box.sh could not make target/release-dist on the box"
scp -q "$CELLS" "$BOX:$REMOTE/$RCELLS" || die 74 "cannot send $CELLS to $BOX:$REMOTE/$RCELLS"
ARGS=(--binary "$STAGE")
[ "$STAGE" != portable ] || ARGS+=(--tarball "target/release-dist/$NAME.tar.gz")
LOG=$OUT/sitting-$STAGE.log
(cd "$TREE" && just release-sitting "$VERSION" "$RCELLS" "${ARGS[@]}" ${EXTRA[@]+"${EXTRA[@]}"}) 2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}
[ "$DRY" = 0 ] || exit "$RC"

VERDICT=$(sed -n 's/^sitting: verdict //p' "$LOG" | tail -n 1)
WORKDIR=$(sed -n 's/^sitting: work //p' "$LOG" | tail -n 1)
if [ -z "$VERDICT" ]; then
  echo "sit.sh: the sitting printed no verdict path (exit $RC): nothing to fetch; $LOG has what it said" >&2
  exit "$RC"
fi
scp -q "$BOX:$VERDICT" "$OUT/" || die 74 "cannot fetch the verdict $BOX:$VERDICT"
[ -z "$WORKDIR" ] || scp -qr "$BOX:$WORKDIR" "$OUT/" || echo "sit.sh: cannot fetch the work directory $BOX:$WORKDIR (the verdict is in $OUT)" >&2
LOCAL=$OUT/$(basename "$VERDICT")
echo
echo "sit.sh: verdict $LOCAL (exit $RC)"

# The notes' two tables from the verdict: the headline rows (the means over both rounds of each cell's arms, [cold] rows out)
# and the user-facing pass (round 1's first-request checks).
python3 -I - "$LOCAL" << 'PY'
import re
import sys

path = sys.argv[1]
lines = open(path, errors="replace").read().split("\n")
head = {}
for ln in lines:
    if not ln.strip():
        break
    if "=" in ln:
        k, v = ln.split("=", 1)
        head[k] = v
cells = {}
blocks = []
cur = None
for ln in lines:
    m = re.match(r"^cell (\d+): (\S+) place=(\S+) cards=(\S+) ctx=(\S+) D=(\S+) checks=(.*)$", ln)
    if m:
        cells[int(m.group(1))] = dict(zip(("prof", "place", "cards", "ctx", "deps", "checks"), m.groups()[1:]))
        continue
    m = re.match(r"^== round (\d+) cell (\d+) rc=(\d+) result=(\S+)", ln)
    if m:
        cur = ("run", int(m.group(1)), int(m.group(2)), m.group(4), [])
        blocks.append(cur)
        continue
    m = re.match(r"^== cell (\d+) means", ln)
    if m:
        cur = ("mean", 0, int(m.group(1)), "", [])
        blocks.append(cur)
        continue
    if ln.startswith("== "):
        cur = None
        continue
    if cur is not None:
        cur[4].append(ln)


def model(c):
    prof = c["prof"]
    return prof.split("=", 1)[1].rstrip("/").rsplit("/", 1)[-1] if "=" in prof else prof


print(f"stage={head.get('stage')} result={head.get('result')} binary sha256 {head.get('binary_sha256', '')[:12]} "
      f"({head.get('binary_version', '')}); tarball {head.get('tarball', '-')}")
print()
print("Headline rows (tok/s, mean of the warm rows over both rounds; cards, place and context as the plan picked them)")
print()
print("| model file | cards | place | ctx | D | decode tok/s | pp tok/s | rows warm/all |")
print("|---|---|---|---|---|---|---|---|")
for kind, _, idx, _, body in blocks:
    if kind != "mean" or idx not in cells:
        continue
    for ln in body:
        m = re.match(r"^mean \S+/place=(\S+)/ctx=(\d+) D=(\d+) \| (.*)$", ln)
        if not m:
            continue
        place, ctx, dep, rest = m.groups()
        tg = re.search(r"tg ([\d.]+) tok/s", rest)
        pp = re.search(r"pp ([\d.]+) tok/s", rest)
        n = re.search(r"\[cold (\d+)/(\d+)\]", rest)
        warm = f"{int(n.group(2)) - int(n.group(1))}/{n.group(2)}" if n else "?"
        print(f"| {model(cells[idx])} | {cells[idx]['cards']} | {place} | {ctx} | {dep} | "
              f"{tg.group(1) if tg else '-'} | {pp.group(1) if pp else '-'} | {warm} |")
print()
print("User-facing pass (round 1, the first requests on a fresh server at the serving defaults)")
print()
names = []
rows = []
for kind, rnd, idx, res, body in blocks:
    if kind != "run" or rnd != 1 or idx not in cells:
        continue
    chk = {}
    for ln in body:
        m = re.match(r"^check (\w+): (PASS|FAIL|SKIP)", ln)
        if m:
            chk[m.group(1)] = m.group(2)
            if m.group(1) not in names:
                names.append(m.group(1))
    rows.append((idx, res, chk))
print("| model file | cards | place | run | " + " | ".join(names) + " |")
print("|---|---|---|---|" + "---|" * len(names))
for idx, res, chk in rows:
    c = cells[idx]
    print(f"| {model(c)} | {c['cards']} | {c['place']} | {res} | " + " | ".join(chk.get(n, "-") for n in names) + " |")
PY
exit "$RC"
