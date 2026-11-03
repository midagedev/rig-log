#!/bin/bash
# DGX Spark (GB10) health and baseline check, 2026-11-03. Runs on the Spark as root from a directory that holds
# bw.c (tools/membw), gpu-bw.cu and gemm.cu. Builds them, then measures in this order:
#   CPU read bandwidth (thread sweep, X925 vs A725 clusters), GPU read/copy bandwidth, cuBLAS GEMM rates,
#   NVMe raw sequential read (O_DIRECT, read-only on the block device), 300 s GPU sustain with 1 s telemetry,
#   CPU+GPU contention on the shared pool, then AER/RAS counts.
# Every block starts and ends with a witness line (load1, IO pressure, GPU compute apps) — docs/quiet-machine.md.
# Output: stdout (the caller redirects it). Sentinel: the last line is HEALTH_DONE rc=<n>.
set -u
export PATH=/usr/local/cuda/bin:$PATH
cd "$(dirname "$0")"
say(){ echo "$(date -u +%H:%M:%SZ) $*"; }
wit(){ echo "  witness load1=$(cut -d' ' -f1 /proc/loadavg) io_$(awk '/^some/{print $2}' /proc/pressure/io) gpu_apps=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader | grep -c .) temp=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader)C"; }
drop(){ sync; echo 3 > /proc/sys/vm/drop_caches; }
X925=5-9,15-19; A725=0-4,10-14
rc=0

say "build"
gcc -O3 -mcpu=native -fopenmp -o bw bw.c || rc=1
nvcc -O3 -arch=sm_121 -o gpu-bw gpu-bw.cu || rc=1
nvcc -O3 -arch=sm_121 -o gemm gemm.cu -lcublas || rc=1
[ $rc -ne 0 ] && { say "build failed"; echo "HEALTH_DONE rc=$rc"; exit $rc; }
say "kernel $(uname -r)  driver $(nvidia-smi --query-gpu=driver_version --format=csv,noheader)  aer_before=$(ras-mc-ctl --summary 2>/dev/null | awk '/Corrected errors/{print $1}')"
drop; grep -E "MemTotal|MemAvailable" /proc/meminfo | sed 's/^/  /'

say "cpu read bandwidth (16 GiB buffer, best of 5)"; wit
for t in 1 2 5 10 20; do echo "  all    $(OMP_PROC_BIND=spread OMP_PLACES=cores ./bw $t 16 5)"; done
echo "  X925x10 $(OMP_PROC_BIND=close taskset -c $X925 ./bw 10 16 5)"
echo "  A725x10 $(OMP_PROC_BIND=close taskset -c $A725 ./bw 10 16 5)"
echo "  X925x1  $(taskset -c 5 ./bw 1 16 5)"
echo "  A725x1  $(taskset -c 0 ./bw 1 16 5)"
wit

say "gpu bandwidth"; drop; wit
echo "  $(./gpu-bw read 16 20)"
echo "  $(./gpu-bw read 2 50)"
echo "  $(./gpu-bw copy 8 20)"
wit

say "gemm"; wit
for ty in bf16 fp16 tf32; do echo "  $(./gemm $ty 8192 20)"; done
echo "  $(./gemm fp32 4096 10)"
wit

# NVMe is measured by nvme-sweep.sh (nvread over a file it wrote). The first run's raw-device dd read the first
# 16 GiB of the block device, which may hold unwritten LBAs an SSD answers without NAND reads (2026-11-03).

say "gpu sustain 300 s (telemetry every 1 s)"; drop; wit
nvidia-smi --query-gpu=timestamp,temperature.gpu,power.draw,clocks.sm,clocks_event_reasons.active --format=csv,noheader -l 1 > telemetry.csv &
tel=$!
./gpu-bw sustain 16 300 > sustain.txt
kill $tel; wait $tel 2>/dev/null
# "t=  1 s" and "t=296 s" split into different field counts, so pick the number by its unit (2026-11-03 fix:
# the first run's $4 read the word "read" and printed min 0.0)
grep -o '[0-9.]* GB/s' sustain.txt | awk '{print $1}' | sort -n | awk '{a[NR]=$1} END{printf "  sustain GB/s: min %.1f  median %.1f  max %.1f  (%d s)\n", a[1], a[int((NR+1)/2)], a[NR], NR}'
echo "  first 3 s:"; head -3 sustain.txt | sed 's/^/    /'; echo "  last 3 s:"; tail -3 sustain.txt | sed 's/^/    /'
awk -F', ' '{t[NR]=$2; p[NR]=$3+0; c[NR]=$4+0; if($5!="0x0000000000000000") r[$5]++} END{
  n=NR; asort(t); asort(p); asort(c);
  printf "  telemetry n=%d  temp C min/med/max %s/%s/%s  power W %.1f/%.1f/%.1f  sm MHz %d/%d/%d\n", n, t[1], t[int((n+1)/2)], t[n], p[1], p[int((n+1)/2)], p[n], c[1], c[int((n+1)/2)], c[n];
  for (k in r) printf "  event reason %s: %d s\n", k, r[k] }' telemetry.csv
for z in /sys/class/thermal/thermal_zone*; do printf "%s " "$(( $(cat $z/temp) / 1000 ))"; done | sed 's/^/  acpitz C after: /'; echo
wit

say "cpu+gpu contention on the shared pool"; drop; sleep 20; wit
./gpu-bw sustain 16 40 > contend.txt &
g=$!
sleep 12; echo "  cpu during gpu: $(OMP_PROC_BIND=spread OMP_PLACES=cores ./bw 20 16 8)"
wait $g
echo "  gpu per second (cpu probe started at ~t=12):"; grep -o '[0-9.]* GB/s' contend.txt | awk '{printf " %s", $1} END{print ""}' | fold -w 120 | sed 's/^/   /'
wit

say "errors"
echo "  aer_after=$(ras-mc-ctl --summary 2>/dev/null | awk '/Corrected errors/{print $1}')  mem: $(ras-mc-ctl --summary 2>/dev/null | grep -i -m1 'memory errors')"
journalctl -k -b --no-pager -p err --since "-40min" | grep -v -E "pwrap probe failed" | tail -5 | sed 's/^/  /'
echo "HEALTH_DONE rc=$rc"
