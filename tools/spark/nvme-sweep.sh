#!/bin/bash
# NVMe queue-depth sweep on the DGX Spark, 2026-11-03, shaped like the workstation's 10-11 sweep (log/2026-10-11.md):
# QD order 4, 1, 32, 2, 16, 8, three rounds, 4 MiB O_DIRECT preads over a 32 GiB file of written data.
# Writes the file first (one thread, 4 MiB O_DIRECT) — that row sits beside the workstation's 32 GiB burst write
# (log/2026-09-12.md), which measured the SLC cache, not the drive floor. Witness line before and after each block.
# Usage (root, from the directory holding nvread.c): nvme-sweep.sh [file=/var/tmp/nvread.bin]. Sentinel NVME_DONE.
set -u
cd "$(dirname "$0")"
F=${1:-/var/tmp/nvread.bin}
say(){ echo "$(date -u +%H:%M:%SZ) $*"; }
wit(){ echo "  witness load1=$(cut -d' ' -f1 /proc/loadavg) io_$(awk '/^some/{print $2}' /proc/pressure/io) gpu_apps=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader | grep -c .) nvme_temp=$(smartctl -A /dev/nvme0n1 | awk '/^Temperature:/{print $2}')C"; }
gcc -O2 -pthread -o nvread nvread.c || { echo "NVME_DONE rc=1"; exit 1; }
say "write"; wit; ./nvread write "$F" 32 | sed 's/^/  /'; wit
sleep 30
say "read sweep"; wit
for r in 1 2 3; do for q in 4 1 32 2 16 8; do echo "  r$r $(./nvread read "$F" $q 4)"; done; done | tee sweep.txt
wit
say "median of 3 by QD"
for q in 1 2 4 8 16 32; do awk -v q=$q '$3=="qd" && $4==q {print $5}' sweep.txt | sort -n | sed -n 2p | sed "s/^/  qd $q  /;s/$/ GB\/s/"; done
rm -f "$F"
echo "NVME_DONE rc=0"
