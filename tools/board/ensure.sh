#!/usr/bin/env bash
# Keep the status board's launchd agent alive on this Mac. The board (bloomery's tools/board/README.md) moves only while
# `com.bloomery.board` runs board.py --publish: an agent that was booted out, a plist that fell behind its template, or a run that
# fails every time left the pinned issue unchanged for days while sessions kept writing notes. This notices at the next call, fixes
# what a launchctl call can fix and names the rest. It lives here, not in bloomery, because it serves this machine's agent only.
#
#   ensure.sh [--repo PATH]               check the agent, fix it, print one line
#   ensure.sh [--repo PATH] --self-test   stub launchctl and stub board.py in a scratch directory; no agent is touched
#
# PATH (or BOARD_REPO) is a bloomery checkout: the plist template and board.py are its. A worktree of it names its main checkout,
# which is the one the agent runs, so the agent never points into a track's tree. The checkout is kept in BOARD_DIR/REPO after a
# call that named one, so later calls need no flag; a call with none and nothing kept is exit 64.
#
# The check, in this order; the output line carries every launchctl call of the run with its exit code:
# 1. The agent is not loaded (launchctl print rc 113): render the plist from the checkout's template as bloomery's tools/board/README.md
#    "Install" does, write it to ~/Library/LaunchAgents, bootstrap it.
# 2. The installed plist differs from a fresh render, or the definition launchd holds does not run the render's command (a plist
#    edited after it was loaded): bootout, wait until the agent is gone, write the render, bootstrap.
# 3. board.py --stamp-status (the stamp that board.py --publish writes after every attempt) says the agent is not
#    publishing: the stamp is missing, unreadable or older than 3 x StartInterval, or the last 3 attempts failed.
#    kickstart -k, and the warning names the last problem line (and, if gh has no token for the account, says so). A last
#    attempt that failed fewer than 3 times in a row is a warning with no kick, and so is a run that has been going for less
#    than StartInterval: a slow run is not a dead one, and a kick would restart it from nothing.
# An install or a kick is not repeated for 120 s.
#
# The line starts `ensure: ok:` (nothing to do), `ensure: FIXED:` (the agent was installed or re-installed) or
# `ensure: WARN:` (something is still wrong, with its text). Exit: 0 ok or fixed; 1 a warning; 64 usage (no checkout named). A caller
# that ignores the code loses nothing to it, and one that reads the line sees every failure by name. Not macOS: one line, exit 0.
#
# Callers: board-note.sh (a session's note), and bloomery's tools/gate-batch.sh through its start hook, set once in the shell profile:
#   export BLOOMERY_BATCH_START_HOOK="bash <this directory>/ensure.sh --repo <the bloomery checkout>"
#
# Environment, all optional: BOARD_REPO, BOARD_DIR (state directory, default ~/.cache/bloomery/board), BOARD_AGENTS (default
# ~/Library/LaunchAgents), BOARD_ISSUE (the pinned issue's number; kept in BOARD_DIR/ISSUE, the install's memory of it), BOARD_GHUSER
# (default midagedev); BOARD_LAUNCHCTL, BOARD_GH, BOARD_PS, BOARD_PY and BOARD_UNAME are the self-test's stubs.
# Runs under the Mac's bash 3.2: no associative arrays, no mapfile.
set -uo pipefail

LABEL=com.bloomery.board
BOARD_DIR=${BOARD_DIR:-$HOME/.cache/bloomery/board}
AGENTS=${BOARD_AGENTS:-$HOME/Library/LaunchAgents}
LAUNCHCTL=${BOARD_LAUNCHCTL:-launchctl}
GHUSER=${BOARD_GHUSER:-midagedev}
GH=${BOARD_GH:-gh}
STAMP=publish.stamp # board.py's file in the state directory
PS=${BOARD_PS:-ps}
UNAME=${BOARD_UNAME:-$(uname)}
STALE_RUNS=3 # the stamp is stale after this many StartInterval periods, and red after this many failed attempts in a row
KICK_MIN=120 # seconds before an install or a kick is repeated
LOCK_DEAD=120 # seconds after which another ensure's lock is taken over even if its pid still answers

CALLS='' # every launchctl call of this run with its rc, appended to the output line

say() { printf 'ensure: %s%s\n' "$1" "${CALLS:+ (launchctl: $CALLS)}"; }

# lc VERB ARGS…: one launchctl call; its rc joins CALLS, its output is LC_OUT, its rc LC_RC.
lc() {
  local verb=$1
  shift
  LC_OUT=$("$LAUNCHCTL" "$verb" "$@" 2>&1)
  LC_RC=$?
  CALLS="${CALLS:+$CALLS, }$verb rc=$LC_RC"
}

first_line() { printf '%s\n' "$1" | awk 'NF { print; exit }' | cut -c1-200; }

# plist_value KEY FILE: the value on the line after <key>KEY</key>.
plist_value() {
  awk -v k="<key>$1</key>" 'index($0, k) { getline; gsub(/.*<(string|integer)>|<\/(string|integer)>.*/, ""); print; exit }' "$2"
}

# main_of PATH: the checkout the agent should run from. PATH, absolute; a git work tree's root names the main checkout of its
# repository, whichever worktree it is. Not a directory: nothing and rc 1.
main_of() {
  local d common top
  d=$(cd "$1" 2> /dev/null && pwd -P) || return 1
  top=$(git -C "$d" rev-parse --show-toplevel 2> /dev/null) || top=''
  common=$(git -C "$d" rev-parse --path-format=absolute --git-common-dir 2> /dev/null) || common=''
  if [ "$top" = "$d" ] && [ "$(basename "$common")" = .git ]; then dirname "$common"; else printf '%s\n' "$d"; fi
}

# find_python PATHLIST: the first python3 on that colon list. The agent's own PATH is the list, so the PATH of whoever calls
# this cannot change the plist and make two callers re-install it back and forth.
find_python() {
  local d IFS=:
  for d in $1; do
    if [ -x "$d/python3" ]; then
      printf '%s\n' "$d/python3"
      return 0
    fi
  done
  return 1
}

# render PYTHON REPO ISSUE GHUSER HOME: the template filled in as the README's install fills it.
render() {
  sed -e "s|@PYTHON@|$1|" -e "s|@REPO@|$2|g" -e "s|@ISSUE@|$3|" -e "s|@GHUSER@|$4|" -e "s|@HOME@|$5|g" "$TEMPLATE"
}

# last_log_line: the last line of the agent's log that is not the privacy filter's count, among its final 20 and only if the log
# was written after the stamp (the log lines carry no time: an older file holds no news); else (none: why).
last_log_line() {
  local log=$BOARD_DIR/launchd.log l
  [ -f "$log" ] || { printf '(none: no %s)' "$log"; return 0; }
  if [ -f "$BOARD_DIR/$STAMP" ] && ! [ "$log" -nt "$BOARD_DIR/$STAMP" ]; then
    printf '(none: no log output since the last stamp)'
    return 0
  fi
  l=$(tail -n 20 "$log" | grep -v 'lines withheld' | awk 'NF { l = $0 } END { print l }' | cut -c1-200)
  [ -n "$l" ] || l="(none: no problem line in the last 20 lines of the log)"
  printf '%s' "$l"
}

# running_secs PRINT_OUTPUT: how long the job's current run has been going (the pid of launchctl print's output, ps's elapsed time),
# or nothing and rc 1 when no run is going.
running_secs() {
  local pid
  pid=$(printf '%s\n' "$1" | awk '/^\tstate = running$/ { r = 1 } /^\tpid = / { p = $3 } END { if (r) print p }')
  [ -n "$pid" ] || return 1
  "$PS" -o etime= -p "$pid" 2> /dev/null | tr -d ' ' | awk -F'[-:]' 'NF == 2 { print $1 * 60 + $2 } NF == 3 { print ($1 * 60 + $2) * 60 + $3 } NF == 4 { print (($1 * 24 + $2) * 60 + $3) * 60 + $4 }' | grep .
}

# no_token: when gh holds no token for the agent's account (the plist's first step), why, on one line; else nothing and rc 1.
no_token() {
  local e
  e=$("$GH" auth token --user "$GHUSER" 2>&1 > /dev/null) && return 1
  printf 'gh has no token for %s: %s' "$GHUSER" "$(first_line "$e")"
}

# kick_due: no install or kick in the last KICK_MIN seconds.
kick_due() {
  local t
  t=$(cat "$BOARD_DIR/ensure.kick" 2> /dev/null) || return 0
  case $t in '' | *[!0-9]*) return 0 ;; esac
  [ $(($(date +%s) - t)) -ge "$KICK_MIN" ]
}

# install_plist: the fresh render becomes the installed plist, whole or not at all.
install_plist() {
  cp "$FRESH" "$PLIST.new" && mv "$PLIST.new" "$PLIST" || { say "WARN: cannot write $PLIST"; return 1; }
}

# bootstrap: load the agent (RunAtLoad starts its first run, which writes the first stamp); counts as a kick.
bootstrap() {
  lc bootstrap "$DOMAIN" "$PLIST"
  if [ "$LC_RC" != 0 ]; then
    say "WARN: launchctl bootstrap rc=$LC_RC: $(first_line "$LC_OUT")"
    return 1
  fi
  date +%s > "$BOARD_DIR/ensure.kick"
}

# ensure: the check; every return has said its line.
ensure() {
  local python issue interval max_age st k v state='' age='' rc='' streak='' last='' why cmdline printed secs tok
  resolve_repo || return $?
  TEMPLATE=$REPO/tools/board/com.bloomery.board.plist
  why=$(template_ok "$REPO") || { say "WARN: $why"; return 1; }
  issue=${BOARD_ISSUE:-$(cat "$BOARD_DIR/ISSUE" 2> /dev/null)}
  case $issue in '' | *[!0-9]*) say "WARN: no board issue number (set BOARD_ISSUE once; it is kept in $BOARD_DIR/ISSUE)"; return 1 ;; esac
  python=$(find_python "$(plist_value PATH "$TEMPLATE")") || { say "WARN: no python3 on the agent's PATH ($(plist_value PATH "$TEMPLATE"))"; return 1; }
  DOMAIN=gui/$(id -u)
  PLIST=$AGENTS/$LABEL.plist
  mkdir -p "$BOARD_DIR/trains" "$BOARD_DIR/batch" "$BOARD_DIR/workers" "$AGENTS" || { say "WARN: cannot create $BOARD_DIR or $AGENTS"; return 1; }
  [ "$(cat "$BOARD_DIR/ISSUE" 2> /dev/null)" = "$issue" ] || printf '%s\n' "$issue" > "$BOARD_DIR/ISSUE"
  [ "$(cat "$BOARD_DIR/REPO" 2> /dev/null)" = "$REPO" ] || printf '%s\n' "$REPO" > "$BOARD_DIR/REPO"
  FRESH=$BOARD_DIR/.ensure.plist.$$
  render "$python" "$REPO" "$issue" "$GHUSER" "$HOME" > "$FRESH" || { say "WARN: the plist did not render from $TEMPLATE"; return 1; }

  lc print "$DOMAIN/$LABEL"
  printed=$LC_OUT
  case $LC_RC in
    0) ;;
    113)
      install_plist && bootstrap || return 1
      say "FIXED: the board agent was not loaded; wrote $PLIST and bootstrapped it"
      return 0 ;;
    *) say "WARN: launchctl print rc=$LC_RC: $(first_line "$LC_OUT")"; return 1 ;;
  esac
  cmdline=$(sed -n 's|^ *<string>\(.*board\.py.*\)</string>$|\1|p' "$FRESH")
  if ! cmp -s "$FRESH" "$PLIST" || ! printf '%s\n' "$printed" | grep -qF -- "$cmdline"; then
    lc bootout "$DOMAIN/$LABEL"
    [ "$LC_RC" = 0 ] || { say "WARN: launchctl bootout rc=$LC_RC: $(first_line "$LC_OUT")"; return 1; }
    for k in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do # bootout returns before the service is gone: bootstrap would fail on it
      lc print "$DOMAIN/$LABEL"
      [ "$LC_RC" = 0 ] || break
      sleep 0.25
    done
    install_plist && bootstrap || return 1
    say "FIXED: the installed plist or the loaded definition differed from a fresh render of the template; wrote it and re-bootstrapped"
    return 0
  fi

  interval=$(plist_value StartInterval "$PLIST")
  case $interval in '' | *[!0-9]*) say "WARN: no StartInterval in $PLIST"; return 1 ;; esac
  max_age=$((STALE_RUNS * interval))
  BOARD_PY=${BOARD_PY:-$REPO/tools/board/board.py}
  st=$("$python" "$BOARD_PY" --stamp-status "$max_age" --dir "$BOARD_DIR" 2>&1) || { say "WARN: $BOARD_PY --stamp-status failed: $(first_line "$st")"; return 1; }
  while IFS== read -r k v; do
    case $k in state) state=$v ;; age) age=$v ;; rc) rc=$v ;; streak) streak=$v ;; last) last=$v ;; esac
  done << EOF
$st
EOF
  case $state in
    ok) say "ok: the board agent is loaded and publishing (last attempt ${age}s ago, rc=$rc)"; return 0 ;;
    failing) say "WARN: the last publish failed (rc=$rc, $streak in a row; a kick at $STALE_RUNS): ${last:-no text}"; return 1 ;;
    red) why="the last $streak publishes failed (rc=$rc): ${last:-no text}" ;;
    stale) why="no publish for ${age}s (limit ${max_age}s); last problem line: $(last_log_line)" ;;
    missing) why="the agent has written no stamp; last problem line: $(last_log_line)" ;;
    unreadable) why="the stamp cannot be read: $last" ;;
    *) say "WARN: --stamp-status said state=${state:-nothing}: $(first_line "$st")"; return 1 ;;
  esac
  tok=$(no_token) && why="$why; $tok"
  if secs=$(running_secs "$printed") && [ "$secs" -lt "$interval" ]; then
    say "WARN: $why; a run has been going for ${secs}s, not kicked"
    return 1
  fi
  if ! kick_due; then
    say "WARN: $why; kicked less than ${KICK_MIN}s ago, not again yet"
    return 1
  fi
  lc kickstart -k "$DOMAIN/$LABEL"
  date +%s > "$BOARD_DIR/ensure.kick"
  if [ "$LC_RC" = 0 ]; then say "WARN: $why; kickstart -k sent"; else say "WARN: $why; kickstart -k failed: $(first_line "$LC_OUT")"; fi
  return 1
}

# locked_ensure: one ensure at a time. Sessions and batches call this at the same moment, and two bootstraps race to a false
# warning. The lock is a directory holding its owner's pid and start; a dead owner's, or one older than LOCK_DEAD, is taken over.
locked_ensure() {
  local lock=$BOARD_DIR/ensure.lock pid='' t=0 rc
  [ "$UNAME" = Darwin ] || { say "ok: not macOS ($UNAME); the board agent is a launchd job, nothing to do"; return 0; }
  mkdir -p "$BOARD_DIR" || { say "WARN: cannot create $BOARD_DIR"; return 1; }
  if ! mkdir "$lock" 2> /dev/null; then
    read -r pid t 2> /dev/null < "$lock/owner" || { pid=''; t=0; }
    if [ -n "$pid" ] && kill -0 "$pid" 2> /dev/null && [ $(($(date +%s) - t)) -lt "$LOCK_DEAD" ]; then
      say "ok: another ensure (pid $pid) is running; not repeated"
      return 0
    fi
    rm -rf "$lock"
    mkdir "$lock" 2> /dev/null || { say "WARN: cannot take $lock"; return 1; }
  fi
  echo "$$ $(date +%s)" > "$lock/owner"
  ensure
  rc=$?
  rm -rf "$lock" "$BOARD_DIR/.ensure.plist.$$"
  return "$rc"
}

# template_ok DIR: the checkout at DIR carries a plist template this script can render and read: every @WORD@ it fills, a numeric
# StartInterval, a PATH and the board.py command line. Prints why not, rc 1. An unfilled word would be installed as it is.
template_ok() {
  local tpl=$1/tools/board/com.bloomery.board.plist r left
  [ -f "$tpl" ] || { echo "no plist template at $tpl"; return 1; }
  r=$(TEMPLATE=$tpl render /py "$1" 7 user /home) || { echo "the template does not render: $tpl"; return 1; }
  left=$(printf '%s\n' "$r" | grep -o '@[A-Z]*@' | sort -u | tr '\n' ' ')
  [ -z "$left" ] || { echo "the render of $tpl leaves ${left}unfilled (this script fills @PYTHON@ @REPO@ @ISSUE@ @GHUSER@ @HOME@)"; return 1; }
  case $(plist_value StartInterval "$tpl") in '' | *[!0-9]*) echo "no numeric StartInterval in $tpl"; return 1 ;; esac
  [ -n "$(plist_value PATH "$tpl")" ] || { echo "no PATH in $tpl"; return 1; }
  [ -n "$(printf '%s\n' "$r" | sed -n 's|^ *<string>\(.*board\.py.*\)</string>$|\1|p')" ] || { echo "no board.py command line in $tpl"; return 1; }
}

# resolve_repo: REPO, the main checkout the agent runs from. --repo, else BOARD_REPO, else the one kept in BOARD_DIR/REPO. It says its
# WARN line itself: rc 64 when none is named, 1 when the one named is not a directory.
resolve_repo() {
  local from want
  if [ -n "$REPO_ARG" ]; then from='--repo'; want=$REPO_ARG
  elif [ -n "${BOARD_REPO:-}" ]; then from='BOARD_REPO'; want=$BOARD_REPO
  else from="$BOARD_DIR/REPO"; want=$(cat "$from" 2> /dev/null)
  fi
  [ -n "$want" ] || { say "WARN: no bloomery checkout named: pass --repo PATH or set BOARD_REPO (it is kept in $BOARD_DIR/REPO after a call that names one)"; return 64; }
  REPO=$(main_of "$want") || { say "WARN: the bloomery checkout $want ($from) is not a directory"; return 1; }
}

# check_template: the checkout's template and board.py are ones this script can use (--check-template): after a change to either side.
check_template() {
  local why bp
  resolve_repo || return $?
  why=$(template_ok "$REPO") || { say "WARN: $why"; return 1; }
  bp=$REPO/tools/board/board.py
  [ -f "$bp" ] || { say "WARN: no board.py at $bp"; return 1; }
  grep -q -- '--stamp-status' "$bp" || { say "WARN: $bp has no --stamp-status: that checkout is older than the stamp"; return 1; }
  say "ok: the template and board.py in $REPO are ones this script can use"
}

# ---- self-test: stub launchctl and stub board.py in a scratch world; the real agent is never touched

self_test() {
  local t n=0 bad=0 mut=0 self=${BASH_SOURCE[0]}
  t=$(mktemp -d "${TMPDIR:-/tmp}/board-ensure-selftest.XXXXXX")
  t=$(cd "$t" && pwd -P) # the render names the canonical path of the checkout
  SCRATCH=$t
  trap 'rm -rf "$SCRATCH"' EXIT
  # world DIR: a scratch world with the stubs; the cases run in one, each mutant in its own so they can run side by side.
  # launchctl keeps "loaded" in a file and every call in calls.log; a file rc-VERB makes that verb fail with the rc it holds.
  world() {
    mkdir -p "$1/repo/tools/board" "$1/stub"
    # the template's keys that this script reads, as bloomery's tools/board/com.bloomery.board.plist has them (template_ok holds a real one to them)
    cat > "$1/repo/tools/board/com.bloomery.board.plist" << 'PLIST'
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.bloomery.board</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>-c</string>
    <string>GH_TOKEN=$(gh auth token --user @GHUSER@) || exit 1; export GH_TOKEN; exec @PYTHON@ @REPO@/tools/board/board.py --publish @ISSUE@</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>StartInterval</key>
  <integer>600</integer>
  <key>StandardOutPath</key>
  <string>@HOME@/.cache/bloomery/board/launchd.log</string>
</dict>
</plist>
PLIST
    cat > "$1/stub/launchctl" << 'STUB'
#!/usr/bin/env bash
d=$STUB_DIR
echo "$*" >> "$d/calls.log"
v=$1
[ ! -f "$d/rc-$v" ] || { echo "stub $v failed" >&2; exit "$(cat "$d/rc-$v")"; }
case $v in
  print) # a loaded agent shows its state and the strings of the definition launchd holds (the copy made at bootstrap)
    if [ -f "$d/loaded" ]; then
      if [ -f "$d/running" ]; then printf '\tstate = running\n\tpid = %s\n' "$(cat "$d/running")"; else printf '\tstate = not running\n'; fi
      sed -n 's|^ *<string>\(.*\)</string>$|\t\t\1|p' "$d/loaded"
      exit 0
    fi
    echo "Could not find service" >&2; exit 113 ;;
  bootstrap) cp "$3" "$d/loaded" ;;
  bootout) rm -f "$d/loaded" ;;
esac
STUB
    # board.py's stand-in: it records its arguments and prints the canned --stamp-status.
    cat > "$1/repo/tools/board/board.py" << 'STUB'
# answers --stamp-status
import os, sys
d = os.environ["STUB_DIR"]
open(d + "/board-args", "a").write(" ".join(sys.argv[1:]) + "\n")
sys.stdout.write(open(d + "/status").read())
STUB
    # gh and ps: a token unless rc-gh exists; the elapsed time in the file etime
    cat > "$1/stub/gh" << 'STUB'
#!/usr/bin/env bash
[ ! -f "$STUB_DIR/rc-gh" ] || { echo "no oauth token found for github.com account $4" >&2; exit 1; }
echo "a-token-that-must-not-be-printed"
STUB
    cat > "$1/stub/ps" << 'STUB'
#!/usr/bin/env bash
cat "$STUB_DIR/etime"
STUB
    chmod +x "$1/stub/launchctl" "$1/stub/gh" "$1/stub/ps"
  }
  world "$t"
  export STUB_DIR=$t/stub

  prep() { # a fresh scratch world: nothing loaded, a healthy canned status
    rm -rf "$t/home" "$t/board" "$t/agents" "$t/stub/calls.log" "$t/stub/board-args" "$t/stub"/rc-* "$t/stub/loaded" "$t/stub/running"
    mkdir -p "$t/home" "$t/board" "$t/agents"
    printf 'state=ok\nage=30\nrc=0\nproblems=0\nstreak=0\nlast=\n' > "$t/stub/status"
    : > "$t/stub/calls.log"
  }
  status() { printf 'state=%s\nage=%s\nrc=%s\nproblems=1\nstreak=%s\nlast=%s\n' "$1" "$2" "$3" "$4" "$5" > "$t/stub/status"; }
  run() { # run SCRIPT [ARGS]: the script in the scratch world; stdout in $t/out, stderr in $t/err, its rc in RC
    local script=$1
    shift
    RC=0
    HOME=$t/home BOARD_DIR=$t/board BOARD_AGENTS=$t/agents BOARD_REPO=${REPO_ENV-$t/repo} BOARD_ISSUE=7 BOARD_GHUSER=tester \
      BOARD_LAUNCHCTL=$t/stub/launchctl BOARD_GH=$t/stub/gh BOARD_PS=$t/stub/ps BOARD_UNAME=${UN:-Darwin} bash "$script" "$@" > "$t/out" 2> "$t/err" < "${STDIN:-/dev/null}" || RC=$?
  }
  fresh() { # the plist a correct install writes in the scratch world
    local tpl=$t/repo/tools/board/com.bloomery.board.plist
    TEMPLATE=$tpl render "$(find_python "$(plist_value PATH "$tpl")")" "$t/repo" 7 tester "$t/home"
  }
  load_current() { fresh > "$t/agents/$LABEL.plist"; cp "$t/agents/$LABEL.plist" "$t/stub/loaded"; }
  age() { sed 's|/tools/board/board.py|/tools/board/old.py|' "$1" > "$t/p" && mv "$t/p" "$1"; }
  age_plist() { age "$t/agents/$LABEL.plist"; } # the file on disk falls behind the template
  age_loaded() { age "$t/stub/loaded"; } # the file is current and the definition launchd holds is not
  pass() { n=$((n + 1)); echo "ok $1"; }
  fail() { n=$((n + 1)); bad=$((bad + 1)); echo "FAIL $1: ${2:-}"; }
  one() { [ "$(wc -l < "$t/out" | tr -d ' ')" = 1 ] && [ ! -s "$t/err" ]; } # exactly one stdout line, nothing on stderr
  has() { grep -Eq -- "$1" "${2:-$t/out}"; }
  kicks() { grep -c '^kickstart' "$t/stub/calls.log" || true; }
  detail() { echo "rc $RC; out: $(cat "$t/out"); err: $(cat "$t/err"); calls: $(tr '\n' '|' < "$t/stub/calls.log")"; }

  # cases SCRIPT: the spec's five states, then the edges, against the script given. Prints ok/FAIL lines.
  cases() {
    local s=$1 w limit tpl=$t/repo/tools/board/com.bloomery.board.plist
    limit=$((STALE_RUNS * $(plist_value StartInterval "$tpl")))

    prep; run "$s"
    if [ "$RC" = 0 ] && one && has '^ensure: FIXED: the board agent was not loaded' && has 'launchctl: print rc=113, bootstrap rc=0\)$' \
      && has "^bootstrap gui/$(id -u) $t/agents/$LABEL.plist\$" "$t/stub/calls.log" && cmp -s "$t/agents/$LABEL.plist" <(fresh) \
      && ! grep -q '@[A-Z]*@' "$t/agents/$LABEL.plist" && grep -q 'tester' "$t/agents/$LABEL.plist"; then
      pass "not loaded: renders the plist from the template, bootstraps it, one FIXED line with every launchctl rc, exit 0"
    else fail "not loaded: renders the plist from the template, bootstraps it, one FIXED line with every launchctl rc, exit 0" "$(detail)"; fi
    if [ "$(cat "$t/board/ISSUE")" = 7 ] && [ -d "$t/board/workers" ] && [ -d "$t/board/batch" ] && [ -d "$t/board/trains" ]; then
      pass "not loaded: the issue number is kept and the watched directories exist"
    else fail "not loaded: the issue number is kept and the watched directories exist" "$(ls -a "$t/board")"; fi

    prep; load_current; age_plist; run "$s"
    if [ "$RC" = 0 ] && one && has '^ensure: FIXED: the installed plist or the loaded definition differed' && has 'bootout rc=0.*bootstrap rc=0\)$' && cmp -s "$t/agents/$LABEL.plist" <(fresh) \
      && [ "$(grep -n '^bootout' "$t/stub/calls.log" | cut -d: -f1)" -lt "$(grep -n '^bootstrap' "$t/stub/calls.log" | cut -d: -f1)" ]; then
      pass "stale plist: boots out, writes the render, boots in; one FIXED line, exit 0"
    else fail "stale plist: boots out, writes the render, boots in; one FIXED line, exit 0" "$(detail)"; fi

    prep; load_current; status stale 9000 0 0 old
    : > "$t/board/$STAMP"; touch -t 202001010000 "$t/board/$STAMP" # the log below is written after the stamp
    printf 'board.py: 1 lines withheld (tilde-home)\nno oauth token found for github.com account tester\nboard.py: 1 lines withheld (tilde-home)\n' > "$t/board/launchd.log"
    run "$s"
    if [ "$RC" = 1 ] && one && has '^ensure: WARN: no publish for 9000s .*; last problem line: no oauth token found for github.com account tester; kickstart -k sent' \
      && has 'kickstart rc=0\)$' && has "^kickstart -k gui/$(id -u)/$LABEL\$" "$t/stub/calls.log"; then
      pass "stale stamp: kickstart -k, one WARN line with the age and the last problem line of launchd.log, exit 1"
    else fail "stale stamp: kickstart -k, one WARN line with the age and the last problem line of launchd.log, exit 1" "$(detail)"; fi
    if grep -q -- "^--stamp-status $limit --dir $t/board\$" "$t/stub/board-args"; then pass "stale stamp: the limit asked of board.py is 3 x StartInterval ($limit s)"
    else fail "stale stamp: the limit asked of board.py is 3 x StartInterval ($limit s)" "$(cat "$t/stub/board-args")"; fi
    run "$s"
    if [ "$RC" = 1 ] && one && has 'kicked less than 120s ago, not again yet' && [ "$(kicks)" = 1 ]; then pass "stale stamp: a second call inside the kick window warns and does not kick again"
    else fail "stale stamp: a second call inside the kick window warns and does not kick again" "$(detail)"; fi
    echo $(($(date +%s) - 200)) > "$t/board/ensure.kick"; run "$s"
    if [ "$RC" = 1 ] && [ "$(kicks)" = 2 ]; then pass "stale stamp: after the window it kicks again"; else fail "stale stamp: after the window it kicks again" "$(detail)"; fi

    prep; load_current; age_loaded; run "$s"
    if [ "$RC" = 0 ] && one && has '^ensure: FIXED: the installed plist or the loaded definition differed' && has 'bootout rc=0.*bootstrap rc=0\)$' \
      && cmp -s "$t/stub/loaded" <(fresh); then
      pass "loaded definition behind the file: boots out and in, so launchd holds the render"
    else fail "loaded definition behind the file: boots out and in, so launchd holds the render" "$(detail)"; fi

    prep; load_current; echo 4242 > "$t/stub/running"; echo 00:42 > "$t/stub/etime"; status stale 9000 0 0 old; run "$s"
    if [ "$RC" = 1 ] && one && has 'WARN: no publish for 9000s .*; a run has been going for 42s, not kicked' && [ "$(kicks)" = 0 ]; then
      pass "stale stamp, a run under StartInterval going: warns with the run's age and does not kick it"
    else fail "stale stamp, a run under StartInterval going: warns with the run's age and does not kick it" "$(detail)"; fi
    for w in 10:00 01:00:00 1-00:00:00; do
      echo "$w" > "$t/stub/etime"; rm -f "$t/board/ensure.kick"; run "$s"
      if [ "$RC" = 1 ] && has 'kickstart -k sent' && [ "$(kicks)" -ge 1 ]; then pass "stale stamp, a run going $w (StartInterval or more): kicked, the elapsed time read in its ps format"
      else fail "stale stamp, a run going $w (StartInterval or more): kicked, the elapsed time read in its ps format" "$(detail)"; fi
      rm -f "$t/stub/calls.log"
    done
    prep; load_current; echo 4242 > "$t/stub/running"; echo 09:59 > "$t/stub/etime"; status red 40 1 3 'gh pr list failed (exit 1)'; run "$s"
    if [ "$RC" = 1 ] && has 'a run has been going for 599s, not kicked' && [ "$(kicks)" = 0 ]; then pass "red stamp, a run at 599 s: not kicked; the limit is StartInterval"
    else fail "red stamp, a run at 599 s: not kicked; the limit is StartInterval" "$(detail)"; fi

    prep; load_current; status stale 9000 0 0 old; echo 1 > "$t/stub/rc-gh"; run "$s"
    if [ "$RC" = 1 ] && one && has 'gh has no token for tester: no oauth token found for github.com account tester; kickstart -k sent' && ! has 'a-token-that-must' ; then
      pass "gh without a token for the account: the warning says so, and no token is printed"
    else fail "gh without a token for the account: the warning says so, and no token is printed" "$(detail)"; fi
    prep; load_current; status stale 9000 0 0 old
    : > "$t/board/$STAMP"; touch -t 202001010000 "$t/board/$STAMP"
    { echo 'board.py: gh issue edit 40 failed: an old problem'; for w in $(seq 1 25); do echo 'board.py: 1 lines withheld (tilde-home)'; done; } > "$t/board/launchd.log"; run "$s"
    if [ "$RC" = 1 ] && has 'last problem line: \(none: no problem line in the last 20 lines of the log\)' && ! has 'an old problem'; then pass "stale stamp: a problem older than the log's last 20 lines is not named as the last"
    else fail "stale stamp: a problem older than the log's last 20 lines is not named as the last" "$(detail)"; fi
    prep; load_current; status stale 9000 0 0 old
    echo 'no oauth token found for github.com account tester' > "$t/board/launchd.log"; touch -t 202001010000 "$t/board/launchd.log"; : > "$t/board/$STAMP"; run "$s"
    if [ "$RC" = 1 ] && has 'last problem line: \(none: no log output since the last stamp\)' && ! has 'oauth'; then pass "stale stamp: a log older than the stamp holds no news, so its last line is not named"
    else fail "stale stamp: a log older than the stamp holds no news, so its last line is not named" "$(detail)"; fi

    prep; load_current; status red 40 1 3 'gh pr list failed (exit 1)'; run "$s"
    if [ "$RC" = 1 ] && one && has '^ensure: WARN: the last 3 publishes failed \(rc=1\): gh pr list failed \(exit 1\); kickstart -k sent' && [ "$(kicks)" = 1 ]; then
      pass "red stamp: kickstart -k, one WARN line with the stamp's last problem, exit 1"
    else fail "red stamp: kickstart -k, one WARN line with the stamp's last problem, exit 1" "$(detail)"; fi

    prep; load_current; run "$s"
    if [ "$RC" = 0 ] && one && has '^ensure: ok: the board agent is loaded and publishing \(last attempt 30s ago, rc=0\) \(launchctl: print rc=0\)$' \
      && [ "$(cat "$t/stub/calls.log")" = "print gui/$(id -u)/$LABEL" ]; then pass "healthy: one ok line, exit 0, launchctl print was the only call"
    else fail "healthy: one ok line, exit 0, launchctl print was the only call" "$(detail)"; fi
    run "$s"
    if [ "$RC" = 0 ] && one && [ "$(grep -c . "$t/stub/calls.log")" = 2 ] && cmp -s "$t/agents/$LABEL.plist" <(fresh); then pass "healthy: a second call changes nothing"
    else fail "healthy: a second call changes nothing" "$(detail)"; fi

    prep; load_current; status failing 40 1 2 'gh issue edit 7 failed'; run "$s"
    if [ "$RC" = 1 ] && one && has 'WARN: the last publish failed \(rc=1, 2 in a row; a kick at 3\): gh issue edit 7 failed' && [ "$(kicks)" = 0 ]; then
      pass "failing below the limit: a WARN with the count and the text, no kick"
    else fail "failing below the limit: a WARN with the count and the text, no kick" "$(detail)"; fi
    for w in missing unreadable; do
      prep; load_current; status "$w" - - - 'bad stamp'; run "$s"
      if [ "$RC" = 1 ] && one && has '^ensure: WARN: .*kickstart -k sent' && [ "$(kicks)" = 1 ]; then pass "$w stamp: kickstart -k and a WARN, exit 1"
      else fail "$w stamp: kickstart -k and a WARN, exit 1" "$(detail)"; fi
    done

    prep; echo 5 > "$t/stub/rc-bootstrap"; run "$s"
    if [ "$RC" = 1 ] && one && has 'WARN: launchctl bootstrap rc=5: stub bootstrap failed' && has 'bootstrap rc=5\)$'; then pass "a failing bootstrap: exit 1, its rc and message in the one line"
    else fail "a failing bootstrap: exit 1, its rc and message in the one line" "$(detail)"; fi
    prep; echo 125 > "$t/stub/rc-print"; run "$s"
    if [ "$RC" = 1 ] && one && has 'WARN: launchctl print rc=125' && [ ! -e "$t/agents/$LABEL.plist" ] && [ "$(grep -c . "$t/stub/calls.log")" = 1 ]; then
      pass "a launchctl print that is neither loaded nor not-found: exit 1, its rc named, nothing installed"
    else fail "a launchctl print that is neither loaded nor not-found: exit 1, its rc named, nothing installed" "$(detail)"; fi
    prep; load_current; age_plist; cp "$t/agents/$LABEL.plist" "$t/aged.plist"; echo 3 > "$t/stub/rc-bootout"; run "$s"
    if [ "$RC" = 1 ] && has 'WARN: launchctl bootout rc=3' && ! has '^bootstrap' "$t/stub/calls.log" && cmp -s "$t/agents/$LABEL.plist" "$t/aged.plist"; then
      pass "a failing bootout: exit 1, no bootstrap, and the old plist stays so the next call tries again"
    else fail "a failing bootout: exit 1, no bootstrap, and the old plist stays so the next call tries again" "$(detail)"; fi
    prep; UN=Linux run "$s"
    if [ "$RC" = 0 ] && one && has '^ensure: ok: not macOS \(Linux\)' && [ ! -s "$t/stub/calls.log" ] && [ ! -e "$t/board/ensure.lock" ]; then pass "not macOS: one line, exit 0, no launchctl call"
    else fail "not macOS: one line, exit 0, no launchctl call" "$(detail)"; fi

    prep; load_current; mkdir "$t/board/ensure.lock"; echo "$$ $(date +%s)" > "$t/board/ensure.lock/owner"; run "$s"
    if [ "$RC" = 0 ] && one && has 'another ensure \(pid [0-9]+\) is running' && [ "$(grep -c . "$t/stub/calls.log")" = 0 ]; then pass "a live ensure holds the lock: one ok line, no launchctl call"
    else fail "a live ensure holds the lock: one ok line, no launchctl call" "$(detail)"; fi
    echo "999999 $(date +%s)" > "$t/board/ensure.lock/owner"; run "$s"
    if [ "$RC" = 0 ] && has '^ensure: ok: the board agent is loaded' && [ ! -e "$t/board/ensure.lock" ]; then pass "a dead owner's lock is taken over, and the lock is gone after"
    else fail "a dead owner's lock is taken over, and the lock is gone after" "$(detail)"; fi

    # the bloomery checkout: --repo, BOARD_REPO, the kept one, a worktree, and the ways it is missing or unusable
    if [ ! -d "$t/wt" ]; then
      g() { env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE git -C "$t/repo" -c user.name=t -c user.email=t@t -c commit.gpgsign=false -c core.hooksPath=/dev/null "$@"; }
      g init -q -b main && g add -A && g commit -q -m fixture && g worktree add -q "$t/wt" -b track > /dev/null 2>&1 || { echo "FAIL fixture: no scratch git repository with a worktree"; return 1; }
    fi
    cp "$tpl" "$t/tpl.good"
    prep; REPO_ENV='' run "$s" --repo "$t/repo"
    if [ "$RC" = 0 ] && one && has '^ensure: FIXED: the board agent was not loaded' && cmp -s "$t/agents/$LABEL.plist" <(fresh); then pass "repo: --repo names the checkout when BOARD_REPO is unset"
    else fail "repo: --repo names the checkout when BOARD_REPO is unset" "$(detail)"; fi
    REPO_ENV='' run "$s"
    if [ "$RC" = 0 ] && one && has '^ensure: ok: the board agent is loaded' && [ "$(cat "$t/board/REPO")" = "$t/repo" ]; then pass "repo: the checkout is kept, so the next call needs no flag"
    else fail "repo: the checkout is kept, so the next call needs no flag" "$(detail)"; fi
    prep; REPO_ENV='' run "$s"
    if [ "$RC" = 64 ] && one && has '^ensure: WARN: no bloomery checkout named: pass --repo PATH or set BOARD_REPO' && [ ! -s "$t/stub/calls.log" ] && [ -z "$(ls -A "$t/agents")" ]; then
      pass "repo: none named and none kept is 64, named, and nothing is called or installed"
    else fail "repo: none named and none kept is 64, named, and nothing is called or installed" "$(detail)"; fi
    prep; REPO_ENV='' run "$s" --repo "$t/nodir"
    if [ "$RC" = 1 ] && one && has "^ensure: WARN: the bloomery checkout $t/nodir \(--repo\) is not a directory" && [ ! -s "$t/stub/calls.log" ]; then pass "repo: a path that is not a directory is named with where it came from"
    else fail "repo: a path that is not a directory is named with where it came from" "$(detail)"; fi
    prep; echo "$t/gone" > "$t/board/REPO"; REPO_ENV='' run "$s"
    if [ "$RC" = 1 ] && has "^ensure: WARN: the bloomery checkout $t/gone \($t/board/REPO\) is not a directory"; then pass "repo: a kept checkout that is gone is named with the file it was kept in"
    else fail "repo: a kept checkout that is gone is named with the file it was kept in" "$(detail)"; fi
    mkdir -p "$t/empty"; prep; run "$s" --repo "$t/empty"
    if [ "$RC" = 1 ] && one && has "^ensure: WARN: no plist template at $t/empty/tools/board/com.bloomery.board.plist" && [ -z "$(ls -A "$t/agents")" ]; then pass "repo: a directory without the template is named and nothing is installed"
    else fail "repo: a directory without the template is named and nothing is installed" "$(detail)"; fi
    prep; run "$s" --repo "$t/wt"
    if [ "$RC" = 0 ] && cmp -s "$t/agents/$LABEL.plist" <(fresh) && ! grep -qF "$t/wt" "$t/agents/$LABEL.plist" && [ "$(cat "$t/board/REPO")" = "$t/repo" ]; then
      pass "repo: a worktree names its main checkout, so the agent never points into a track's tree"
    else fail "repo: a worktree names its main checkout, so the agent never points into a track's tree" "$(detail)"; fi
    prep; REPO_ENV=$t/empty run "$s" --repo "$t/repo"
    if [ "$RC" = 0 ] && cmp -s "$t/agents/$LABEL.plist" <(fresh); then pass "repo: --repo beats BOARD_REPO"
    else fail "repo: --repo beats BOARD_REPO" "$(detail)"; fi

    # the template this script renders and the board.py it asks
    prep; run "$s" --check-template
    if [ "$RC" = 0 ] && one && has '^ensure: ok: the template and board.py in .* are ones this script can use' && [ ! -s "$t/stub/calls.log" ]; then pass "template: --check-template passes a template and a board.py it can use, and calls nothing"
    else fail "template: --check-template passes a template and a board.py it can use, and calls nothing" "$(detail)"; fi
    echo '<string>@NEWWORD@</string>' >> "$tpl"
    prep; run "$s"
    if [ "$RC" = 1 ] && one && has 'leaves @NEWWORD@ unfilled' && [ -z "$(ls -A "$t/agents")" ] && ! has '^bootstrap' "$t/stub/calls.log"; then
      pass "template: a word the render leaves unfilled is named and the plist is not installed"
    else fail "template: a word the render leaves unfilled is named and the plist is not installed" "$(detail)"; fi
    cp "$t/tpl.good" "$tpl"
    mv "$t/repo/tools/board/board.py" "$t/board.py.keep"; printf 'print("old")\n' > "$t/repo/tools/board/board.py"
    prep; run "$s" --check-template
    if [ "$RC" = 1 ] && one && has 'board.py has no --stamp-status|board.py has no --stamp-status: that checkout is older'; then pass "template: --check-template names a board.py that is older than the stamp"
    else fail "template: --check-template names a board.py that is older than the stamp" "$(detail)"; fi
    mv "$t/board.py.keep" "$t/repo/tools/board/board.py"
  }

  echo "ensure self-test: the script"
  cases "$self"
  # FAIL-first: every group of cases must go red on a copy of the script with its step broken. The sed must apply, or the mutant proves
  # nothing. The mutants run side by side, each in a world of its own (cases reads $t and STUB_DIR, which the subshell moves).
  MUTANTS=''
  mutate() { # <tag> <sed expr> <the case-name prefix that must go red>
    local tag=$1 expr=$2 want=$3 m=$t/ensure-$1.sh
    sed "$expr" "$self" > "$m"
    mut=$((mut + 1))
    MUTANTS="$MUTANTS $tag"
    echo "$want" > "$t/want-$tag"
    if cmp -s "$self" "$m"; then echo "the sed did not apply: $expr" > "$t/sedfail-$tag"; return; fi
    ( t=$t/w-$tag; world "$t"; STUB_DIR=$t/stub; export STUB_DIR; cases "$m" > "$SCRATCH/out-$tag" 2>&1 ) &
  }
  mutate not-loaded 's|^      install_plist && bootstrap \|\| return 1$|      true|' 'not loaded: renders'
  mutate stale-plist 's#^  if ! cmp -s "\$FRESH" "\$PLIST" ||#  if false ||#' 'stale plist'
  mutate stale-stamp 's|^    stale) why=.*$|    stale) say "ok: ignored"; return 0 ;;|' 'stale stamp: kickstart'
  mutate red-stamp 's|^    red) why=.*$|    red) say "ok: ignored"; return 0 ;;|' 'red stamp'
  mutate healthy-kick 's|^    ok) say |    ok) lc kickstart -k "x"; say |' 'healthy: one ok line'
  mutate kick-window 's|^  t=\$(cat "\$BOARD_DIR/ensure.kick" 2> /dev/null) \|\| return 0$|  return 0|' 'stale stamp: a second call'
  mutate no-rc 's|^  CALLS="\${CALLS:+\$CALLS, }\$verb rc=\$LC_RC"$|  CALLS=""|' 'not loaded: renders'
  mutate lock 's|^  if ! mkdir "\$lock" 2> /dev/null; then$|  if false; then|' 'a live ensure holds the lock'
  mutate darwin-only 's|^  \[ "\$UNAME" = Darwin \] .*$|  :|' 'not macOS'
  mutate loaded-def 's#^  if ! cmp -s "\$FRESH" "\$PLIST" || .*; then$#  if ! cmp -s "$FRESH" "$PLIST"; then#' 'loaded definition behind'
  mutate run-guard 's|^  if secs=\$(running_secs "\$printed") \&\& \[ "\$secs" -lt "\$interval" \]; then$|  if false; then|' 'stale stamp, a run under'
  mutate run-limit 's|-lt "\$interval" \]; then$|-le 99999 ]; then|' 'stale stamp, a run going 10:00'
  mutate no-token 's|^  tok=\$(no_token) \&\& why=.*$|  true|' 'gh without a token'
  mutate log-window 's|tail -n 20 |cat |' 'stale stamp: a problem older'
  mutate log-news 's#^  if \[ -f "\$BOARD_DIR/\$STAMP" \] \&\& ! \[ "\$log" -nt "\$BOARD_DIR/\$STAMP" \]; then$#  if false; then#' 'stale stamp: a log older'
  mutate bootout-first 's|^    lc bootout "\$DOMAIN/\$LABEL"$|    install_plist; lc bootout "$DOMAIN/$LABEL"|' 'a failing bootout'
  mutate repo-none 's|^  \[ -n "\$want" \] \|\| { say "WARN: no bloomery checkout named.*$|  [ -n "$want" ] \|\| want=$PWD|' 'repo: none named'
  mutate repo-arg 's|^  if \[ -n "\$REPO_ARG" \]; then from=.--repo.; want=\$REPO_ARG$|  if false; then from=x; want=$REPO_ARG|' 'repo: --repo names'
  mutate repo-kept 's|^  \[ "\$(cat "\$BOARD_DIR/REPO" 2> /dev/null)" = "\$REPO" \] .*$|  :|' 'repo: the checkout is kept'
  mutate main-of 's#then dirname "\$common"; else#then echo "$d"; else#' 'repo: a worktree'
  mutate repo-notdir 's#^  REPO=\$(main_of "\$want") .*$#  REPO=$(main_of "$want") || REPO=$want#' 'repo: a path that is not'
  mutate repo-tpl 's#^  why=\$(template_ok "\$REPO") .*$#  :#' 'repo: a directory without'
  mutate tmpl-left 's#^  \[ -z "\$left" \] .*$#  :#' 'template: a word'
  mutate tmpl-stamp 's#^  grep -q -- .*stamp-status.*$#  :#' 'template: --check-template names'
  wait
  local tag want
  for tag in $MUTANTS; do
    want=$(cat "$t/want-$tag")
    if [ -f "$t/sedfail-$tag" ]; then bad=$((bad + 1)); echo "FAIL mutant $tag: $(cat "$t/sedfail-$tag")"
    elif grep -q "^FAIL $want" "$t/out-$tag"; then echo "mutant $tag: red as expected: $(grep -m1 "^FAIL $want" "$t/out-$tag" | cut -c1-150)"
    else bad=$((bad + 1)); echo "FAIL mutant $tag: no case starting '$want' went red"; fi
  done

  if [ "$bad" = 0 ]; then echo "ensure self-test: ok ($n cases, $mut mutants red)"; return 0; fi
  echo "ensure self-test: FAIL ($bad of $n)"
  return 1
}

usage() { echo "ensure: usage: ensure.sh [--repo PATH] [--check-template | --self-test]" >&2; exit 64; }
REPO_ARG=''
MODE=ensure
while [ $# -gt 0 ]; do
  case $1 in
    --repo) [ $# -ge 2 ] && [ -n "$2" ] || usage; REPO_ARG=$2; shift 2 ;;
    --self-test | --check-template) [ "$MODE" = ensure ] || usage; MODE=$1; shift ;;
    *) usage ;;
  esac
done
case $MODE in
  --self-test) [ -z "$REPO_ARG" ] || usage; self_test; exit $? ;;
  --check-template) check_template; exit $? ;;
  *) locked_ensure; exit $? ;;
esac
