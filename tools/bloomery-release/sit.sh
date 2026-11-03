#!/usr/bin/env bash
# One bloomery release sitting, driven from the lead's Mac: the cells go to the box, `just release-sitting` runs them in
# one hold on one binary, and the verdict and the tapes come back with the two tables the release notes carry.
#
#   sit.sh <version> [--binary tree|portable] [--cells FILE] [--tree DIR] [--keep-going] [--dry-run] [--no-build | --rebuild]
#   sit.sh --self-test
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
#   --dry-run      the sitting's plan and predicted wall (the cells are sent; no hold goes up, nothing is fetched, nothing is built)
#   --no-build     skip the archive builds below (the archives are on the box some other way)
#   --rebuild      build both archives whatever the box holds
#
# The builds. A portable sitting runs on the tarball of this tree's commit, and the release also ships the sm_120a archive, so
# before the hold goes up the box is asked for both x86-64 archives (target/release-dist, sm_86 and sm_120a) and the tree's
# `just release-build <version>` runs for each one that is absent or was built at another commit, the two at once (each archive
# builds in a target directory of its own, tools/release/build.sh). They run with no BLOOMERY_HOLD_OWNER, so any hold on the box
# makes them wait, and the sitting starts only after both have ended: a build never runs under the sitting's hold, and the
# sitting's first quiet look finds no compile. A build that fails ends sit.sh before any hold, naming the archive and its log.
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
  echo "usage: sit.sh <version> [--binary tree|portable] [--cells FILE] [--tree DIR] [--keep-going] [--dry-run] [--no-build | --rebuild] | --self-test" >&2
}
die() {
  echo "sit.sh: $2" >&2
  exit "$1"
}

# archive_commits <tree> <version>: one `<arch> <commit>` line for each x86-64 archive on the box (sm86, sm120a), the commit its
# VERSION file names, or `-` for an archive that is absent.
archive_commits() {
  (cd "$1" && bash tools/box.sh "for a in sm86 sm120a; do n=bloomery-$2-linux-x86_64-cuda-\$a; if [ -f target/release-dist/\$n.tar.gz ]; then echo \"\$a \$(tar -xzOf target/release-dist/\$n.tar.gz \$n/VERSION 2> /dev/null | sed -n 2p)\"; else echo \"\$a -\"; fi; done" 2> /dev/null) | grep -E '^(sm86|sm120a) ' || true
}

# run_builds <tree> <version> <out dir> <mode: auto|yes>: the archive builds, before any hold. An archive the box already holds
# at the tree's commit is kept unless mode is yes. The builds that remain run at once, each its own `just release-build`, with no
# BLOOMERY_HOLD_OWNER (any hold makes them wait), and every one is waited for (by the pid captured at its start) before this
# returns: 0 all built or kept, 1 a build failed (named, with its log).
run_builds() {
  local tree=$1 version=$2 out=$3 mode=$4 head have arch name todo=() pids=() names=() i failed=0
  head=$(git -C "$tree" rev-parse --short=12 HEAD) || { echo "sit.sh: cannot read the tree's HEAD in $tree" >&2; return 1; }
  have=$(archive_commits "$tree" "$version")
  for arch in sm_86 sm_120a; do
    name=${arch/_/}
    if [ "$mode" = auto ] && grep -qx "$name $head" <<< "$have"; then
      echo "sit.sh: [build] $arch: the box holds the $name archive at $head, kept"
    else
      todo+=("$arch")
    fi
  done
  [ ${#todo[@]} -gt 0 ] || return 0
  for arch in "${todo[@]}"; do
    echo "sit.sh: [build] $arch: just release-build $version at $head (log $out/build-$arch.log)"
    (cd "$tree" && env -u BLOOMERY_HOLD_OWNER BLOOMERY_ARCH="$arch" just release-build "$version") > "$out/build-$arch.log" 2>&1 &
    pids+=($!)
    names+=("$arch")
  done
  for i in "${!pids[@]}"; do
    if wait "${pids[$i]}"; then
      echo "sit.sh: [build] ${names[$i]}: done"
    else
      echo "sit.sh: [build] ${names[$i]}: failed (rc $?); the end of $out/build-${names[$i]}.log:" >&2
      tail -n 5 "$out/build-${names[$i]}.log" | sed 's/^/  /' >&2
      failed=1
    fi
  done
  return "$failed"
}

# self_test: sit.sh in a temporary tree against a fake box directory and stub `just`, `scp` and tools/box.sh (the stub box.sh runs its
# command in the fake directory): the archive builds start before the sitting, run at once, carry no hold owner, are all waited for
# and end before the sitting; archives at the tree's commit are kept; a failed build ends sit.sh before any hold. Each guard has a
# mutant of this script that its case must turn red.
self_test() {
  local t me head fails=0 cases=0 out rc
  me=$(cd "$(dirname "$0")" && pwd)/$(basename "$0")
  t=$(mktemp -d "${TMPDIR:-/tmp}/sit-test.XXXXXX") || return 70
  mkdir -p "$t/tree/tools/release" "$t/tree/docs/cards" "$t/box" "$t/bin" "$t/home"
  : > "$t/tree/tools/release/sitting.sh"
  : > "$t/tree/docs/cards/rel001-headline.card"
  printf '#!/bin/sh\ncd "$FAKE_BOX" && exec sh -c "$1"\n' > "$t/tree/tools/box.sh"
  cat > "$t/bin/just" << 'EOF'
#!/bin/sh
case "$1" in
  release-build)
    echo "build-start $BLOOMERY_ARCH hold=${BLOOMERY_HOLD_OWNER-unset}" >> "$STUB_LOG"
    sleep 1
    if [ "$BLOOMERY_ARCH" = "$STUB_FAIL" ]; then echo "stub: the build broke"; exit 3; fi
    echo "build-end $BLOOMERY_ARCH" >> "$STUB_LOG" ;;
  release-sitting)
    echo "sitting-start hold=${BLOOMERY_HOLD_OWNER-unset}" >> "$STUB_LOG" ;;
esac
EOF
  printf '#!/bin/sh\nexit 0\n' > "$t/bin/scp"
  chmod +x "$t/bin/just" "$t/bin/scp"
  printf 'x\n' > "$t/cells.tsv"
  git -C "$t/tree" init -q
  git -C "$t/tree" add -A
  git -C "$t/tree" -c user.name=selftest -c user.email=selftest@invalid commit -q -m tree
  head=$(git -C "$t/tree" rev-parse --short=12 HEAD)
  mk_archive() { # mk_archive <sm86|sm120a> <commit>: the archive on the fake box, its VERSION file naming the commit
    local n=bloomery-0.0.1-linux-x86_64-cuda-$1
    mkdir -p "$t/box/target/release-dist/$n"
    printf '0.0.1\n%s\n' "$2" > "$t/box/target/release-dist/$n/VERSION"
    tar -czf "$t/box/target/release-dist/$n.tar.gz" -C "$t/box/target/release-dist" "$n"
  }
  # run_sit <script> <fail arch or ''> <sit.sh args…>: a fresh log, the script run, $out and $rc
  run_sit() {
    local script=$1 fail=$2
    shift 2
    : > "$t/log"
    out=$(env PATH="$t/bin:$PATH" HOME="$t/home" BLOOMERY_BOX=fakebox BLOOMERY_REMOTE=/fake FAKE_BOX="$t/box" STUB_LOG="$t/log" STUB_FAIL="$fail" \
      bash "$script" 0.0.1 --cells "$t/cells.tsv" --tree "$t/tree" "$@" 2>&1) && rc=0 || rc=$?
  }
  # shape: "<starts at once|serial> <builds ended before the sitting|not> <starts>" from the stub's log
  shape() {
    awk '/^build-start/ { ns++; if (ns == 2) s2 = NR } /^build-end/ { if (!fe) fe = NR; le = NR } /^sitting-start/ { st = NR }
      END { printf "%s %s %d %s\n", (s2 && fe && s2 < fe) ? "parallel" : "not-parallel", (le && st && le < st) ? "before-sitting" : "not-before-sitting", ns + 0, st ? "sitting" : "no-sitting" }' "$t/log"
  }
  # all_cases <script> <loud>: the cases; BAD counts the red ones
  all_cases() {
    local script=$1 loud=$2 got
    BAD=0
    check() { # check <case> <want> <got>
      cases=$((cases + 1))
      if [ "$2" != "$3" ]; then
        [ "$loud" = 0 ] || echo "sit self-test: $1: want '$2', got '$3'; output: $out" >&2
        BAD=$((BAD + 1))
      fi
    }
    rm -rf "$t/box"; mkdir -p "$t/box/target/release-dist"
    run_sit "$script" ''
    check "an empty box: both archives build at once, then the sitting" "parallel before-sitting 2 sitting" "$(shape)"
    check "the builds carry no hold owner, the sitting has one" "build-start sm_120a hold=unset|build-start sm_86 hold=unset|sitting-start hold=rel" "$(grep -E '^(build-start|sitting-start)' "$t/log" | sort | tr '\n' '|' | sed 's/|$//')"
    run_sit "$script" sm_120a
    got=$(shape)
    check "a failed build: no sitting" "no-sitting" "${got##* }"
    check "a failed build ends sit.sh by name" "1 sit.sh: [build] sm_120a: failed" "$([ "$rc" != 0 ] && echo 1) $(grep -o 'sit.sh: \[build\] sm_120a: failed' <<< "$out" | head -n 1)"
    check "a failed build: the other one was still waited for" "build-end sm_86" "$(grep '^build-end' "$t/log")"
    rm -rf "$t/box"; mkdir -p "$t/box/target/release-dist"
    mk_archive sm86 "$head"
    run_sit "$script" ''
    check "an sm_86 archive at the tree's commit is kept" "build-start sm_120a hold=unset" "$(grep '^build-start' "$t/log")"
    rm -rf "$t/box"; mkdir -p "$t/box/target/release-dist"
    mk_archive sm86 deadbeef0000
    mk_archive sm120a "$head"
    run_sit "$script" ''
    check "an archive at another commit is rebuilt, the one at the tree's kept" "build-start sm_86 hold=unset" "$(grep '^build-start' "$t/log")"
    mk_archive sm86 "$head"
    run_sit "$script" ''
    check "both archives at the tree's commit: no build, the sitting runs" "parallel-less 0 sitting" "$(shape | sed 's/^not-parallel not-before-sitting/parallel-less/')"
    run_sit "$script" '' --rebuild
    check "--rebuild builds both whatever the box holds" "parallel before-sitting 2 sitting" "$(shape)"
    rm -rf "$t/box"; mkdir -p "$t/box/target/release-dist"
    run_sit "$script" '' --no-build
    check "--no-build builds nothing" "0 sitting" "$(shape | awk '{print $3, $4}')"
    run_sit "$script" '' --binary tree
    check "a tree stage builds no archive" "0 sitting" "$(shape | awk '{print $3, $4}')"
    run_sit "$script" '' --dry-run
    check "a dry run builds nothing" "0" "$(shape | awk '{print $3}')"
    return "$BAD"
  }
  # mutant <name> <old text> <new text>: this script with the first <old text> replaced; at least one case must go red. The text
  # for the main flow has a newline round it, which this self-test spells \n.
  mutant() {
    cp "$me" "$t/mutant.sh"
    python3 -I - "$t/mutant.sh" "$2" "$3" << 'PY' || { echo "sit self-test: mutant $1: the text to replace is not in the code" >&2; fails=$((fails + 1)); return 0; }
import sys

path, old, new = sys.argv[1:4]
s = open(path).read()
i = s.find(old)
if i < 0:
    sys.exit(1)
open(path, "w").write(s[:i] + new + s[i + len(old):])
PY
    if all_cases "$t/mutant.sh" 0; then
      echo "sit self-test: mutant $1 left every case green: the cases do not hold it" >&2
      fails=$((fails + 1))
    fi
    sleep 1.5 # a mutant's builds may outlive sit.sh
  }
  all_cases "$me" 1 || fails=$((fails + BAD))
  mutant "no build step" $'\n    run_builds "$TREE" "$VERSION" "$OUT" "$BUILD" || die 70' $'\n    : || die 70'
  mutant "builds under the hold owner" 'env -u BLOOMERY_HOLD_OWNER BLOOMERY_ARCH="$arch" just' 'env BLOOMERY_ARCH="$arch" just'
  mutant "the sitting does not wait for the builds" 'if wait "${pids[$i]}"; then' 'if true; then'
  mutant "a failed build is ignored" 'failed=1' 'failed=0'
  mutant "the builds run one after the other" '"$out/build-$arch.log" 2>&1 &' '"$out/build-$arch.log" 2>&1'
  mutant "an archive at another commit is kept" 'grep -qx "$name $head" <<< "$have"' 'grep -q "^$name " <<< "$have"'
  rm -rf "$t"
  if [ "$fails" = 0 ]; then
    echo "sit.sh: self-test ok ($cases cases)"
  else
    echo "sit.sh: self-test $fails failure(s)" >&2
    return 1
  fi
}

if [ "${1:-}" = --self-test ]; then
  [ $# -eq 1 ] || { usage; exit 64; }
  self_test
  exit $?
fi

VERSION=${1:-}
[ $# -eq 0 ] || shift
STAGE=portable CELLS=$(cd "$(dirname "$0")" && pwd)/cells.tsv TREE=$PWD DRY=0 EXTRA=() BUILD=auto
while [ $# -gt 0 ]; do
  case $1 in
    --no-build) BUILD=no; shift ;;
    --rebuild) BUILD=yes; shift ;;
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
# The archive builds come first and end before the hold goes up (the header).
if [ "$STAGE" = portable ] && [ "$BUILD" != no ]; then
  if [ "$DRY" = 1 ]; then
    echo "sit.sh: [build] dry run: the box holds: $(archive_commits "$TREE" "$VERSION" | tr '\n' ';'); a real run builds each archive not at $(git -C "$TREE" rev-parse --short=12 HEAD) before the hold"
  else
    run_builds "$TREE" "$VERSION" "$OUT" "$BUILD" || die 70 "an archive build failed: the sitting would run on a tarball that is not this tree's; no hold was put up"
  fi
fi
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
