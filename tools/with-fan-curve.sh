#!/bin/bash
# with-fan-curve.sh [--gpu UUID] [--curve SPEC] [--floor N] -- <command…>
#
# Run one measurement with [`gpu-fan-curve.py`](gpu-fan-curve.py) owning the fan, and
# hand the fan back before the next one starts. It exists for the same reason
# [`gpu-clock-lock.sh`](gpu-clock-lock.sh) does: a fan speed is machine state that
# outlives the process that set it, so a take that leaves it set has silently changed
# every thermal number taken afterwards — including other sessions' takes on a shared box.
#
# What this adds over running the daemon by hand: the daemon restores the fan on SIGTERM,
# and this guarantees it *receives* one. The pid comes from `$!` at launch and is the only
# thing ever signalled — never a pattern match, because a pattern on this machine has
# matched the signalling shell's own command line and stopped the session (2026-09-13).
#
#   with-fan-curve.sh --gpu <a6000-uuid> -- bash ltx-take.sh fan-on-probe
#
# The witness is the take's own dmon.csv: fan.speed is already a column there, so the
# curve's effect is visible in the take rather than needing a second instrument. What this
# script prints is the ramp the daemon commanded, so a row can say what was asked for
# alongside what the card did.
set -u
GPU=""; CURVE=""; FLOOR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --gpu)   GPU=$2; shift 2 ;;
    --curve) CURVE=$2; shift 2 ;;
    --floor) FLOOR=$2; shift 2 ;;
    --)      shift; break ;;
    *)       echo "with-fan-curve.sh: unknown argument $1" >&2; exit 64 ;;
  esac
done
[ $# -gt 0 ] || { echo "usage: with-fan-curve.sh [--gpu UUID] [--curve SPEC] [--floor N] -- <command…>" >&2; exit 64; }

D=${FAN_CURVE:-/home/user/gpu-fan-curve.py}
[ -f "$D" ] || { echo "with-fan-curve.sh: no daemon at $D" >&2; exit 64; }
LOG=${FAN_LOG:-/home/user/ik-vram/fan-curve-$(date +%H%M%S).log}
mkdir -p "$(dirname "$LOG")"
say(){ echo "$(date +%T) fan: $*"; }

ARGS=()
[ -z "$GPU" ]   || ARGS+=(--gpu "$GPU")
[ -z "$CURVE" ] || ARGS+=(--curve "$CURVE")
[ -z "$FLOOR" ] || ARGS+=(--floor "$FLOOR")

DPID=""
stop(){
  if [ -n "$DPID" ] && kill -0 "$DPID" 2>/dev/null; then
    kill -TERM "$DPID"
    for i in $(seq 20); do kill -0 "$DPID" 2>/dev/null || break; sleep 1; done
    if kill -0 "$DPID" 2>/dev/null; then
      # the daemon's own restore never ran, so do it here rather than leaving a manual fan
      say "daemon $DPID alive after SIGTERM — forcing every fan back to its card's curve"
      kill -KILL "$DPID" 2>/dev/null
      /usr/local/bin/uv run --with nvidia-ml-py python "${D%/*}/gpu-fan.py" --all-auto \
        >/dev/null 2>&1 && say "fans restored by gpu-fan.py --all-auto" \
        || say "FANS NOT RESTORED — check gpu-fan.py before the next take"
    else
      say "daemon stopped; $(grep -c . "$LOG" 2>/dev/null || echo 0) lines in $LOG"
    fi
    DPID=""
  fi
}
trap 'stop; exit 130' INT TERM

/usr/local/bin/uv run --with nvidia-ml-py python "$D" "${ARGS[@]}" > "$LOG" 2>&1 &
DPID=$!
sleep 3
kill -0 "$DPID" 2>/dev/null || { say "daemon died on start:"; cat "$LOG"; exit 1; }
say "curve owned by pid $DPID, log $LOG"

"$@"; rc=$?

stop
say "commanded ramp:"
awk '/ C  /{print "  " $0}' "$LOG" | head -40
exit $rc
