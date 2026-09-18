#!/bin/bash
# gpu-fan-stop-check.sh — does stopping the fan unit hand the fans back, how fast, and what does
# the fan do WHILE it is stopping?
#
# FAIL-first, measured 2026-09-18 06:01 on the version this replaces: `systemctl stop` took 90 s
# (the default TimeoutStopSec) and ended `failed`, because ExecStart ran the daemon under
# `uv run` so systemd's main pid was uv, not the daemon. Through those 90 s the fan stayed in
# policy=manual at its last commanded 32 % while a 296 W job drove the die 60 -> 79 C. The card's
# own curve is locked out while manual is held, so a stalled controller is worse than none.
#
# Elapsed time alone would not have caught that, and would not catch its miniature either: a stop
# that returns in 200 ms and leaves a manual fan behind is the same hazard (the point is a peer
# session's, 2026-09-18). So this samples fan percent and policy through the whole window at 2 Hz
# and prints the trace, and it runs under a real load by default because an idle card's fan says
# nothing about a hazard that only bites while heat is rising.
#
#   bash tools/gpu-fan-stop-check.sh                 # burn the A6000, stop mid-burn, measure
#   LOAD=none bash tools/gpu-fan-stop-check.sh       # no load (weaker: the trace is not meaningful)
#   KEEP_STOPPED=1 ...                               # leave it stopped, for a matched-pair arm
set -u
UNIT=${UNIT:-gpu-fan}
STOP_MAX=${STOP_MAX:-10}
LOAD=${LOAD:-a6000}
BURN_S=${BURN_S:-120}
VP=/home/user/.venv-gpufan/bin/python
. /home/user/gpu-order.env
OUT=${OUT:-/home/user/gpu-check/fan-stop-check}; mkdir -p $OUT
fail=0
say(){ echo "$(date +%T) $*"; }

# fan percent AND policy, both cards, 2 Hz. Policy is the whole point: a fan reading of 32 % is
# benign under policy=auto and is the hazard under policy=manual.
cat > $OUT/sample.py <<'PY'
import pynvml as N, time, sys
N.nvmlInit()
end = time.time() + float(sys.argv[1])
while time.time() < end:
    row = [time.strftime("%H:%M:%S")]
    for i in range(N.nvmlDeviceGetCount()):
        h = N.nvmlDeviceGetHandleByIndex(i)
        name = N.nvmlDeviceGetName(h).split()[-1]
        try: pol = {0: "auto", 1: "manual"}.get(N.nvmlDeviceGetFanControlPolicy_v2(h, 0), "?")
        except N.NVMLError: pol = "?"
        row.append(f"{name} {N.nvmlDeviceGetTemperature(h, N.NVML_TEMPERATURE_GPU)}C "
                   f"{N.nvmlDeviceGetFanSpeed_v2(h, 0)}% {pol}")
    print(" | ".join(row), flush=True)
    time.sleep(0.5)
PY

BPID=""
if [ "$LOAD" = a6000 ]; then
  ( cd /home/user/gpu-check-tools/gpu-burn; export CUDA_VISIBLE_DEVICES=$A6000_UUID; exec ./gpu_burn $BURN_S ) > $OUT/burn.log 2>&1 &
  BPID=$!
  say "load: gpu_burn on the A6000, pid $BPID; letting it reach steady state"
  sleep 45
fi

$VP $OUT/sample.py 30 > $OUT/trace.txt 2>&1 &
SPID=$!
sleep 3

say "before: $(systemctl is-active $UNIT)"
t0=$(date +%s%N); systemctl stop $UNIT; t1=$(date +%s%N)
took=$(( (t1-t0)/1000000 ))
state=$(systemctl is-active $UNIT)
say "stop returned in ${took} ms, unit is '$state'"

sleep 8
kill -TERM $SPID 2>/dev/null
[ -n "$BPID" ] && kill -TERM $BPID 2>/dev/null

echo "--- fan trace through the stop (2 Hz) ---"; cat $OUT/trace.txt

[ "$state" = inactive ] || { say "FAIL: expected 'inactive', got '$state'"; fail=1; }
[ "$took" -le $((STOP_MAX*1000)) ] || { say "FAIL: stop took ${took} ms, limit $((STOP_MAX*1000))"; fail=1; }
# the assertion the elapsed time cannot make: nothing is left in manual once the unit is gone
tail -4 $OUT/trace.txt | grep -q manual && { say "FAIL: a fan is still in policy=manual after the stop"; fail=1; }
# and the one the 06:01 failure would have tripped: manual held across many samples while stopping
held=$(grep -c manual $OUT/trace.txt)
say "samples with a fan in manual: $held of $(grep -c . $OUT/trace.txt)"

if [ -z "${KEEP_STOPPED:-}" ]; then
  systemctl start $UNIT; sleep 8
  say "after start: $(systemctl is-active $UNIT)"
  [ "$(systemctl is-active $UNIT)" = active ] || { say "FAIL: unit did not come back"; fail=1; }
fi
[ $fail -eq 0 ] && say "PASS" || say "FAILED"
exit $fail
