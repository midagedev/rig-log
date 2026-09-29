#!/bin/bash
# L3 read bandwidth for the offload-bandwidth clip (2026-09-30): the bw probe at cache-resident sizes, plus the
# 8 GiB DRAM row as the same-window reference against 147.7 GB/s. 5975WX: 32 MiB L3 per CCD (8 cores), 512 KiB L2
# per core, so 32 threads with a 64 MiB buffer read 2 MiB each and 16 MiB per CCD — past L2, inside L3.
# Waits for the box's timing lease (/root/bloomery-cpu.lock, the flock bloomery's runners take) and every
# /root/bloomery-*-hold to be free, IO pressure some avg10 < 5 and load1 < 4, then holds the lease for the run.
# Gives up after BOUND seconds (default 6 h). Witnesses at start and end. Sentinel L3_DONE.
say(){ echo "$(date -u +%H:%M:%SZ) $*"; }
wit(){ echo "witness load1=$(cut -d' ' -f1 /proc/loadavg) io_$(grep some /proc/pressure/io | cut -d' ' -f2) gpu_apps=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -c .) holds=$(ls /root/bloomery-*-hold 2>/dev/null | wc -l)"; }
cd "$(dirname "$0")"
gcc -O2 -mavx2 -fopenmp -o bw bw.c || { say "bw build failed"; exit 1; }
BOUND=${BOUND:-21600}; start=$(date +%s)
exec 9>>/root/bloomery-cpu.lock
while :; do
  if flock -n 9; then
    io=$(awk '/^some/{sub("avg10=","",$2); print $2}' /proc/pressure/io); l=$(cut -d' ' -f1 /proc/loadavg)
    holds=$(ls /root/bloomery-*-hold 2>/dev/null | wc -l)
    if [ "$holds" -eq 0 ] && awk -v a="$io" -v b="$l" 'BEGIN{exit !(a<5 && b<4)}'; then break; fi
    flock -u 9
  fi
  [ $(( $(date +%s) - start )) -ge "$BOUND" ] && { say "not quiet after ${BOUND}s: $(wit)"; exit 75; }
  sleep 60
done
say "lease taken  $(wit)"
say "THP $(cat /sys/kernel/mm/transparent_hugepage/enabled)  cap $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq)"
for s in 16M 32M 64M 96M 256M 8; do
  echo "  $(OMP_PROC_BIND=spread OMP_PLACES=cores ./bw 32 $s 7)"
done
echo "  1 thread: $(OMP_PROC_BIND=close OMP_PLACES=cores ./bw 1 2M 7)"
say "done  $(wit)"
flock -u 9
say L3_DONE
