#!/bin/bash
# WKS-22 follow-up: where does the 132 GB/s read cap live? Per-CCD probe (5975WX: 4 CCDs, cores 0-7 | 8-15 | 16-23 | 24-31, SMT siblings +32).
# Pins the bw probe to one CCD, two CCDs, then all four, at fixed threads-per-CCD. Waits BW_DONE. Sentinel CCD_DONE.
say(){ echo "$(date +%H:%M:%S) $*"; }
io(){ grep some /proc/pressure/io | sed 's/ total=.*//'; }
until grep -q BW_DONE ~/bw-window.log 2>/dev/null; do sleep 20; done
say "ccd probe start  $(io)  cap $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq)"
run(){ label=$1; cpus=$2; t=$3; echo "  $label  cpus $cpus  $(OMP_PLACES=cores OMP_PROC_BIND=close taskset -c $cpus ~/bw $t 8 5)"; }
for t in 1 2 4 8; do run "1 CCD " 0-7 $t; done
for t in 2 4 8 16; do run "2 CCDs" 0-15 $t; done
for t in 4 8 16 32; do run "4 CCDs" 0-31 $t; done
run "CCD0 only" 0-7 8; run "CCD1 only" 8-15 8; run "CCD2 only" 16-23 8; run "CCD3 only" 24-31 8
run "SMT 16 on 1 CCD" 0-7,32-39 16
say "ccd probe done  $(io)"
say CCD_DONE
