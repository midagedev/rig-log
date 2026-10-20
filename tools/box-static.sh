#!/bin/bash
# box-static.sh [-C TREE] [BASE|--full] — bloomery's static tier on the box, inside rounds.slice.
#
#   bash ~/repo/rig-log/tools/box-static.sh origin/main          # from inside a bloomery tree (TREE defaults to $PWD)
#   bash ~/repo/rig-log/tools/box-static.sh -C ~/repo/bloomery-foo --full
#
# Called from the Mac. It does one thing:
#   tools/box.sh 'bash tools/mac-static.sh --native --slice rounds.slice [BASE|--full]'
# The lanes (fmt, lint, the feature combos, the check scripts) belong to bloomery's tools/mac-static.sh --native. The
# slice's name and caps are this machine's, so they live only here and in configs/rounds.slice, which owns the caps
# (AllowedCPUs, MemoryHigh, MemoryMax); this script holds no value. A slice not installed on the box is refused 69 by the lane (install lines: configs/rounds.slice's header).
# The remote directory follows box.sh's rule: BLOOMERY_REMOTE (default ~/repo/<tree name>). BASE resolves against the pushed HEAD and origin/main.
#
# Environment (tests): BOX_STATIC_SLICE (rounds.slice), the slice name to use.
# rc: the lane's (as box.sh returns it), 64 a usage error, 66 TREE has no tools/box.sh or tools/mac-static.sh.
# Test: bash tools/box-static.sh --self-test   (a stub box.sh; the box is not used)
set -u
SELF=$(cd "$(dirname "$0")" && pwd)/$(basename "$0")
SLICE=${BOX_STATIC_SLICE:-rounds.slice}
say() { printf '%s\n' "box-static: $*" >&2; }

# run TREE ARG…: run the lane in TREE through box.sh. ARG is one BASE or --full, or none.
run() {
  local tree=$1 arg=${2:-}
  [ $# -le 2 ] || { say "usage: box-static.sh [-C TREE] [BASE|--full] (one BASE, got $(($# - 1)))"; return 64; }
  case $arg in
    '' | --full) ;;
    -*) say "usage: box-static.sh [-C TREE] [BASE|--full] ('$arg' is not one)"; return 64 ;;
    *[!A-Za-z0-9_./~^-]*) say "the BASE '$arg' has a character outside [A-Za-z0-9_./~^-]: it goes into a command line on the box"; return 64 ;;
  esac
  cd "$tree" 2> /dev/null || { say "$tree is no directory"; return 66; }
  [ -f tools/box.sh ] && [ -f tools/mac-static.sh ] || { say "no tools/box.sh and tools/mac-static.sh in $tree: it is no bloomery tree"; return 66; }
  ./tools/box.sh "bash tools/mac-static.sh --native --slice $SLICE${arg:+ $arg}"
}

selftest() {
  local fx rc out bad=0
  fail() { echo "box-static self-test FAIL: $*" >&2; bad=$((bad + 1)); }
  # expect RC WANT_RC OUT PATTERN WHAT: rc is WANT_RC and OUT holds PATTERN
  expect() {
    case $3 in *"$4"*) [ "$1" = "$2" ] && return 0 ;; esac
    fail "$5: rc $1 (want $2): $3"
  }
  fx=$(mktemp -d) || return 69
  mkdir -p "$fx/tree/tools" "$fx/bare"
  # shellcheck disable=SC2016 # the stub's own text
  printf '%s\n' '#!/bin/sh' 'echo "box.sh got: $*"' 'exit "${BOX_RC:-0}"' > "$fx/tree/tools/box.sh"
  : > "$fx/tree/tools/mac-static.sh"
  chmod +x "$fx/tree/tools/box.sh"
  local want='box.sh got: bash tools/mac-static.sh --native --slice rounds.slice'

  rc=0; out=$(cd "$fx/tree" && bash "$SELF" origin/main 2>&1) || rc=$?
  expect "$rc" 0 "$out" "$want origin/main" "a BASE in the tree it is called from"
  rc=0; out=$(cd "$fx/bare" && bash "$SELF" -C "$fx/tree" origin/main..HEAD 2>&1) || rc=$?
  expect "$rc" 0 "$out" "$want origin/main..HEAD" "a range through -C"
  rc=0; out=$(cd "$fx/tree" && bash "$SELF" 2>&1) || rc=$?
  [ "$rc" = 0 ] && [ "$out" = "$want" ] || fail "no argument: rc $rc: $out"
  rc=0; out=$(cd "$fx/tree" && bash "$SELF" --full 2>&1) || rc=$?
  expect "$rc" 0 "$out" "$want --full" "--full"
  rc=0; out=$(cd "$fx/tree" && BOX_STATIC_SLICE=rounds-test.slice bash "$SELF" 2>&1) || rc=$?
  expect "$rc" 0 "$out" "--slice rounds-test.slice" "the scratch slice name"
  rc=0; out=$(cd "$fx/tree" && BOX_RC=3 bash "$SELF" 2>&1) || rc=$?
  expect "$rc" 3 "$out" "box.sh got" "the lane's rc"
  rc=0; out=$(cd "$fx/tree" && bash "$SELF" 'a; rm -rf x' 2>&1) || rc=$?
  expect "$rc" 64 "$out" "outside [A-Za-z0-9_./~^-]" "a BASE that is a command line"
  rc=0; out=$(cd "$fx/tree" && bash "$SELF" a b 2>&1) || rc=$?
  expect "$rc" 64 "$out" "one BASE" "two arguments"
  rc=0; out=$(cd "$fx/tree" && bash "$SELF" --bogus 2>&1) || rc=$?
  expect "$rc" 64 "$out" "is not one" "an unknown option"
  rc=0; out=$(cd "$fx/bare" && bash "$SELF" 2>&1) || rc=$?
  expect "$rc" 66 "$out" "it is no bloomery tree" "a directory that is no bloomery tree"
  rc=0; out=$(cd "$fx/tree" && bash "$SELF" -C "$fx/nowhere" 2>&1) || rc=$?
  expect "$rc" 66 "$out" "is no directory" "a TREE that is not there"
  rc=0; out=$(cd "$fx/tree" && bash "$SELF" -C 2>&1) || rc=$?
  expect "$rc" 64 "$out" "usage" "-C with no TREE"
  rm -rf "$fx"
  [ "$bad" = 0 ] || { echo "box-static: self-test $bad failed" >&2; return 1; }
  echo "box-static: self-test ok"
}

tree=$PWD
case ${1:-} in
  --self-test) selftest; exit $? ;;
  -h | --help) sed -n '2,/^set -u/p' "$0" | sed '$d'; exit 0 ;;
  -C)
    [ $# -ge 2 ] || { say "usage: box-static.sh [-C TREE] [BASE|--full] (-C takes a directory)"; exit 64; }
    tree=$2
    shift 2
    ;;
esac
run "$tree" "$@"
exit $?
