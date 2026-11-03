#!/bin/bash
# The workstation's 18 TB HDD (Seagate Exos X18, /data), 2026-11-03. Two measurements:
#   1. configs/disk-bench.sh on /data — the same fio cells the two NVMe drives got on 2026-09-12;
#   2. a zone curve: 1 GiB O_DIRECT reads at 0, 10, …, 90 and 99 % of the raw device. Read-only on the block device.
#      Valid on a disk with platters: an HDD reads unwritten sectors off the platter like any other, unlike an SSD,
#      which answers unmapped LBAs without touching NAND (why tools/spark/nvread.c reads a written file instead).
# Holds the bloomery timing lease (/root/bloomery-cpu.lock) for the run so no timing seat overlaps it; waits up to
# 10 min for it. Witness line (load1, IO pressure, holds, GPU apps) before and after each block.
# usage (root, on the workstation, beside disk-bench.sh): hdd-bench.sh [dev=sda] [dir=/data]. Sentinel HDD_DONE rc=<n>.
set -u -o pipefail   # pipefail: the first run piped disk-bench.sh into grep|sed and its death read as rc 0
cd "$(dirname "$0")"
DEV=${1:-sda}; DIR=${2:-/data}
say(){ echo "$(date -u +%H:%M:%SZ) $*"; }
wit(){ echo "  witness load1=$(cut -d' ' -f1 /proc/loadavg) io_$(awk '/^some/{print $2}' /proc/pressure/io) holds=$(ls /root/bloomery-*-hold 2>/dev/null | wc -l) gpu_apps=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -c .) temp=$(smartctl -A /dev/$DEV | awk '$2=="Temperature_Celsius"{print $10}')C"; }
exec 9>>/root/bloomery-cpu.lock
flock -w 600 9 || { say "lease not free after 600 s"; echo "HDD_DONE rc=75"; exit 75; }
say "lease held"; rc=0

say "fio (disk-bench.sh $DIR)"; wit
bash ./disk-bench.sh "$DIR" "hdd $DEV" > fio.out 2>&1 || rc=1
grep -v '^# device' fio.out | sed 's/^/  /'                    # the device line carries the serial
grep -q 'rand write' fio.out || { echo "  fio produced no last cell"; rc=1; }
wit

[ "${SKIP_ZONE:-0}" = 1 ] && { echo "HDD_DONE rc=$rc"; exit $rc; }
say "zone curve: 1 GiB O_DIRECT read at each position of /dev/$DEV"; wit
sz=$(blockdev --getsize64 /dev/$DEV); gib=$((1 << 30))
for pct in 0 10 20 30 40 50 60 70 80 90 99; do
  skip=$(( sz / 100 * pct / gib ))                 # in 1 GiB blocks
  out=$(dd if=/dev/$DEV of=/dev/null bs=1G count=1 skip=$skip iflag=direct 2>&1 | tail -1)
  printf "  %3d %%  %s\n" "$pct" "$(printf %s "$out" | grep -oE '[0-9.,]+ [MG]B/s')"
done
wit
echo "HDD_DONE rc=$rc"
