#!/usr/bin/env bash
# bloomery's follower: one real-tier pass over the gates that matter daily (the main families, the families new in the release, the
# common and tooling gates), run at origin/main on the box's idle time from a worktree this script makes and resets itself, and a
# watermark W: the newest commit whose whole list is green on the lead's ledger. It runs on the machine that runs
# tools/gate-batch.sh (the lead's ledger is that machine's file) and reaches the box through tools/box.sh.
#
#   run.sh [--dry-run [--tree DIR]] [--list FILE]
#   run.sh --tarballs VERSION      the archives of W, as tools/release/pick.sh's PICK_TARBALLS hook reads them (step 8)
#   run.sh --self-test
#
# One call is at most one pass. launchd calls it every half hour (configs/dev.midage.bloomery-follow.plist); a call with nothing to
# do (the box busy, W already at origin/main with its archives, another pass running) ends at once, and a pass that was cut short by a
# sitting (its items yielded) leaves W where it was, so the next idle call runs the rest: the items already green are ledger skips.
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
#   8. The release archives at W (after a green pass wrote W, and on a later call while W is current and has none): the box is
#      asked for idle again (the same probe; a hold, the lease or a compute process ends it as "deferred": nothing is built and the
#      next idle call tries). The Mac-side checks of `just release-build` that still apply to a watermark run in the worktree (no
#      uncommitted change; tools/release/carry.sh); the README check does not (main's README names the published release), and
#      the box-side `build.sh --stage w` checks the crate versions instead. Then, for sm_86 and sm_120a at once, from the worktree,
#      through tools/box.sh with BLOOMERY_ARCH, the follower's remote directory, BLOOMERY_BOX_WAIT=0 (a hold that goes up in the
#      gap is rc 75, not a wait) and no BLOOMERY_HOLD_OWNER: `timeout --kill-after=10 <bound> bash tools/release/build.sh --stage w
#      <W's serve crate version> <W's 12-digit commit>`; tools/release/build.sh gives each archive its own target and PTX directory.
#      Each build is bounded ($BLOOMERY_FOLLOW_BUILD_BOUND, default 1800 s: the box's own timeout, and TERM to its captured pid
#      $BLOOMERY_FOLLOW_BUILD_GRACE, default 60 s, later). Both built: the names
#      and sha256 of the archives (read from the build logs' last lines) are written to W.archives. A build that fails, ends past
#      its bound or leaves no sha256 line for the archive it was to make fails the step: W stands (the pass was green), the report
#      names the failure and the log, and the next call tries again up to $BLOOMERY_FOLLOW_BUILD_TRIES (default 2) times for that
#      commit; after that archives.fail stands and nothing is retried until it is removed or W moves. The Mac archive is not built
#      here (it needs the signing identity on the lead's Mac). --dry-run runs each build's `build.sh --dry-run` on the box instead
#      (the tree check and the directories; nothing is built).
#
#   8b. The GB10 archive, after the x86-64 archives are built at W (or already are: a call with W current builds what is missing): on our DGX
#      Spark, natively, by spark-box.sh beside this script (rsync of the worktree, the bench protocol of docs/spark-hold.md, tools/release/
#      build.sh --stage w <version> <commit> there under tools/box.sh's local mode). No wait for a bench: a Spark whose bench hold is up
#      (spark-box.sh rc 75) is "deferred" and the next idle call tries again, like a busy box. The call is bounded as an x86-64 build is
#      ($BLOOMERY_FOLLOW_BUILD_BOUND, the Spark's own timeout inside it). Built: the line `gb10 <sha256> <name>` joins W.archives, with
#      gb10_host= and gb10_remote= (where the archive is, for publish.sh's BLOOMERY_GB10_BOX and BLOOMERY_GB10_REMOTE). A build that fails,
#      ends past its bound or leaves no sha256 line fails the step: W and the x86-64 record stand, the report names it (`GB10 ARCHIVE FAILED`),
#      gb10.fail counts the tries at that commit ($BLOOMERY_FOLLOW_BUILD_TRIES) and after them nothing is retried until it is removed or W moves.
#      BLOOMERY_FOLLOW_GB10=0 leaves the step out. --dry-run runs the Spark's `build.sh --dry-run` the same way.
#
# State, $STATE (default ~/.cache/bloomery/follow; BLOOMERY_FOLLOW_HOME):
#   W          commit= (full sha), epoch=, date=, list= (the batch's total), skipped=, deferred= and never= (items the ledger could
#              not hold: ledger=never), pass= (the batch's directory); written atomically, only by a green pass
#   W.log      one line per write
#   W.archives commit= (full sha), version=, epoch=, date=, remote= and dist= (where the archives are on the box), then one line
#              each: `sm86 <sha256> <name>` and `sm120a <sha256> <name>`; written atomically, only when both were built at that
#              commit. It is removed when a build starts (the box's archives are then being replaced) and stays absent after a
#              failure. The release flow reads the archives at <remote>/<dist>: BLOOMERY_REMOTE=<remote> for pick.sh's default
#              read of the box, or PICK_TARBALLS='bash <this script> --tarballs' for the record (lines `<arch> <sha256> <commit>`,
#              or `<arch> absent` for another version)
#              and, once the GB10 archive is built at that commit: gb10_host=, gb10_remote= and the row `gb10 <sha256> <name>` (the Spark's
#              directory holds target/release-dist like the box's; the x86-64 rows are not touched by that step)
#   W.archives.log one line per write; archives.fail the last failed x86-64 build, gb10.fail the last failed GB10 build (commit=, tries=,
#              reason=, date=)
#   report.txt the last pass's report (a call that only built the archives writes its own); status.txt the last call's one line
#   runs/      one directory a pass or an archive build (the newest $BLOOMERY_FOLLOW_KEEP, default 14, stay), tree/, lock.d/
#
# Environment: BLOOMERY_FOLLOW_HOME, _REPO (default ~/repo/bloomery: the clone the worktree is added to), _REF (origin/main), _REMOTE,
# _STUB_LIST, _KEEP, _BUILD_BOUND, _BUILD_GRACE, _BUILD_TRIES, _POLL (seconds between looks at the builds, default 5), _GB10 (1: build the
# GB10 archive on the Spark, 0: not; default 1), _GB10_SLACK (seconds past the bound before the call stops the build: the sync, default 120), _GB10_HOST (the ssh host, spark), _GB10_REMOTE (the Spark's tree, /root/bloomery-gb10),
# _SPARK_BOX (the runner, spark-box.sh beside this script; the self-test's stub). The
# box is tools/box.sh's: BLOOMERY_BOX names it. The ledger is gate-batch.sh's (BLOOMERY_GATE_LEDGER).
# Exit: 0 a green pass with its archives built, W current with its archives (or with archives that failed their tries), or a dry run
# that ended 0; 1 a pass with a red gate, one whose items ran green but were not all recorded, or an archive build that failed;
# 75 the box busy (also at the archives step: W is written, the next idle call builds), another pass running, the batch refused to
# start on a hold, or a pass cut short by one (items yielded: the next idle call continues); 64 usage; 66 no list, no ref or a path
# that is not the follower's worktree; 70 the box could not be probed or the tree would not clean; 143 stopped by INT or TERM.
set -uo pipefail

SELF=$(cd "$(dirname "$0")" && pwd -P)/$(basename "$0")
STATE=${BLOOMERY_FOLLOW_HOME:-$HOME/.cache/bloomery/follow}
REPO=${BLOOMERY_FOLLOW_REPO:-$HOME/repo/bloomery}
REF=${BLOOMERY_FOLLOW_REF:-origin/main}
REMOTE=${BLOOMERY_FOLLOW_REMOTE:-'~/repo/bloomery-follow'}
STUB_LIST=${BLOOMERY_FOLLOW_STUB_LIST:-$STATE/list.stub}
KEEP=${BLOOMERY_FOLLOW_KEEP:-14}
GB10_SLACK=${BLOOMERY_FOLLOW_GB10_SLACK:-120}
GB10_ON=${BLOOMERY_FOLLOW_GB10:-1}
GB10_HOST=${BLOOMERY_FOLLOW_GB10_HOST:-spark}
GB10_REMOTE=${BLOOMERY_FOLLOW_GB10_REMOTE:-/root/bloomery-gb10}
SPARK_BOX=${BLOOMERY_FOLLOW_SPARK_BOX:-$(dirname "$SELF")/spark-box.sh}
BUILD_BOUND=${BLOOMERY_FOLLOW_BUILD_BOUND:-1800}
BUILD_GRACE=${BLOOMERY_FOLLOW_BUILD_GRACE:-60}
BUILD_TRIES=${BLOOMERY_FOLLOW_BUILD_TRIES:-2}
POLL=${BLOOMERY_FOLLOW_POLL:-5}

usage() { echo "usage: run.sh [--dry-run [--tree DIR]] [--list FILE] | --tarballs VERSION | --self-test" >&2; }
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

# --- the release archives at W (step 8) ---

# wa_get <key>: a value of the W.archives file ('' when there is none or no such key).
wa_get() { sed -n "s/^$1=//p" "$STATE/W.archives" 2> /dev/null | head -1; }

# x86_ready <commit>: 0 when W.archives names this commit with both x86-64 archives.
x86_ready() {
  [ -f "$STATE/W.archives" ] || return 1
  [ "$(wa_get commit)" = "$1" ] || return 1
  grep -q '^sm86 ' "$STATE/W.archives" && grep -q '^sm120a ' "$STATE/W.archives"
}

# gb10_sha: the GB10 archive's sha256 in W.archives ('' when there is none).
gb10_sha() { awk '$1 == "gb10" { print $2; exit }' "$STATE/W.archives" 2> /dev/null; }

# gb10_gaveup <commit>: 0 when gb10.fail names this commit with BUILD_TRIES failures.
gb10_gaveup() {
  [ "$(sed -n 's/^commit=//p' "$STATE/gb10.fail" 2> /dev/null | head -1)" = "$1" ] \
    && [ "$(sed -n 's/^tries=//p' "$STATE/gb10.fail" 2> /dev/null | head -1)" -ge "$BUILD_TRIES" ] 2> /dev/null
}

# archives_ready <commit>: 0 when the x86-64 archives are built at it and the GB10 archive is too, or is left out or given up on.
archives_ready() {
  x86_ready "$1" || return 1
  [ "$GB10_ON" != 1 ] || [ -n "$(gb10_sha)" ] || gb10_gaveup "$1"
}

# tarballs <version>: pick.sh's PICK_TARBALLS hook — `<arch> <sha256> <commit>` for each x86-64 archive W.archives holds for that
# version, else `<arch> absent`, and the same for gb10 while the GB10 step is on. It reads the record and asks nothing of the box.
tarballs() {
  local v=$1 a sha
  [ -n "$v" ] || { usage; return 64; }
  for a in sm86 sm120a $([ "$GB10_ON" != 1 ] || echo gb10); do
    sha=$(awk -v a="$a" '$1 == a { print $2; exit }' "$STATE/W.archives" 2> /dev/null)
    if [ -n "$sha" ] && [ "$(wa_get version)" = "$v" ]; then echo "$a $sha $(wa_get commit)"; else echo "$a absent"; fi
  done
}

# fail_get <key>: a value of archives.fail ('' when there is none).
fail_get() { sed -n "s/^$1=//p" "$STATE/archives.fail" 2> /dev/null | head -1; }

# serve_version <tree> <commit>: the serve crate's version at that commit, the one the build is given.
serve_version() { git -C "$1" show "$2:crates/serve/Cargo.toml" 2> /dev/null | awk -F'"' '/^version = "/ { print $2; exit }'; }

# build_problem <tree> <commit>: why the worktree cannot be built from, in BAD (empty when it can); ARCH_VER is the serve crate's version at
# the commit, ARCH_C12 its 12-digit id, both for the build that follows. Every archive of W is built from the same worktree, checked the same way.
BAD='' ARCH_VER='' ARCH_C12=''
build_problem() {
  local tree=$1 commit=$2 carry
  BAD=''
  ARCH_C12=$(git -C "$tree" rev-parse --short=12 "$commit" 2> /dev/null || echo "${commit:0:12}")
  ARCH_VER=$(serve_version "$tree" "$commit")
  if [ -z "$ARCH_VER" ]; then
    BAD="cannot read the serve crate's version at $ARCH_C12"
  elif [ "$(git -C "$tree" rev-parse HEAD 2> /dev/null)" != "$commit" ]; then
    BAD="the worktree is not at $ARCH_C12"
  elif [ -n "$(git -C "$tree" status --porcelain --untracked-files=no 2> /dev/null)" ]; then
    BAD="the worktree has uncommitted changes"
  elif ! carry=$(cd "$tree" && ./tools/release/carry.sh 2>&1); then
    BAD="carry.sh refused: $(printf '%s\n' "$carry" | grep -v '^[[:space:]]*$' | head -1 | cut -c1-160)"
  fi
}

# build_x86 <tree> <commit>: sm_86 and sm_120a at once, bounded. ARCH_STATE is built, deferred, failed or gaveup, ARCH_NOTE says
# why, ARCH_DIR is the directory of the build logs (when any build started) and ARCH_VER and ARCH_C12 name what was built.
BUILD_PIDS='' ARCH_STATE='' ARCH_NOTE='' ARCH_DIR=''
build_x86() {
  local tree=$1 commit=$2 arch name i rc line t0 live n log bad='' defer='' dir
  local -a pids=() names=() rows=() timed=()
  ARCH_STATE=failed ARCH_NOTE='' ARCH_DIR='' ARCH_C12=$(git -C "$tree" rev-parse --short=12 "$commit" 2> /dev/null || echo "${commit:0:12}")
  if [ "$(fail_get commit)" = "$commit" ] && [ "$(fail_get tries)" -ge "$BUILD_TRIES" ] 2> /dev/null; then
    ARCH_STATE=gaveup ARCH_NOTE="failed $(fail_get tries) time(s) at this commit, not tried again (last: $(fail_get reason)); remove $STATE/archives.fail to try"
    return
  fi
  build_problem "$tree" "$commit"
  bad=$BAD
  if [ -z "$bad" ]; then
    box_idle "$tree"
    rc=$?
    if [ "$rc" != 0 ]; then
      ARCH_STATE=deferred ARCH_NOTE="the box is not idle ($IDLE_WHY)"
      return
    fi
    dir=$STATE/runs/build-$(date '+%Y%m%d-%H%M%S')-$$
    mkdir -p "$dir" || die 70 "cannot make $dir"
    ARCH_DIR=$dir
    rm -f "$STATE/W.archives" # the box's archives are replaced from here on: the record would name files that are gone
    for arch in sm_86 sm_120a; do
      (cd "$tree" && exec env -u BLOOMERY_HOLD_OWNER BLOOMERY_REMOTE="$REMOTE" BLOOMERY_ARCH="$arch" BLOOMERY_BOX_WAIT=0 tools/box.sh "timeout --kill-after=10 $BUILD_BOUND bash tools/release/build.sh --stage w $ARCH_VER $ARCH_C12") > "$dir/build-$arch.log" 2>&1 < /dev/null &
      pids+=($!)
      names+=("$arch")
      timed+=(0)
    done
    BUILD_PIDS="${pids[*]}"
    trap 'kill -TERM $BUILD_PIDS 2> /dev/null; wait $BUILD_PIDS 2> /dev/null; echo "run.sh: interrupted: the archive builds (pids $BUILD_PIDS) were signalled" >&2; exit 143' INT TERM
    t0=$SECONDS
    while :; do
      live=0
      for i in "${!pids[@]}"; do kill -0 "${pids[$i]}" 2> /dev/null && live=$((live + 1)); done
      [ "$live" != 0 ] || break
      if [ $((SECONDS - t0)) -ge $((BUILD_BOUND + BUILD_GRACE)) ]; then
        for i in "${!pids[@]}"; do
          if kill -0 "${pids[$i]}" 2> /dev/null; then
            timed[$i]=1
            kill -TERM "${pids[$i]}" 2> /dev/null
          fi
        done
        n=0
        while [ "$n" -lt 40 ]; do
          live=0
          for i in "${!pids[@]}"; do kill -0 "${pids[$i]}" 2> /dev/null && live=$((live + 1)); done
          [ "$live" != 0 ] || break
          sleep 0.5
          n=$((n + 1))
        done
        for i in "${!pids[@]}"; do kill -0 "${pids[$i]}" 2> /dev/null && kill -KILL "${pids[$i]}" 2> /dev/null; done
        break
      fi
      sleep "$POLL"
    done
    for i in "${!pids[@]}"; do
      arch=${names[$i]}
      name=bloomery-$ARCH_VER-linux-x86_64-cuda-${arch/_/}.tar.gz
      log=$dir/build-$arch.log
      rc=0
      wait "${pids[$i]}" 2> /dev/null || rc=$?
      if [ "${timed[$i]}" = 1 ]; then
        bad="$bad${bad:+; }$arch: no end in $((BUILD_BOUND + BUILD_GRACE)) s, stopped"
      elif [ "$rc" = 75 ]; then
        defer="$defer${defer:+, }$arch"
      elif [ "$rc" = 124 ] || [ "$rc" = 137 ]; then
        bad="$bad${bad:+; }$arch: no end in $BUILD_BOUND s (the box's timeout, rc $rc)"
      elif [ "$rc" != 0 ]; then
        bad="$bad${bad:+; }$arch: rc $rc: $(grep -v '^[[:space:]]*$' "$log" | tail -1 | cut -c1-160)"
      else
        line=$(sed -n -E 's/^([0-9a-f]{64})  (bloomery-.*\.tar\.gz)$/\1 \2/p' "$log" | tail -1)
        if [ "${line#* }" = "$name" ]; then
          rows+=("${arch/_/} $line")
        else
          bad="$bad${bad:+; }$arch: built, but its log has no sha256 line for $name"
        fi
      fi
    done
    trap - INT TERM
    BUILD_PIDS=''
  fi
  if [ -n "$bad" ]; then
    n=1
    [ "$(fail_get commit)" != "$commit" ] || n=$(($(fail_get tries) + 1))
    printf 'commit=%s\ntries=%s\nreason=%s\ndate=%s\n' "$commit" "$n" "$bad" "$(date '+%Y-%m-%dT%H:%M:%S%z')" > "$STATE/archives.fail"
    ARCH_STATE=failed ARCH_NOTE="try $n of $BUILD_TRIES: $bad"
  elif [ -n "$defer" ]; then
    ARCH_STATE=deferred ARCH_NOTE="the box turned busy ($defer: rc 75)"
  else
    {
      echo "commit=$commit"
      echo "version=$ARCH_VER"
      echo "epoch=$(date +%s)"
      echo "date=$(date '+%Y-%m-%dT%H:%M:%S%z')"
      echo "remote=$REMOTE"
      echo "dist=target/release-dist"
      printf '%s\n' "${rows[@]}"
    } > "$STATE/W.archives.tmp.$$" && mv "$STATE/W.archives.tmp.$$" "$STATE/W.archives" || die 70 "cannot write $STATE/W.archives"
    echo "$(date '+%F %T') $commit v$ARCH_VER ${rows[*]}" >> "$STATE/W.archives.log"
    rm -f "$STATE/archives.fail"
    ARCH_STATE=built ARCH_NOTE=$(printf '%s' "${rows[*]}" | awk '{ for (i = 1; i <= NF; i += 3) printf "%s%s %s", (i > 1 ? ", " : ""), $i, substr($(i + 1), 1, 12) }')
  fi
}

# gb10_fail_get <key>: a value of gb10.fail ('' when there is none).
gb10_fail_get() { sed -n "s/^$1=//p" "$STATE/gb10.fail" 2> /dev/null | head -1; }

# wa_drop_gb10: W.archives without its GB10 lines (the Spark's archive is being replaced); the x86-64 lines are the box's and stay.
wa_drop_gb10() {
  [ -f "$STATE/W.archives" ] || return 0
  { grep -v '^gb10' "$STATE/W.archives" || true; } > "$STATE/W.archives.tmp.$$" && mv "$STATE/W.archives.tmp.$$" "$STATE/W.archives" || die 70 "cannot write $STATE/W.archives"
}

# build_gb10 <tree> <commit>: the GB10 archive on the Spark, bounded, once the x86-64 archives stand at that commit. GB10_STATE is built,
# ready (already in W.archives), deferred, failed, gaveup or off; GB10_NOTE says why and GB10_DIR is the log directory (when a build started).
GB10_STATE='' GB10_NOTE='' GB10_DIR=''
build_gb10() {
  local tree=$1 commit=$2 name rc=0 line t0 pid dir bad='' timed=0 log n sha=''
  GB10_STATE=off GB10_NOTE='' GB10_DIR=''
  [ "$GB10_ON" = 1 ] || return 0
  GB10_STATE=failed
  if [ -n "$(gb10_sha)" ] && [ "$(wa_get commit)" = "$commit" ]; then
    GB10_STATE=ready GB10_NOTE="gb10 $(gb10_sha | cut -c1-12)"
    return 0
  fi
  if gb10_gaveup "$commit"; then
    GB10_STATE=gaveup GB10_NOTE="failed $(gb10_fail_get tries) time(s) at this commit, not tried again (last: $(gb10_fail_get reason)); remove $STATE/gb10.fail to try"
    return 0
  fi
  build_problem "$tree" "$commit"
  bad=$BAD
  if [ -z "$bad" ]; then
    dir=$STATE/runs/build-gb10-$(date '+%Y%m%d-%H%M%S')-$$
    mkdir -p "$dir" || die 70 "cannot make $dir"
    GB10_DIR=$dir log=$dir/build-gb10.log
    wa_drop_gb10
    (cd "$tree" && exec env -u BLOOMERY_HOLD_OWNER BLOOMERY_SPARK="$GB10_HOST" BLOOMERY_SPARK_REMOTE="$GB10_REMOTE" bash "$SPARK_BOX" --tree "$tree" --wait 0 --bound "$BUILD_BOUND" --reason "follower: the GB10 archive at $ARCH_C12" -- "bash tools/release/build.sh --stage w $ARCH_VER $ARCH_C12") > "$log" 2>&1 < /dev/null &
    pid=$!
    BUILD_PIDS=$pid
    trap 'kill -TERM $BUILD_PIDS 2> /dev/null; wait $BUILD_PIDS 2> /dev/null; echo "run.sh: interrupted: the GB10 build (pid $BUILD_PIDS) was signalled" >&2; exit 143' INT TERM
    t0=$SECONDS
    while kill -0 "$pid" 2> /dev/null; do
      if [ $((SECONDS - t0)) -ge $((BUILD_BOUND + BUILD_GRACE + GB10_SLACK)) ]; then # the Spark's own timeout (BUILD_BOUND) and the sync come first
        timed=1
        kill -TERM "$pid" 2> /dev/null
        n=0
        while [ "$n" -lt 40 ] && kill -0 "$pid" 2> /dev/null; do sleep 0.5; n=$((n + 1)); done
        ! kill -0 "$pid" 2> /dev/null || kill -KILL "$pid" 2> /dev/null
        break
      fi
      sleep "$POLL"
    done
    wait "$pid" 2> /dev/null || rc=$?
    trap - INT TERM
    BUILD_PIDS=''
    name=bloomery-$ARCH_VER-linux-aarch64-cuda-sm121a.tar.gz
    if [ "$timed" = 1 ]; then
      bad="no end in $((BUILD_BOUND + BUILD_GRACE + GB10_SLACK)) s, stopped"
    elif [ "$rc" = 75 ]; then
      GB10_STATE=deferred GB10_NOTE="the Spark is busy (rc 75): $( { grep -m1 '^spark-box: busy:' "$log" || grep -v '^[[:space:]]*$' "$log" | tail -1; } | cut -c1-150)"
      return 0
    elif [ "$rc" = 124 ] || [ "$rc" = 137 ]; then
      bad="no end in $BUILD_BOUND s (the Spark's timeout, rc $rc)"
    elif [ "$rc" != 0 ]; then
      bad="rc $rc: $(grep -v '^[[:space:]]*$' "$log" | tail -1 | cut -c1-160)"
    else
      line=$(sed -n -E 's/^([0-9a-f]{64})  (bloomery-.*\.tar\.gz)$/\1 \2/p' "$log" | tail -1)
      if [ "${line#* }" = "$name" ]; then
        sha=${line%% *}
      else
        bad="built, but its log has no sha256 line for $name"
      fi
    fi
  fi
  if [ -n "$bad" ]; then
    n=1
    [ "$(gb10_fail_get commit)" != "$commit" ] || n=$(($(gb10_fail_get tries) + 1))
    printf 'commit=%s\ntries=%s\nreason=%s\ndate=%s\n' "$commit" "$n" "$bad" "$(date '+%Y-%m-%dT%H:%M:%S%z')" > "$STATE/gb10.fail"
    GB10_STATE=failed GB10_NOTE="try $n of $BUILD_TRIES: $bad"
  else
    {
      cat "$STATE/W.archives"
      echo "gb10_host=$GB10_HOST"
      echo "gb10_remote=$GB10_REMOTE"
      echo "gb10 $sha $name"
    } > "$STATE/W.archives.tmp.$$" && mv "$STATE/W.archives.tmp.$$" "$STATE/W.archives" || die 70 "cannot write $STATE/W.archives"
    echo "$(date '+%F %T') $commit v$ARCH_VER gb10 $sha $name" >> "$STATE/W.archives.log"
    rm -f "$STATE/gb10.fail"
    GB10_STATE=built GB10_NOTE="gb10 ${sha:0:12}"
  fi
}

# build_archives <tree> <commit>: the x86-64 archives, then the GB10 one. ARCH_STATE is build_x86's, or `ready` when W.archives already
# holds both at the commit; GB10_STATE is build_gb10's, and that step runs only when the x86-64 archives stand.
build_archives() {
  local tree=$1 commit=$2
  GB10_STATE='' GB10_NOTE='' GB10_DIR=''
  if x86_ready "$commit"; then
    ARCH_STATE=ready ARCH_DIR='' ARCH_VER=$(wa_get version) ARCH_C12=$(git -C "$tree" rev-parse --short=12 "$commit" 2> /dev/null || echo "${commit:0:12}")
    ARCH_NOTE=$(awk '$1 == "sm86" || $1 == "sm120a" { printf "%s%s %s", (n++ ? ", " : ""), $1, substr($2, 1, 12) }' "$STATE/W.archives")
  else
    build_x86 "$tree" "$commit"
  fi
  case $ARCH_STATE in built | ready) build_gb10 "$tree" "$commit" ;; esac
}

# archive_lines: the report's lines for ARCH_STATE and GB10_STATE (none when no step ran).
archive_lines() {
  case $ARCH_STATE in
    built | ready) echo "archives: $ARCH_NOTE at ${ARCH_C12} v$ARCH_VER in $REMOTE/target/release-dist (W.archives)" ;;
    deferred) echo "archives NOT built: $ARCH_NOTE; the next idle call builds them" ;;
    failed) echo "ARCHIVES FAILED at ${ARCH_C12}: $ARCH_NOTE (W stands); logs: ${ARCH_DIR:-none}" ;;
    gaveup) echo "ARCHIVES NOT BUILT at ${ARCH_C12}: $ARCH_NOTE" ;;
  esac
  case $GB10_STATE in
    built | ready) echo "GB10 archive: $GB10_NOTE at ${ARCH_C12} built natively on $GB10_HOST, in $GB10_REMOTE/target/release-dist (W.archives)" ;;
    deferred) echo "GB10 archive NOT built: $GB10_NOTE; the next idle call builds it" ;;
    failed) echo "GB10 ARCHIVE FAILED at ${ARCH_C12}: $GB10_NOTE (W and the x86-64 archives stand); logs: ${GB10_DIR:-none}" ;;
    gaveup) echo "GB10 ARCHIVE NOT BUILT at ${ARCH_C12}: $GB10_NOTE" ;;
  esac
}

# archives_exit: the call's exit code for ARCH_STATE and GB10_STATE.
archives_exit() {
  case $ARCH_STATE in
    deferred) return 75 ;;
    failed) return 1 ;;
  esac
  case $GB10_STATE in
    deferred) return 75 ;;
    failed) return 1 ;;
  esac
  return 0
}

# archives_dry <tree>: each archive's `build.sh --dry-run` on the box (the tree check and the directories; nothing is built); rc 0 when
# both ended 0.
archives_dry() {
  local tree=$1 v c12 arch rc=0 r out
  v=$(serve_version "$tree" HEAD)
  c12=$(git -C "$tree" rev-parse --short=12 HEAD 2> /dev/null)
  if [ -z "$v" ] || [ -z "$c12" ]; then echo "run.sh: dry run: cannot read the serve crate's version or HEAD in $tree"; return 66; fi
  for arch in sm_86 sm_120a; do
    r=0
    out=$(cd "$tree" && env -u BLOOMERY_HOLD_OWNER BLOOMERY_REMOTE="$REMOTE" BLOOMERY_ARCH="$arch" BLOOMERY_BOX_WAIT=0 tools/box.sh "bash tools/release/build.sh --dry-run --stage w $v $c12" 2>&1 < /dev/null) || r=$?
    printf '%s\n' "$out" | sed "s/^/[$arch] /"
    [ "$r" = 0 ] || rc=$r
  done
  if [ "$GB10_ON" = 1 ]; then
    r=0
    out=$(cd "$tree" && env -u BLOOMERY_HOLD_OWNER BLOOMERY_SPARK="$GB10_HOST" BLOOMERY_SPARK_REMOTE="$GB10_REMOTE" bash "$SPARK_BOX" --tree "$tree" --wait 0 --bound 300 --reason "follower: dry run" -- "bash tools/release/build.sh --dry-run --stage w $v $c12" 2>&1 < /dev/null) || r=$?
    printf '%s\n' "$out" | sed "s/^/[gb10] /"
    [ "$r" = 0 ] || rc=$r
  fi
  return "$rc"
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
  [ -z "$ARCH_STATE" ] || lines+=("$(archive_lines)")
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
  local dry=0 tree_arg='' list_file out stamp rc=0 drc pid old mode='' batch_args=()
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
    if archives_ready "$old"; then
      status "W is at $REF (${TARGET:0:12}): nothing to do$(! gb10_gaveup "$old" || echo " (the GB10 archive failed $(gb10_fail_get tries) time(s) at this commit and is not tried again; remove $STATE/gb10.fail to try)")"
      exit 0
    fi
    build_archives "$WT" "$TARGET" # W is current and has no archives yet: a call that only builds them
    case "$ARCH_STATE $GB10_STATE" in
      *built* | *failed*)
        { echo "bloomery-follow $(date '+%F %H:%M'): archives at W ${TARGET:0:12}: $ARCH_STATE${GB10_STATE:+, gb10 $GB10_STATE}"; archive_lines; } | head -15 | tee "$STATE/report.txt"
        prune_runs ;;
    esac
    status "W is at $REF (${TARGET:0:12}): archives ${ARCH_STATE/gaveup/not built}${GB10_STATE:+, gb10 ${GB10_STATE/gaveup/not built}}${ARCH_NOTE:+ ($ARCH_NOTE)}"
    archives_exit
    exit $?
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
    drc=0
    archives_dry "$WT" || drc=$?
    [ "$rc" != 0 ] || rc=$drc
    exit "$rc"
  fi
  verdict "$out/run.log" "$rc"
  if [ "$VERDICT" = NOTRUN ] && [ "$rc" = 75 ]; then
    status "the batch did not start (rc 75: the timing lease or a hold is up): nothing ran"
    exit 75
  fi
  if [ "$VERDICT" = GREEN ]; then
    write_w "$TARGET" "$out/run.log" "$out"
    build_archives "$WT" "$TARGET"
  fi
  report "$VERDICT" "$TARGET" "$out/run.log" "$out" "$old"
  prune_runs
  status "pass at ${TARGET:0:12} ended $VERDICT${ARCH_STATE:+, archives $ARCH_STATE}${GB10_STATE:+, gb10 $GB10_STATE}"
  case $VERDICT in
    GREEN) archives_exit; exit $? ;;
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
  # (green | greenlease | red | manyred | yield | unrecorded | refuse | slow), follow.mode (ok | missing), build.mode (ok | fail120 | to120 | hang86 |
  # defer | nosha), build.hang (seconds hang86 sleeps) and carry.mode (ok | fail); batch.mode greendirty is green with a tracked file edited.
  cat > "$t/origin/tools/box.sh" << 'EOF'
#!/usr/bin/env bash
echo "$BLOOMERY_REMOTE ro=${BLOOMERY_BOX_READONLY:-0} wait=${BLOOMERY_BOX_WAIT:-} $1" | cut -c1-120 >> "$FX/box.calls"
[ -z "${BLOOMERY_ARCH-}" ] || echo "$BLOOMERY_ARCH $1" >> "$FX/box.arch"
state=$(cat "$FX/box.state" 2> /dev/null || echo idle)
case "$state" in
  lease) echo "[guard]   the timing lease /root/bloomery-cpu.lock is held (a sitting runs); its holders:" >&2; echo "busy: the timing lease or a sitting hold is up"; exit 75 ;;
  down) echo "ssh: connect failed" >&2; exit 255 ;;
esac
case "$1" in
  *"build.sh --dry-run"*) echo "release: dry run (stub)"; exit 0 ;;
  *"tools/release/build.sh "*)
    # the archive build: logs the call, then ends as FX/build.mode says; the archive's sha256 is that of its arch's name
    arch=${BLOOMERY_ARCH:-}
    sp=''
    trap '[ -z "$sp" ] || kill "$sp" 2> /dev/null; exit 143' TERM
    v=$(awk '{ print $(NF - 1) }' <<< "$1")
    echo "arch=$arch cmd=$1 remote=${BLOOMERY_REMOTE:-} wait=${BLOOMERY_BOX_WAIT-unset} hold=${BLOOMERY_HOLD_OWNER-unset} cwd=$(pwd -P) head=$(git rev-parse --short=12 HEAD)" >> "$FX/build.calls"
    echo $$ > "$FX/build.pid.$arch"
    name=bloomery-$v-linux-x86_64-cuda-${arch/_/}.tar.gz
    case "$(cat "$FX/build.mode" 2> /dev/null || echo ok):$arch" in
      fail120:sm_120a) echo "release: sm_120a: the build broke" >&2; exit 3 ;;
      to120:sm_120a) exit 124 ;;
      hang86:sm_86) sleep "$(cat "$FX/build.hang" 2> /dev/null || echo 30)" & sp=$!; wait "$sp" ;;
      defer:*) echo "[guard] the timing lease /root/bloomery-cpu.lock is held" >&2; exit 75 ;;
      nosha:*) echo "release: built, and nothing else said"; exit 0 ;;
    esac
    echo "release: /root/repo/bloomery-follow/target/release-dist/$name 4242 bytes"
    echo "$(printf '%s' "$arch" | shasum -a 256 | cut -d' ' -f1)  $name"
    exit 0 ;;
esac
case "$state" in
  idle) echo idle ;;
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
    green | greenlease | greendirty) printf 'gate-a rc=0 5s try=1 lane=A tier=real ledger=pending\ngate-b rc=skip green-at=abc 2026-11-03T00:00:00+0900 lane=B tier=real\nledger gate-a recorded\nDONE total=5 red=0 tier=real skipped=3 wall=9s plan=8s laneA=5s laneB=0s\n' ;;
    red) printf 'gate-a rc=0 5s try=1 lane=A tier=real ledger=pending\nplain-any rc=1 12s try=1 lane=B tier=real ledger=red last_green=aaaaaaaaaaaa@2026-11-02T09:00:00+0900 tier=real card=3090 range=aaaaaaaaaaaa..bbbbbbbbbbbb commits=2 touching=[1234567 Dave; 89abcde Erin Fox] item=plain-any@X=1\nledger gate-a recorded\nDONE total=2 red=1 tier=real skipped=0 wall=17s plan=8s laneA=5s laneB=12s\n' ;;
    manyred) for i in 1 2 3 4 5 6 7 8 9 10; do printf 'gate-r%s rc=1 1s try=1 lane=A tier=real ledger=red last_green=none range=none\n' "$i"; done; printf 'DONE total=10 red=10 tier=real skipped=0 wall=10s plan=8s laneA=10s laneB=0s\n' ;;
    yield) printf 'gate-a rc=0 5s try=1 lane=A tier=real ledger=pending\ngate-y rc=yield held by timing-lease: not retried (the follower yields; the next pass runs it again) 1s try=1 lane=B tier=real ledger=yield\nledger gate-a recorded\nDONE total=2 red=0 tier=real skipped=0 yielded=1 wall=6s plan=8s laneA=5s laneB=1s\n' ;;
    unrecorded) printf 'gate-a rc=0 5s try=1 lane=A tier=real ledger=pending\nledger gate-a changed\nDONE total=1 red=0 tier=real skipped=0 wall=5s plan=8s laneA=5s laneB=0s\n' ;;
    slow) printf 'gate-a rc=0 5s try=1 lane=A tier=real ledger=pending\n' ;;
  esac
} > "$out/run.log"
[ "$mode" != greenlease ] || echo lease > "$FX/box.state" # a hold goes up while the pass ends
[ "$mode" != greendirty ] || echo '# edit' >> tools/rotation.py # the pass leaves a tracked file edited
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
  mkdir -p "$t/origin/crates/serve"
  printf '[package]\nname = "bloomery-serve"\nversion = "0.0.1"\n' > "$t/origin/crates/serve/Cargo.toml"
  # tools/release/carry.sh: the Mac-side carry check of a release build, ending as FX/carry.mode says
  mkdir -p "$t/origin/tools/release"
  cat > "$t/origin/tools/release/carry.sh" << 'EOF'
#!/usr/bin/env bash
echo "carry $*" >> "$FX/carry.calls"
[ "$(cat "$FX/carry.mode" 2> /dev/null || echo ok)" != fail ] || { echo "release-build: HEAD lacks a fix tools/release/carry.tsv lists" >&2; exit 1; }
echo "release-build: HEAD carries all rows"
EOF
  chmod +x "$t/origin/tools/release/carry.sh"
  # tools/bloomery-follow/spark-box.sh stands in as a stub that logs its call and ends as FX/spark.mode says: ok | hold (the bench is up: rc 75) |
  # fail (rc 3) | to (rc 124) | nosha (rc 0, no sha256 line) | hang (spark.hang seconds, then built); its --dry-run is an rc 0.
  cat > "$t/spark-box.stub" << 'EOF'
#!/usr/bin/env bash
sp=''
trap '[ -z "$sp" ] || kill "$sp" 2> /dev/null; exit 143' TERM
cmd=${!#}
echo "host=${BLOOMERY_SPARK-unset} remote=${BLOOMERY_SPARK_REMOTE-unset} cwd=$(pwd -P) head=$(git rev-parse --short=12 HEAD) args=$*" >> "$FX/spark.calls"
case "$cmd" in *"--dry-run"*) echo "release: dry run (spark stub)"; exit 0 ;; esac
echo $$ > "$FX/spark.pid"
v=$(awk '{ print $(NF - 1) }' <<< "$cmd")
name=bloomery-$v-linux-aarch64-cuda-sm121a.tar.gz
case "$(cat "$FX/spark.mode" 2> /dev/null || echo ok)" in
  hold) echo "spark-box: busy: the bench hold /root/spark-bench.hold: owner=bench since=1 until=9999999999 reason=stub" >&2; echo "spark-box: the bench is still up after 0 s: nothing was synced or run" >&2; exit 75 ;;
  fail) echo "release: the GB10 build broke" >&2; exit 3 ;;
  to) exit 124 ;;
  nosha) echo "release: built, and nothing else said"; exit 0 ;;
  hang) sleep "$(cat "$FX/spark.hang" 2> /dev/null || echo 30)" & sp=$!; wait "$sp" ;;
esac
echo "release: /root/bloomery-gb10/target/release-dist/$name 4242 bytes"
echo "$(printf '%s' gb10 | shasum -a 256 | cut -d' ' -f1)  $name"
EOF
  chmod +x "$t/spark-box.stub"
  export BLOOMERY_FOLLOW_SPARK_BOX="$t/spark-box.stub"
  export BLOOMERY_FOLLOW_POLL=0.1 BLOOMERY_FOLLOW_BUILD_BOUND=1800 BLOOMERY_FOLLOW_BUILD_GRACE=0 BLOOMERY_FOLLOW_BUILD_TRIES=2
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
  wa_commit() { sed -n 's/^commit=//p' "$st/W.archives" 2> /dev/null; }
  alive() { [ "${1:-0}" -gt 0 ] 2> /dev/null && kill -0 "$1" 2> /dev/null; } # a captured pid that is there; never pid 0, which kill -0 and -TERM read as the whole process group
  build_ok() { # <version> <head12>: both archives were asked for once, as step 8 says: stage w, W's version and commit, no wait, no hold owner, the worktree at W
    [ "$(grep -c . "$fx/build.calls" 2> /dev/null)" = 2 ] || return 1
    local a
    for a in sm_86 sm_120a; do
      grep -q "^arch=$a cmd=timeout --kill-after=10 1800 bash tools/release/build.sh --stage w $1 $2 remote=~/repo/bloomery-follow wait=0 hold=unset cwd=$st/tree head=$2\$" "$fx/build.calls" || return 1
    done
  }
  local sha86 sha120 shag
  shag=$(printf '%s' gb10 | shasum -a 256 | cut -d' ' -f1)
  sha86=$(printf '%s' sm_86 | shasum -a 256 | cut -d' ' -f1)
  sha120=$(printf '%s' sm_120a | shasum -a 256 | cut -d' ' -f1)
  unset BLOOMERY_ARCH BLOOMERY_HOLD_OWNER BLOOMERY_BOX_WAIT # a case that wants one sets it; the caller's own must not reach the stubs
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
  expect 'archives: a green pass builds sm_86 and sm_120a at W (the recipe, the serve crate'"'"'s version, no wait, no hold owner, from the worktree at the target)' \
    "$(build_ok 0.0.1 "${c1:0:12}"; echo $?)" "$(cat "$fx/build.calls" 2>&1)"
  expect '  … W.archives names both with their sha256, the commit, the version and where they are on the box' \
    "$(grep -q "^commit=$c1\$" "$st/W.archives" && grep -q '^version=0.0.1$' "$st/W.archives" && grep -q '^remote=~/repo/bloomery-follow$' "$st/W.archives" \
       && grep -q "^sm86 $sha86 bloomery-0.0.1-linux-x86_64-cuda-sm86.tar.gz\$" "$st/W.archives" && grep -q "^sm120a $sha120 bloomery-0.0.1-linux-x86_64-cuda-sm120a.tar.gz\$" "$st/W.archives" \
       && [ ! -e "$st/archives.fail" ]; echo $?)" "$(cat "$st/W.archives" 2>&1)"
  expect '  … the report names them in its second block, within its 15 lines' \
    "$(grep -q "^archives: sm86 ${sha86:0:12}, sm120a ${sha120:0:12} at ${c1:0:12} v0.0.1 in ~/repo/bloomery-follow/target/release-dist" "$st/report.txt"; echo $?)" "$(cat "$st/report.txt")"
  tb=$(env BLOOMERY_FOLLOW_HOME="$st" bash "$runsh" --tarballs 0.0.1 2>&1); tb2=$(env BLOOMERY_FOLLOW_HOME="$st" bash "$runsh" --tarballs 0.0.2 2>&1)
  expect '  … --tarballs gives pick.sh'"'"'s hook lines for that version and `absent` for another' \
    "$([ "$tb" = "$(printf 'sm86 %s %s\nsm120a %s %s\ngb10 %s %s' "$sha86" "$c1" "$sha120" "$c1" "$shag" "$c1")" ] && [ "$tb2" = "$(printf 'sm86 absent\nsm120a absent\ngb10 absent')" ]; echo $?)" "$tb | $tb2"
  # 3. W at origin/main: nothing to do
  rm -f "$fx/batch.calls" "$fx/build.calls"
  step current -- 
  expect 'current: W at origin/main with its archives ends 0 and starts nothing (no batch, no build)' "$([ "$rc" = 0 ] && grep -q 'nothing to do' <<< "$out" && [ ! -e "$fx/batch.calls" ] && [ ! -e "$fx/build.calls" ]; echo $?)" "rc=$rc $out"
  # 4. a new commit and a red pass: W stays, the report names the red with its range
  origin_commit two; c2=$first
  echo red > "$fx/batch.mode"; w_before=$(cat "$st/W"); rm -f "$fx/build.calls"
  step red -- 
  expect 'red: the pass ends 1, leaves W as it was and builds no archives' "$([ "$rc" = 1 ] && [ "$(cat "$st/W")" = "$w_before" ] && [ ! -e "$fx/build.calls" ]; echo $?)" "rc=$rc"
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
  expect 'probe: a remote directory that is not there yet is made by one plain call, then probed again (and once more before the archives, which add their own two calls)' \
    "$([ "$rc" = 0 ] && [ "$(grep -vc 'build.sh --stage w' "$fx/box.calls")" = 4 ] && sed -n 2p "$fx/box.calls" | grep -q 'ro=0 wait=0 true'; echo $?)" "rc=$rc $(cat "$fx/box.calls")"
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
  rm -f "$fx/batch.calls" "$fx/box.arch" "$fx/build.calls"; origin_commit six; w_dry=$(cat "$st/W"); r_dry=$(cat "$st/report.txt")
  step dry -- --dry-run --tree "$t/repo"
  expect 'dry run: the batch gets --dry-run, and W and the report stay as they were' \
    "$([ "$rc" = 0 ] && grep -q '^args: .*--dry-run' "$fx/batch.calls" && [ "$(cat "$st/W")" = "$w_dry" ] && [ "$(cat "$st/report.txt")" = "$r_dry" ]; echo $?)" "rc=$rc $(cat "$fx/batch.calls" 2>&1)"
  expect '  … and each archive'"'"'s build.sh --dry-run runs on the box (serve version, tree commit) while nothing is built' \
    "$([ "$(grep -c . "$fx/box.arch")" = 2 ] && grep -q "^sm_86 bash tools/release/build.sh --dry-run --stage w 0.0.1 ${c1:0:12}\$" "$fx/box.arch" && grep -q "^sm_120a bash tools/release/build.sh --dry-run --stage w 0.0.1 ${c1:0:12}\$" "$fx/box.arch" && [ ! -e "$fx/build.calls" ]; echo $?)" "$(cat "$fx/box.arch" 2>&1) | $(cat "$fx/build.calls" 2>&1)"
  # 11. a stop signals the batch's pid and nothing else
  echo slow > "$fx/batch.mode"; rm -f "$fx/batch.pid"
  env FX="$fx" BLOOMERY_FOLLOW_HOME="$st" BLOOMERY_FOLLOW_REPO="$t/repo" bash "$runsh" > "$t/out-term.log" 2>&1 < /dev/null &
  local rpid=$! k=0 bpid
  while [ ! -s "$fx/batch.pid" ] && [ "$k" -lt 100 ]; do sleep 0.1; k=$((k + 1)); done
  bpid=$(cat "$fx/batch.pid" 2> /dev/null || echo 0)
  kill -TERM "$rpid" 2> /dev/null
  rc=0; wait "$rpid" 2> /dev/null || rc=$?
  k=0; while alive "$bpid" && [ "$k" -lt 50 ]; do sleep 0.1; k=$((k + 1)); done
  expect 'stop: TERM to the script ends it 143, signals the batch it started, and frees the lock' "$([ "$rc" = 143 ] && [ "$bpid" != 0 ] && ! alive "$bpid" && [ ! -e "$st/lock.d" ]; echo $?)" "rc=$rc batch pid $bpid alive: $(alive "$bpid" && echo yes)"
  # 12. the release archives (step 8): after a green pass, and on a later call while W has none
  echo idle > "$fx/box.state"; echo ok > "$fx/build.mode"
  origin_commit seven; c7=$first
  echo greenlease > "$fx/batch.mode"; rm -f "$fx/build.calls"; : > "$fx/box.calls"; local wa_before
  wa_before=$(wa_commit)
  step arch-busy -- 
  expect 'archives: a hold that goes up as the pass ends: W moves, no build starts (rc 75), and the report says the next idle call builds' \
    "$([ "$rc" = 75 ] && [ "$(w_commit)" = "$c7" ] && [ ! -e "$fx/build.calls" ] && ! grep -q 'build.sh --stage w' "$fx/box.calls" && grep -q '^archives NOT built: the box is not idle' "$st/report.txt" && grep -q 'the next idle call builds them' "$st/report.txt"; echo $?)" "rc=$rc $(cat "$st/report.txt" 2>&1)"
  expect '  … and the record of the older build stays, naming its own commit' "$([ -n "$wa_before" ] && [ "$(wa_commit)" = "$wa_before" ] && [ "$wa_before" != "$c7" ]; echo $?)" "W.archives: $(wa_commit) (before: $wa_before)"
  echo idle > "$fx/box.state"; echo green > "$fx/batch.mode"; rm -f "$fx/batch.calls"
  step arch-retry -- 
  expect 'archives: W current and its archives missing: the next idle call builds them without a pass (rc 0), and the report says so' \
    "$([ "$rc" = 0 ] && build_ok 0.0.1 "${c7:0:12}" && [ "$(wa_commit)" = "$c7" ] && [ ! -e "$fx/batch.calls" ] && grep -q "^bloomery-follow .*: archives at W ${c7:0:12}: built, gb10 built\$" "$st/report.txt" && grep -q '^archives: sm86 ' "$st/report.txt"; echo $?)" "rc=$rc $out | $(cat "$st/report.txt" 2>&1)"
  origin_commit eight; c8=$first
  echo fail120 > "$fx/build.mode"; rm -f "$fx/build.calls" "$fx/batch.calls"
  step arch-fail -- 
  expect 'archives: a failed build leaves W standing at the new commit with no record (rc 1), and the report names the archive, the failure and the logs' \
    "$([ "$rc" = 1 ] && [ "$(w_commit)" = "$c8" ] && [ ! -e "$st/W.archives" ] && [ "$(sed -n 's/^tries=//p' "$st/archives.fail")" = 1 ] \
       && grep -q "^ARCHIVES FAILED at ${c8:0:12}: try 1 of 2: sm_120a: rc 3: release: sm_120a: the build broke (W stands); logs: .*/runs/build-" "$st/report.txt" && [ "$(grep -c . "$fx/build.calls")" = 2 ]; echo $?)" "rc=$rc $(cat "$st/report.txt" 2>&1)"
  rm -f "$fx/build.calls" "$fx/batch.calls"
  step arch-fail2 -- 
  expect '  … the next call tries again (W is current, no pass runs) and the second failure counts' \
    "$([ "$rc" = 1 ] && [ "$(grep -c . "$fx/build.calls")" = 2 ] && [ "$(sed -n 's/^tries=//p' "$st/archives.fail")" = 2 ] && [ ! -e "$fx/batch.calls" ]; echo $?)" "rc=$rc $(cat "$st/archives.fail" 2>&1)"
  rm -f "$fx/build.calls"
  step arch-gaveup -- 
  expect '  … after BLOOMERY_FOLLOW_BUILD_TRIES failures at a commit nothing is started (rc 0) and the status names the way out' \
    "$([ "$rc" = 0 ] && [ ! -e "$fx/build.calls" ] && grep -q 'not tried again' "$st/status.txt" && grep -q 'remove .*archives.fail' "$st/status.txt"; echo $?)" "rc=$rc $(cat "$st/status.txt" 2>&1)"
  echo ok > "$fx/build.mode"; rm -f "$st/archives.fail" "$fx/build.calls"
  step arch-fixed -- 
  expect '  … with the failure gone the next call builds, writes the record and leaves no archives.fail' \
    "$([ "$rc" = 0 ] && build_ok 0.0.1 "${c8:0:12}" && [ "$(wa_commit)" = "$c8" ] && [ ! -e "$st/archives.fail" ]; echo $?)" "rc=$rc $out"
  origin_commit nine; c9=$first
  echo defer > "$fx/build.mode"; rm -f "$fx/build.calls" "$fx/batch.calls"
  step arch-defer -- 
  expect 'archives: a build that finds the box busy (box.sh rc 75) is deferred, not failed: rc 75, no archives.fail, no record, W at the new commit' \
    "$([ "$rc" = 75 ] && [ "$(w_commit)" = "$c9" ] && [ ! -e "$st/archives.fail" ] && [ ! -e "$st/W.archives" ] && grep -q '^archives NOT built: the box turned busy (sm_86, sm_120a: rc 75)' "$st/report.txt"; echo $?)" "rc=$rc $(cat "$st/report.txt" 2>&1)"
  origin_commit ten
  echo nosha > "$fx/build.mode"; rm -f "$fx/build.calls"
  step arch-nosha -- 
  expect 'archives: a build that ends 0 but leaves no sha256 line for the archive it was to make fails the step by name (rc 1, no record)' \
    "$([ "$rc" = 1 ] && [ ! -e "$st/W.archives" ] && grep -q 'sm_86: built, but its log has no sha256 line for bloomery-0.0.1-linux-x86_64-cuda-sm86.tar.gz' "$st/report.txt"; echo $?)" "rc=$rc $(cat "$st/report.txt" 2>&1)"
  origin_commit carry
  echo fail > "$fx/carry.mode"; echo ok > "$fx/build.mode"; rm -f "$fx/build.calls"; : > "$fx/box.calls"
  step arch-carry -- 
  expect 'archives: a carry.sh refusal (a fix tools/release/carry.tsv lists is missing) fails the step by name before the box is asked: rc 1, no build call, no record' \
    "$([ "$rc" = 1 ] && [ ! -e "$st/W.archives" ] && ! grep -q 'build.sh --stage w' "$fx/box.calls" && grep -q 'ARCHIVES FAILED at .*: try 1 of 2: carry.sh refused: release-build: HEAD lacks a fix tools/release/carry.tsv lists' "$st/report.txt"; echo $?)" "rc=$rc $(cat "$st/report.txt" 2>&1)"
  echo ok > "$fx/carry.mode"; rm -f "$fx/build.calls"
  step arch-carry-ok -- 
  expect '  … and once the commit carries it the next call builds (rc 0)' "$([ "$rc" = 0 ] && build_ok 0.0.1 "$(git -C "$st/tree" rev-parse --short=12 HEAD)"; echo $?)" "rc=$rc $out"
  origin_commit dirty
  echo greendirty > "$fx/batch.mode"; rm -f "$fx/build.calls"; : > "$fx/box.calls"
  step arch-dirty -- 
  expect 'archives: a worktree the pass left edited is not built from: rc 1, named, no build call' \
    "$([ "$rc" = 1 ] && ! grep -q 'build.sh --stage w' "$fx/box.calls" && grep -q 'ARCHIVES FAILED at .*: try 1 of 2: the worktree has uncommitted changes' "$st/report.txt"; echo $?)" "rc=$rc $(cat "$st/report.txt" 2>&1)"
  echo green > "$fx/batch.mode"
  step arch-dirty-ok -- 
  expect '  … and the next call resets the worktree to W and builds (rc 0)' "$([ "$rc" = 0 ] && build_ok 0.0.1 "$(git -C "$st/tree" rev-parse --short=12 HEAD)"; echo $?)" "rc=$rc $out"
  origin_commit to120
  echo to120 > "$fx/build.mode"; rm -f "$fx/build.calls"
  step arch-timeout -- 
  expect 'archives: the box'"'"'s own timeout (rc 124) is named as the bound hit, not as a plain failure' \
    "$([ "$rc" = 1 ] && [ ! -e "$st/W.archives" ] && grep -q "sm_120a: no end in 1800 s (the box.s timeout, rc 124)" "$st/report.txt"; echo $?)" "rc=$rc $(cat "$st/report.txt" 2>&1)"
  echo ok > "$fx/build.mode"
  origin_commit eleven
  echo hang86 > "$fx/build.mode"; echo 5 > "$fx/build.hang"; rm -f "$fx/build.calls" "$fx/build.pid.sm_86"
  step arch-bound BLOOMERY_FOLLOW_BUILD_BOUND=2 -- 
  expect 'archives: a build that does not end in BLOOMERY_FOLLOW_BUILD_BOUND is signalled (its captured pid) and fails the step by name (rc 1, no record)' \
    "$([ "$rc" = 1 ] && [ ! -e "$st/W.archives" ] && grep -q 'sm_86: no end in 2 s, stopped' "$st/report.txt" && [ -s "$fx/build.pid.sm_86" ] && ! alive "$(cat "$fx/build.pid.sm_86")"; echo $?)" "rc=$rc $(cat "$st/report.txt" 2>&1)"
  origin_commit twelve; c12=$first
  echo 8 > "$fx/build.hang"; rm -f "$fx/build.calls" "$fx/build.pid.sm_86"
  env FX="$fx" BLOOMERY_FOLLOW_HOME="$st" BLOOMERY_FOLLOW_REPO="$t/repo" bash "$runsh" > "$t/out-termb.log" 2>&1 < /dev/null &
  rpid=$! k=0
  while [ ! -s "$fx/build.pid.sm_86" ] && [ "$k" -lt 150 ]; do sleep 0.1; k=$((k + 1)); done
  bpid=$(cat "$fx/build.pid.sm_86" 2> /dev/null || echo 0)
  kill -TERM "$rpid" 2> /dev/null
  rc=0; wait "$rpid" 2> /dev/null || rc=$?
  k=0; while alive "$bpid" && [ "$k" -lt 50 ]; do sleep 0.1; k=$((k + 1)); done
  expect 'archives: TERM to the script while the builds run ends it 143, signals the builds it started and frees the lock' \
    "$([ "$rc" = 143 ] && [ "$bpid" != 0 ] && ! alive "$bpid" && [ ! -e "$st/lock.d" ]; echo $?)" "rc=$rc build pid $bpid alive: $(alive "$bpid" && echo yes)"
  echo ok > "$fx/build.mode"; rm -f "$fx/build.calls"
  step arch-after-term -- 
  expect '  … and the next call builds the archives at the W that call had written' "$([ "$rc" = 0 ] && build_ok 0.0.1 "${c12:0:12}" && [ "$(wa_commit)" = "$c12" ]; echo $?)" "rc=$rc $out"
  # 13. the GB10 archive (step 8b), built on the Spark after the x86-64 archives
  echo ok > "$fx/build.mode"; echo green > "$fx/batch.mode"; echo ok > "$fx/spark.mode"; echo idle > "$fx/box.state"
  gb_ok() { # <version> <head12>: the Spark was asked once for the GB10 archive, as step 8b says
    [ "$(grep -c . "$fx/spark.calls" 2> /dev/null)" = 1 ] \
      && grep -q "^host=spark remote=/root/bloomery-gb10 cwd=$st/tree head=$2 args=--tree $st/tree --wait 0 --bound 1800 --reason follower: the GB10 archive at $2 -- bash tools/release/build.sh --stage w $1 $2\$" "$fx/spark.calls"
  }
  gb_row() { awk '$1 == "gb10" { print $2 }' "$st/W.archives" 2> /dev/null; }
  origin_commit gb1; cg1=$first; rm -f "$fx/spark.calls" "$fx/build.calls" "$fx/spark.pid"
  step gb-green --
  expect 'gb10: a green pass builds the x86-64 archives, then the GB10 one on the Spark (host, remote directory, the worktree, no wait, the bound, stage w, version, commit)' \
    "$([ "$rc" = 0 ] && build_ok 0.0.1 "${cg1:0:12}" && gb_ok 0.0.1 "${cg1:0:12}"; echo $?)" "rc=$rc $(cat "$fx/spark.calls" 2>&1) | $out"
  expect '  … W.archives gains the gb10 row, its host and its directory, and keeps the x86-64 rows' \
    "$(grep -q "^gb10 $shag bloomery-0.0.1-linux-aarch64-cuda-sm121a.tar.gz\$" "$st/W.archives" && grep -q '^gb10_host=spark$' "$st/W.archives" && grep -q '^gb10_remote=/root/bloomery-gb10$' "$st/W.archives" \
       && grep -q "^sm86 $sha86 " "$st/W.archives" && grep -q "^sm120a $sha120 " "$st/W.archives" && [ ! -e "$st/gb10.fail" ]; echo $?)" "$(cat "$st/W.archives" 2>&1)"
  expect '  … the report names it, and with the pass stays within 15 lines' \
    "$([ "$(wc -l < "$st/report.txt")" -le 15 ] && grep -q "^GB10 archive: gb10 ${shag:0:12} at ${cg1:0:12} built natively on spark, in /root/bloomery-gb10/target/release-dist" "$st/report.txt"; echo $?)" "$(cat "$st/report.txt")"
  expect '  … and --tarballs gives pick.sh a gb10 row' "$(env BLOOMERY_FOLLOW_HOME="$st" bash "$runsh" --tarballs 0.0.1 | grep -qx "gb10 $shag $cg1"; echo $?)" "$(env BLOOMERY_FOLLOW_HOME="$st" bash "$runsh" --tarballs 0.0.1)"
  # a bench hold on the Spark: deferred, never failed; the next idle call builds only the GB10 archive
  origin_commit gb2; cg2=$first; echo hold > "$fx/spark.mode"; rm -f "$fx/spark.calls" "$fx/build.calls"
  step gb-hold --
  expect 'gb10: a bench hold up on the Spark (rc 75) defers the GB10 build: rc 75, W moves, the x86-64 record stands, no gb10 row, no gb10.fail' \
    "$([ "$rc" = 75 ] && [ "$(w_commit)" = "$cg2" ] && [ "$(wa_commit)" = "$cg2" ] && grep -q '^sm86 ' "$st/W.archives" && [ -z "$(gb_row)" ] && [ ! -e "$st/gb10.fail" ] && [ "$(grep -c . "$fx/spark.calls")" = 1 ]; echo $?)" "rc=$rc $(cat "$st/W.archives" 2>&1) $out"
  expect '  … the report says it is the Spark that is busy and that the next idle call builds it' \
    "$(grep -q '^GB10 archive NOT built: the Spark is busy (rc 75): spark-box: busy: the bench hold' "$st/report.txt" && grep -q 'the next idle call builds it' "$st/report.txt"; echo $?)" "$(cat "$st/report.txt" 2>&1)"
  echo ok > "$fx/spark.mode"; rm -f "$fx/spark.calls" "$fx/build.calls" "$fx/batch.calls"
  step gb-retry --
  expect '  … the next idle call (W current, the x86-64 archives built) builds only the GB10 one: no batch, no x86-64 build, one Spark call, the gb10 row is recorded' \
    "$([ "$rc" = 0 ] && [ ! -e "$fx/batch.calls" ] && [ ! -e "$fx/build.calls" ] && gb_ok 0.0.1 "${cg2:0:12}" && [ "$(gb_row)" = "$shag" ] && grep -q "^bloomery-follow .*: archives at W ${cg2:0:12}: ready, gb10 built\$" "$st/report.txt"; echo $?)" "rc=$rc $out | $(cat "$st/report.txt" 2>&1)"
  rm -f "$fx/spark.calls"
  step gb-current --
  expect '  … and with the gb10 row in place a current W has nothing to do (no Spark call)' "$([ "$rc" = 0 ] && grep -q 'nothing to do' <<< "$out" && [ ! -e "$fx/spark.calls" ]; echo $?)" "rc=$rc $out"
  # a failure: W and the x86-64 record stand, the tries count, then it gives up
  origin_commit gb3; cg3=$first; echo fail > "$fx/spark.mode"; rm -f "$fx/spark.calls" "$fx/build.calls"
  step gb-fail --
  expect 'gb10: a failed GB10 build leaves W and the x86-64 record standing (rc 1), counts the try, and the report names it' \
    "$([ "$rc" = 1 ] && [ "$(w_commit)" = "$cg3" ] && [ "$(wa_commit)" = "$cg3" ] && [ -z "$(gb_row)" ] && [ "$(sed -n 's/^tries=//p' "$st/gb10.fail")" = 1 ] \
       && grep -q "^GB10 ARCHIVE FAILED at ${cg3:0:12}: try 1 of 2: rc 3: release: the GB10 build broke (W and the x86-64 archives stand); logs: .*/runs/build-gb10-" "$st/report.txt"; echo $?)" "rc=$rc $(cat "$st/report.txt" 2>&1)"
  rm -f "$fx/build.calls"
  step gb-fail2 --
  expect '  … the next call tries once more (no x86-64 build, no pass) and counts the second failure' \
    "$([ "$rc" = 1 ] && [ "$(sed -n 's/^tries=//p' "$st/gb10.fail")" = 2 ] && [ "$(grep -c . "$fx/spark.calls")" = 2 ] && [ ! -e "$fx/build.calls" ]; echo $?)" "rc=$rc $(cat "$st/gb10.fail" 2>&1)"
  step gb-gaveup --
  expect '  … after BLOOMERY_FOLLOW_BUILD_TRIES failures at the commit nothing is started (rc 0) and the status names the way out' \
    "$([ "$rc" = 0 ] && [ "$(grep -c . "$fx/spark.calls")" = 2 ] && grep -q 'not tried again' "$st/status.txt" && grep -q 'remove .*gb10.fail' "$st/status.txt"; echo $?)" "rc=$rc $(cat "$st/status.txt" 2>&1)"
  echo ok > "$fx/spark.mode"; rm -f "$st/gb10.fail" "$fx/spark.calls"
  step gb-fixed --
  expect '  … with the failure gone the next call builds it and leaves no gb10.fail' "$([ "$rc" = 0 ] && [ "$(gb_row)" = "$shag" ] && [ ! -e "$st/gb10.fail" ]; echo $?)" "rc=$rc $out"
  # no sha256 line, the Spark's own timeout, a call that outlasts its bound
  origin_commit gb4; echo nosha > "$fx/spark.mode"
  step gb-nosha --
  expect 'gb10: a build that ends 0 with no sha256 line for its archive fails the step by name (rc 1, no row)' \
    "$([ "$rc" = 1 ] && [ -z "$(gb_row)" ] && grep -q 'try 1 of 2: built, but its log has no sha256 line for bloomery-0.0.1-linux-aarch64-cuda-sm121a.tar.gz' "$st/report.txt"; echo $?)" "rc=$rc $(cat "$st/report.txt" 2>&1)"
  origin_commit gb5; echo to > "$fx/spark.mode"
  step gb-to --
  expect 'gb10: the Spark'"'"'s own timeout (rc 124) is named as the bound hit' "$([ "$rc" = 1 ] && grep -q "no end in 1800 s (the Spark's timeout, rc 124)" "$st/report.txt"; echo $?)" "rc=$rc $(cat "$st/report.txt" 2>&1)"
  origin_commit gb6; echo hang > "$fx/spark.mode"; echo 5 > "$fx/spark.hang"; rm -f "$fx/spark.pid"
  step gb-bound BLOOMERY_FOLLOW_BUILD_BOUND=1 BLOOMERY_FOLLOW_GB10_SLACK=0 --
  expect 'gb10: a call that does not end in its bound is signalled (its captured pid) and fails the step by name (rc 1, no row)' \
    "$([ "$rc" = 1 ] && [ -z "$(gb_row)" ] && grep -q 'try 1 of 2: no end in 1 s, stopped' "$st/report.txt" && [ -s "$fx/spark.pid" ] && ! alive "$(cat "$fx/spark.pid")"; echo $?)" "rc=$rc $(cat "$st/report.txt" 2>&1)"
  # a TERM while the Spark build runs stops it and frees the lock
  origin_commit gb7; echo 8 > "$fx/spark.hang"; rm -f "$fx/spark.pid"
  env FX="$fx" BLOOMERY_FOLLOW_HOME="$st" BLOOMERY_FOLLOW_REPO="$t/repo" bash "$runsh" > "$t/out-termg.log" 2>&1 < /dev/null &
  rpid=$! k=0
  while [ ! -s "$fx/spark.pid" ] && [ "$k" -lt 150 ]; do sleep 0.1; k=$((k + 1)); done
  bpid=$(cat "$fx/spark.pid" 2> /dev/null || echo 0)
  kill -TERM "$rpid" 2> /dev/null
  rc=0; wait "$rpid" 2> /dev/null || rc=$?
  k=0; while alive "$bpid" && [ "$k" -lt 50 ]; do sleep 0.1; k=$((k + 1)); done
  expect 'gb10: TERM to the script while the Spark build runs ends it 143, signals that build and frees the lock' \
    "$([ "$rc" = 143 ] && [ "$bpid" != 0 ] && ! alive "$bpid" && [ ! -e "$st/lock.d" ]; echo $?)" "rc=$rc spark pid $bpid alive: $(alive "$bpid" && echo yes)"
  # left out: BLOOMERY_FOLLOW_GB10=0 asks the Spark nothing and records no row; --tarballs then has no gb10 row
  origin_commit gb8; echo ok > "$fx/spark.mode"; rm -f "$fx/spark.calls" "$fx/build.calls"
  step gb-off BLOOMERY_FOLLOW_GB10=0 --
  expect 'gb10: BLOOMERY_FOLLOW_GB10=0 builds the x86-64 archives and asks the Spark nothing' \
    "$([ "$rc" = 0 ] && [ -e "$fx/build.calls" ] && [ ! -e "$fx/spark.calls" ] && [ -z "$(gb_row)" ] && [ -e "$st/W.archives" ]; echo $?)" "rc=$rc $out"
  expect '  … and its --tarballs has the x86-64 rows alone' "$([ "$(env BLOOMERY_FOLLOW_GB10=0 BLOOMERY_FOLLOW_HOME="$st" bash "$runsh" --tarballs 0.0.1 | wc -l | tr -d ' ')" = 2 ]; echo $?)" "$(env BLOOMERY_FOLLOW_GB10=0 BLOOMERY_FOLLOW_HOME="$st" bash "$runsh" --tarballs 0.0.1)"
  # the dry run asks the Spark's build.sh --dry-run too, and builds nothing there
  rm -f "$fx/spark.calls" "$fx/spark.pid"
  step gb-dry -- --dry-run --tree "$t/repo"
  expect 'gb10: a dry run asks the Spark for build.sh --dry-run (serve version, tree commit), and nothing is built' \
    "$(grep -q "^host=spark remote=/root/bloomery-gb10 cwd=$t/repo head=$(git -C "$t/repo" rev-parse --short=12 HEAD) args=--tree $t/repo --wait 0 --bound 300 --reason follower: dry run -- bash tools/release/build.sh --dry-run --stage w 0.0.1 " "$fx/spark.calls" && [ ! -e "$fx/spark.pid" ]; echo $?)" "rc=$rc $(cat "$fx/spark.calls" 2>&1)"
  rm -f "$st/W.archives"
  tb=$(env BLOOMERY_FOLLOW_HOME="$st" bash "$runsh" --tarballs 0.0.1 2>&1)
  expect 'tarballs: with no record every archive is absent' "$([ "$tb" = "$(printf 'sm86 absent\nsm120a absent\ngb10 absent')" ]; echo $?)" "$tb"
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
  mutant no-build 's/^    build_archives "\$WT" "\$TARGET"$/    true/' '^    true$'
  mutant no-retry 's/^    build_archives "\$WT" "\$TARGET" # W is current.*$/    true/' '^    true$'
  mutant no-probe 's/^    box_idle "\$tree"$/    true/' '^    true$'
  mutant waits 's/ BLOOMERY_BOX_WAIT=0 tools\/box.sh "timeout/ tools\/box.sh "timeout/' '"[$]arch" tools/box.sh "timeout'
  mutant partial 's/^  if \[ -n "\$bad" \]; then$/  if false; then/' '^  if false; then$'
  mutant no-bound 's/^      if \[ \$((SECONDS - t0)) -ge .*; then$/      if false; then/' '^      if false; then$'
  mutant no-kill-builds 's/trap .kill -TERM \$BUILD_PIDS 2> \/dev\/null; wait/trap '"'"':; wait/' "trap ':; wait"
  mutant no-sha 's/^        if \[ "\${line#\* }" = "\$name" \]; then$/        if true; then/' '^        if true; then$'
  mutant 75-fails 's/^      elif \[ "\$rc" = 75 \]; then$/      elif false; then/' '^      elif false; then$'
  mutant no-tries 's/-ge "\$BUILD_TRIES" \]/-ge 99 ]/' '-ge 99 \]'
  mutant no-carry 's/^  elif ! carry=.*; then$/  elif false; then/' '^  elif false; then$'
  mutant no-dirty 's/^  elif \[ -n "\$(git -C "\$tree" status --porcelain.*; then$/  elif false; then/' '^  elif false; then$'
  mutant rc124 's/^      elif \[ "\$rc" = 124 \] || \[ "\$rc" = 137 \]; then$/      elif false; then/' '^      elif false; then$'
  mutant no-stage 's/build.sh --stage w \$ARCH_VER/build.sh $ARCH_VER/' 'build.sh [$]ARCH_VER'
  mutant no-dry-build 's/^    archives_dry "\$WT" || drc=\$?$/    true/' '^    true$'
  # state for the mutant cases: a fresh W at c1-equivalent is not needed; each starts from its own state directory
  echo red > "$fx/batch.mode"; echo lease > "$fx/box.state"; rm -rf "$st" "$fx/batch.calls"
  RUNSH=$t/run-no-idle.sh step m-noidle -- 
  expect 'mutant no-idle: a lease up no longer stops the pass (the batch runs)' "$([ -e "$fx/batch.calls" ]; echo $?)" "rc=$rc $out"
  echo idle > "$fx/box.state"; rm -rf "$st"; echo green > "$fx/batch.mode"
  echo red > "$fx/batch.mode"
  rm -f "$fx/build.calls"
  RUNSH=$t/run-w-on-red.sh step m-wred -- 
  expect 'mutant w-on-red: a red pass moves W and builds archives for it' "$([ -e "$st/W" ] && [ -e "$fx/build.calls" ]; echo $?)" "rc=$rc"
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
  expect 'mutant no-kill: without the signal the batch outlives the script' "$(alive "$bpid"; echo $?)" "batch pid $bpid is gone"
  ! alive "$bpid" || kill -TERM "$bpid" 2> /dev/null
  wait "$rpid" 2> /dev/null || true
  # the archives' mutants: each runs its scenario on a fresh state directory
  mrun() { # <mutant> <tag> <env…>: the mutant script, one step, in a fresh state; the stubs' files are the caller's
    rm -rf "$st"; rm -f "$fx/build.calls" "$fx/batch.calls" "$fx/box.arch"; : > "$fx/box.calls"
    RUNSH=$t/run-$1.sh step "$2" "${@:3}" -- 
  }
  echo ok > "$fx/build.mode"; echo green > "$fx/batch.mode"; echo idle > "$fx/box.state"
  mrun no-build m-nobuild
  expect 'mutant no-build: a green pass writes W and builds nothing' "$([ -e "$st/W" ] && [ ! -e "$fx/build.calls" ] && [ ! -e "$st/W.archives" ]; echo $?)" "rc=$rc"
  echo defer > "$fx/build.mode"; rm -rf "$st"
  step m-seed-retry -- 
  echo ok > "$fx/build.mode"; rm -f "$fx/build.calls"
  RUNSH=$t/run-no-retry.sh step m-noretry -- 
  expect 'mutant no-retry: a current W without archives is left without (nothing built, rc 0)' "$([ ! -e "$fx/build.calls" ] && [ ! -e "$st/W.archives" ]; echo $?)" "rc=$rc $out"
  echo greenlease > "$fx/batch.mode"
  mrun no-probe m-noprobe
  echo idle > "$fx/box.state"
  expect 'mutant no-probe: without the second look at the box the builds start under the hold that went up' "$(grep -q 'build.sh --stage w' "$fx/box.calls"; echo $?)" "rc=$rc"
  echo green > "$fx/batch.mode"
  mrun waits m-waits
  expect 'mutant waits: without BLOOMERY_BOX_WAIT=0 the build would wait out a hold (the call carries no wait)' "$(grep -q 'wait=unset' "$fx/build.calls"; echo $?)" "$(cat "$fx/build.calls" 2>&1)"
  echo fail120 > "$fx/build.mode"
  mrun partial m-partial
  expect 'mutant partial: a failed archive no longer fails the step: a record with the one archive that was built is written' "$([ -e "$st/W.archives" ] && ! grep -q '^sm120a ' "$st/W.archives"; echo $?)" "rc=$rc $(cat "$st/W.archives" 2>&1)"
  echo hang86 > "$fx/build.mode"; echo 5 > "$fx/build.hang"
  mrun no-bound m-nobound BLOOMERY_FOLLOW_BUILD_BOUND=2
  expect 'mutant no-bound: a build that outlasts its bound is waited for to its end (rc 0, a record)' "$([ "$rc" = 0 ] && [ -e "$st/W.archives" ]; echo $?)" "rc=$rc $(cat "$st/report.txt" 2>&1)"
  echo 8 > "$fx/build.hang"; rm -f "$fx/build.pid.sm_86"
  rm -rf "$st"
  env FX="$fx" BLOOMERY_FOLLOW_HOME="$st" BLOOMERY_FOLLOW_REPO="$t/repo" bash "$t/run-no-kill-builds.sh" > "$t/out-term3.log" 2>&1 < /dev/null &
  rpid=$! k=0
  while [ ! -s "$fx/build.pid.sm_86" ] && [ "$k" -lt 150 ]; do sleep 0.1; k=$((k + 1)); done
  bpid=$(cat "$fx/build.pid.sm_86" 2> /dev/null || echo 0)
  kill -TERM "$rpid" 2> /dev/null
  sleep 1
  expect 'mutant no-kill-builds: without the signal the build outlives the script' "$(alive "$bpid"; echo $?)" "build pid $bpid is gone"
  ! alive "$bpid" || kill -TERM "$bpid" 2> /dev/null
  wait "$rpid" 2> /dev/null || true
  echo nosha > "$fx/build.mode"
  mrun no-sha m-nosha
  expect 'mutant no-sha: an archive with no sha256 line in its log is recorded all the same' "$([ -e "$st/W.archives" ]; echo $?)" "rc=$rc"
  echo defer > "$fx/build.mode"
  mrun 75-fails m-75fails
  expect 'mutant 75-fails: a build that found the box busy is counted as a failed one (rc 1, archives.fail)' "$([ "$rc" = 1 ] && [ -e "$st/archives.fail" ]; echo $?)" "rc=$rc"
  echo fail120 > "$fx/build.mode"
  rm -rf "$st"; step m-seed-tries -- 
  step m-seed-tries2 -- 
  rm -f "$fx/build.calls"
  RUNSH=$t/run-no-tries.sh step m-notries -- 
  expect 'mutant no-tries: a third try is made at a commit that failed BLOOMERY_FOLLOW_BUILD_TRIES times' "$([ -e "$fx/build.calls" ]; echo $?)" "rc=$rc $out"
  echo ok > "$fx/build.mode"; echo fail > "$fx/carry.mode"
  mrun no-carry m-nocarry
  echo ok > "$fx/carry.mode"
  expect 'mutant no-carry: a commit that lacks a listed fix is built all the same' "$([ -e "$fx/build.calls" ]; echo $?)" "rc=$rc"
  echo greendirty > "$fx/batch.mode"
  mrun no-dirty m-nodirty
  echo green > "$fx/batch.mode"
  expect 'mutant no-dirty: a worktree with uncommitted changes is built from' "$([ -e "$fx/build.calls" ]; echo $?)" "rc=$rc"
  echo to120 > "$fx/build.mode"
  mrun rc124 m-rc124
  expect 'mutant rc124: the box'"'"'s timeout is reported as a plain failure (rc 124: …)' "$(grep -q 'sm_120a: rc 124' "$st/report.txt"; echo $?)" "$(cat "$st/report.txt" 2>&1)"
  echo ok > "$fx/build.mode"
  mrun no-stage m-nostage
  expect 'mutant no-stage: the box build runs without --stage w (main'"'"'s README would refuse it)' "$([ -e "$fx/build.calls" ] && ! grep -q -- '--stage w' "$fx/build.calls"; echo $?)" "$(cat "$fx/build.calls" 2>&1)"
  echo ok > "$fx/build.mode"
  rm -f "$fx/box.arch" "$fx/build.calls"; rm -rf "$st"
  RUNSH=$t/run-no-dry-build.sh step m-nodry -- --dry-run --tree "$t/repo"
  expect 'mutant no-dry-build: a dry run no longer asks the box for each archive'"'"'s build.sh --dry-run' "$([ ! -e "$fx/box.arch" ]; echo $?)" "rc=$rc"
  # the GB10 step's mutants
  mutant g-no-gb10 's/^  case \$ARCH_STATE in built | ready) build_gb10 "\$tree" "\$commit" ;; esac$/  true/' '^  true$'
  mutant g-75-fails 's/^    elif \[ "\$rc" = 75 \]; then$/    elif false; then/' '^    elif false; then$'
  mutant g-no-sha 's/^      if \[ "\${line#\* }" = "\$name" \]; then$/      if true; then/' '^      if true; then$'
  mutant g-keep-x86 's/^  { grep -v .\^gb10. "\$STATE\/W.archives" || true; } > .*$/  rm -f "$STATE\/W.archives"/' '^  rm -f "[$]STATE/W.archives"$'
  mutant g-no-kill 's/trap .kill -TERM \$BUILD_PIDS 2> \/dev\/null; wait \$BUILD_PIDS 2> \/dev\/null; echo "run.sh: interrupted: the GB10/trap '"'"':; wait $BUILD_PIDS 2> \/dev\/null; echo "run.sh: interrupted: the GB10/' "trap ':; wait [$]BUILD_PIDS 2> /dev/null; echo .run.sh: interrupted: the GB10"
  mutant g-no-bound 's/^      if \[ \$((SECONDS - t0)) -ge \$((BUILD_BOUND + BUILD_GRACE + GB10_SLACK)) \]; then.*$/      if false; then/' '^      if false; then$'
  mutant g-off 's/^  \[ "\$GB10_ON" = 1 \] || return 0$/  true/' '^  true$'
  mutant g-no-dry 's/^  if \[ "\$GB10_ON" = 1 \]; then$/  if false; then/' '^  if false; then$'
  mutant g-ready-skip 's/^  \[ "\$GB10_ON" != 1 \] || \[ -n "\$(gb10_sha)" \] || gb10_gaveup "\$1"$/  true/' '^  true$'
  grun() { # <mutant> <tag> <env…>: the mutant script on a fresh state, the Spark stub's files cleared
    rm -rf "$st"; rm -f "$fx/build.calls" "$fx/batch.calls" "$fx/spark.calls" "$fx/spark.pid"; : > "$fx/box.calls"
    RUNSH=$t/run-$1.sh step "$2" "${@:3}" -- 
  }
  echo ok > "$fx/build.mode"; echo green > "$fx/batch.mode"; echo idle > "$fx/box.state"; echo ok > "$fx/spark.mode"
  grun g-no-gb10 m-gnogb10
  expect 'mutant g-no-gb10: a green pass builds the x86-64 archives and never asks the Spark' "$([ -e "$st/W.archives" ] && [ ! -e "$fx/spark.calls" ] && ! grep -q '^gb10 ' "$st/W.archives"; echo $?)" "rc=$rc"
  echo hold > "$fx/spark.mode"
  grun g-75-fails m-g75
  expect 'mutant g-75-fails: a Spark held by a bench is counted as a failed build (rc 1, gb10.fail)' "$([ "$rc" = 1 ] && [ -e "$st/gb10.fail" ]; echo $?)" "rc=$rc"
  echo nosha > "$fx/spark.mode"
  grun g-no-sha m-gnosha
  expect 'mutant g-no-sha: an archive with no sha256 line in its log is recorded all the same' "$(grep -q '^gb10 ' "$st/W.archives"; echo $?)" "rc=$rc"
  echo fail > "$fx/spark.mode"
  grun g-keep-x86 m-gkeep
  expect 'mutant g-keep-x86: a failed GB10 build takes the x86-64 record with it' "$([ ! -e "$st/W.archives" ]; echo $?)" "rc=$rc"
  echo ok > "$fx/spark.mode"; echo 8 > "$fx/spark.hang"; echo hang > "$fx/spark.mode"; rm -rf "$st"; rm -f "$fx/spark.pid" "$fx/spark.calls"
  env FX="$fx" BLOOMERY_FOLLOW_HOME="$st" BLOOMERY_FOLLOW_REPO="$t/repo" bash "$t/run-g-no-kill.sh" > "$t/out-term4.log" 2>&1 < /dev/null &
  rpid=$! k=0
  while [ ! -s "$fx/spark.pid" ] && [ "$k" -lt 150 ]; do sleep 0.1; k=$((k + 1)); done
  bpid=$(cat "$fx/spark.pid" 2> /dev/null || echo 0)
  kill -TERM "$rpid" 2> /dev/null
  sleep 1
  expect 'mutant g-no-kill: without the signal the Spark build outlives the script' "$(alive "$bpid"; echo $?)" "spark pid $bpid is gone"
  ! alive "$bpid" || kill -TERM "$bpid" 2> /dev/null
  wait "$rpid" 2> /dev/null || true
  echo 5 > "$fx/spark.hang"
  grun g-no-bound m-gnobound BLOOMERY_FOLLOW_BUILD_BOUND=1 BLOOMERY_FOLLOW_GB10_SLACK=0
  expect 'mutant g-no-bound: a Spark build that outlasts its bound is waited for to its end (rc 0, a gb10 row)' "$([ "$rc" = 0 ] && grep -q '^gb10 ' "$st/W.archives"; echo $?)" "rc=$rc $(cat "$st/report.txt" 2>&1)"
  echo ok > "$fx/spark.mode"
  grun g-off m-goff BLOOMERY_FOLLOW_GB10=0
  expect 'mutant g-off: BLOOMERY_FOLLOW_GB10=0 is ignored (the Spark is asked)' "$([ -e "$fx/spark.calls" ]; echo $?)" "rc=$rc"
  rm -rf "$st"; rm -f "$fx/spark.calls"
  RUNSH=$t/run-g-no-dry.sh step m-gnodry -- --dry-run --tree "$t/repo"
  expect 'mutant g-no-dry: a dry run no longer asks the Spark for its build.sh --dry-run' "$([ ! -e "$fx/spark.calls" ]; echo $?)" "rc=$rc"
  echo hold > "$fx/spark.mode"
  grun g-ready-skip m-gready
  echo ok > "$fx/spark.mode"; rm -f "$fx/spark.calls"
  RUNSH=$t/run-g-ready-skip.sh step m-gready2 -- 
  expect 'mutant g-ready-skip: a current W with its x86-64 archives and no GB10 archive reads as done (the Spark is never asked again)' "$([ ! -e "$fx/spark.calls" ]; echo $?)" "rc=$rc $out"
  echo fail > "$fx/spark.mode"
  grun no-tries m-gnotries
  RUNSH=$t/run-no-tries.sh step m-gnotries2 -- 
  rm -f "$fx/spark.calls"
  RUNSH=$t/run-no-tries.sh step m-gnotries3 -- 
  expect 'mutant no-tries: a third GB10 try is made at a commit that failed BLOOMERY_FOLLOW_BUILD_TRIES times' "$([ -e "$fx/spark.calls" ]; echo $?)" "rc=$rc $out"
  echo ok > "$fx/spark.mode"
  echo "run.sh self-test: $((n - bad)) of $n ok"
  [ "$bad" = 0 ]
}
if [ "${1:-}" = --self-test ]; then
  self_test
  exit $?
fi
if [ "${1:-}" = --tarballs ]; then
  [ $# = 2 ] || { usage; exit 64; }
  tarballs "$2"
  exit $?
fi
run_main "$@"
