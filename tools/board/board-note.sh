#!/usr/bin/env bash
# Write a session's status-board note, then check that the agent that publishes it is alive. A note written by hand into a board whose
# agent was booted out sat unpublished for days; here the same call that writes the note runs ensure.sh, so a dead agent shows at once.
#
#   printf 'round: x\nETA 15:00\n' | board-note.sh [--repo PATH] ROLE
#   board-note.sh --self-test
#
# Stdin becomes workers/ROLE.md in the board's state directory (BOARD_DIR, default ~/.cache/bloomery/board), whole or not at all: a temp
# file in the state directory, then one rename into workers/, which launchd watches, so the agent runs once on a finished file and a
# reader never sees half a note. The layout (workers/<role>.md) is bloomery's tools/board/README.md. Then ensure.sh, beside this script
# (BOARD_ENSURE names another), runs with --repo PATH if given; its line and its exit code are this script's. BOARD_REPO and the others
# reach it through the environment.
#
# Exit: 0 and 1 as ensure.sh; 64 usage (a role with characters other than letters, digits, - and _; no role; stdin a terminal); 65 an
# empty note (nothing written and the old note stays: remove workers/ROLE.md to clear a note); 74 the note could not be written.
# Runs under the Mac's bash 3.2.
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
BOARD_DIR=${BOARD_DIR:-$HOME/.cache/bloomery/board}
ENSURE=${BOARD_ENSURE:-$HERE/ensure.sh}

usage() { echo "board-note: usage: printf 'round: x\\nETA 15:00\\n' | board-note.sh [--repo PATH] ROLE" >&2; exit 64; }

# note ROLE: stdin to workers/ROLE.md, whole or not at all.
note() {
  local role=$1 tmp
  case $role in
    '' | *[!A-Za-z0-9_-]*) echo "board-note: a role is letters, digits, - and _ (got '$role')" >&2; return 64 ;;
  esac
  [ ! -t 0 ] || { echo "board-note: the note is read from stdin: printf 'round: x\\nETA 15:00\\n' | board-note.sh $role" >&2; return 64; }
  mkdir -p "$BOARD_DIR/workers" || { echo "board-note: cannot create $BOARD_DIR/workers" >&2; return 74; }
  tmp=$BOARD_DIR/.note.$$
  cat > "$tmp" || { rm -f "$tmp"; echo "board-note: cannot write the note under $BOARD_DIR" >&2; return 74; }
  if [ ! -s "$tmp" ]; then
    rm -f "$tmp"
    echo "board-note: the note is empty, nothing written (remove $BOARD_DIR/workers/$role.md to clear a note)" >&2
    return 65
  fi
  mv "$tmp" "$BOARD_DIR/workers/$role.md" || { rm -f "$tmp"; echo "board-note: cannot move the note into $BOARD_DIR/workers" >&2; return 74; }
  echo "board-note: workers/$role.md written ($(wc -l < "$BOARD_DIR/workers/$role.md" | tr -d ' ') lines)"
}

# ---- self-test: a stub ensure.sh in a scratch state directory; the real board and agent are never touched

self_test() {
  local t n=0 bad=0 mut=0 self=${BASH_SOURCE[0]} tag want w
  t=$(mktemp -d "${TMPDIR:-/tmp}/board-note-selftest.XXXXXX") || { echo "board-note: no temporary directory" >&2; return 74; }
  SCRATCH=$t
  trap 'rm -rf "$SCRATCH"' EXIT
  world() { # a scratch world: the stub ensure records its arguments and says one line with the exit code in ENSURE_RC
    mkdir -p "$1/board"
    cat > "$1/ensure.sh" << 'STUB'
#!/usr/bin/env bash
echo "$*" >> "$(dirname "$0")/ensure.args"
echo "ensure: ok: stub"
exit "${ENSURE_RC:-0}"
STUB
  }
  pass() { n=$((n + 1)); echo "ok $1"; }
  fail() { n=$((n + 1)); bad=$((bad + 1)); echo "FAIL $1: ${2:-}"; }
  detail() { echo "rc $RC; out: $(cat "$t/out"); err: $(cat "$t/err"); ensure args: $(tr '\n' '|' < "$t/ensure.args" 2> /dev/null)"; }
  run() { # run SCRIPT [ARGS]: stdin from $STDIN (default empty); stdout in $t/out, stderr in $t/err, rc in RC
    local script=$1
    shift
    RC=0
    BOARD_DIR=$t/board BOARD_ENSURE=$t/ensure.sh bash "$script" "$@" > "$t/out" 2> "$t/err" < "${STDIN:-/dev/null}" || RC=$?
  }
  prep() { rm -rf "$t/board" "$t/ensure.args"; mkdir -p "$t/board"; }

  cases() {
    local s=$1 tty
    prep; STDIN=$t/in; printf 'round: boardfix\nETA 14:00\n' > "$STDIN"; run "$s" lead
    if [ "$RC" = 0 ] && [ "$(cat "$t/board/workers/lead.md")" = "$(printf 'round: boardfix\nETA 14:00')" ] \
      && [ "$(sed -n 1p "$t/out")" = 'board-note: workers/lead.md written (2 lines)' ] && [ "$(sed -n 2p "$t/out")" = 'ensure: ok: stub' ] \
      && [ "$(wc -l < "$t/ensure.args" | tr -d ' ')" = 1 ] && [ ! -s "$t/err" ] && [ -z "$(ls -A "$t/board" | grep '^\.note')" ]; then
      pass "note: stdin lands whole in workers/ROLE.md, then ensure.sh runs once and its line follows, no temp file left"
    else fail "note: stdin lands whole in workers/ROLE.md, then ensure.sh runs once and its line follows, no temp file left" "$(detail)"; fi
    run "$s" --repo /some/checkout lead
    if [ "$RC" = 0 ] && [ "$(tail -1 "$t/ensure.args")" = '--repo /some/checkout' ]; then pass "note: --repo PATH reaches ensure.sh"
    else fail "note: --repo PATH reaches ensure.sh" "$(detail)"; fi
    ENSURE_RC=1 run "$s" lead
    if [ "$RC" = 1 ] && grep -q '^ensure: ok: stub$' "$t/out"; then pass "note: ensure.sh's exit code is the script's, and its line is shown"
    else fail "note: ensure.sh's exit code is the script's, and its line is shown" "$(detail)"; fi
    for w in 'a/b' '../x' 'x y' '.hid' '-x/'; do
      prep; run "$s" "$w"
      if [ "$RC" = 64 ] && [ -s "$t/err" ] && [ ! -e "$t/board/workers" ] && [ ! -e "$t/ensure.args" ]; then pass "note: the role '$w' is refused with 64, nothing written, ensure.sh not run"
      else fail "note: the role '$w' is refused with 64, nothing written, ensure.sh not run" "$(detail)"; fi
    done
    prep; run "$s"
    if [ "$RC" = 64 ] && [ -s "$t/err" ] && [ ! -e "$t/ensure.args" ]; then pass "note: no role is 64"
    else fail "note: no role is 64" "$(detail)"; fi
    prep; STDIN=$t/in; printf 'one\n' > "$STDIN"; run "$s" lead; : > "$STDIN"; rm -f "$t/ensure.args"; run "$s" lead
    if [ "$RC" = 65 ] && grep -q 'the note is empty' "$t/err" && [ "$(cat "$t/board/workers/lead.md")" = one ] && [ ! -e "$t/ensure.args" ] && [ ! -s "$t/out" ]; then
      pass "note: an empty note is 65, the old note stays, ensure.sh not run"
    else fail "note: an empty note is 65, the old note stays, ensure.sh not run" "$(detail)"; fi
    prep; : > "$t/board/workers"; STDIN=$t/in; printf 'x\n' > "$STDIN"; run "$s" lead
    if [ "$RC" = 74 ] && grep -q 'cannot create' "$t/err" && [ ! -e "$t/ensure.args" ]; then pass "note: a state directory that cannot take workers/ is 74, named, ensure.sh not run"
    else fail "note: a state directory that cannot take workers/ is 74, named, ensure.sh not run" "$(detail)"; fi
    # stdin a terminal: python's pty gives the script one; a script that waits for it is ended by the alarm (the shell then reads 142)
    prep; STDIN=''
    tty=$(BOARD_DIR=$t/board BOARD_ENSURE=$t/ensure.sh python3 -c 'import os, pty, signal, sys
signal.alarm(10)
sys.exit(os.waitstatus_to_exitcode(pty.spawn(["bash", sys.argv[1], "lead"])))' "$s" 2> /dev/null > "$t/tty.out"; echo $?)
    if [ "$tty" = 64 ] && grep -q 'read from stdin' "$t/tty.out" && [ ! -e "$t/ensure.args" ] && [ ! -e "$t/board/workers" ]; then pass "note: a terminal as stdin is 64, named, nothing written"
    else fail "note: a terminal as stdin is 64, named, nothing written" "rc $tty; $(cat "$t/tty.out")"; fi
  }

  world "$t"
  echo "board-note self-test: the script"
  cases "$self"
  # FAIL-first: every group of cases must go red on a copy of the script with its step broken. The sed must apply, or the mutant proves
  # nothing. The mutants run side by side, each in a world of its own.
  MUTANTS=''
  mutate() { # <tag> <sed expr> <the case-name prefix that must go red>
    local tag=$1 expr=$2 want=$3 m=$t/note-$1.sh
    sed "$expr" "$self" > "$m"
    mut=$((mut + 1))
    MUTANTS="$MUTANTS $tag"
    echo "$want" > "$t/want-$tag"
    if cmp -s "$self" "$m"; then echo "the sed did not apply: $expr" > "$t/sedfail-$tag"; return; fi
    ( t=$t/w-$tag; world "$t"; cases "$m" > "$SCRATCH/out-$tag" 2>&1 ) &
  }
  mutate role "s/^    '' | \*\[!A-Za-z0-9_-\]\*) echo/    '') echo/" 'note: the role'
  mutate empty 's|^  if \[ ! -s "\$tmp" \]; then$|  if false; then|' 'note: an empty note'
  mutate no-ensure 's|^bash "\$ENSURE".*$|rc=0|' 'note: stdin lands whole'
  mutate no-repo 's|\${repo\[@\]+"\${repo\[@\]}"}||' 'note: --repo PATH reaches'
  mutate rc 's|^exit "\$rc"$|exit 0|' "note: ensure.sh's exit code"
  mutate tty 's|^  \[ ! -t 0 \] .*$|  :|' 'note: a terminal as stdin'
  mutate mkdir 's|^  mkdir -p "\$BOARD_DIR/workers" .*$|  mkdir -p "$BOARD_DIR"|' 'note: a state directory that cannot'
  wait
  for tag in $MUTANTS; do
    want=$(cat "$t/want-$tag")
    if [ -f "$t/sedfail-$tag" ]; then bad=$((bad + 1)); echo "FAIL mutant $tag: $(cat "$t/sedfail-$tag")"
    elif grep -q "^FAIL $want" "$t/out-$tag"; then echo "mutant $tag: red as expected: $(grep -m1 "^FAIL $want" "$t/out-$tag" | cut -c1-150)"
    else bad=$((bad + 1)); echo "FAIL mutant $tag: no case starting '$want' went red"; fi
  done

  if [ "$bad" = 0 ]; then echo "board-note self-test: ok ($n cases, $mut mutants red)"; return 0; fi
  echo "board-note self-test: FAIL ($bad of $n)"
  return 1
}

repo=()
role=''
have_role=0
mode=note
while [ $# -gt 0 ]; do
  case $1 in
    --repo) [ $# -ge 2 ] && [ -n "$2" ] || usage; repo=(--repo "$2"); shift 2 ;;
    --self-test) mode=self-test; shift ;;
    -*) usage ;;
    *) [ "$have_role" = 0 ] || usage; role=$1; have_role=1; shift ;;
  esac
done
if [ "$mode" = self-test ]; then
  [ "$have_role" = 0 ] && [ "${#repo[@]}" = 0 ] || usage
  self_test
  exit $?
fi
[ "$have_role" = 1 ] || usage
note "$role" || exit $?
bash "$ENSURE" ${repo[@]+"${repo[@]}"}
rc=$?
exit "$rc"
