#!/bin/bash
# comfy-session.sh start <tag> [minutes] | run <tag> [minutes] | stop <tag> | status <tag>
#
# An interactive ComfyUI window under the same contract as every take: the lease is taken
# only after the gates pass, the server is a SIMPLE command so $! is ComfyUI itself, stop is
# SIGTERM to that one pid, and the lease is released only after the card's VRAM comes back.
# A session is not a measurement (no dmon; start/stop witnesses like serve-coder-next.sh),
# but it is a thermal event on a shared box, so the gates are the take gates.
#
#   bash comfy-session.sh start evening1        # A6000 (default; LTX and Z-Image exceed 24 GB)
#   bash comfy-session.sh run evening1 90       # start, then hold the window in the foreground;
#                                              # SIGTERM runs the lawful stop. This is what the
#                                              # dispatcher runs, so a session is an ordinary job.
#   CARD=3090 bash comfy-session.sh start yue2  # 7 GB YuE2 fits the gate card
#   TS_SERVE=1 ... start                       # also expose the web UI at <box>:8445 over serve
#
# Sentinels COMFY_DONE / COMFY_FAILED at stop.
set -u
cmd=${1:?usage: comfy-session.sh start|run|stop|status <tag> [minutes]}; shift
TAG=${1:?tag}; shift
C=/home/user/ComfyUI
RUN=/home/user/comfy-runs/$TAG
PIDF=$RUN/run.pid; LOG=$RUN/run.log
LEASE=/home/user/gpu-lease
PORT=${PORT:-8188}
CARD=${CARD:-a6000}
TS_SERVE_PORT=8445
say(){ echo "$(date +%T) $*"; }
mkdir -p "$RUN"

# A private copy to re-enter for stop: an scp over this script mid-session must not change
# what "stop" does (the chain-s lesson, 2026-09-16).
SNAP=$(cp "$0" "/tmp/comfy-session.$$.sh" && echo "/tmp/comfy-session.$$.sh")
trap 'rm -f "$SNAP"' EXIT

witness(){ # witness <when>
  { echo "=== witness $1 $(date -Is) ==="
    nvidia-smi --query-gpu=index,name,uuid,memory.used,memory.total,utilization.gpu,power.draw \
               --format=csv,noheader
    echo "loadavg: $(cat /proc/loadavg)"
    echo "io: $(awk '/some/{print $0}' /proc/pressure/io)"
    echo "compute-apps: $(nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader | tr '\n' ';')"
  } >> "$RUN/witness.txt"; }

uuid_for(){ . /home/user/gpu-order.env
  case "$1" in
    a6000) echo "$A6000_UUID" ;;
    3090)  echo "$GF3090_UUID" ;;
    *)     echo "" ;;
  esac; }
cardidle(){ [ "$(nvidia-smi -i "$(uuid_for "$CARD")" --query-gpu=memory.used --format=csv,noheader,nounits)" -lt 2000 ]; }
leasepid(){ awk '{for(i=2;i<=3;i++) if($i+0>0){print $i; exit}}' "$LEASE" 2>/dev/null; }
leaselive(){ local p; p=$(leasepid); [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }

status(){
  if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
    say "running pid $(cat "$PIDF") port $PORT card $CARD lease: $(cat "$LEASE" 2>/dev/null || echo none)"
    curl -sf -o /dev/null http://127.0.0.1:$PORT/ && say "http: answering" || say "http: not answering yet"
  else
    say "not running (pid file $( [ -f "$PIDF" ] && echo present || echo absent))"
  fi
  exit 0; }

stop(){
  [ -f "$PIDF" ] || { say "no pid file $PIDF"; exit 1; }
  SPID=$(cat "$PIDF")
  if kill -0 "$SPID" 2>/dev/null; then
    say "SIGTERM -> $SPID"; kill -TERM "$SPID"
    for _ in $(seq 120); do kill -0 "$SPID" 2>/dev/null || break; sleep 1; done
    kill -0 "$SPID" 2>/dev/null && { say "pid $SPID alive after 120 s; NOT escalating"; echo COMFY_FAILED; exit 1; }
  else
    say "pid $SPID already gone"
  fi
  members(){ ps -eo pid=,sid= | awk -v s=$SPID '$2==s && $1!=s{printf "%s ", $1}'; }
  for _ in $(seq 15); do [ -z "$(members)" ] && break; sleep 1; done
  [ -n "$(members)" ] && say "session members still alive: $(members) (reporting, not escalating)"
  [ "${TS_SERVE:-0}" = 1 ] && tailscale serve --https=$TS_SERVE_PORT off 2>/dev/null
  witness stop
  for _ in $(seq 45); do cardidle && break; sleep 2; done
  if cardidle; then
    [ -f $LEASE ] && grep -q "^comfy-$TAG " $LEASE && rm -f $LEASE && say "lease released"
    rm -f "$PIDF"; say "card $CARD back"; echo COMFY_DONE; exit 0
  else
    say "GPUS NOT RELEASED: lease kept ($(cat $LEASE 2>/dev/null))"; echo COMFY_FAILED; exit 1
  fi; }

case "$cmd" in status) status;; stop) stop;; run)
  # run = start, then hold until the ComfyUI pid dies, SIGTERM, or the window elapses.
  # Signals come to this process only: the trap turns them into the lawful stop.
  MODE_RUN=1 ;; start) ;; *) say "unknown command $cmd"; exit 2 ;; esac
MINUTES=${1:-0}

# gates, take order: exists, curfew, card idle, lease, bloomery locks
[ -x $C/.venv/bin/python ] || { say "refused: no ComfyUI venv (comfy-setup.sh)"; echo COMFY_FAILED; exit 1; }
[ "$(date +%H%M)" -lt 2330 ] || { say "refused: after 23:30 KST"; echo COMFY_FAILED; exit 1; }
cardidle || { say "refused: card $CARD busy"; echo COMFY_FAILED; exit 1; }
if [ -f $LEASE ]; then
  leaselive && { say "refused: lease held: $(cat $LEASE)"; echo COMFY_FAILED; exit 1; }
  say "clearing stale lease (pid dead): $(cat $LEASE)"; rm -f $LEASE
fi
for L in /root/bloomery-cpu.lock /root/bloomery-gate.lock /root/bloomery-gate-a6000.lock; do
  if [ -e "$L" ] && ! flock -s -n "$L" true 2>/dev/null; then
    say "refused: bloomery lock held: $L"; echo COMFY_FAILED; exit 1; fi
done
[ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null && { say "refused: $TAG already running"; exit 1; }

echo "comfy-$TAG $$ $(date +%FT%T)" > $LEASE
witness start
say "$TAG: card=$CARD port=$PORT minutes=${MINUTES:-unbounded}"

CUDA_VISIBLE_DEVICES="$(uuid_for "$CARD")" setsid nohup \
  $C/.venv/bin/python $C/main.py --listen 127.0.0.1 --port $PORT \
  > "$LOG" 2>&1 < /dev/null &
SPID=$!; echo "$SPID" > "$PIDF"
kill -0 $SPID 2>/dev/null || { say "run exited immediately"; tail -20 "$LOG"; rm -f $LEASE; echo COMFY_FAILED; exit 1; }
[ "$(ps -o sid= -p $SPID | tr -d ' ')" = "$SPID" ] || { say "launch assertion failed (pid $SPID is not a session leader)"; kill -TERM $SPID; rm -f $LEASE; echo COMFY_FAILED; exit 1; }
say "run pid $SPID"

# health wait: ComfyUI answers / when the UI is up (torch import dominates the first boot)
for _ in $(seq 900); do
  curl -sf -o /dev/null http://127.0.0.1:$PORT/ && break
  kill -0 $SPID 2>/dev/null || { say "ComfyUI died during startup"; tail -20 "$LOG"; bash "$SNAP" stop "$TAG"; echo COMFY_FAILED; exit 1; }
  sleep 1
done
curl -sf -o /dev/null http://127.0.0.1:$PORT/ || { say "no answer on $PORT after 900 s"; bash "$SNAP" stop "$TAG"; echo COMFY_FAILED; exit 1; }
say "http answering on $PORT"

if [ "${TS_SERVE:-0}" = 1 ]; then
  tailscale serve --bg --https=$TS_SERVE_PORT http://127.0.0.1:$PORT && say "web UI: https://<box>:$TS_SERVE_PORT (serve)"
fi

if [ "${MODE_RUN:-0}" = 1 ]; then
  # hold the window in the foreground; a signal (or the bound) closes it lawfully
  trap 'bash "$SNAP" stop "$TAG"; exit' TERM INT
  if [ "${MINUTES:-0}" -gt 0 ]; then
    END=$(( $(date +%s) + MINUTES * 60 ))
    while kill -0 "$SPID" 2>/dev/null && [ "$(date +%s)" -lt "$END" ]; do sleep 5; done
  else
    while kill -0 "$SPID" 2>/dev/null; do sleep 5; done
  fi
  bash "$SNAP" stop "$TAG"
  exit $?
fi
# a bounded window closes itself via the private copy; unbounded waits for an explicit stop
if [ "${MINUTES:-0}" -gt 0 ]; then
  ( sleep "$((MINUTES * 60))" && bash "$SNAP" stop "$TAG" ) >/dev/null 2>&1 &
fi
say "session $TAG up"
