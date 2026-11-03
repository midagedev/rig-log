#!/usr/bin/env bash
# bloomery's follower: one real-tier pass over the gates that matter daily (the main families, the families new in the release, the
# common and tooling gates), run at origin/main on the box's idle time from a worktree this script makes and resets itself, and a
# watermark W: the newest commit whose whole list is green on the lead's ledger. It runs on the machine that runs
# tools/gate-batch.sh (the lead's ledger is that machine's file) and reaches the box through tools/box.sh.
#
#   run.sh [--dry-run [--tree DIR]] [--list FILE]
#   run.sh --self-test
#
# One call is at most one pass. launchd calls it every half hour (configs/dev.midage.bloomery-follow.plist); a call with nothing to
# do (the box busy, W already at origin/main, another pass running) ends at once, and a pass that was cut short by a sitting (its
# items yielded) leaves W where it was, so the next idle call runs the rest: the items already green are ledger skips.
#
# Steps:
#   1. State lock (one pass at a time; a dead pid's lock is taken over). Fetch; the target commit is $BLOOMERY_FOLLOW_REF (origin/main).
#      W at the target: nothing to do.
#   2. The box is idle: no timing lease and no sitting hold (tools/ref/lease-probe.sh's lease_guard 0), no GPU hold of the lead's
#      landing batch, no compute process on a card. One READONLY tools/box.sh call. Busy: the call ends 75 and starts nothing.
#   3. The tree: $STATE/tree, a worktree of $BLOOMERY_FOLLOW_REPO that this script adds when it is missing, then checks out at the
#      target (detached, forced) and cleans (untracked files, never ignored ones). A path that is not that worktree is refused; no lead
#      or round tree is ever used. --dry-run --tree DIR runs the dry run in a tree you name instead, and touches nothing.
#   4. The list: `python3 tools/rotation.py follow-list` in the tree; when the tree has no such subcommand, the stub list file
#      $BLOOMERY_FOLLOW_STUB_LIST (default $STATE/list.stub, one gate-batch item a line) — and a named error (66) when neither is there.
#      --list FILE names the list outright.
#   5. `tools/gate-batch.sh --tier real --ledger --yield --list LIST --out $STATE/runs/<stamp>` in the tree, remote directory
#      $BLOOMERY_FOLLOW_REMOTE (its own, ~/repo/bloomery-follow). The pass is a background job with its pid captured; INT/TERM signal that
#      pid and nothing else. --dry-run is the same call with gate-batch's --dry-run: it reads the box manifest and nothing runs on a card.
#   6. The verdict, from the batch's run.log: green when the batch ended 0, its DONE line has red=0, no yielded=, and no item's
#      ledger state is changed, unkeyed or append-failed. Green writes W (below) at the target; anything else leaves W as it was.
#   7. The report, at most 15 lines: $STATE/report.txt and stdout.
#
# State, $STATE (default ~/.cache/bloomery/follow; BLOOMERY_FOLLOW_HOME):
#   W          commit= (full sha), epoch=, date=, list= (the batch's total), skipped=, deferred= and never= (items the ledger could
#              not hold: ledger=never), pass= (the batch's directory); written atomically, only by a green pass
#   W.log      one line per write
#   report.txt the last pass's report; status.txt the last call's one line
#   runs/      one directory a pass (the newest $BLOOMERY_FOLLOW_KEEP, default 14, stay), tree/, lock.d/
#
# Environment: BLOOMERY_FOLLOW_HOME, _REPO (default ~/repo/bloomery: the clone the worktree is added to), _REF (origin/main), _REMOTE,
# _STUB_LIST, _KEEP. The box is tools/box.sh's: BLOOMERY_BOX names it. The ledger is gate-batch.sh's (BLOOMERY_GATE_LEDGER).
# Exit: 0 a green pass, W current, or a dry run that ended 0; 1 a pass with a red gate, or one whose items ran green but were not
# all recorded; 75 the box busy, another pass running, the batch refused to start on a hold, or a pass cut short by one (items
# yielded: the next idle call continues); 64 usage; 66 no list, no ref or a path that is not the follower's worktree; 70 the box
# could not be probed or the tree would not clean; 143 stopped by INT or TERM.
set -uo pipefail

SELF=$(cd "$(dirname "$0")" && pwd -P)/$(basename "$0")
STATE=${BLOOMERY_FOLLOW_HOME:-$HOME/.cache/bloomery/follow}
REPO=${BLOOMERY_FOLLOW_REPO:-$HOME/repo/bloomery}
REF=${BLOOMERY_FOLLOW_REF:-origin/main}
REMOTE=${BLOOMERY_FOLLOW_REMOTE:-'~/repo/bloomery-follow'}
STUB_LIST=${BLOOMERY_FOLLOW_STUB_LIST:-$STATE/list.stub}
KEEP=${BLOOMERY_FOLLOW_KEEP:-14}

usage() { echo "usage: run.sh [--dry-run [--tree DIR]] [--list FILE] | --self-test" >&2; }
die() { # <rc> <message>: the call's one status line, then out
  echo "run.sh: $2" >&2
  [ -d "$STATE" ] && printf '%s %s\n' "$(date '+%F %T')" "$2" > "$STATE/status.txt" 2> /dev/null
  exit "$1"
}
status() { # <message>: the call's one status line, without ending
  echo "run.sh: $1"
  printf '%s %s\n' "$(date '+%F %T')" "$1" > "$STATE/status.txt"
}

# w_get <key>: a value of the W file ('' when there is no W or no such key).
w_get() { sed -n "s/^$1=//p" "$STATE/W" 2> /dev/null | head -1; }

# The lock: a directory with the owner's pid. A pid that is gone leaves a stale lock, taken over; a live one is another pass.
lock_take() {
  local pid
  if ! mkdir "$STATE/lock.d" 2> /dev/null; then
    pid=$(cat "$STATE/lock.d/pid" 2> /dev/null || echo 0)
    if [ "$pid" -gt 0 ] 2> /dev/null && kill -0 "$pid" 2> /dev/null; then
      status "another pass is running (pid $pid): nothing started"
      exit 75
    fi
    rm -rf "$STATE/lock.d"
    mkdir "$STATE/lock.d" 2> /dev/null || die 70 "cannot take $STATE/lock.d"
  fi
  echo $$ > "$STATE/lock.d/pid"
  trap 'rm -rf "$STATE/lock.d"' EXIT
}

# box_idle: 0 when the box is idle, else 75 with what is up in IDLE_WHY, or 70 when it cannot be asked. One READONLY box.sh call from the
# tree (no sync, no guard wait). A remote directory that is not there yet (66) takes one plain call that makes it.
IDLE_CMD='. tools/ref/lease-probe.sh; lease_guard 0 || { echo "busy: the timing lease or a sitting hold is up"; exit 75; }; if [ -e "$LOCK_DIR/bloomery-batch.gpuhold" ]; then echo "busy: the lead landing batch holds the GPU hold"; exit 75; fi; if command -v nvidia-smi > /dev/null 2>&1 && nvidia-smi --query-compute-apps=pid --format=csv,noheader 2> /dev/null | grep -q .; then echo "busy: a compute process is on a card"; exit 75; fi; echo idle'
IDLE_WHY=''
box_idle() { # <tree>
  local tree=$1 rc=0 out
  out=$(cd "$tree" && BLOOMERY_REMOTE=$REMOTE BLOOMERY_BOX_READONLY=1 BLOOMERY_BOX_WAIT=0 tools/box.sh "$IDLE_CMD" 2>&1 < /dev/null) || rc=$?
  if [ "$rc" = 66 ]; then
    rc=0
    out=$(cd "$tree" && BLOOMERY_REMOTE=$REMOTE BLOOMERY_BOX_WAIT=0 tools/box.sh true 2>&1 < /dev/null) || rc=$?
    if [ "$rc" = 0 ]; then
      rc=0
      out=$(cd "$tree" && BLOOMERY_REMOTE=$REMOTE BLOOMERY_BOX_READONLY=1 BLOOMERY_BOX_WAIT=0 tools/box.sh "$IDLE_CMD" 2>&1 < /dev/null) || rc=$?
    fi
  fi
  case $rc in
    0) IDLE_WHY=idle; return 0 ;;
    75) IDLE_WHY=$(printf '%s\n' "$out" | grep -E '^busy:|^\[guard\]  ' | head -3 | tr '\n' ';' | sed 's/;$//'); [ -n "$IDLE_WHY" ] || IDLE_WHY="the box is busy (rc 75)"; return 75 ;;
    *) IDLE_WHY="the box could not be asked (rc $rc): $(printf '%s\n' "$out" | tail -1)"; return 70 ;;
  esac
}

# prepare_tree: the target commit in TARGET and the clean worktree in WT.
prepare_tree() {
  local reg
  git -C "$REPO" fetch -q origin || die 70 "git fetch origin failed in $REPO"
  TARGET=$(git -C "$REPO" rev-parse --verify -q "$REF^{commit}") || die 66 "no $REF in $REPO"
  WT=$(cd "$STATE" && pwd -P)/tree
  if [ -e "$WT" ]; then
    reg=$(git -C "$REPO" worktree list --porcelain | sed -n 's/^worktree //p')
    printf '%s\n' "$reg" | grep -qxF "$WT" || die 66 "$WT exists and is not a worktree of $REPO: it is not touched (a lead or round tree is never the follower's)"
  else
    git -C "$REPO" worktree add -q -f --detach "$WT" "$TARGET" || die 70 "git worktree add $WT failed"
  fi
  git -C "$WT" checkout -q --detach -f "$TARGET" || die 70 "git checkout $TARGET failed in $WT"
  git -C "$WT" clean -fdq || die 70 "git clean failed in $WT"
  [ -z "$(git -C "$WT" status --porcelain)" ] || die 70 "$WT is not clean after the checkout"
}

# make_list <tree> <file>: the follower's list into <file>; LIST_FROM says where it came from.
make_list() {
  local tree=$1 out=$2 rc=0
  if [ -n "$LIST_ARG" ]; then
    [ -r "$LIST_ARG" ] || die 66 "--list $LIST_ARG is not a readable file"
    cp "$LIST_ARG" "$out"
    LIST_FROM="--list $LIST_ARG"
  else
    (cd "$tree" && python3 tools/rotation.py follow-list) > "$out" 2> "$out.err" < /dev/null || rc=$?
    if [ "$rc" = 0 ] && grep -qvE '^[[:space:]]*(#|$)' "$out"; then
      LIST_FROM="rotation.py follow-list"
    elif [ -r "$STUB_LIST" ]; then
      cp "$STUB_LIST" "$out"
      LIST_FROM="the stub list $STUB_LIST (rotation.py follow-list: rc $rc, $(tail -1 "$out.err" 2> /dev/null))"
    else
      die 66 "no list: rotation.py follow-list ended rc $rc ($(tail -1 "$out.err" 2> /dev/null)) and there is no stub list at $STUB_LIST"
    fi
  fi
  grep -qvE '^[[:space:]]*(#|$)' "$out" || die 66 "the list is empty ($LIST_FROM)"
}

# done_field <run.log> <key>: a key=value of the batch's DONE line.
done_field() { awk -v k="$2" '/^DONE / { for (i = 2; i <= NF; i++) if (index($i, k "=") == 1) { print substr($i, length(k) + 2); exit } }' "$1"; }

# verdict <run.log> <batch rc>: VERDICT is GREEN, or why not — NOTRUN, RED, YIELDED or UNRECORDED — and VERDICT_WHY the details.
verdict() {
  local log=$1 rc=$2 red yielded bad
  VERDICT_WHY=''
  if [ ! -f "$log" ] || ! grep -q '^DONE ' "$log"; then VERDICT=NOTRUN VERDICT_WHY="the batch ended rc $rc with no DONE line"; return; fi
  red=$(done_field "$log" red); yielded=$(done_field "$log" yielded)
  [ -n "$red" ] || red=0
  [ -n "$yielded" ] || yielded=0
  bad=$(grep -cE '^ledger [^ ]+ (changed|unkeyed|append-failed)$' "$log" || true)
  if [ "$red" != 0 ]; then VERDICT=RED VERDICT_WHY="red=$red"
  elif [ "$yielded" != 0 ]; then VERDICT=YIELDED VERDICT_WHY="yielded=$yielded"
  elif [ "$bad" != 0 ]; then VERDICT=UNRECORDED VERDICT_WHY="$bad item(s) ran and were not recorded in the ledger"
  elif [ "$rc" != 0 ]; then VERDICT=RED VERDICT_WHY="red=0 but the batch ended rc $rc (a canary stop?)"
  else VERDICT=GREEN; fi
}

write_w() { # <commit> <run.log> <out dir>
  local tmp=$STATE/W.tmp.$$ now
  now=$(date +%s)
  {
    echo "commit=$1"
    echo "epoch=$now"
    echo "date=$(date '+%Y-%m-%dT%H:%M:%S%z')"
    echo "list=$(done_field "$2" total)"
    echo "skipped=$(done_field "$2" skipped)"
    echo "deferred=$(done_field "$2" deferred)"
    echo "never=$(grep -c ' ledger=never' "$2" || true)"
    echo "pass=$3"
  } > "$tmp" && mv "$tmp" "$STATE/W" || die 70 "cannot write $STATE/W"
  echo "$(date '+%F %T') $1 list=$(done_field "$2" total) pass=$3" >> "$STATE/W.log"
}

# report <verdict> <commit> <run.log> <out dir> <old W commit>: at most 15 lines to $STATE/report.txt and stdout.
report() {
  local verdict=$1 commit=$2 log=$3 out=$4 old=$5 reds=0 shown=0 line attr y
  local -a lines=()
  lines+=("bloomery-follow $(date '+%F %H:%M'): pass at ${commit:0:12} ($LIST_FROM): $verdict${VERDICT_WHY:+ ($VERDICT_WHY)}")
  if [ "$verdict" = GREEN ]; then
    lines+=("W: ${old:+${old:0:12} -> }${commit:0:12} (list $(done_field "$log" total), $(done_field "$log" skipped) skipped by the ledger)")
  elif [ -n "$old" ]; then
    lines+=("W stays at ${old:0:12} ($(w_get date))")
  else
    lines+=("W stays unset: no pass has been green yet")
  fi
  if [ -f "$log" ] && grep -q '^DONE ' "$log"; then
    lines+=("$(grep '^DONE ' "$log" | head -1 | cut -c1-200)")
  fi
  if [ -f "$log" ]; then
    reds=$(grep -cE '^[^ ]+ rc=([1-9][0-9]*) ' "$log" || true)
    while IFS= read -r line; do
      [ "$shown" -lt 8 ] || break
      shown=$((shown + 1))
      attr=$(sed -n -E 's/.* (last_green=.*)$/\1/p' <<< "$line" | sed -E 's/ item=.*$//' | cut -c1-300)
      [ -n "$attr" ] || attr="(no attribution on the line)"
      lines+=("RED $(sed -E 's/^([^ ]+) rc=([0-9]+) .*$/\1 rc=\2/' <<< "$line"): $attr")
    done < <(grep -E '^[^ ]+ rc=([1-9][0-9]*) ' "$log")
    [ "$reds" -le "$shown" ] || lines+=("… and $((reds - shown)) more red item(s): $log")
    y=$(grep -c ' rc=yield ' "$log" || true)
    [ "$y" = 0 ] || lines+=("$y item(s) yielded to a lease, hold or sitting (not red, not recorded): the next idle call runs them")
  fi
  lines+=("log: $out/run.log")
  printf '%s\n' "${lines[@]}" | head -15 | tee "$STATE/report.txt"
}

prune_runs() {
  local d n=0
  while IFS= read -r d; do
    n=$((n + 1))
    [ "$n" -le "$KEEP" ] || rm -rf "$STATE/runs/$d"
  done < <(ls -1t "$STATE/runs" 2> /dev/null)
}

run_main() {
  local dry=0 tree_arg='' list_file out stamp rc=0 pid old mode='' batch_args=()
  LIST_ARG=''
  while [ $# -gt 0 ]; do
    case $1 in
      --dry-run) dry=1; shift ;;
      --tree) [ $# -ge 2 ] || { usage; exit 64; }; tree_arg=$2; shift 2 ;;
      --list) [ $# -ge 2 ] || { usage; exit 64; }; LIST_ARG=$2; shift 2 ;;
      -h | --help) sed -n '2,/^set -uo/p' "$SELF" | sed '$d'; exit 0 ;;
      *) usage; exit 64 ;;
    esac
  done
  [ -z "$tree_arg" ] || [ "$dry" = 1 ] || { usage; echo "run.sh: --tree is a dry run's (a real pass makes its own worktree)" >&2; exit 64; }
  case $KEEP in '' | *[!0-9]* | 0) echo "run.sh: BLOOMERY_FOLLOW_KEEP is whole runs from 1, got '$KEEP'" >&2; exit 64 ;; esac
  mkdir -p "$STATE/runs" || die 70 "cannot make $STATE"
  lock_take
  old=$(w_get commit)
  if [ -n "$tree_arg" ]; then
    WT=$(cd "$tree_arg" && pwd -P) || die 66 "--tree $tree_arg is not a directory"
    TARGET=$(git -C "$WT" rev-parse HEAD 2> /dev/null) || TARGET=unknown
  else
    prepare_tree
  fi
  if [ "$dry" = 0 ] && [ -n "$old" ] && [ "$old" = "$TARGET" ]; then
    status "W is at $REF (${TARGET:0:12}): nothing to do"
    exit 0
  fi
  box_idle "$WT"
  rc=$?
  if [ "$rc" != 0 ]; then
    if [ "$dry" = 1 ]; then echo "run.sh: dry run: the box is not idle ($IDLE_WHY); gate-batch's own check follows"
    elif [ "$rc" = 75 ]; then status "the box is busy ($IDLE_WHY): nothing started"; exit 75
    else die 70 "$IDLE_WHY"; fi
  else
    echo "run.sh: the box is idle"
  fi
  list_file=$STATE/list.txt
  make_list "$WT" "$list_file"
  stamp=$(date '+%Y%m%d-%H%M%S')-$$ # the pid: a pass directory is never an earlier pass's, so its run.log is this pass's or none
  out=$STATE/runs/$stamp
  [ "$dry" = 0 ] || out=$STATE/runs/dry-$stamp
  batch_args=(--tier real --ledger --yield --list "$list_file" --out "$out")
  [ "$dry" = 0 ] || batch_args+=(--dry-run)
  [ "$dry" = 0 ] || mode='dry run: '
  status "${mode}pass at ${TARGET:0:12}: list from $LIST_FROM: tools/gate-batch.sh ${batch_args[*]}"
  (cd "$WT" && exec env BLOOMERY_REMOTE="$REMOTE" bash tools/gate-batch.sh "${batch_args[@]}") > "$STATE/batch.out" 2>&1 < /dev/null &
  pid=$!
  trap 'kill -TERM "$pid" 2> /dev/null; wait "$pid" 2> /dev/null; echo "run.sh: interrupted: the batch (pid $pid) was signalled" >&2; exit 143' INT TERM
  wait "$pid" || rc=$?
  trap - INT TERM
  tail -5 "$STATE/batch.out"
  if [ "$dry" = 1 ]; then
    status "dry run of pass at ${TARGET:0:12} ended rc $rc (output $STATE/batch.out)"
    exit "$rc"
  fi
  verdict "$out/run.log" "$rc"
  if [ "$VERDICT" = NOTRUN ] && [ "$rc" = 75 ]; then
    status "the batch did not start (rc 75: the timing lease or a hold is up): nothing ran"
    exit 75
  fi
  if [ "$VERDICT" = GREEN ]; then
    write_w "$TARGET" "$out/run.log" "$out"
  fi
  report "$VERDICT" "$TARGET" "$out/run.log" "$out" "$old"
  prune_runs
  status "pass at ${TARGET:0:12} ended $VERDICT"
  case $VERDICT in
    GREEN) exit 0 ;;
    YIELDED) exit 75 ;;
    *) exit 1 ;;
  esac
}

# --self-test: the whole script against a fixture — a git repository "origin" holding stub tools/box.sh, tools/gate-batch.sh and
# tools/rotation.py, a clone of it as the follower's REPO, and a state directory of its own. No box, no ssh, no ledger: the stubs
# answer from files under the fixture. One line per case, `ok <name>` or `FAIL <name>: <why>`; exit 0 iff none failed. Each mutant
# is a copy of this script with one line changed; its case shows the defect that line prevents.
self_test() {
  local t n=0 bad=0 rc out fx
  t=$(mktemp -d "${TMPDIR:-/tmp}/bloomery-follow-test.XXXXXX") || { echo "run.sh: self-test: no temporary directory" >&2; return 70; }
  # shellcheck disable=SC2064 # the path is fixed now
  trap "rm -rf '$t'" EXIT
  t=$(cd "$t" && pwd -P)
  fx=$t/fx
  pass() { n=$((n + 1)); echo "ok $1"; }
  fail() { n=$((n + 1)); bad=$((bad + 1)); echo "FAIL $1: $2"; }
  mkdir -p "$fx" "$t/origin/tools"
  # The stubs. They answer from the fixture directory ($FX), set per call: box.state (idle | lease | down | nodir), batch.mode
  # (green | red | manyred | yield | unrecorded | refuse | slow), follow.mode (ok | missing).
  cat > "$t/origin/tools/box.sh" << 'EOF'
#!/usr/bin/env bash
echo "$BLOOMERY_REMOTE ro=${BLOOMERY_BOX_READONLY:-0} wait=${BLOOMERY_BOX_WAIT:-} $1" | cut -c1-120 >> "$FX/box.calls"
case "$(cat "$FX/box.state" 2> /dev/null || echo idle)" in
  idle) echo idle ;;
  lease) echo "[guard]   the timing lease /root/bloomery-cpu.lock is held (a sitting runs); its holders:" >&2; echo "busy: the timing lease or a sitting hold is up"; exit 75 ;;
  down) echo "ssh: connect failed" >&2; exit 255 ;;
  nodir) if [ "${BLOOMERY_BOX_READONLY:-0}" = 1 ] && [ ! -e "$FX/dir-made" ]; then echo "box.sh: no such remote directory" >&2; exit 66; fi
         [ "${BLOOMERY_BOX_READONLY:-0}" = 1 ] || : > "$FX/dir-made"
         echo idle ;;
esac
EOF
  cat > "$t/origin/tools/gate-batch.sh" << 'EOF'
#!/usr/bin/env bash
# stub: logs its call, then ends as FX/batch.mode says
sp=''
trap '[ -z "$sp" ] || kill "$sp" 2> /dev/null; exit 143' TERM
echo "args: $*" >> "$FX/batch.calls"
echo "remote: ${BLOOMERY_REMOTE:-} cwd: $(pwd -P) head: $(git rev-parse HEAD) dirty: $(git status --porcelain | wc -l | tr -d ' ')" >> "$FX/batch.calls"
out=''
while [ $# -gt 0 ]; do case $1 in --out) out=$2; shift 2 ;; --list) cp "$2" "$FX/batch.list"; shift 2 ;; *) shift ;; esac; done
case " $* " in *" --dry-run "*) echo "gate-batch: dry run (stub)"; exit 0 ;; esac
mode=$(cat "$FX/batch.mode" 2> /dev/null || echo green)
[ "$mode" != refuse ] || { echo "gate-batch: the timing lease or a hold is up (above) — not starting" >&2; exit 75; }
mkdir -p "$out"
echo $$ > "$FX/batch.pid"
{
  echo "plan laneA=1s laneB=1s wall=1s defaults=0 (predicted)"
  case $mode in
    green) printf 'gate-a rc=0 5s try=1 lane=A tier=real ledger=pending\ngate-b rc=skip green-at=abc 2026-11-03T00:00:00+0900 lane=B tier=real\nledger gate-a recorded\nDONE total=5 red=0 tier=real skipped=3 wall=9s plan=8s laneA=5s laneB=0s\n' ;;
    red) printf 'gate-a rc=0 5s try=1 lane=A tier=real ledger=pending\nplain-any rc=1 12s try=1 lane=B tier=real ledger=red last_green=aaaaaaaaaaaa@2026-11-02T09:00:00+0900 tier=real card=3090 range=aaaaaaaaaaaa..bbbbbbbbbbbb commits=2 touching=[1234567 Dave; 89abcde Erin Fox] item=plain-any@X=1\nledger gate-a recorded\nDONE total=2 red=1 tier=real skipped=0 wall=17s plan=8s laneA=5s laneB=12s\n' ;;
    manyred) for i in 1 2 3 4 5 6 7 8 9 10; do printf 'gate-r%s rc=1 1s try=1 lane=A tier=real ledger=red last_green=none range=none\n' "$i"; done; printf 'DONE total=10 red=10 tier=real skipped=0 wall=10s plan=8s laneA=10s laneB=0s\n' ;;
    yield) printf 'gate-a rc=0 5s try=1 lane=A tier=real ledger=pending\ngate-y rc=yield held by timing-lease: not retried (the follower yields; the next pass runs it again) 1s try=1 lane=B tier=real ledger=yield\nledger gate-a recorded\nDONE total=2 red=0 tier=real skipped=0 yielded=1 wall=6s plan=8s laneA=5s laneB=1s\n' ;;
    unrecorded) printf 'gate-a rc=0 5s try=1 lane=A tier=real ledger=pending\nledger gate-a changed\nDONE total=1 red=0 tier=real skipped=0 wall=5s plan=8s laneA=5s laneB=0s\n' ;;
    slow) printf 'gate-a rc=0 5s try=1 lane=A tier=real ledger=pending\n' ;;
  esac
} > "$out/run.log"
if [ "$mode" = slow ]; then sleep 20 & sp=$!; wait $sp; exit 0; fi
case $mode in red | manyred) exit 1 ;; *) exit 0 ;; esac
EOF
  cat > "$t/origin/tools/rotation.py" << 'EOF'
#!/usr/bin/env python3
import os, sys
if sys.argv[1:] != ["follow-list"] or open(os.environ["FX"] + "/follow.mode").read().strip() == "missing":
    sys.stderr.write("rotation.py: error: argument cmd: invalid choice: 'follow-list'\n")
    sys.exit(2)
print("# the follower's list (stub)")
print("gate-a")
print("gate-b")
EOF
  echo ok > "$fx/follow.mode"
  chmod +x "$t/origin/tools/box.sh" "$t/origin/tools/gate-batch.sh" "$t/origin/tools/rotation.py"
  git init -q -b main "$t/origin" && git -C "$t/origin" add -A \
    && git -C "$t/origin" -c user.email=t@t -c user.name=T -c commit.gpgsign=false commit -q -m one \
    && git clone -q "$t/origin" "$t/repo" || { echo "run.sh: self-test: the fixture repository could not be made" >&2; return 70; }
  local runsh=$SELF st=$t/state first
  step() { # <tag> <env…> -- <args…>: one call of the script under test (RUNSH), the fixture's state; rc in $rc, output in $out
    local tag=$1
    shift
    local envs=()
    while [ "$1" != -- ]; do envs+=("$1"); shift; done
    shift
    rc=0
    out=$(env FX="$fx" BLOOMERY_FOLLOW_HOME="$st" BLOOMERY_FOLLOW_REPO="$t/repo" BLOOMERY_FOLLOW_STUB_LIST="$t/stub.list" ${envs[@]+"${envs[@]}"} bash "${RUNSH:-$runsh}" "$@" 2>&1 < /dev/null) || rc=$?
    printf '%s\n' "$out" > "$t/out-$tag.log"
  }
  expect() { # <name> <condition: 0 holds> <why>
    if [ "$2" = 0 ]; then pass "$1"; else fail "$1" "$3"; fi
  }
  origin_commit() { # a new commit on origin/main; its full sha in $first
    echo "$1" > "$t/origin/f-$1"
    git -C "$t/origin" add -A && git -C "$t/origin" -c user.email=t@t -c user.name=T -c commit.gpgsign=false commit -q -m "$1"
    first=$(git -C "$t/origin" rev-parse HEAD)
  }
  w_commit() { sed -n 's/^commit=//p' "$st/W" 2> /dev/null; }
  local c1 c2
  c1=$(git -C "$t/origin" rev-parse HEAD)
  # 1. a sitting's lease: the box is busy, nothing starts
  echo lease > "$fx/box.state"
  step busy -- 
  expect 'busy: a lease up ends 75 and names the box busy' "$([ "$rc" = 75 ] && grep -q 'the box is busy' <<< "$out"; echo $?)" "rc=$rc $out"
  expect '  … and starts no batch, writes no W' "$([ ! -e "$fx/batch.calls" ] && [ ! -e "$st/W" ]; echo $?)" "batch.calls: $(cat "$fx/batch.calls" 2>&1)"
  expect '  … through one READONLY box call with no guard wait, in the follower'"'"'s own remote directory' \
    "$(grep -q '^~/repo/bloomery-follow ro=1 wait=0 ' "$fx/box.calls"; echo $?)" "$(cat "$fx/box.calls")"
  # 2. an idle box and a green pass writes W
  echo idle > "$fx/box.state"; echo green > "$fx/batch.mode"; rm -f "$fx/box.calls"
  step green -- 
  expect 'green: the pass ends 0 and writes W at origin/main' "$([ "$rc" = 0 ] && [ "$(w_commit)" = "$c1" ]; echo $?)" "rc=$rc W: $(cat "$st/W" 2>&1) $out"
  expect '  … with the list size, the epoch and the pass directory' "$(grep -q '^list=5$' "$st/W" && grep -q '^epoch=[0-9]\{9,\}$' "$st/W" && grep -q '^pass=.*/runs/' "$st/W"; echo $?)" "$(cat "$st/W")"
  expect '  … the pass directory is named by the second and the pid, so no pass reads an earlier pass'"'"'s log' "$(grep -Eq '^pass=.*/runs/[0-9]{8}-[0-9]{6}-[0-9]+$' "$st/W"; echo $?)" "$(grep '^pass=' "$st/W")"
  expect '  … the batch ran with the follower'"'"'s flags, its own remote directory, from the worktree at the target, clean' \
    "$(grep -q '^args: --tier real --ledger --yield --list .*/list.txt --out .*/runs/[0-9-]*$' "$fx/batch.calls" \
       && grep -q "^remote: ~/repo/bloomery-follow cwd: $st/tree head: $c1 dirty: 0\$" "$fx/batch.calls"; echo $?)" "$(cat "$fx/batch.calls")"
  expect '  … on the list rotation.py follow-list gave' "$(grep -q '^gate-a$' "$fx/batch.list"; echo $?)" "$(cat "$fx/batch.list" 2>&1)"
  expect '  … and the report is at most 15 lines and says GREEN with the W move' "$([ "$(wc -l < "$st/report.txt")" -le 15 ] && grep -q 'GREEN' "$st/report.txt" && grep -q "^W: ${c1:0:12} (list 5, 3 skipped" "$st/report.txt"; echo $?)" "$(cat "$st/report.txt")"
  # 3. W at origin/main: nothing to do
  rm -f "$fx/batch.calls"
  step current -- 
  expect 'current: W at origin/main ends 0 and starts nothing' "$([ "$rc" = 0 ] && grep -q 'nothing to do' <<< "$out" && [ ! -e "$fx/batch.calls" ]; echo $?)" "rc=$rc $out"
  # 4. a new commit and a red pass: W stays, the report names the red with its range
  origin_commit two; c2=$first
  echo red > "$fx/batch.mode"; w_before=$(cat "$st/W")
  step red -- 
  expect 'red: the pass ends 1 and leaves W as it was' "$([ "$rc" = 1 ] && [ "$(cat "$st/W")" = "$w_before" ]; echo $?)" "rc=$rc"
  expect '  … the report names the red with its last green and range' \
    "$(grep -q '^RED plain-any rc=1: last_green=aaaaaaaaaaaa@2026-11-02T09:00:00+0900 tier=real card=3090 range=aaaaaaaaaaaa..bbbbbbbbbbbb commits=2 touching=\[1234567 Dave; 89abcde Erin Fox\]$' "$st/report.txt" \
       && grep -q "pass at ${c2:0:12}" "$st/report.txt" && grep -q "^W stays at ${c1:0:12}" "$st/report.txt"; echo $?)" "$(cat "$st/report.txt")"
  echo manyred > "$fx/batch.mode"
  step manyred -- 
  expect 'red: ten reds are eight lines and a count, in at most 15 lines' "$([ "$(wc -l < "$st/report.txt")" -le 15 ] && [ "$(grep -c '^RED ' "$st/report.txt")" = 8 ] && grep -q '^… and 2 more red item(s)' "$st/report.txt"; echo $?)" "$(cat "$st/report.txt")"
  expect '  … a red item with no attribution says so' "$(grep -q '^RED gate-r1 rc=1: last_green=none range=none$' "$st/report.txt"; echo $?)" "$(cat "$st/report.txt")"
  # 5. yielded items: not green, not red; the next call continues
  echo yield > "$fx/batch.mode"
  step yield -- 
  expect 'yield: a pass whose item yielded ends 75, leaves W, and says the next idle call runs it' \
    "$([ "$rc" = 75 ] && [ "$(cat "$st/W")" = "$w_before" ] && grep -q 'YIELDED (yielded=1)' "$st/report.txt" && grep -q '^1 item(s) yielded' "$st/report.txt"; echo $?)" "rc=$rc $(cat "$st/report.txt")"
  echo unrecorded > "$fx/batch.mode"
  step unrec -- 
  expect 'unrecorded: green items the ledger did not record leave W (rc 1)' "$([ "$rc" = 1 ] && [ "$(cat "$st/W")" = "$w_before" ] && grep -q UNRECORDED "$st/report.txt"; echo $?)" "rc=$rc $(cat "$st/report.txt")"
  echo refuse > "$fx/batch.mode"
  step refuse -- 
  expect 'refused: a batch that would not start on a hold ends 75 and leaves W' "$([ "$rc" = 75 ] && [ "$(cat "$st/W")" = "$w_before" ]; echo $?)" "rc=$rc $out"
  # 6. the worktree is the follower's: reset to the target, cleaned
  echo green > "$fx/batch.mode"
  echo junk > "$st/tree/tools/junk"; echo '# edit' >> "$st/tree/tools/gate-batch.sh"; rm -f "$fx/batch.calls"
  step reset -- 
  expect 'tree: a dirty worktree is reset to the target before the batch runs (clean, at origin/main)' \
    "$([ "$rc" = 0 ] && grep -q "head: $c2 dirty: 0\$" "$fx/batch.calls" && [ "$(w_commit)" = "$c2" ]; echo $?)" "rc=$rc $(cat "$fx/batch.calls" 2>&1)"
  mkdir -p "$t/state2/tree"; echo mine > "$t/state2/tree/keep"
  rc=0; out=$(env FX="$fx" BLOOMERY_FOLLOW_HOME="$t/state2" BLOOMERY_FOLLOW_REPO="$t/repo" bash "$runsh" 2>&1 < /dev/null) || rc=$?
  expect 'tree: a path that is not the follower'"'"'s worktree is refused (66) and left alone' "$([ "$rc" = 66 ] && [ -e "$t/state2/tree/keep" ]; echo $?)" "rc=$rc $out"
  # 7. the list
  origin_commit three
  echo missing > "$fx/follow.mode"; rm -f "$st/W" "$fx/batch.calls" "$fx/batch.list"
  step nolist -- 
  expect 'list: no follow-list and no stub list is a named 66' "$([ "$rc" = 66 ] && grep -q 'no list: rotation.py follow-list ended rc 2' <<< "$out" && [ ! -e "$fx/batch.calls" ]; echo $?)" "rc=$rc $out"
  printf '# stub\nstub-gate-1\nstub-gate-2\n' > "$t/stub.list"
  step stub -- 
  expect 'list: the stub list stands in until follow-list exists' "$([ "$rc" = 0 ] && grep -q '^stub-gate-1$' "$fx/batch.list" && grep -q 'the stub list' "$st/report.txt"; echo $?)" "rc=$rc $(cat "$fx/batch.list" 2>&1) $(cat "$st/report.txt")"
  echo ok > "$fx/follow.mode"; rm -f "$t/stub.list"
  # 8. the box probe
  origin_commit four; rm -f "$fx/box.calls" "$fx/dir-made" "$fx/batch.calls"
  echo nodir > "$fx/box.state"
  step nodir -- 
  expect 'probe: a remote directory that is not there yet is made by one plain call, then probed again' \
    "$([ "$rc" = 0 ] && [ "$(grep -c . "$fx/box.calls")" = 3 ] && sed -n 2p "$fx/box.calls" | grep -q 'ro=0 wait=0 true'; echo $?)" "rc=$rc $(cat "$fx/box.calls")"
  origin_commit five; rm -f "$fx/batch.calls"
  echo down > "$fx/box.state"
  step down -- 
  expect 'probe: a box that cannot be asked ends 70 and starts nothing' "$([ "$rc" = 70 ] && [ ! -e "$fx/batch.calls" ]; echo $?)" "rc=$rc $out"
  echo idle > "$fx/box.state"
  # 9. the lock
  sleep 30 &
  local live=$!
  mkdir -p "$st/lock.d"; echo "$live" > "$st/lock.d/pid"
  step locked -- 
  expect 'lock: a pass running (a live pid) ends 75 and starts nothing' "$([ "$rc" = 75 ] && grep -q 'another pass is running' <<< "$out" && [ ! -e "$fx/batch.calls" ]; echo $?)" "rc=$rc $out"
  kill "$live" 2> /dev/null; wait "$live" 2> /dev/null
  echo "$live" > "$st/lock.d/pid"
  step stale -- 
  expect 'lock: a dead pid'"'"'s lock is taken over, and the lock is gone at the end' "$([ "$rc" = 0 ] && [ ! -e "$st/lock.d" ]; echo $?)" "rc=$rc $out"
  # 10. options
  step treeopt -- --tree "$t/repo"
  expect 'usage: --tree without --dry-run is 64' "$([ "$rc" = 64 ]; echo $?)" "rc=$rc"
  rm -f "$fx/batch.calls"; origin_commit six; w_dry=$(cat "$st/W"); r_dry=$(cat "$st/report.txt")
  step dry -- --dry-run --tree "$t/repo"
  expect 'dry run: the batch gets --dry-run, and W and the report stay as they were' \
    "$([ "$rc" = 0 ] && grep -q '^args: .*--dry-run' "$fx/batch.calls" && [ "$(cat "$st/W")" = "$w_dry" ] && [ "$(cat "$st/report.txt")" = "$r_dry" ]; echo $?)" "rc=$rc $(cat "$fx/batch.calls" 2>&1)"
  # 11. a stop signals the batch's pid and nothing else
  echo slow > "$fx/batch.mode"; rm -f "$fx/batch.pid"
  env FX="$fx" BLOOMERY_FOLLOW_HOME="$st" BLOOMERY_FOLLOW_REPO="$t/repo" bash "$runsh" > "$t/out-term.log" 2>&1 < /dev/null &
  local rpid=$! k=0 bpid
  while [ ! -s "$fx/batch.pid" ] && [ "$k" -lt 100 ]; do sleep 0.1; k=$((k + 1)); done
  bpid=$(cat "$fx/batch.pid" 2> /dev/null || echo 0)
  kill -TERM "$rpid" 2> /dev/null
  rc=0; wait "$rpid" 2> /dev/null || rc=$?
  k=0; while kill -0 "$bpid" 2> /dev/null && [ "$k" -lt 50 ]; do sleep 0.1; k=$((k + 1)); done
  expect 'stop: TERM to the script ends it 143, signals the batch it started, and frees the lock' "$([ "$rc" = 143 ] && ! kill -0 "$bpid" 2> /dev/null && [ ! -e "$st/lock.d" ]; echo $?)" "rc=$rc batch pid $bpid alive: $(kill -0 "$bpid" 2>&1 && echo yes)"
  # mutants (FAIL-first): one line of the script changed, the defect it prevents shows
  mutant() { # <tag> <sed expr> <ERE proving the sed applied>
    sed "$2" "$runsh" > "$t/run-$1.sh"
    if grep -Eq -- "$3" "$t/run-$1.sh"; then echo "mutant $1: $2"; else bad=$((bad + 1)); n=$((n + 1)); echo "FAIL mutant $1: the sed did not apply: $2"; fi
  }
  mutant w-on-red 's/^  if \[ "\$VERDICT" = GREEN \]; then$/  if true; then/' '^  if true; then$'
  mutant no-idle 's/^  box_idle "\$WT"$/  true/' '^  true$'
  mutant no-reset 's/^  git -C "\$WT" checkout -q --detach -f "\$TARGET".*$/  true/' '^  true$'
  mutant no-yield 's/--ledger --yield --list/--ledger --list/' 'tier real --ledger --list'
  mutant stamp-reuse 's/^  stamp=.*$/  stamp=fixed/' '^  stamp=fixed$'
  mutant no-kill 's/^  trap .kill -TERM "\$pid" 2> \/dev\/null; wait/  trap '"'"':; wait/' "trap ':; wait"
  # state for the mutant cases: a fresh W at c1-equivalent is not needed; each starts from its own state directory
  echo red > "$fx/batch.mode"; echo lease > "$fx/box.state"; rm -rf "$st" "$fx/batch.calls"
  RUNSH=$t/run-no-idle.sh step m-noidle -- 
  expect 'mutant no-idle: a lease up no longer stops the pass (the batch runs)' "$([ -e "$fx/batch.calls" ]; echo $?)" "rc=$rc $out"
  echo idle > "$fx/box.state"; rm -rf "$st"; echo green > "$fx/batch.mode"
  echo red > "$fx/batch.mode"
  RUNSH=$t/run-w-on-red.sh step m-wred -- 
  expect 'mutant w-on-red: a red pass moves W' "$([ -e "$st/W" ]; echo $?)" "rc=$rc"
  rm -rf "$st"; echo green > "$fx/batch.mode"; rm -f "$fx/batch.calls"
  step m-seed -- 
  echo '# edit' >> "$st/tree/tools/gate-batch.sh"; rm -f "$st/W"; rm -f "$fx/batch.calls"
  RUNSH=$t/run-no-reset.sh step m-noreset -- 
  expect 'mutant no-reset: a dirty worktree is not reset (only the clean check stops the pass, 70, so the reset case above turns red)' \
    "$([ "$rc" = 70 ] && grep -q 'is not clean after the checkout' <<< "$out" && [ ! -e "$fx/batch.calls" ]; echo $?)" "rc=$rc $out"
  rm -rf "$st"; rm -f "$fx/batch.calls"
  RUNSH=$t/run-no-yield.sh step m-noyield -- 
  expect 'mutant no-yield: without the flag the batch is the lead'"'"'s' "$(grep -q '^args: --tier real --ledger --list' "$fx/batch.calls"; echo $?)" "$(cat "$fx/batch.calls" 2>&1)"
  rm -rf "$st"; echo unrecorded > "$fx/batch.mode"
  RUNSH=$t/run-stamp-reuse.sh step m-stale1 -- 
  echo refuse > "$fx/batch.mode"
  RUNSH=$t/run-stamp-reuse.sh step m-stale2 -- 
  expect 'mutant stamp-reuse: a reused pass directory lets the earlier pass'"'"'s log answer for a batch that never started (rc 1, not 75)' \
    "$([ "$rc" = 1 ] && grep -q UNRECORDED "$st/report.txt"; echo $?)" "rc=$rc $(cat "$st/report.txt" 2>&1)"
  rm -rf "$st"; echo slow > "$fx/batch.mode"; rm -f "$fx/batch.pid"
  env FX="$fx" BLOOMERY_FOLLOW_HOME="$st" BLOOMERY_FOLLOW_REPO="$t/repo" bash "$t/run-no-kill.sh" > "$t/out-term2.log" 2>&1 < /dev/null &
  rpid=$! k=0
  while [ ! -s "$fx/batch.pid" ] && [ "$k" -lt 100 ]; do sleep 0.1; k=$((k + 1)); done
  bpid=$(cat "$fx/batch.pid" 2> /dev/null || echo 0)
  kill -TERM "$rpid" 2> /dev/null
  sleep 1
  expect 'mutant no-kill: without the signal the batch outlives the script' "$(kill -0 "$bpid" 2> /dev/null; echo $?)" "batch pid $bpid is gone"
  kill -TERM "$bpid" 2> /dev/null
  wait "$rpid" 2> /dev/null || true
  echo "run.sh self-test: $((n - bad)) of $n ok"
  [ "$bad" = 0 ]
}
if [ "${1:-}" = --self-test ]; then
  self_test
  exit $?
fi
run_main "$@"
