#!/bin/bash
# bmc-loop.sh — the per-slot PCIe sensors, read through a cached SDR.
set -u
OUT=${1:?}; SECS=${2:-1200}
end=$(( $(date +%s) + SECS ))
echo "epoch,pcie01_c,pcie05_c,ok,ms"
while [ "$(date +%s)" -lt $end ]; do
  t0=$(date +%s%3N)
  r=$(timeout 4 ipmitool -S "$OUT/sdr.cache" sensor reading "PCIE01 Temp." "PCIE05 Temp." 2>/dev/null)
  t1=$(date +%s%3N)
  p1=$(echo "$r" | awk -F'|' '/PCIE01/{gsub(/ /,"",$2); print $2}')
  p5=$(echo "$r" | awk -F'|' '/PCIE05/{gsub(/ /,"",$2); print $2}')
  ok=1; [ -z "$p1$p5" ] && ok=0
  echo "$(date +%s.%N),${p1},${p5},${ok},$((t1-t0))"
done
