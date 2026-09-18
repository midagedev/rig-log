#!/bin/bash
# run-rung1.sh — the pinned-DMA control, start to forensics.
#
# Rung 1 of the ladder in log/2026-09-18-b: does sustained host-interface traffic,
# with no NCCL anywhere, take a card off the bus? Two NCCL DDP runs did, at 133 s and
# 110 s. Three compute-bound controls did not, one of them 30 minutes at a HIGHER
# power than the fault. This varies bus traffic and nothing else.
#
# Rung 1 is bare DMA (EXTRA empty). Rung 1b adds compute beside it: measured
# 2026-09-18, "--compute 4096 --compute-iters 4" holds 418 W while still moving
# 19 GB/s aggregate, which beats the faulting run on BOTH axes (it peaked at 384 W).
# Raising compute-iters past 4 buys no power and costs transfer rate.
#
#   bash gpu-dma-control-run.sh <tag> [seconds] [extra args for gpu-dma-control.py]
set -u
TAG=${1:?tag}; SECS=${2:-900}; shift 2 2>/dev/null || shift $#
EXTRA="$*"
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=/home/user/gpu-check/rung1-$TAG
LEASE=/home/user/gpu-lease
GF3090=GPU-307fa0f6-daae-24e5-6fd3-cd50620de6b1
A6000=GPU-8c129fa6-7382-35a5-2464-9ff01d99fcd4
PY=/webuta/venv/bin/python

mkdir -p "$OUT"
say(){ echo "$(date +%T) $*" | tee -a "$OUT/run.log"; }
aer(){ for d in 41:00.0 40:01.1 61:00.0 60:01.1; do
         echo "## 0000:$d"; lspci -vvv -s $d 2>/dev/null | grep -E "LnkSta:|UESta:|CESta:"; done; }

held=0
cleanup(){
  bash "$HERE/gpu-witness-stop.sh" "$OUT" 2>&1 | tee -a "$OUT/run.log"
  if [ "$held" = 1 ] && [ -f "$LEASE" ] && [ "$(awk '{print $1}' "$LEASE")" = "$$" ]; then
    rm -f "$LEASE"; say "lease released"
  fi
}
trap cleanup EXIT

# --- the lease, and the reader's half of it ---------------------------------------
# A lease file is only a lease if the pid in it answers. One stale file cost a peer
# session a night's training on 2026-09-17.
if [ -f "$LEASE" ]; then
  hp=$(awk '{print $1}' "$LEASE")
  if [ -d "/proc/$hp" ]; then say "lease held by pid $hp: $(cat "$LEASE")"; exit 1; fi
  say "stale lease from dead pid $hp, taking it: $(cat "$LEASE")"
fi
echo "$$ rung1-dma-control $(date -Is)" > "$LEASE"; held=1
say "lease acquired by pid $$"

say "=== pinned host<->device DMA, no NCCL, both cards, ${SECS}s, extra: ${EXTRA:-none} ==="
say "quiet: $(cat /proc/pressure/io | head -1)"
say "load: $(uptime | sed 's/.*average/average/')"
say "fan unit: $(systemctl is-active gpu-fan)  llm: $(systemctl is-active llm.service 2>/dev/null)"
nvidia-smi --query-gpu=index,name,uuid,memory.used --format=csv > "$OUT/smi-before.csv"
aer > "$OUT/aer-before.txt"
date +%s.%N > "$OUT/t_start"
journalctl -k -n 1 --no-pager -o short-precise > "$OUT/journal-mark.txt" 2>/dev/null

bash "$HERE/gpu-fault-witness.sh" "$OUT" $((SECS + 300))
# Assert the witness actually came up rather than announcing that it did. Measured
# 2026-09-18: a rename left the box with the old script names, the witness call failed,
# and this line printed "witness up" anyway -- so rung 1b ran for fifteen minutes with
# no telemetry at all and the run log said everything was fine. A run whose instruments
# are silent is not a cheaper run, it is a wasted one, so this refuses to start the load.
sleep 4
for f in dmon-3090.log dmon-a6000.log bmc.csv presence.csv; do
  [ -s "$OUT/$f" ] || { say "ABORT: witness produced no $f -- not starting the load"; exit 1; }
done
for n in dmon-3090 dmon-a6000 bmc presence; do
  p=$(cat "$OUT/$n.pid" 2>/dev/null || echo 0)
  [ -d "/proc/$p" ] || { say "ABORT: witness logger $n (pid $p) is not running"; exit 1; }
done
say "witness up and verified: 4 loggers live, 4 files growing"
sleep 3

# --- the load: one process per card, selected by UUID ------------------------------
# The load writes its OWN pid file. $! here names a bash: an env-var prefix plus setsid
# makes the shell fork a subshell, and the smoke run proved it again -- comm=bash, the
# fourth time on this machine that a runner recorded a wrapper instead of the program.
rm -f "$OUT/load-3090.pid" "$OUT/load-a6000.pid"
CUDA_VISIBLE_DEVICES=$GF3090 setsid "$PY" "$HERE/gpu-dma-control.py" --seconds "$SECS" --label 3090 $EXTRA \
  --pidfile "$OUT/load-3090.pid" > "$OUT/load-3090.log" 2>&1 &
CUDA_VISIBLE_DEVICES=$A6000 setsid "$PY" "$HERE/gpu-dma-control.py" --seconds "$SECS" --label a6000 $EXTRA \
  --pidfile "$OUT/load-a6000.pid" > "$OUT/load-a6000.log" 2>&1 &
for i in $(seq 1 60); do
  [ -s "$OUT/load-3090.pid" ] && [ -s "$OUT/load-a6000.pid" ] && break; sleep 1
done
for n in 3090 a6000; do
  p=$(cat "$OUT/load-$n.pid" 2>/dev/null || echo 0)
  say "load $n pid $p comm=$(cat /proc/$p/comm 2>/dev/null || echo GONE)"
done

say "both loads launched; watching for a fault"
end=$(( $(date +%s) + SECS + 60 ))
faulted=0
while [ "$(date +%s)" -lt $end ]; do
  if [ -f "$OUT/FAULT" ]; then faulted=1; break; fi
  a=$(cat "$OUT/load-3090.pid"); b=$(cat "$OUT/load-a6000.pid")
  if [ ! -d "/proc/$a" ] && [ ! -d "/proc/$b" ]; then say "both loads exited"; break; fi
  sleep 2
done

# --- forensics ---------------------------------------------------------------------
if [ "$faulted" = 1 ]; then
  say "*** FAULT: $(cat "$OUT/FAULT" | tr '\n' ' ')"
  say "capturing forensics before anything else touches the machine"
  timeout 20 nvidia-smi -L                       > "$OUT/f-smi-L.txt" 2>&1
  timeout 30 nvidia-smi                          > "$OUT/f-smi.txt" 2>&1
  lspci -xxx -s 41:00.0                          > "$OUT/f-cfg-3090.txt" 2>&1
  lspci -xxx -s 61:00.0                          > "$OUT/f-cfg-a6000.txt" 2>&1
  aer                                            > "$OUT/f-aer.txt" 2>&1
  lspci -vvv                                     > "$OUT/f-lspci.txt" 2>&1
  timeout 20 ipmitool -S "$OUT/sdr.cache" sdr type temperature > "$OUT/f-ipmi.txt" 2>&1
  journalctl -k --since "@$(cut -d. -f1 < "$OUT/t_start")" --no-pager -o short-precise \
                                                 > "$OUT/f-journal.txt" 2>&1
  grep -E "Xid|fallen off|NVRM: GPU at|recovery action" "$OUT/f-journal.txt" | head -40 \
                                                 > "$OUT/f-xid.txt" 2>&1
  say "forensics in $OUT (f-*.txt)"
  say "xid lines: $(wc -l < "$OUT/f-xid.txt")"
else
  say "no fault in ${SECS}s"
  aer > "$OUT/aer-after.txt"
  journalctl -k --since "@$(cut -d. -f1 < "$OUT/t_start")" --no-pager -o short-precise \
             > "$OUT/journal-after.txt" 2>&1
  say "kernel lines during the run: $(wc -l < "$OUT/journal-after.txt")"
fi
say "=== done, faulted=$faulted ==="
