#!/bin/bash
# gpu-ddp-round.sh — run the DDP arm under the fixed witness, and get something out of it
# whether or not it faults.
#
# Rungs 1 and 1b both came back clean: neither sustained bidirectional DMA at the link's
# limit (37 GB/s, 900 s, 160 W) nor the same traffic with the card at the power the fault
# happened at (18.5 GB/s, 900 s, 419 W) will take this card off the bus. The variable that
# remains is the NCCL path itself, so this round runs it -- with the instruments that the
# last fault showed were needed and were not there:
#
#   - presence by `nvidia-smi -L`, ~0.04 s a sample, so the driver's clock is fine
#   - the BMC's side-band channel at ~0.12 s, from 5.2 s, because the ordering claim
#     rests on it and it could not resolve anything finer than five seconds
#   - rxpci/txpci per card, which no previous fault run recorded
#   - the step counter once a second, so a run that dies in two minutes still yields the
#     throughput number this configuration has never produced
#   - GSP firmware logs, enabled for the first time (NVreg_EnableGpuFirmwareLogs=1):
#     when the card stopped answering, every engine-dump callback returned GPU_IS_LOST,
#     so the driver could say nothing about what happened. GSP speaks from inside the chip.
#
# The arm script takes the GPU lease itself and refuses to run without a name on the
# command line, so this does not take the lease and does not supply that name.
#
# With PL3090/PLA6000 set, the round first takes the power budget away. That is this
# repo's standing answer to a question about power -- measured 2026-09-15 on the serving
# side, 47 % less budget cost 15 % of the rate -- and here it is the only test of the
# transient hypothesis the machine can actually run: nothing on this box can SEE a
# transient (NVML's power sensor updates every ~240 ms, and the BMC's +12V reading did
# not move once in twelve seconds of polling), so the way to ask is to remove the
# headroom and see whether the failure goes away. It also prices the mitigation, because
# the step sampler keeps running.
#
#   bash gpu-ddp-round.sh <tag> <approver> [seconds]
#   PL3090=250 PLA6000=250 bash gpu-ddp-round.sh <tag> <approver> 900
set -u
TAG=${1:?tag}; WHO=${2:?approver name}; SECS=${3:-1500}
PL3090=${PL3090:-}; PLA6000=${PLA6000:-}
GF=GPU-307fa0f6-daae-24e5-6fd3-cd50620de6b1
A6=GPU-8c129fa6-7382-35a5-2464-9ff01d99fcd4
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=/home/user/gpu-check/ddp-$TAG
TLOG=/webuta/logs/voc-train.log
mkdir -p "$OUT"
say(){ echo "$(date +%T) $*" | tee -a "$OUT/run.log"; }
aer(){ for d in 41:00.0 40:01.1 61:00.0 60:01.1; do
         echo "## 0000:$d"; lspci -vvv -s $d 2>/dev/null | grep -E "LnkSta:|UESta:|CESta:"; done; }

restore_pl(){
  # Every exit path puts the budget back, including SIGTERM and the timeout. A crash does
  # it too: -pl does not survive a driver reload, so a fault restores the defaults itself.
  [ -n "$PL3090" ]  && nvidia-smi -i "$GF" -pl "$(nvidia-smi -i "$GF" --query-gpu=power.default_limit --format=csv,noheader,nounits)" >/dev/null 2>&1
  [ -n "$PLA6000" ] && nvidia-smi -i "$A6" -pl "$(nvidia-smi -i "$A6" --query-gpu=power.default_limit --format=csv,noheader,nounits)" >/dev/null 2>&1
  [ -n "$PL3090$PLA6000" ] && say "power limits restored: $(nvidia-smi --query-gpu=name,power.limit --format=csv,noheader | tr '\n' ' ')"
  return 0
}
cleanup(){ bash "$HERE/gpu-witness-stop.sh" "$OUT" 2>&1 | tee -a "$OUT/run.log"; restore_pl; }
trap cleanup EXIT

say "=== DDP round '$TAG', approved by $WHO, ${SECS}s max ==="
say "GSP firmware logs: $(cat /sys/module/nvidia/parameters/NVreg_EnableGpuFirmwareLogs)"
say "lease: $(cat /home/user/gpu-lease 2>/dev/null || echo free)"
say "quiet: $(head -1 /proc/pressure/io)"
if [ -n "$PL3090" ]; then nvidia-smi -i "$GF" -pl "$PL3090" 2>&1 | tail -1 | tee -a "$OUT/run.log"; fi
if [ -n "$PLA6000" ]; then nvidia-smi -i "$A6" -pl "$PLA6000" 2>&1 | tail -1 | tee -a "$OUT/run.log"; fi
say "power limits in force: $(nvidia-smi --query-gpu=name,power.limit --format=csv,noheader | tr '\n' ' ')"
nvidia-smi --query-gpu=index,name,uuid,memory.used,power.limit --format=csv > "$OUT/smi-before.csv"
aer > "$OUT/aer-before.txt"
date +%s.%N > "$OUT/t_start"

bash "$HERE/gpu-fault-witness.sh" "$OUT" $((SECS + 300))
sleep 4
for f in dmon-3090.log dmon-a6000.log bmc.csv presence.csv; do
  [ -s "$OUT/$f" ] || { say "ABORT: witness produced no $f"; exit 1; }
done
for n in dmon-3090 dmon-a6000 bmc presence; do
  p=$(cat "$OUT/$n.pid" 2>/dev/null || echo 0)
  [ -d "/proc/$p" ] || { say "ABORT: witness logger $n (pid $p) is not running"; exit 1; }
done
say "witness up and verified: 4 loggers live, 4 files growing"

bash "$HERE/gpu-ddp-round-steps.sh" "$TLOG" $((SECS + 300)) > "$OUT/steps.csv" 2>"$OUT/steps.err" &
echo $! > "$OUT/steps.pid"; say "step sampler pid $(cat "$OUT/steps.pid") comm=$(cat /proc/$(cat "$OUT/steps.pid")/comm 2>/dev/null)"

say "launching the DDP arm"
setsid bash /webuta/voc-measure-arm.sh ddp --approved-by "$WHO" > "$OUT/arm.out" 2>&1 &
sleep 5
say "arm.out: $(head -3 "$OUT/arm.out" | tr '\n' ' ')"

end=$(( $(date +%s) + SECS ))
faulted=0
while [ "$(date +%s)" -lt $end ]; do
  [ -f "$OUT/FAULT" ] && { faulted=1; break; }
  if [ -f /webuta/logs/voc-train.pid ]; then
    tp=$(cat /webuta/logs/voc-train.pid 2>/dev/null || echo 0)
    [ -d "/proc/$tp" ] || { say "training pid $tp is gone"; break; }
  fi
  sleep 2
done

if [ "$faulted" = 1 ]; then
  say "*** FAULT: $(tr '\n' ' ' < "$OUT/FAULT")"
  timeout 20 nvidia-smi -L                       > "$OUT/f-smi-L.txt" 2>&1
  timeout 30 nvidia-smi                          > "$OUT/f-smi.txt" 2>&1
  lspci -xxx -s 41:00.0                          > "$OUT/f-cfg-3090.txt" 2>&1
  lspci -xxx -s 61:00.0                          > "$OUT/f-cfg-a6000.txt" 2>&1
  aer                                            > "$OUT/f-aer.txt" 2>&1
  lspci -vvv                                     > "$OUT/f-lspci.txt" 2>&1
  timeout 20 ipmitool -S "$OUT/sdr.cache" sdr type temperature > "$OUT/f-ipmi.txt" 2>&1
  journalctl -k -b 0 --since "@$(cut -d. -f1 < "$OUT/t_start")" --no-pager -o short-precise \
                                                 > "$OUT/f-journal.txt" 2>&1
  grep -iE "Xid|fallen off|recovery action|GSP|libos|gsp" "$OUT/f-journal.txt" | head -200 \
                                                 > "$OUT/f-gsp-and-xid.txt" 2>&1
  say "forensics written; xid/gsp lines: $(wc -l < "$OUT/f-gsp-and-xid.txt")"
else
  say "no fault"
  aer > "$OUT/aer-after.txt"
  journalctl -k -b 0 --since "@$(cut -d. -f1 < "$OUT/t_start")" --no-pager -o short-precise \
             > "$OUT/journal-after.txt" 2>&1
fi
say "=== done, faulted=$faulted ==="
