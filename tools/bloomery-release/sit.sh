#!/usr/bin/env bash
# One bloomery release sitting, driven from the lead's Mac: the cells go to the box, `just release-sitting` runs them in
# one hold on one binary, and the verdict and the tapes come back with the two tables the release notes carry.
#
#   sit.sh <version> [--binary tree|portable] [--w | --release-build] [--cells FILE] [--tree DIR] [--keep-going]
#                    [--fold off|depths] [--dry-run] [--no-build | --rebuild]
#   sit.sh --self-test
#
#   <version>      the release, e.g. 0.3.11: names the tarball (bloomery-<version>-linux-x86_64-cuda-sm86.tar.gz in the
#                  box tree's target/release-dist/), the prediction card (docs/cards/rel0311-headline.card, kind
#                  baseline, written before the sitting: the version without its dots, as the earlier cards are) and
#                  the output directory (~/.cache/bloomery/rel0311/)
#   --binary       portable (default): the release's verdict, the tarball's own bloomery-serve. tree: an iteration's,
#                  the tree's target/release build, marked stage=tree, never a release number
#   --w            sit on the archives the follower built at its watermark (rig-log tools/bloomery-follow/run.sh, its record
#                  W.archives): no build. The tarball is read at the box directory the record names, the sitting's binary is
#                  that directory's target/portable (`--tree <its name>` for tools/release/sitting.sh), and the verdict lands
#                  beside the tarball, where tools/release/publish.sh reads it with BLOOMERY_REMOTE the record's directory. This
#                  tree's tools run the sitting from its own box directory, which must not be the follower's (64): a sync would
#                  change the sources the binary was built from, and depth-serve refuses a binary older than them. Refused by
#                  name when W.archives is absent (66), names another version than <version> or another shape than the follower
#                  writes (65), or the box's archive is not at the record's commit (65). The record is BLOOMERY_FOLLOW_HOME's
#                  (default ~/.cache/bloomery/follow)
#   --release-build  build with the plain `just release-build <version>`, which also holds this tree's README to <version>
#                  (publish.sh's tree check): for a release-commit tree whose README names the release (the picker's HEAD
#                  case), where a README refused after the archives were built moves the tag; the default builds at a
#                  watermark's way, below, and a tree before the release commit cannot pass that README check
#   --cells FILE   default: cells.tsv beside this script; copy and edit it per release (its header names the columns)
#   --tree DIR     the release tree on this Mac (default: the current directory); it must be synced by `tools/box.sh`
#                  to the box's directory of the same name, where the archives are built
#   --keep-going   run the round's other cells after a red one (tools/release/sitting.sh's flag)
#   --fold         the sitting's fold (tools/release/sitting.sh's --fold): off or depths; unset, sitting.sh's own default
#   --dry-run      the sitting's plan and predicted wall (the cells are sent; no hold goes up, nothing is fetched, nothing is
#                  built: each archive that a real run would build gets its `build.sh --dry-run --stage w` on the box)
#   --no-build     skip the archive builds below (the archives are on the box some other way)
#   --rebuild      build both archives whatever the box holds
#
# The builds. A portable sitting runs on the tarball of this tree's commit, and the release also ships the sm_120a archive, so
# before the hold goes up the box is asked for both x86-64 archives (target/release-dist, sm_86 and sm_120a) and each one that is
# absent or was built at another commit is built, the two at once (each archive builds in a target directory of its own,
# tools/release/build.sh). A build is the follower's: after a clean-tree check and tools/release/carry.sh here (the Mac lines of
# `just release-build`), `bash tools/release/build.sh --stage w <version> <commit>` through tools/box.sh from this tree, bounded by
# SIT_BUILD_BOUND (default 1800 s) on the box. --stage w holds the crates' versions to <version> and not the README, which on main
# names the last published release until the release commit; the archive is the same program and its --version names this
# tree's commit. They run with no BLOOMERY_HOLD_OWNER, so any hold on the box makes them wait, and the sitting starts only after
# both have ended: a build never runs under the sitting's hold, and the sitting's first quiet look finds no compile. A refused
# check or a failed build ends sit.sh before any hold, naming the check, or the archive and its log.
#
# The box is BLOOMERY_BOX (a ssh name, as tools/release/publish.sh reads it; required: no host is named here) and its
# directory BLOOMERY_REMOTE (default ~/repo/<the tree's name>). BLOOMERY_HOLD_OWNER (default rel) owns the hold on both
# sides: this call passes it, and nothing else on the box starts until the sitting ends.
#
# Output, in ~/.cache/bloomery/rel<version without dots>/: sitting-<binary>.log (the sitting's whole output), <verdict>.sitting
# (the verdict tools/release/publish.sh reads from the box) and <verdict>.sitting.d/ (each call's log and every
# server's session directory, the tapes among them). Exit: the sitting's (0 green, 1 red, 75 the box is busy); 64 usage,
# 65 a W.archives that does not describe this sitting's archives, 66 an input file missing, 70 a build or its Mac-side check.
set -uo pipefail

usage() {
  echo "usage: sit.sh <version> [--binary tree|portable] [--w | --release-build] [--cells FILE] [--tree DIR] [--keep-going] [--fold off|depths] [--dry-run] [--no-build | --rebuild] | --self-test" >&2
}
die() {
  echo "sit.sh: $2" >&2
  exit "$1"
}

# archive_commits <tree> <version> [<dir>]: one `<arch> <commit>` line for each x86-64 archive on the box (sm86, sm120a) in <dir>
# (default target/release-dist, beside the tree's box directory; a `~/repo/...` directory is expanded by the box's shell), the
# commit its VERSION file names, or `-` for an archive that is absent.
archive_commits() {
  local d=${3:-target/release-dist}
  (cd "$1" && bash tools/box.sh "d=$d; for a in sm86 sm120a; do n=bloomery-$2-linux-x86_64-cuda-\$a; if [ -f \$d/\$n.tar.gz ]; then echo \"\$a \$(tar -xzOf \$d/\$n.tar.gz \$n/VERSION 2> /dev/null | sed -n 2p)\"; else echo \"\$a -\"; fi; done" 2> /dev/null) | grep -E '^(sm86|sm120a) ' || true
}

# mac_checks <tree>: the Mac lines of `just release-build`, before the box is touched: no uncommitted change to a tracked file (the
# archives are named for HEAD), and every fix tools/release/carry.tsv lists an ancestor of HEAD (tools/release/carry.sh, which reads
# .git, so it runs here). 0 both hold, 1 one refused (printed).
mac_checks() {
  local tree=$1 dirt carry
  dirt=$(git -C "$tree" status --porcelain --untracked-files=no 2>&1) || { echo "sit.sh: cannot read the status of $tree: $dirt" >&2; return 1; }
  if [ -n "$dirt" ]; then
    echo "sit.sh: the tree $tree has uncommitted changes: an archive built from it would not be its commit's" >&2
    return 1
  fi
  if ! carry=$(cd "$tree" && ./tools/release/carry.sh 2>&1); then
    echo "sit.sh: carry.sh refused: $(printf '%s\n' "$carry" | grep -v '^[[:space:]]*$' | head -n 1 | cut -c1-200)" >&2
    return 1
  fi
}

# run_builds <tree> <version> <out dir> <mode: auto|yes> <dry: 0|1>: the archive builds, before any hold. An archive the box already
# holds at the tree's commit is kept unless mode is yes. The builds that remain run at once (RELEASE_BUILD=1: each its own `just
# release-build`; else each `build.sh --stage w` through tools/box.sh, after mac_checks), with no BLOOMERY_HOLD_OWNER (any hold makes
# them wait), and every one is waited for (by the pid captured at its start) before this returns: 0 all built or kept, 1 a check
# refused or a build failed (named, with its log). A dry run asks each remaining archive's `build.sh --dry-run --stage w` on the box
# in turn (the tree check and the directories) and starts no build.
run_builds() {
  local tree=$1 version=$2 out=$3 mode=$4 dry=$5 head have arch name todo=() pids=() names=() cmd i failed=0 rc
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
  if [ "$RELEASE_BUILD" = 1 ] && [ "$dry" = 1 ]; then
    echo "sit.sh: [build] dry run: the box holds: $(tr '\n' ';' <<< "$have"); a real run builds ${todo[*]} with just release-build $version at $head before the hold"
    return 0
  fi
  [ "$RELEASE_BUILD" = 1 ] || mac_checks "$tree" || return 1
  if [ "$dry" = 1 ]; then
    for arch in "${todo[@]}"; do
      echo "sit.sh: [build] $arch: dry run of build.sh --stage w $version $head on the box (the tree check and the directories; nothing is built)"
      (cd "$tree" && env -u BLOOMERY_HOLD_OWNER BLOOMERY_ARCH="$arch" bash tools/box.sh "bash tools/release/build.sh --dry-run --stage w $version $head") 2>&1 | sed "s/^/[$arch] /"
      rc=${PIPESTATUS[0]}
      [ "$rc" = 0 ] || { echo "sit.sh: [build] $arch: the dry run ended rc $rc" >&2; failed=1; }
    done
    return "$failed"
  fi
  for arch in "${todo[@]}"; do
    if [ "$RELEASE_BUILD" = 1 ]; then
      echo "sit.sh: [build] $arch: just release-build $version at $head (log $out/build-$arch.log)"
      cmd=(just release-build "$version")
    else
      echo "sit.sh: [build] $arch: build.sh --stage w $version $head through tools/box.sh (log $out/build-$arch.log)"
      cmd=(bash tools/box.sh "timeout --kill-after=10 $SIT_BUILD_BOUND bash tools/release/build.sh --stage w $version $head")
    fi
    (cd "$tree" && env -u BLOOMERY_HOLD_OWNER BLOOMERY_ARCH="$arch" "${cmd[@]}") > "$out/build-$arch.log" 2>&1 &
    pids+=($!)
    names+=("$arch")
  done
  for i in "${!pids[@]}"; do
    rc=0
    wait "${pids[$i]}" || rc=$?
    if [ "$rc" = 0 ]; then
      echo "sit.sh: [build] ${names[$i]}: done"
    else
      echo "sit.sh: [build] ${names[$i]}: failed (rc $rc); the end of $out/build-${names[$i]}.log:" >&2
      tail -n 5 "$out/build-${names[$i]}.log" | sed 's/^/  /' >&2
      failed=1
    fi
  done
  return "$failed"
}

# self_test: sit.sh in a temporary tree against a fake box directory and stub `just`, `scp`, tools/box.sh (the stub box.sh runs its
# command in the fake directory, and answers a build.sh call itself) and tools/release/carry.sh: the archive builds are `build.sh
# --stage w` at the tree's version and commit even when the tree's README names the last release, start before the sitting, run at
# once, carry no hold owner, are all waited for and end before the sitting; archives at the tree's commit are kept; a dirty tree or a
# carry refusal ends sit.sh before any build; a failed build ends it before any hold; --w sits on the archives W.archives names and
# builds nothing, and is refused by name for a missing record, another version, another shape, or a box that does not hold the
# archive at the record's commit; --fold reaches the sitting. Each guard has a mutant of this script that its case must turn red.
# shellcheck disable=SC2088 # the tilde is literal on purpose: W.archives names its directory so, and the box's shell expands it
self_test() {
  local t me head fails=0 cases=0 out rc wdist green=0 mutants=0
  me=$(cd "$(dirname "$0")" && pwd)/$(basename "$0")
  t=$(mktemp -d "${TMPDIR:-/tmp}/sit-test.XXXXXX") || return 70
  mkdir -p "$t/tree/tools/release" "$t/tree/docs/cards" "$t/box" "$t/bin" "$t/home/.cache/bloomery/follow"
  wdist=$t/home/repo/bloomery-follow/target/release-dist
  : > "$t/tree/tools/release/sitting.sh"
  : > "$t/tree/docs/cards/rel001-headline.card"
  printf '## Status (0.0.0)\n' > "$t/tree/README.md" # a README that names the last release, as main's does before the release commit
  cat > "$t/tree/tools/release/carry.sh" << 'EOF'
#!/bin/sh
echo "carry-ran" >> "$STUB_LOG"
[ -z "$STUB_CARRY" ] || { echo "release-build: stub lacks fix x (pending)" >&2; exit 1; }
EOF
  chmod +x "$t/tree/tools/release/carry.sh"
  cat > "$t/tree/tools/box.sh" << 'EOF'
#!/bin/sh
echo "box-call arch=${BLOOMERY_ARCH-unset} hold=${BLOOMERY_HOLD_OWNER-unset} cmd=$1" >> "$STUB_CALLS"
case $1 in
  *"tools/release/build.sh --dry-run"*)
    echo "build-dry ${BLOOMERY_ARCH-unset}" >> "$STUB_LOG"
    echo "release: dry run: stub"
    exit 0 ;;
  *"tools/release/build.sh "*)
    echo "build-start $BLOOMERY_ARCH hold=${BLOOMERY_HOLD_OWNER-unset}" >> "$STUB_LOG"
    sleep 0.6
    if [ "$BLOOMERY_ARCH" = "$STUB_FAIL" ]; then echo "stub: the build broke"; exit 3; fi
    echo "build-end $BLOOMERY_ARCH" >> "$STUB_LOG"
    exit 0 ;;
esac
cd "$FAKE_BOX" && exec sh -c "$1"
EOF
  cat > "$t/bin/just" << 'EOF'
#!/bin/sh
case "$1" in
  release-build)
    grep -q '^## Status (0.0.1)' README.md || { echo "stub: README.md does not name '## Status (0.0.1)'"; exit 1; }
    echo "build-start $BLOOMERY_ARCH hold=${BLOOMERY_HOLD_OWNER-unset}" >> "$STUB_LOG"
    sleep 0.6
    if [ "$BLOOMERY_ARCH" = "$STUB_FAIL" ]; then echo "stub: the build broke"; exit 3; fi
    echo "build-end $BLOOMERY_ARCH" >> "$STUB_LOG" ;;
  release-sitting)
    shift
    echo "sitting-start hold=${BLOOMERY_HOLD_OWNER-unset} args=$*" >> "$STUB_LOG" ;;
esac
EOF
  printf '#!/bin/sh\nexit 0\n' > "$t/bin/scp"
  chmod +x "$t/bin/just" "$t/bin/scp"
  printf 'x\n' > "$t/cells.tsv"
  git -C "$t/tree" init -q
  git -C "$t/tree" add -A
  git -C "$t/tree" -c user.name=selftest -c user.email=selftest@invalid commit -q -m tree
  head=$(git -C "$t/tree" rev-parse --short=12 HEAD)
  mk_archive() { # mk_archive <sm86|sm120a> <commit> [<dist dir>]: the archive on the fake box, its VERSION file naming the commit
    local n=bloomery-0.0.1-linux-x86_64-cuda-$1 d=${3:-$t/box/target/release-dist}
    mkdir -p "$d/$n"
    printf '0.0.1\n%s\n' "$2" > "$d/$n/VERSION"
    tar -czf "$d/$n.tar.gz" -C "$d" "$n"
  }
  mk_record() { # mk_record <version> <remote>: the follower's W.archives, naming the tree's commit
    printf 'commit=%s\nversion=%s\nepoch=1\ndate=x\nremote=%s\ndist=target/release-dist\nsm86 aaaa bloomery-%s-linux-x86_64-cuda-sm86.tar.gz\nsm120a bbbb bloomery-%s-linux-x86_64-cuda-sm120a.tar.gz\n' \
      "$(git -C "$t/tree" rev-parse HEAD)" "$1" "$2" "$1" "$1" > "$t/home/.cache/bloomery/follow/W.archives"
  }
  fresh_box() { rm -rf "$t/box" "$t/home/repo"; mkdir -p "$t/box/target/release-dist" "$wdist"; }
  # run_sit <script> <fail arch or ''> <sit.sh args…>: a fresh log, the script run, $out and $rc. Under a mutant (loud 0) the runs
  # after its first red case are skipped: the mutant is already caught, and the rest would only cost time.
  run_sit() {
    local script=$1 fail=$2
    shift 2
    if [ "$loud" = 0 ] && [ "$BAD" != 0 ]; then return 0; fi
    : > "$t/log"
    : > "$t/calls"
    out=$(env -u BLOOMERY_FOLLOW_HOME -u SIT_BUILD_BOUND PATH="$t/bin:$PATH" HOME="$t/home" BLOOMERY_BOX=fakebox BLOOMERY_REMOTE="${SIT_TEST_REMOTE:-/fake}" FAKE_BOX="$t/box" STUB_LOG="$t/log" STUB_CALLS="$t/calls" STUB_FAIL="$fail" STUB_CARRY="${STUB_CARRY:-}" \
      bash "$script" 0.0.1 --cells "$t/cells.tsv" --tree "$t/tree" "$@" 2>&1) && rc=0 || rc=$?
  }
  # shape: "<starts at once|serial> <builds ended before the sitting|not> <starts>" from the stub's log
  shape() {
    awk '/^build-start/ { ns++; if (ns == 2) s2 = NR } /^build-end/ { if (!fe) fe = NR; le = NR } /^sitting-start/ { st = NR }
      END { printf "%s %s %d %s\n", (s2 && fe && s2 < fe) ? "parallel" : "not-parallel", (le && st && le < st) ? "before-sitting" : "not-before-sitting", ns + 0, st ? "sitting" : "no-sitting" }' "$t/log"
  }
  sitting_args() { sed -n 's/^sitting-start hold=[^ ]* args=//p' "$t/log" | head -n 1; }
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
    fresh_box
    run_sit "$script" ''
    check "an empty box: both archives build at once, then the sitting" "parallel before-sitting 2 sitting" "$(shape)"
    check "the builds carry no hold owner, the sitting has one" "build-start sm_120a hold=unset|build-start sm_86 hold=unset|sitting-start hold=rel" "$(grep -E '^(build-start|sitting-start)' "$t/log" | sed 's/ args=.*//' | sort | tr '\n' '|' | sed 's/|$//')"
    check "a README that names the last release still builds: each archive is build.sh --stage w at the version and the tree's commit, bounded, through tools/box.sh" \
      "sm_120a timeout --kill-after=10 1800 bash tools/release/build.sh --stage w 0.0.1 $head|sm_86 timeout --kill-after=10 1800 bash tools/release/build.sh --stage w 0.0.1 $head" \
      "$(grep 'tools/release/build.sh' "$t/calls" | sed -E 's/^box-call arch=([^ ]+) hold=[^ ]+ cmd=/\1 /' | sort | tr '\n' '|' | sed 's/|$//')"
    check "the Mac-side checks ran once before the builds" "carry-ran" "$(grep -c '^carry-ran' "$t/log" | sed 's/^1$/carry-ran/')"
    run_sit "$script" sm_120a
    got=$(shape)
    check "a failed build: no sitting" "no-sitting" "${got##* }"
    check "a failed build ends sit.sh by name" "1 sit.sh: [build] sm_120a: failed" "$([ "$rc" != 0 ] && echo 1) $(grep -o 'sit.sh: \[build\] sm_120a: failed' <<< "$out" | head -n 1)"
    check "a failed build: the other one was still waited for" "build-end sm_86" "$(grep '^build-end' "$t/log")"
    fresh_box
    mk_archive sm86 "$head"
    run_sit "$script" ''
    check "an sm_86 archive at the tree's commit is kept" "build-start sm_120a hold=unset" "$(grep '^build-start' "$t/log")"
    fresh_box
    mk_archive sm86 deadbeef0000
    mk_archive sm120a "$head"
    run_sit "$script" ''
    check "an archive at another commit is rebuilt, the one at the tree's kept" "build-start sm_86 hold=unset" "$(grep '^build-start' "$t/log")"
    mk_archive sm86 "$head"
    run_sit "$script" ''
    check "both archives at the tree's commit: no build, the sitting runs" "parallel-less 0 sitting" "$(shape | sed 's/^not-parallel not-before-sitting/parallel-less/')"
    run_sit "$script" '' --rebuild
    check "--rebuild builds both whatever the box holds" "parallel before-sitting 2 sitting" "$(shape)"
    fresh_box
    run_sit "$script" '' --no-build
    check "--no-build builds nothing" "0 sitting" "$(shape | awk '{print $3, $4}')"
    run_sit "$script" '' --binary tree
    check "a tree stage builds no archive" "0 sitting" "$(shape | awk '{print $3, $4}')"
    run_sit "$script" '' --dry-run
    check "a dry run builds nothing" "0" "$(shape | awk '{print $3}')"
    check "a dry run asks each archive's build.sh --dry-run on the box" "build-dry sm_120a|build-dry sm_86" "$(grep '^build-dry' "$t/log" | sort | tr '\n' '|' | sed 's/|$//')"
    check "a dry run's sitting is the sitting's dry run" "1" "$(sitting_args | grep -c -- '--dry-run')"
    echo 'x' >> "$t/tree/tools/release/sitting.sh"
    run_sit "$script" ''
    check "a tree with an uncommitted change: no build, no sitting, refused by name" "0 no-sitting 1 uncommitted" "$(shape | awk '{print $3, $4}') $([ "$rc" != 0 ] && echo 1) $(grep -o 'uncommitted' <<< "$out" | head -n 1)"
    : > "$t/tree/tools/release/sitting.sh"
    STUB_CARRY=1 run_sit "$script" ''
    check "a carry refusal: no build, no sitting, refused by name" "0 no-sitting 1 carry.sh refused: release-build: stub lacks fix x (pending)" "$(shape | awk '{print $3, $4}') $([ "$rc" != 0 ] && echo 1) $(grep -o 'carry.sh refused: release-build: stub lacks fix x (pending)' <<< "$out" | head -n 1)"
    run_sit "$script" '' --no-build --fold depths
    check "--fold depths reaches the sitting" "--fold depths" "$(sitting_args | grep -o -- '--fold [a-z]*')"
    run_sit "$script" '' --no-build --fold off
    check "--fold off reaches the sitting" "--fold off" "$(sitting_args | grep -o -- '--fold [a-z]*')"
    run_sit "$script" '' --no-build
    check "no --fold: the sitting's own default (none passed)" "0" "$(sitting_args | grep -c -- '--fold')"
    run_sit "$script" '' --no-build --fold sideways
    check "a --fold that is neither is refused by name, nothing sent" "64 0 --fold" "$rc $(grep -c . "$t/calls") $(grep -o -- '--fold' <<< "$out" | head -n 1)"
    # --w: the follower's archives
    fresh_box
    mk_record 0.0.1 '~/repo/bloomery-follow'
    mk_archive sm86 "$head" "$wdist"
    run_sit "$script" '' --w
    check "--w builds nothing and sits" "0 sitting" "$(shape | awk '{print $3, $4}')"
    check "--w sits on the tarball the record names, in the follower's box directory, and its tree's binary" \
      "--binary portable --tarball ~/repo/bloomery-follow/target/release-dist/bloomery-0.0.1-linux-x86_64-cuda-sm86.tar.gz --tree bloomery-follow" \
      "$(sitting_args | grep -o -- '--binary portable --tarball [^ ]* --tree [^ ]*')"
    run_sit "$script" '' --w --dry-run --fold off
    check "--w with --dry-run and --fold: both reach the sitting" "1 1" "$(sitting_args | grep -c -- '--dry-run') $(sitting_args | grep -c -- '--fold off')"
    rm -f "$t/home/.cache/bloomery/follow/W.archives"
    run_sit "$script" '' --w
    check "--w with no W.archives: refused by name (66), nothing sent to the box, no sitting" "66 0 no-sitting W.archives" "$rc $(grep -c . "$t/calls") $(shape | awk '{print $4}') $(grep -o 'W.archives' <<< "$out" | head -n 1)"
    mk_record 0.0.0 '~/repo/bloomery-follow'
    run_sit "$script" '' --w
    check "--w with another version's record: refused by name (65), nothing sent" "65 0 no-sitting names version '0.0.0', not 0.0.1" "$rc $(grep -c . "$t/calls") $(shape | awk '{print $4}') $(grep -o "names version '0.0.0', not 0.0.1" <<< "$out" | head -n 1)"
    mk_record 0.0.1 '/tmp/not-under-repo'
    run_sit "$script" '' --w
    check "--w with a record whose directory is not ~/repo/<name>: refused by name (65)" "65 no-sitting ~/repo/<name>" "$rc $(shape | awk '{print $4}') $(grep -o '~/repo/<name>' <<< "$out" | head -n 1)"
    mk_record 0.0.1 '~/repo/bloomery-follow'
    rm -rf "$wdist"
    mkdir -p "$wdist"
    mk_archive sm86 deadbeef0000 "$wdist"
    run_sit "$script" '' --w
    check "--w when the box's archive is at another commit than the record's: refused by name (65), no sitting" "65 no-sitting the box holds no sm86 archive at" "$rc $(shape | awk '{print $4}') $(grep -o 'the box holds no sm86 archive at' <<< "$out" | head -n 1)"
    SIT_TEST_REMOTE='~/repo/bloomery-follow' run_sit "$script" '' --w
    check "--w when the sitting's own box directory is the follower's: refused by name (64), nothing sent, no sitting" "64 0 no-sitting is the follower's" "$rc $(grep -c . "$t/calls") $(shape | awk '{print $4}') $(grep -o "is the follower's" <<< "$out" | head -n 1)"
    run_sit "$script" '' --w --rebuild
    check "--w with --rebuild contradicts: refused (64)" "64" "$rc"
    run_sit "$script" '' --w --binary tree
    check "--w with --binary tree contradicts: refused (64)" "64" "$rc"
    # --release-build: the plain recipe, for a tree whose README names the release
    fresh_box
    run_sit "$script" '' --release-build
    check "--release-build on a README that names the last release: the recipe refuses it, no sitting" "no-sitting 1" "$(shape | awk '{print $4}') $([ "$rc" != 0 ] && echo 1)"
    printf '## Status (0.0.1)\n' > "$t/tree/README.md"
    run_sit "$script" '' --release-build
    check "--release-build on a README that names the release: both archives build at once with just release-build, then the sitting" "parallel before-sitting 2 sitting 0" "$(shape) $(grep -c 'tools/release/build.sh' "$t/calls")"
    printf '## Status (0.0.0)\n' > "$t/tree/README.md"
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
    mutants=$((mutants + 1))
    sleep 1 # a mutant's builds may outlive sit.sh
  }
  all_cases "$me" 1 || fails=$((fails + BAD))
  green=$cases
  mutant "no build step" $'\n  run_builds "$TREE" "$VERSION" "$OUT" "$BUILD" "$DRY" || die 70' $'\n  : || die 70'
  mutant "builds under the hold owner" 'env -u BLOOMERY_HOLD_OWNER BLOOMERY_ARCH="$arch" "${cmd[@]}"' 'env BLOOMERY_ARCH="$arch" "${cmd[@]}"'
  mutant "the sitting does not wait for the builds" 'wait "${pids[$i]}" || rc=$?' 'rc=0'
  mutant "a failed build is ignored" $'      failed=1\n    fi\n  done\n  return "$failed"' $'      failed=0\n    fi\n  done\n  return "$failed"'
  mutant "the builds run one after the other" '"$out/build-$arch.log" 2>&1 &' '"$out/build-$arch.log" 2>&1'
  mutant "an archive at another commit is kept" 'grep -qx "$name $head" <<< "$have"' 'grep -q "^$name " <<< "$have"'
  mutant "the stage is ignored" 'bash tools/release/build.sh --stage w $version $head")' 'bash tools/release/build.sh $version $head")'
  mutant "the recipe is the default build" $'\nRELEASE_BUILD=0' $'\nRELEASE_BUILD=1'
  mutant "no clean-tree check" '[ -n "$dirt" ]' 'false'
  mutant "no carry check" './tools/release/carry.sh 2>&1)' 'true 2>&1)'
  mutant "a dry run builds" 'bash tools/release/build.sh --dry-run --stage w $version $head")' 'bash tools/release/build.sh --stage w $version $head")'
  mutant "--fold is not passed on" $'\n[ -z "$FOLD" ] || EXTRA+=(--fold "$FOLD")' $'\n:'
  mutant "--w sits on the tree's own archive" $'\n    ARGS+=(--tarball "$W_REMOTE/$W_DIST/$NAME.tar.gz" --tree "$W_TREE")' $'\n    ARGS+=(--tarball "target/release-dist/$NAME.tar.gz")'
  mutant "--w builds as well" $'\nif [ "$STAGE" = portable ] && [ "$BUILD" != no ] && [ "$USE_W" = 0 ]; then' $'\nif [ "$STAGE" = portable ] && [ "$BUILD" != no ]; then'
  mutant "--w does not need its record" $'\n  [ -r "$WREC" ] || die 66' $'\n  [ -r "$WREC" ] || :'
  mutant "--w takes another version's record" $'\n  [ "$W_VER" = "$VERSION" ] || die 65' $'\n  true || die 65'
  mutant "--w takes a directory outside ~/repo" $'\n  [[ $W_REMOTE =~ ^~/repo/[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die 65' $'\n  true || die 65'
  mutant "--w does not read the box's archive" $'\n  grep -qx "sm86 ${W_COMMIT:0:12}" <<< "$W_HAVE" || die 65' $'\n  true || die 65'
  mutant "--w may sync this tree over the follower's directory" $'\n  [ "${REMOTE%/}" != "$W_REMOTE" ] || die 64' $'\n  true || die 64'
  mutant "--w with --rebuild is allowed" $'\n  [ "$BUILD" != yes ] || die 64 "--w builds nothing' $'\n  [ "$BUILD" != nothing ] || die 64 "--w builds nothing'
  rm -rf "$t"
  if [ "$fails" = 0 ]; then
    echo "sit.sh: self-test ok ($green cases, $mutants mutants each caught by a case)"
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
STAGE=portable CELLS=$(cd "$(dirname "$0")" && pwd)/cells.tsv TREE=$PWD DRY=0 EXTRA=() BUILD=auto USE_W=0 FOLD=''
RELEASE_BUILD=0
SIT_BUILD_BOUND=${SIT_BUILD_BOUND:-1800}
while [ $# -gt 0 ]; do
  case $1 in
    --no-build) BUILD=no; shift ;;
    --rebuild) BUILD=yes; shift ;;
    --w) USE_W=1; shift ;;
    --release-build) RELEASE_BUILD=1; shift ;;
    --binary | --cells | --tree | --fold)
      [ $# -ge 2 ] || { usage; die 64 "$1 needs a value"; }
      case $1 in
        --binary) STAGE=$2 ;;
        --cells) CELLS=$2 ;;
        --tree) TREE=$2 ;;
        --fold) FOLD=$2 ;;
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
case $FOLD in '' | off | depths) ;; *) die 64 "--fold is off or depths, got '$FOLD'" ;; esac
[[ $SIT_BUILD_BOUND =~ ^[1-9][0-9]*$ ]] || die 64 "SIT_BUILD_BOUND is whole seconds, got '$SIT_BUILD_BOUND'"
if [ "$USE_W" = 1 ]; then
  [ "$STAGE" = portable ] || die 64 "--w sits on the follower's archives: it is the portable stage's, not --binary $STAGE"
  [ "$BUILD" != yes ] || die 64 "--w builds nothing: it sits on the archives W.archives names, and --rebuild builds"
  [ "$RELEASE_BUILD" = 0 ] || die 64 "--w builds nothing: --release-build names a build"
fi
[ -z "$FOLD" ] || EXTRA+=(--fold "$FOLD")
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
# --w: the follower's record of the archives it built at its watermark, read before the box is touched. The record is one the
# follower writes only when both archives were built (tools/bloomery-follow/run.sh, W.archives): commit= (full sha), version=,
# remote= and dist= (where the archives are on the box), and a row `sm86 <sha256> <name>.tar.gz`.
if [ "$USE_W" = 1 ]; then
  WREC=${BLOOMERY_FOLLOW_HOME:-$HOME/.cache/bloomery/follow}/W.archives
  [ -r "$WREC" ] || die 66 "--w: no $WREC: the follower has built no archives at its watermark, or one is being built (it removes the record when a build starts); run.sh --tarballs $VERSION reads the same record"
  W_VER=$(sed -n 's/^version=//p' "$WREC" | head -n 1)
  W_COMMIT=$(sed -n 's/^commit=//p' "$WREC" | head -n 1)
  W_REMOTE=$(sed -n 's/^remote=//p' "$WREC" | head -n 1)
  W_DIST=$(sed -n 's/^dist=//p' "$WREC" | head -n 1)
  W_ROW=$(awk '$1 == "sm86" { print $3; exit }' "$WREC")
  [ "$W_VER" = "$VERSION" ] || die 65 "--w: $WREC names version '${W_VER:-none}', not $VERSION: the archives at W are another release's"
  [[ $W_COMMIT =~ ^[0-9a-f]{12,40}$ ]] || die 65 "--w: $WREC names no commit (commit= '$W_COMMIT')"
  [[ $W_REMOTE =~ ^~/repo/[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die 65 "--w: $WREC names the box directory '$W_REMOTE', which is not ~/repo/<name>: tools/release/sitting.sh reads a tree's binary at ~/repo/<name>/target/portable"
  [[ $W_DIST =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] && [[ $W_DIST != *..* ]] || die 65 "--w: $WREC names the directory '$W_DIST', which is no path under the box directory"
  [ "$W_ROW" = "$NAME.tar.gz" ] || die 65 "--w: $WREC has no row for the archive $NAME.tar.gz (its sm86 row names '${W_ROW:-nothing}')"
  W_TREE=${W_REMOTE##*/}
  [ "${REMOTE%/}" != "$W_REMOTE" ] || die 64 "--w: the sitting's box directory $REMOTE is the follower's: syncing this tree there would change the sources its binary was built from (the stale-binary rule, rc 3); give the sitting another BLOOMERY_REMOTE"
fi
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
if [ "$USE_W" = 1 ]; then
  # The box is asked, apart from the record: the sitting's own checks (the binary equals the tarball's member) would catch a replaced
  # archive too, but only after its hold went up.
  W_HAVE=$(archive_commits "$TREE" "$VERSION" "$W_REMOTE/$W_DIST")
  grep -qx "sm86 ${W_COMMIT:0:12}" <<< "$W_HAVE" || die 65 "--w: the box holds no sm86 archive at ${W_COMMIT:0:12} in $W_REMOTE/$W_DIST (it holds: $(tr '\n' ';' <<< "$W_HAVE")): the record and the box disagree"
  echo "sit.sh: [w] the archives at W: v$VERSION at ${W_COMMIT:0:12} in $W_REMOTE/$W_DIST; the sitting's tools are this tree's ($(git -C "$TREE" rev-parse --short=12 HEAD)), its binary $W_REMOTE/target/portable's, the verdict lands beside the tarball"
fi
# The archive builds come first and end before the hold goes up (the header).
if [ "$STAGE" = portable ] && [ "$BUILD" != no ] && [ "$USE_W" = 0 ]; then
  run_builds "$TREE" "$VERSION" "$OUT" "$BUILD" "$DRY" || die 70 "an archive build was refused or failed (above): the sitting would run on a tarball that is not this tree's; no hold was put up"
fi
ARGS=(--binary "$STAGE")
if [ "$STAGE" = portable ]; then
  if [ "$USE_W" = 1 ]; then
    ARGS+=(--tarball "$W_REMOTE/$W_DIST/$NAME.tar.gz" --tree "$W_TREE")
  else
    ARGS+=(--tarball "target/release-dist/$NAME.tar.gz")
  fi
fi
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
