#!/usr/bin/env bash
# Runs one command on our DGX Spark (ssh alias spark: aarch64, GB10 sm_121a, root) in a synced copy of a bloomery tree, the way
# tools/box.sh runs one on the box, and keeps the Spark shared with its bench sessions: the command waits while a bench is up and
# puts up the lead's own hold while it runs. The GB10 release archive is built through it (the follower's step 8b, tools/release/
# build.sh --stage w on the Spark); machine paths live here and in configs/spark/, never in the bloomery repo.
#
#   spark-box.sh [--tree DIR] [--wait S] [--bound S] [--reason TEXT] -- <command…>
#   spark-box.sh --probe [--hold-dir DIR]    one look: `idle` (rc 0), or `busy: …` lines (rc 75); rc 70: the Spark cannot be asked
#   spark-box.sh --install-env               configs/spark/bloomery-env.sh to the Spark's ~/bloomery-env.sh (when it differs)
#   spark-box.sh --setup [--tree DIR]        once per cuda-oxide pin: the CUDA 13.3 toolkit (below), the pin's cargo-oxide and patched
#                                            backend under the Spark's ~/.cargo/cuda-oxide-bloomery/<rev>/ (cargo install,
#                                            tools/oxide-backend.sh); each is a run, so the bench protocol applies
#   spark-box.sh --self-test
#
# Why not tools/box.sh with BLOOMERY_BOX=spark: its remote path is the box's — guard and gate locks under /root (the guard would make
# /root/bloomery-cpu.lock there, the file that marks the box), a card picked by name (3090, A6000), the queue, the 3090 pin. Its
# local mode is the Spark's own shape (one card, locks in a directory of its own, the environment file, the cargo-oxide pin check,
# tools/oxide-host.sh) but runs on the machine that has the tree. So this script is the missing half: rsync the tree over, then run
# `BLOOMERY_BOX_LOCAL=1 tools/box.sh '<command>'` there. box.sh is unchanged.
#
# A run:
#   1. Wait while the bench is up (below): poll every $POLL s, name what is up at once and once a minute, start only on two quiet
#      polls in a row after a wait, and end 75 naming it after --wait seconds (default 1800; 0: no wait).
#   2. rsync the tree to $REMOTE (box.sh's flags: content checksums, --delete, no target/, .git/ or the codegen's root files), behind
#      the directory's lock: a run in that directory makes the sync, not the run, refuse (75), so its tree is never replaced under it.
#   3. On the Spark, in one ssh (the pin's cargo-oxide, ~/.cargo/cuda-oxide-bloomery/<rev>/bin of the tree's Cargo.toml rev, goes first on
#      PATH: local mode takes cargo-oxide from PATH, the box's mode from that directory): take that lock, put up /root/spark-lead.hold, look at the bench once more (the later of two holds
#      gives way: a bench hold that went up first or in the same second ends this run 75, the hold taken down, and step 1 starts again),
#      run the command in the tree under `timeout --kill-after=10 --bound` (default 1800) with box.sh's local mode, take the hold down
#      on every exit path (TERM, INT and HUP stop the command first; the command's pid is captured, nothing else is signalled).
# The exit code is the command's; 75 contention (a hold, the directory in use), 70 the Spark could not be asked, 66 no tree or no
# remote directory, 64 usage, 69 the Spark's environment file is missing.
#
# The bench protocol (docs/spark-hold.md carries it for the bench sessions): the bench is up while /root/spark-bench.hold exists and
# is not past its end time, or while /root/spark-lease (the bench's own lease, `<pid> <reason> <start>`) names a live pid. A hold is
# one line of `key=value` words, `owner= since=<epoch> until=<epoch>` first and a free-text `reason=` last. A hold with no until=
# stands until it is removed. The lead's hold, /root/spark-lead.hold, has the same shape with owner=lead, until = start + bound + 120.
#
# Environment (tests set them): BLOOMERY_SPARK (the ssh host, spark), _REMOTE (/root/bloomery-gb10), _LOCKS (/root/bloomery-locks,
# local mode's BLOOMERY_LOCK_DIR), _HOLDS (/root, where the three files above are), _POLL (30). A command that wants the Spark's
# environment finds it in ~/bloomery-env.sh there (box.sh sources it).
set -uo pipefail

SELF=$(cd "$(dirname "$0")" && pwd -P)/$(basename "$0")
HOST=${BLOOMERY_SPARK:-spark}
REMOTE=${BLOOMERY_SPARK_REMOTE:-/root/bloomery-gb10}
LOCKS=${BLOOMERY_SPARK_LOCKS:-/root/bloomery-locks}
HOLDS=${BLOOMERY_SPARK_HOLDS:-/root}
POLL=${BLOOMERY_SPARK_POLL:-30}
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15)
# The tree's tested toolkit is CUDA 13.3 (docs/BUILD.md): its headers carry the driver API the engine binds (cuGraphNodeGetParams, the
# atomic-reduction stream memops), which the Spark's own 13.0 packages lack, so bindgen on them fails. The 13.3 toolkit is taken from
# NVIDIA's devel image, the container the contributor docs name, into a directory of ours; the binary it builds still runs on R580.
CUDA_IMAGE=${BLOOMERY_SPARK_CUDA_IMAGE:-nvidia/cuda:13.3.1-devel-ubuntu24.04}
CUDA_DIR=${BLOOMERY_SPARK_CUDA_DIR:-/root/bloomery-cuda/cuda-13.3.1}
BENCH=$HOLDS/spark-bench.hold LEAD=$HOLDS/spark-lead.hold BLEASE=$HOLDS/spark-lease

usage() { echo "usage: spark-box.sh [--tree DIR] [--wait S] [--bound S] [--reason TEXT] -- <command…> | --probe | --install-env | --setup [--tree DIR] | --self-test" >&2; }
die() { echo "spark-box: $2" >&2; exit "$1"; }

# The bench probe, one text for the Mac's polls and for the run on the Spark: probe sets BENCH_SINCE (the bench hold's since=, 0 for the
# lease or a hold without one; empty when none is up), prints `busy: …` for each thing that is up and `note: …` for a stale hold, and
# returns 1 when something is up.
PROBE_FN='probe() {
  local now line u s pid busy=0
  now=$(date +%s); BENCH_SINCE=
  if [ -e "$BENCH" ]; then
    line=" $(head -n 1 "$BENCH" 2> /dev/null)"
    u=$(printf "%s\n" "$line" | sed -n "s/.* until=\([0-9][0-9]*\).*/\1/p")
    s=$(printf "%s\n" "$line" | sed -n "s/.* since=\([0-9][0-9]*\).*/\1/p")
    if [ -n "$u" ] && [ "$u" -le "$now" ]; then
      echo "note: $BENCH is past its until=$u: stale, ignored"
    else
      echo "busy: the bench hold $BENCH:$line"
      busy=1; BENCH_SINCE=${s:-0}
    fi
  fi
  if [ -f "$BLEASE" ]; then
    pid=$(awk "NR == 1 { print \$1 }" "$BLEASE" 2> /dev/null)
    case $pid in
      "" | *[!0-9]*) ;;
      *) if kill -0 "$pid" 2> /dev/null; then
           echo "busy: the bench lease $BLEASE is held by live pid $pid: $(head -n 1 "$BLEASE" | cut -c1-120)"
           busy=1; BENCH_SINCE=0
         fi ;;
    esac
  fi
  [ "$busy" = 0 ]
}'

# The probe's remote script: its three paths come as arguments, then `probe`.
probe_remote() { # <hold dir>: the remote's output on stdout, its rc 0 idle / 1 busy; 70 when ssh failed
  local out rc=0 script
  script="BENCH=\$1 BLEASE=\$2; $PROBE_FN; probe && echo idle"
  out=$(printf '%s\n' "$script" | ssh "${SSH_OPTS[@]}" "$HOST" "bash -s -- $(printf '%q %q' "$BENCH" "$BLEASE")" 2>&1) || rc=$?
  printf '%s\n' "$out"
  case $rc in 0) return 0 ;; 1) return 1 ;; *) return 70 ;; esac
}

# The run, on the Spark. Arguments: LEAD BENCH BLEASE LOCKS DIR BOUND REASON CMD. Taken under the directory's lock (flock, outside).
RUN_SCRIPT='LEAD=$1 BENCH=$2 BLEASE=$3 LOCKS=$4 DIR=$5 BOUND=$6 REASON=$7 CMD=$8
'"$PROBE_FN"'
now=$(date +%s)
mine="owner=lead since=$now until=$((now + BOUND + 120)) pid=$$ reason=$REASON"
set -C
if ! printf "%s\n" "$mine" > "$LEAD" 2> /dev/null; then
  old=" $(head -n 1 "$LEAD" 2> /dev/null)"
  ou=$(printf "%s\n" "$old" | sed -n "s/.* until=\([0-9][0-9]*\).*/\1/p")
  if [ -n "$ou" ] && [ "$ou" -le "$now" ]; then
    echo "note: $LEAD is past its until=$ou: stale, replaced"
    rm -f "$LEAD"
    printf "%s\n" "$mine" > "$LEAD" || { echo "busy: cannot take $LEAD"; exit 75; }
  else
    echo "busy: the lead hold $LEAD is up:$old"
    exit 75
  fi
fi
set +C
trap "rm -f \"$LEAD\"" EXIT
if ! probe; then
  if [ "${BENCH_SINCE:-0}" -le "$now" ]; then
    echo "busy: the bench went up first (since=${BENCH_SINCE:-0}, ours $now): this run gives way, the hold is down"
    exit 75
  fi
  echo "note: the bench hold went up after ours (since=$BENCH_SINCE): it gives way, this run goes on"
fi
cd "$DIR" || { echo "no $DIR on the Spark"; exit 66; }
rev=$(sed -n "s/^cuda-device = .*rev = .\([0-9a-f]*\)..*/\1/p" Cargo.toml 2> /dev/null | head -n 1)
[ -z "$rev" ] || export PATH="$HOME/.cargo/cuda-oxide-bloomery/$rev/bin:$PATH"
BLOOMERY_BOX_LOCAL=1 BLOOMERY_LOCK_DIR="$LOCKS" BLOOMERY_BOX_WAIT=0 timeout --kill-after=10 "$BOUND" bash tools/box.sh "$CMD" < /dev/null &
pid=$!
trap "kill -TERM $pid 2> /dev/null" TERM INT HUP
rc=0
wait "$pid" || rc=$?
if kill -0 "$pid" 2> /dev/null; then wait "$pid" || rc=$?; fi
exit "$rc"'

# The cancel script: the run on the Spark wrote its own pid in the lead hold (owner=lead); TERM that pid and nothing else. The local ssh
# client being killed does not reach a remote command that has no tty, so an interrupted call names the run by its hold.
CANCEL_SCRIPT='line=" $(head -n 1 "$1" 2> /dev/null)"
case "$line" in
  *" owner=lead "*)
    p=$(printf "%s\n" "$line" | sed -n "s/.* pid=\([0-9][0-9]*\).*/\1/p")
    [ -z "$p" ] || { kill -TERM "$p" 2> /dev/null && echo "spark-box: TERM sent to the run on the Spark, pid $p"; } ;;
esac'

cancel_remote() {
  printf '%s\n' "$CANCEL_SCRIPT" | ssh "${SSH_OPTS[@]}" "$HOST" "bash -s -- $(printf '%q' "$LEAD")" 2>&1 || true
}

sync_tree() { # <tree>: rsync behind the directory's lock; rc 75 when a run holds the directory
  local tree=$1 rc=0 rp
  # the lock file is the run's: flock -n -x fails while one runs there
  rp="mkdir -p $LOCKS && flock -n -x -E 75 $LOCKS/spark-box.lock rsync"
  rsync -rlpgoDcz --delete --exclude target/ --exclude .git/ --exclude '/*.ptx' --exclude '/*.ll' --exclude '/.oxide-artifacts/' \
    --rsync-path="$rp" -e "ssh ${SSH_OPTS[*]}" "$tree"/ "$HOST:$REMOTE/" || rc=$?
  case $rc in
    0) return 0 ;;
    75 | 12) echo "spark-box: a run holds $REMOTE ($LOCKS/spark-box.lock) or the connection broke (rsync rc $rc): the tree there is not replaced" >&2; return 75 ;;
    *) echo "spark-box: rsync to $HOST:$REMOTE failed (rc $rc)" >&2; return "$rc" ;;
  esac
}

run_main() {
  local tree=$PWD wait_s=1800 bound=1800 reason='' cmd='' t0 quiet=0 waited=0 last=-99 out rc
  while [ $# -gt 0 ]; do
    case $1 in
      --tree) [ $# -ge 2 ] || { usage; exit 64; }; tree=$2; shift 2 ;;
      --wait) [ $# -ge 2 ] || { usage; exit 64; }; wait_s=$2; shift 2 ;;
      --bound) [ $# -ge 2 ] || { usage; exit 64; }; bound=$2; shift 2 ;;
      --reason) [ $# -ge 2 ] || { usage; exit 64; }; reason=$2; shift 2 ;;
      --) shift; break ;;
      *) usage; exit 64 ;;
    esac
  done
  [ $# -ge 1 ] || { usage; exit 64; }
  cmd=$*
  for n in "$wait_s" "$bound"; do case $n in '' | *[!0-9]*) die 64 "--wait and --bound are whole seconds, got '$n'" ;; esac; done
  [ "$bound" -ge 1 ] || die 64 "--bound is whole seconds from 1"
  case $POLL in '' | *[!0-9]* | 0) die 64 "BLOOMERY_SPARK_POLL is whole seconds above 0, got '$POLL'" ;; esac
  [ -d "$tree" ] || die 66 "--tree $tree is not a directory"
  tree=$(cd "$tree" && pwd -P)
  [ -n "$reason" ] || reason="spark-box ${cmd:0:60}"
  reason=${reason//$'\n'/ }
  t0=$SECONDS
  while :; do
    # 1. wait for the bench
    rc=0
    out=$(probe_remote) || rc=$?
    case $rc in
      70) die 70 "$HOST could not be asked: $(printf '%s\n' "$out" | tail -n 1)" ;;
      1)
        quiet=0 waited=1
        if [ $((SECONDS - t0)) -ge "$wait_s" ]; then
          printf '%s\n' "$out" | grep '^busy:' | sed 's/^/spark-box: /' >&2
          die 75 "the bench is still up after $wait_s s: nothing was synced or run"
        fi
        if [ $((SECONDS - last)) -ge 60 ]; then
          last=$SECONDS
          printf '%s\n' "$out" | grep '^busy:' | sed 's/^/spark-box: waiting: /' >&2
        fi
        sleep "$POLL"
        continue ;;
    esac
    printf '%s\n' "$out" | grep '^note:' | sed 's/^/spark-box: /' >&2
    quiet=$((quiet + 1))
    if [ "$waited" = 1 ] && [ "$quiet" -lt 2 ]; then sleep "$POLL"; continue; fi
    # 2. the tree; 3. the run
    sync_tree "$tree" || exit $?
    rc=0
    printf '%s\n' "$RUN_SCRIPT" | ssh "${SSH_OPTS[@]}" "$HOST" "mkdir -p $LOCKS && flock -n -x -E 75 $LOCKS/spark-box.lock bash -s -- $(printf '%q ' "$LEAD" "$BENCH" "$BLEASE" "$LOCKS" "$REMOTE" "$bound" "$reason" "$cmd")" &
    SSH_PID=$!
    trap 'cancel_remote >&2; kill -TERM "$SSH_PID" 2> /dev/null; wait "$SSH_PID" 2> /dev/null; echo "spark-box: interrupted: the run on the Spark was signalled, then the ssh (pid $SSH_PID)" >&2; exit 143' INT TERM
    wait "$SSH_PID" || rc=$?
    trap - INT TERM
    if [ "$rc" = 75 ]; then
      # a hold went up first, or the directory is in use: wait again, inside the same bound
      if [ $((SECONDS - t0)) -ge "$wait_s" ]; then die 75 "the Spark stayed busy (a hold or $REMOTE in use) for $wait_s s: the command did not run"; fi
      echo "spark-box: the Spark turned busy as the run began (rc 75): waiting again" >&2
      waited=1 quiet=0
      sleep "$POLL"
      continue
    fi
    exit "$rc"
  done
}

install_env() {
  local src rc=0
  src=$(dirname "$SELF")/../../configs/spark/bloomery-env.sh
  [ -f "$src" ] || die 66 "$src is not there"
  if ssh "${SSH_OPTS[@]}" "$HOST" 'cat ~/bloomery-env.sh 2> /dev/null' < /dev/null 2> /dev/null | cmp -s - "$src"; then
    echo "spark-box: ~/bloomery-env.sh on $HOST is already $src"
    return 0
  fi
  scp -q "${SSH_OPTS[@]}" "$src" "$HOST:bloomery-env.sh" || rc=$?
  [ "$rc" = 0 ] || die 70 "scp of the environment file to $HOST failed (rc $rc)"
  echo "spark-box: wrote ~/bloomery-env.sh on $HOST from $src"
}

install_cuda() { # <tree>: the 13.3 toolkit of CUDA_IMAGE at CUDA_DIR, once
  local parent=${CUDA_DIR%/*}
  bash "$SELF" --tree "$1" --reason "spark setup: the CUDA 13.3 toolkit from $CUDA_IMAGE" -- \
    "if [ -x $CUDA_DIR/bin/nvcc ] && $CUDA_DIR/bin/nvcc --version | grep -q 'release 13.3'; then echo \"spark-box: CUDA 13.3 is already at $CUDA_DIR\"; else mkdir -p $parent && rm -rf $CUDA_DIR.tmp && docker run --rm --network none -v $parent:/out --entrypoint cp $CUDA_IMAGE -a /usr/local/cuda-13.3 /out/${CUDA_DIR##*/}.tmp && mv $CUDA_DIR.tmp $CUDA_DIR && $CUDA_DIR/bin/nvcc --version | tail -n 2; fi"
}

setup() { # --setup [--tree DIR]
  local tree=$PWD rev
  while [ $# -gt 0 ]; do
    case $1 in --tree) [ $# -ge 2 ] || { usage; exit 64; }; tree=$2; shift 2 ;; *) usage; exit 64 ;; esac
  done
  rev=$(sed -n 's/^cuda-device = .*rev = "\([0-9a-f]*\)".*/\1/p' "$tree/Cargo.toml" | head -n 1)
  [ -n "$rev" ] || die 66 "no cuda-oxide rev in $tree/Cargo.toml"
  install_env || exit $?
  install_cuda "$tree" || exit $?
  # The pin's cargo-oxide in its own root, as box.sh's pin check reads it, then the patched backend beside it.
  bash "$SELF" --tree "$tree" --reason "spark setup: cargo-oxide $rev and the patched backend" -- \
    "root=\$HOME/.cargo/cuda-oxide-bloomery/$rev; { [ -x \$root/bin/cargo-oxide ] && cargo install --list --root \$root | grep -q \"#${rev:0:8}\"; } || cargo install --locked --git https://github.com/NVIDIA/cuda-rust.git --rev $rev --root \$root cargo-oxide; PATH=\$root/bin:\$PATH; { bash tools/oxide-backend.sh --check > /dev/null 2>&1 || bash tools/oxide-backend.sh; } && bash tools/oxide-backend.sh --check"
}

# --self-test: the whole script against a stub ssh, rsync, flock and timeout on PATH. The stub ssh runs the remote command in a
# local bash; the "Spark" is a directory of the test (hold dir, lock dir, remote tree), and the tree under test holds a stub
# tools/box.sh that records what it was called with and what the hold and the lock directory looked like during the run.
self_test() {
  local t n=0 bad=0 rc out
  t=$(mktemp -d "${TMPDIR:-/tmp}/spark-box-test.XXXXXX") || { echo "spark-box: self-test: no temporary directory" >&2; return 70; }
  # shellcheck disable=SC2064 # the path is fixed now
  trap "rm -rf '$t'" EXIT
  t=$(cd "$t" && pwd -P)
  pass() { n=$((n + 1)); echo "ok $1"; }
  fail() { n=$((n + 1)); bad=$((bad + 1)); echo "FAIL $1: $2"; }
  expect() { if [ "$2" = 0 ]; then pass "$1"; else fail "$1" "$3"; fi; }
  mkdir -p "$t/bin" "$t/spark/holds" "$t/spark/locks" "$t/tree/tools"
  cat > "$t/bin/ssh" << 'EOF'
#!/usr/bin/env bash
# stub ssh: drops -o options and the host, runs the rest in a local bash (stdin kept, as the real one does)
while [ "${1:-}" = -o ]; do shift 2; done
shift
[ "${STUB_SSH_DOWN:-0}" = 0 ] || { echo "ssh: connect failed" >&2; exit 255; }
exec bash -c "$*"
EOF
  cat > "$t/bin/rsync" << 'EOF'
#!/usr/bin/env bash
# stub rsync: runs the --rsync-path prefix (with `rsync` swapped for true, so the directory's lock is taken and released), then
# copies the tree with cp -R (no deletions beyond the remote dir's replacement)
rp= src= dst=
skip=0
for a in "$@"; do
  if [ "$skip" = 1 ]; then skip=0; continue; fi
  case $a in
    --rsync-path=*) rp=${a#--rsync-path=} ;;
    --exclude | -e) skip=1 ;;
    -*) ;;
    *) if [ -z "$src" ] && [ -d "$a" ]; then src=$a; else dst=$a; fi ;;
  esac
done
echo "rsync $*" >> "$SPARK_TEST/rsync.calls"
[ -z "$rp" ] || { rp=${rp%rsync}true; bash -c "$rp"; r=$?; [ "$r" = 0 ] || exit "$r"; }
[ "${STUB_RSYNC_FAIL:-0}" = 0 ] || exit 23
dst=${dst#*:}
mkdir -p "$dst" && cp -R "$src"/. "$dst"/
EOF
  cat > "$t/bin/flock" << 'EOF'
#!/usr/bin/env bash
# stub flock: `flock -n -x [-E n] FILE cmd…` with a directory as the lock (taken by mkdir, dropped when the command ends)
e=1
while [ $# -gt 0 ]; do case $1 in -n | -x) shift ;; -E) e=$2; shift 2 ;; *) break ;; esac; done
f=$1; shift
mkdir "$f.d" 2> /dev/null || exit "$e"
trap 'rmdir "$f.d"' EXIT
"$@"
EOF
  cat > "$t/bin/timeout" << 'EOF'
#!/usr/bin/env bash
# stub timeout: --kill-after=N and the duration are dropped; the command runs as itself so a TERM reaches it
while [ "${1:-}" != "${1#--}" ] && [ -n "${1:-}" ]; do shift; done
shift
exec "$@"
EOF
  cat > "$t/tree/tools/box.sh" << 'EOF'
#!/usr/bin/env bash
# stub tools/box.sh in the tree: what local mode would be given, what the hold and the lock dir are during the run, then the command
{
  echo "path1=$(printf %s "$PATH" | cut -d: -f1 | sed "s|^$HOME/||")"
  echo "local=${BLOOMERY_BOX_LOCAL-unset} lockdir=${BLOOMERY_LOCK_DIR-unset} wait=${BLOOMERY_BOX_WAIT-unset} cwd=$(pwd -P | sed "s|^$SPARK_TEST/||") cmd=$*"
  echo "lead hold during the run: $(cat "$SPARK_TEST/spark/holds/spark-lead.hold" 2> /dev/null || echo none)"
} >> "$SPARK_TEST/box.calls"
case "$*" in
  *exit3*) exit 3 ;;
  *sleep*) echo $$ > "$SPARK_TEST/box.pid"; sleep 30 & sp=$!; trap 'kill $sp 2> /dev/null; exit 143' TERM; wait $sp ;;
esac
exit 0
EOF
  chmod +x "$t/bin/"* "$t/tree/tools/box.sh"
  echo "tree" > "$t/tree/file"
  echo 'cuda-device = { git = "https://example.invalid/cuda-rust.git", rev = "abc123def456" }' > "$t/tree/Cargo.toml"
  local H=$t/spark/holds R=$t/spark/remote
  # sb <env words…> -- <args…>: one call of the script under test (SB, the real one unless a mutant is named), the stub Spark; rc in $rc, output in $out
  sb() {
    local envs=()
    while [ "$1" != -- ]; do envs+=("$1"); shift; done
    shift
    rc=0
    out=$(env PATH="$t/bin:$PATH" SPARK_TEST="$t" BLOOMERY_SPARK=stub BLOOMERY_SPARK_REMOTE="$R" BLOOMERY_SPARK_LOCKS="$t/spark/locks" \
      BLOOMERY_SPARK_HOLDS="$H" BLOOMERY_SPARK_POLL=1 ${envs[@]+"${envs[@]}"} bash "${SB:-$SELF}" "$@" 2>&1 < /dev/null) || rc=$?
  }
  clean() { rm -rf "${H:?}"/* "$R" "$t/spark/locks"/* "$t/box.calls" "$t/rsync.calls" "$t/box.pid"; }
  local now
  now=$(date +%s)
  # 1. idle: the tree is synced, the command runs in it under local mode with the lock dir, the hold is up during the run and gone after
  clean
  sb -- --tree "$t/tree" -- 'bash tools/release/build.sh --stage w 0.0.1 abc123456789'
  expect 'idle: the command runs on the synced tree and ends 0' "$([ "$rc" = 0 ] && [ -f "$R/file" ] && grep -q "^local=1 lockdir=$t/spark/locks wait=0 cwd=spark/remote cmd=bash tools/release/build.sh --stage w 0.0.1 abc123456789\$" "$t/box.calls"; echo $?)" "rc=$rc $out | $(cat "$t/box.calls" 2>&1)"
  expect '  … with the lead hold up during the run (owner=lead, since, until, pid, reason) and gone after' "$(grep -Eq '^lead hold during the run: owner=lead since=[0-9]+ until=[0-9]+ pid=[0-9]+ reason=spark-box bash tools/release/build.sh' "$t/box.calls" && [ ! -e "$H/spark-lead.hold" ]; echo $?)" "$(cat "$t/box.calls"); hold: $(ls "$H")"
  expect '  … and the sync went through the directory lock with box.sh'"'"'s flags' "$(grep -q -- '--rsync-path=mkdir -p .*flock -n -x -E 75 .*/spark-box.lock rsync' "$t/rsync.calls" && grep -q -- '--delete --exclude target/ --exclude .git/' "$t/rsync.calls"; echo $?)" "$(cat "$t/rsync.calls" 2>&1)"
  expect '  … cargo-oxide of the tree'"'"'s pin rev is first on PATH (local mode finds it there)' "$(grep -q '^path1=.cargo/cuda-oxide-bloomery/abc123def456/bin$' "$t/box.calls"; echo $?)" "$(cat "$t/box.calls")"
  # 2. the command's rc passes through and the hold is still taken down
  clean
  sb -- --tree "$t/tree" -- 'exit3'
  expect 'rc: the command'"'"'s exit code is the call'"'"'s, and the hold is down' "$([ "$rc" = 3 ] && [ ! -e "$H/spark-lead.hold" ]; echo $?)" "rc=$rc hold: $(ls "$H")"
  # 3. a bench hold: no wait → 75 naming it; nothing synced, nothing run
  clean
  echo "owner=bench since=$now until=$((now + 3600)) reason=q8gemv bench" > "$H/spark-bench.hold"
  sb -- --tree "$t/tree" --wait 0 -- 'echo hi'
  expect 'bench hold up: --wait 0 ends 75 naming the hold; nothing synced, nothing run' "$([ "$rc" = 75 ] && grep -q 'busy: the bench hold .*spark-bench.hold: owner=bench' <<< "$out" && [ ! -e "$t/rsync.calls" ] && [ ! -e "$t/box.calls" ]; echo $?)" "rc=$rc $out"
  # 4. an expired bench hold is stale: ignored, said
  clean
  echo "owner=bench since=$((now - 7200)) until=$((now - 60)) reason=old" > "$H/spark-bench.hold"
  sb -- --tree "$t/tree" --wait 0 -- 'echo hi'
  expect 'bench hold past its until: ignored with a note, the command runs' "$([ "$rc" = 0 ] && grep -q 'note: .*past its until' <<< "$out" && [ -e "$t/box.calls" ]; echo $?)" "rc=$rc $out"
  # 5. the bot's own lease: a live pid is busy, a dead pid is not
  clean
  echo "$$ q8gemv-bench 2026-11-04" > "$H/spark-lease"
  sb -- --tree "$t/tree" --wait 0 -- 'echo hi'
  expect 'bench lease naming a live pid: 75' "$([ "$rc" = 75 ] && grep -q 'busy: the bench lease .*live pid' <<< "$out" && [ ! -e "$t/box.calls" ]; echo $?)" "rc=$rc $out"
  echo "999999 gone 2026-11-04" > "$H/spark-lease"
  sb -- --tree "$t/tree" --wait 0 -- 'echo hi'
  expect '  … a dead pid is not' "$([ "$rc" = 0 ] && [ -e "$t/box.calls" ]; echo $?)" "rc=$rc $out"
  # 6. the hold goes down during the wait: the run starts after two quiet polls
  clean
  echo "owner=bench since=$now reason=no end time" > "$H/spark-bench.hold"
  ( sleep 2; rm -f "$H/spark-bench.hold" ) &
  dpid=$!
  sb -- --tree "$t/tree" --wait 30 -- 'echo hi'
  wait "$dpid" 2> /dev/null
  expect 'wait: a hold with no end time stands until it is removed; the run then starts, and says what it waited for' "$([ "$rc" = 0 ] && grep -q 'waiting: busy: the bench hold' <<< "$out" && [ -e "$t/box.calls" ]; echo $?)" "rc=$rc $out"
  # 7. the bound: still up after --wait → 75 naming the bound
  clean
  echo "owner=bench since=$now reason=x" > "$H/spark-bench.hold"
  sb -- --tree "$t/tree" --wait 2 -- 'echo hi'
  expect 'bound: a hold that stays up ends 75 after --wait, naming it' "$([ "$rc" = 75 ] && grep -q 'still up after 2 s' <<< "$out"; echo $?)" "rc=$rc $out"
  # 8. a run holds the directory: the second call's sync is refused (75), its tree is not replaced, the first one is undisturbed
  clean
  env PATH="$t/bin:$PATH" SPARK_TEST="$t" BLOOMERY_SPARK=stub BLOOMERY_SPARK_REMOTE="$R" BLOOMERY_SPARK_LOCKS="$t/spark/locks" BLOOMERY_SPARK_HOLDS="$H" BLOOMERY_SPARK_POLL=1 \
    bash "${SB:-$SELF}" --tree "$t/tree" --wait 0 -- 'sleep30' > "$t/first.out" 2>&1 < /dev/null &
  bpid=$!
  n_try=0; while [ ! -e "$t/box.pid" ] && [ "$n_try" -lt 100 ]; do sleep 0.1; n_try=$((n_try + 1)); done
  rc2=0
  out2=$(env PATH="$t/bin:$PATH" SPARK_TEST="$t" BLOOMERY_SPARK=stub BLOOMERY_SPARK_REMOTE="$R" BLOOMERY_SPARK_LOCKS="$t/spark/locks" BLOOMERY_SPARK_HOLDS="$H" BLOOMERY_SPARK_POLL=1 \
    bash "${SB:-$SELF}" --tree "$t/tree" --wait 0 -- 'echo second' 2>&1 < /dev/null) || rc2=$?
  expect 'directory in use: the second run ends 75 naming the lock, and the first run is untouched' "$([ "$rc2" = 75 ] && grep -q 'a run holds' <<< "$out2" && kill -0 "$(cat "$t/box.pid")" 2> /dev/null; echo $?)" "rc=$rc2 $out2"
  # 9. a TERM to the call stops the run on the Spark by the pid its hold names, and the hold comes down
  bp=$(cat "$t/box.pid" 2> /dev/null || echo 0)
  kill -TERM "$bpid" 2> /dev/null
  rc3=0
  wait "$bpid" 2> /dev/null || rc3=$?
  n_try=0; while [ -e "$H/spark-lead.hold" ] && [ "$n_try" -lt 50 ]; do sleep 0.1; n_try=$((n_try + 1)); done
  expect 'TERM: the call ends 143, the run is stopped (its command too) and the lead hold is down' "$([ "$rc3" = 143 ] && [ ! -e "$H/spark-lead.hold" ] && ! kill -0 "$bp" 2> /dev/null && grep -q 'TERM sent to the run' "$t/first.out"; echo $?)" "rc=$rc3 hold: $(ls "$H") pid $bp alive: $(kill -0 "$bp" 2> /dev/null && echo yes) out: $(cat "$t/first.out")"
  kill -0 "$bp" 2> /dev/null && kill -KILL "$bp" 2> /dev/null # a stray of a failed case: the pid this test captured
  # 10. a stale lead hold (dead run) is replaced; a live one is busy
  clean
  echo "owner=lead since=$((now - 9000)) until=$((now - 100)) pid=1 reason=dead" > "$H/spark-lead.hold"
  sb -- --tree "$t/tree" --wait 0 -- 'echo hi'
  expect 'a lead hold past its until is replaced, said' "$([ "$rc" = 0 ] && grep -q 'spark-lead.hold is past its until' <<< "$out" || grep -q 'stale, replaced' <<< "$out"; echo $?)" "rc=$rc $out"
  clean
  echo "owner=lead since=$now until=$((now + 900)) pid=1 reason=other run" > "$H/spark-lead.hold"
  sb -- --tree "$t/tree" --wait 0 -- 'echo hi'
  expect '  … a live one is busy (75), not touched' "$([ "$rc" = 75 ] && grep -q 'busy: the lead hold' <<< "$out" && [ -e "$H/spark-lead.hold" ] && [ ! -e "$t/box.calls" ]; echo $?)" "rc=$rc $out"
  # 11. the Spark cannot be asked: 70, nothing run
  clean
  sb STUB_SSH_DOWN=1 -- --tree "$t/tree" --wait 0 -- 'echo hi'
  expect 'unreachable: 70 naming the host' "$([ "$rc" = 70 ] && grep -q 'could not be asked' <<< "$out"; echo $?)" "rc=$rc $out"
  # 12. a failed sync: its rc, no run
  clean
  sb STUB_RSYNC_FAIL=1 -- --tree "$t/tree" --wait 0 -- 'echo hi'
  expect 'sync fails: rsync'"'"'s rc is named, the command did not run, no hold left' "$([ "$rc" = 23 ] && grep -q 'rsync to .* failed (rc 23)' <<< "$out" && [ ! -e "$t/box.calls" ] && [ ! -e "$H/spark-lead.hold" ]; echo $?)" "rc=$rc $out"
  # 13. usage
  sb -- --bound x -- 'echo hi'
  expect 'usage: a bound that is not whole seconds is 64' "$([ "$rc" = 64 ]; echo $?)" "rc=$rc $out"
  # 14. --probe
  clean
  sb -- --probe
  expect '--probe: idle is rc 0' "$([ "$rc" = 0 ] && grep -qx idle <<< "$out"; echo $?)" "rc=$rc $out"
  echo "owner=bench since=$now reason=x" > "$H/spark-bench.hold"
  sb -- --probe
  expect '  … a bench hold is rc 75 naming it' "$([ "$rc" = 75 ] && grep -q '^busy: the bench hold' <<< "$out"; echo $?)" "rc=$rc $out"
  # Mutants: each is a copy of this script with one line changed; the case's condition holds when the defect shows.
  mutant() { # <name> <case: hold|bench|expired|lease|lock|cleanup|path|sync> <old text> <new text>
    local m=$t/mut-${1// /_}.sh
    python3 -I - "$SELF" "$m" "$3" "$4" << 'PY' || { fail "mutant $1" "the mutation did not apply"; return; }
import sys
src, dst, old, new = sys.argv[1:5]
text = open(src, encoding="utf-8").read()
if text.count(old) < 1:
    sys.exit(1)
open(dst, "w", encoding="utf-8").write(text.replace(old, new, 1))
PY
    clean
    case $2 in
      hold) SB=$m sb -- --tree "$t/tree" --wait 0 -- 'echo hi'
            expect "mutant: $1 is caught" "$(grep -Eq '^lead hold during the run: none' "$t/box.calls"; echo $?)" "the hold was up during the run" ;;
      bench) echo "owner=bench since=$now until=$((now + 3600)) reason=x" > "$H/spark-bench.hold"
             SB=$m sb -- --tree "$t/tree" --wait 0 -- 'echo hi'
             expect "mutant: $1 is caught" "$([ -e "$t/rsync.calls" ]; echo $?)" "nothing was synced behind the bench" ;;
      expired) echo "owner=bench since=$((now - 7200)) until=$((now - 60)) reason=old" > "$H/spark-bench.hold"
               SB=$m sb -- --tree "$t/tree" --wait 0 -- 'echo hi'
               expect "mutant: $1 is caught" "$([ "$rc" = 75 ]; echo $?)" "rc=$rc: the stale hold did not stop the command" ;;
      lease) echo "$$ x" > "$H/spark-lease"
             SB=$m sb -- --tree "$t/tree" --wait 0 -- 'echo hi'
             expect "mutant: $1 is caught" "$([ "$rc" != 75 ]; echo $?)" "rc=$rc: the live lease stopped the command" ;;
      lock) SB=$m sb -- --tree "$t/tree" --wait 0 -- 'echo hi'
            expect "mutant: $1 is caught" "$(! grep -q "lockdir=$t/spark/locks" "$t/box.calls"; echo $?)" "box.sh was given the lock directory" ;;
      cleanup) SB=$m sb -- --tree "$t/tree" --wait 0 -- 'echo hi'
               expect "mutant: $1 is caught" "$([ -e "$H/spark-lead.hold" ]; echo $?)" "the hold is down" ;;
      path) SB=$m sb -- --tree "$t/tree" --wait 0 -- 'echo hi'
            expect "mutant: $1 is caught" "$(! grep -q '^path1=.cargo/cuda-oxide-bloomery/abc123def456/bin$' "$t/box.calls"; echo $?)" "cargo-oxide is first on PATH" ;;
      sync) SB=$m sb -- --tree "$t/tree" --wait 0 -- 'echo hi'
            expect "mutant: $1 is caught" "$(! grep -q -- 'flock -n -x -E 75' "$t/rsync.calls"; echo $?)" "the sync goes through the lock" ;;
    esac
  }
  mutant "the hold is never put up" hold 'printf "%s\n" "$mine" > "$LEAD" 2> /dev/null; then' 'true; then'
  mutant "the bench is not looked at" bench '1) return 1 ;;' '1) return 0 ;;'
  mutant "a past until is still busy" expired 'if [ -n "$u" ] && [ "$u" -le "$now" ]; then' 'if false; then'
  mutant "the bench lease is not read" lease 'if kill -0 "$pid" 2> /dev/null; then' 'if false; then'
  mutant "box.sh gets no lock directory" lock 'BLOOMERY_LOCK_DIR="$LOCKS" ' ''
  mutant "the hold is left behind" cleanup 'trap "rm -f \"$LEAD\"" EXIT' 'true'
  mutant "cargo-oxide is not put on PATH" path '[ -z "$rev" ] || export PATH="$HOME/.cargo/cuda-oxide-bloomery/$rev/bin:$PATH"' ':'
  mutant "the sync takes no lock" sync 'rp="mkdir -p $LOCKS && flock -n -x -E 75 $LOCKS/spark-box.lock rsync"' 'rp="mkdir -p $LOCKS && rsync"'
  echo "spark-box self-test: $n cases, $bad failed"
  [ "$bad" = 0 ]
}

case ${1:-} in
  --self-test) self_test; exit $? ;;
  --probe)
    shift
    [ $# = 0 ] || { usage; exit 64; }
    probe_remote
    rc=$?
    [ "$rc" != 1 ] || rc=75
    exit "$rc" ;;
  --install-env) install_env; exit $? ;;
  --setup) shift; setup "$@"; exit $? ;;
  -h | --help) sed -n '2,/^set -uo/p' "$SELF" | sed '$d'; exit 0 ;;
  "") usage; exit 64 ;;
  *) run_main "$@" ;;
esac
