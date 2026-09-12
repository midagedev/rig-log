#!/usr/bin/env bash
# Write until the drive stops pretending, and report the rate every 10 seconds.
#
# usage: disk-sustained.sh <directory> [gigabytes]
#
# A 32 GiB burst test lands entirely in an SSD's SLC write cache and measures
# the cache, not the drive. The number that matters here is different: this
# machine moves 155 GB model files around, so the question is what happens when
# the cache runs out and the controller has to fold data down into TLC while
# still accepting writes.
#
# Run on a quiet machine, on a filesystem with room for the whole test file.
set -euo pipefail

DIR=${1:?usage: disk-sustained.sh <directory> [gigabytes]}
GB=${2:-300}
FILE="$DIR/.fio-sustained.tmp"
LOG=$(mktemp -u /tmp/sustained-XXXXXX)

command -v fio >/dev/null || { echo "fio not installed" >&2; exit 1; }

cleanup() { rm -f "$FILE" "$LOG"_bw.*.log; }
trap cleanup EXIT

DEV=$(lsblk -no PKNAME "$(findmnt -no SOURCE --target "$DIR")")
echo "# sustained write: ${GB} GiB to $DIR (/dev/$DEV)"
echo "# fio 1M blocks, QD8, O_DIRECT — free space before: $(df -h "$DIR" | awk 'NR==2{print $4}')"
echo

fio --name=sustained --filename="$FILE" --size="${GB}G" \
    --rw=write --bs=1M --iodepth=8 --direct=1 \
    --ioengine=libaio --numjobs=1 --group_reporting \
    --write_bw_log="$LOG" --log_avg_msec=10000 \
    --output-format=json > "$LOG.json" 2>/dev/null

echo "elapsed   throughput"
# fio's bw log is "msec, KiB/s, ..." per averaging window.
awk -F', *' '{printf "%5.0fs   %6.2f GB/s\n", $1/1000, $2*1024/1e9}' "${LOG}_bw.1.log"

echo
python3 - "$LOG.json" <<'PY'
import json, sys
j = json.load(open(sys.argv[1]))
w = j["jobs"][0]["write"]
print("overall   %.2f GB/s over %.0f seconds, %.0f GiB written"
      % (w["bw_bytes"] / 1e9, w["runtime"] / 1000, w["io_bytes"] / 2**30))
PY
rm -f "$LOG.json"
