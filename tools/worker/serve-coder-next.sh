#!/bin/bash
# serve-coder-next.sh start <tag> <llama-server bin> <port> -- <server args...>  |  stop <tag>
#
# One llama-server on the A6000 alone, started and stopped by the pid this script recorded.
# Written for round WORKER (2026-09-21): three engine builds had to be compared on the same
# model file, and the spec forbids pgrep/pkill/cmdline scans — a /proc scan once froze the
# session's own ssh (docs/quiet-machine.md).
#
# What it enforces, each rule from an incident recorded in docs/quiet-machine.md:
#  - the background job is a SIMPLE command, so `$!` is the server and not a subshell; the
#    launch asserts both `ps -o sid=` == $! and /proc/$!/comm == llama-server before going on
#  - the A6000 is named by UUID (CUDA_VISIBLE_DEVICES), never by index; the 3090 is never
#    made visible, another round owns it
#  - stop is SIGTERM to that one pid, waited on with `kill -0`, and never escalated blind;
#    the session's remaining members are checked afterwards the way tabby-check.sh does it
#  - witnesses (both cards, loadavg, io pressure, llm.service) are printed by the script at
#    start and at stop, so a row carries its own evidence rather than a reconstructed timeline
#
# The server log is <scratch>/<tag>.log, the pid file <scratch>/<tag>.pid, witnesses
# <scratch>/<tag>.witness-{start,stop}.txt. SCRATCH defaults to /root/worker-scratch.
set -u
SCRATCH=${SCRATCH:-/root/worker-scratch}
A6000_UUID=${A6000_UUID:-GPU-8c129fa6-7382-35a5-2464-9ff01d99fcd4}
mkdir -p "$SCRATCH"
say(){ echo "$(date +%H:%M:%S) $*"; }

witness(){ # witness <file> <when>
  { echo "=== witness $2 $(date -Is) ==="
    nvidia-smi --query-gpu=index,name,uuid,memory.used,memory.total,utilization.gpu,power.draw \
               --format=csv,noheader
    echo "loadavg: $(cat /proc/loadavg)"
    echo "io: $(awk '/some/{print $0}' /proc/pressure/io)"
    echo "llm.service: $(systemctl is-active llm.service)"
    echo "compute-apps: $(nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader | tr '\n' ';')"
  } | tee -a "$1"; }

cmd=${1:?usage: serve-coder-next.sh start|stop <tag> ...}; shift
TAG=${1:?tag}; shift
PIDF=$SCRATCH/$TAG.pid; LOG=$SCRATCH/$TAG.log

if [ "$cmd" = stop ]; then
  [ -f "$PIDF" ] || { say "no pid file $PIDF"; exit 1; }
  SPID=$(cat "$PIDF")
  if kill -0 "$SPID" 2>/dev/null; then
    say "SIGTERM -> $SPID ($(ps -o comm= -p "$SPID" 2>/dev/null))"
    kill -TERM "$SPID"
    for _ in $(seq 120); do kill -0 "$SPID" 2>/dev/null || break; sleep 1; done
    kill -0 "$SPID" 2>/dev/null && { say "pid $SPID alive after 120 s; NOT escalating"; exit 1; }
  else
    say "pid $SPID already gone"
  fi
  members(){ ps -eo pid=,sid= | awk -v s="$SPID" '$2==s && $1!=s{printf "%s ", $1}'; }
  for _ in $(seq 15); do [ -z "$(members)" ] && break; sleep 1; done
  [ -n "$(members)" ] && say "session $SPID members still alive: $(members) (reporting, not escalating)"
  for _ in $(seq 45); do
    [ "$(nvidia-smi -i "$A6000_UUID" --query-gpu=memory.used --format=csv,noheader,nounits)" -lt 2000 ] && break
    sleep 2; done
  witness "$SCRATCH/$TAG.witness-stop.txt" stop
  rm -f "$PIDF"
  exit 0
fi

[ "$cmd" = start ] || { say "unknown command $cmd"; exit 2; }
BIN=${1:?bin}; shift
PORT=${1:?port}; shift
[ "${1:-}" = "--" ] && shift

if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
  say "refused: $TAG already running as $(cat "$PIDF")"; exit 1; fi

: > "$SCRATCH/$TAG.witness-start.txt"
witness "$SCRATCH/$TAG.witness-start.txt" start
say "bin $BIN port $PORT"
printf 'argv:'; printf ' %q' "$BIN" --host 127.0.0.1 --port "$PORT" "$@"; echo

# Simple command in the background: $! is the server itself. Do not wrap in `cd x && …`.
CUDA_VISIBLE_DEVICES=$A6000_UUID setsid nohup "$BIN" --host 127.0.0.1 --port "$PORT" "$@" \
  > "$LOG" 2>&1 < /dev/null &
SPID=$!
echo "$SPID" > "$PIDF"
sleep 1
sid=$(ps -o sid= -p "$SPID" 2>/dev/null | tr -d ' ')
comm=$(cat /proc/"$SPID"/comm 2>/dev/null)
if [ "$sid" != "$SPID" ] || [ "$comm" != "llama-server" ]; then
  say "LAUNCH ASSERTION FAILED: pid $SPID sid=$sid comm=$comm (expected sid=$SPID comm=llama-server)"
  tail -20 "$LOG"; exit 1; fi
say "server pid $SPID (session leader, comm=$comm)"

t0=$(date +%s)
until curl -sf "http://127.0.0.1:$PORT/health" -o /dev/null 2>/dev/null; do
  kill -0 "$SPID" 2>/dev/null || { say "server died after $(( $(date +%s) - t0 ))s"; tail -40 "$LOG"; exit 1; }
  [ $(( $(date +%s) - t0 )) -gt 900 ] && { say "health timeout 900s"; exit 1; }
  sleep 2
done
say "healthy after $(( $(date +%s) - t0 ))s"
nvidia-smi -i "$A6000_UUID" --query-gpu=memory.used,memory.total --format=csv,noheader \
  | sed "s/^/vram-after-load: /" | tee -a "$SCRATCH/$TAG.witness-start.txt"
grep -iE "^(load_tensors|llama_context|init:|.*arch .*=|.*n_ctx)" "$LOG" | tail -25
exit 0
