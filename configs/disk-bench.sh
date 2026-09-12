#!/usr/bin/env bash
# Measure one NVMe drive through a filesystem, the way this machine uses it.
#
# usage: disk-bench.sh <directory> [label]
#
# File-based rather than raw-device, deliberately: one of these drives holds
# the root filesystem and writing to its block device is not an option, and a
# number you cannot take on both drives is not a comparison. Everything is
# O_DIRECT, so the page cache is out of the path and the numbers are the
# drive's, not DRAM's.
#
# Run it on a quiet machine. On this one that means stopping llm.service first,
# which otherwise holds 111 GB of resident model and a warm page cache.
set -euo pipefail

DIR=${1:?usage: disk-bench.sh <directory> [label]}
LABEL=${2:-$DIR}
FILE="$DIR/.fio-bench.tmp"
SIZE=${SIZE:-32G}

command -v fio >/dev/null || { echo "fio not installed" >&2; exit 1; }
[ -d "$DIR" ] || { echo "no such directory: $DIR" >&2; exit 1; }

cleanup() { rm -f "$FILE"; }
trap cleanup EXIT

dev_of() {  # directory -> the nvme device holding it, and its serial
    local src pk
    src=$(findmnt -no SOURCE --target "$1")
    pk=$(lsblk -no PKNAME "$src")
    echo "$pk"
}

DEV=$(dev_of "$DIR")
SERIAL=$(cat "/sys/block/$DEV/device/serial" 2>/dev/null | xargs || echo unknown)
MODEL=$(cat "/sys/block/$DEV/device/model" 2>/dev/null | xargs || echo unknown)

temp_now() {  # composite temperature in C, or empty
    # nvme prints "temperature : 48 C (321 Kelvin)"; take the first number only,
    # or the Kelvin figure gets concatenated onto it.
    sudo -n nvme smart-log "/dev/$DEV" 2>/dev/null |
        awk -F: '/^temperature/ {print $2; exit}' | grep -oE '[0-9]+' | head -1
}

run() {  # name rw bs iodepth [extra fio args...]
    local name=$1 rw=$2 bs=$3 qd=$4; shift 4
    local out
    out=$(fio --name="$name" --filename="$FILE" --size="$SIZE" \
              --rw="$rw" --bs="$bs" --iodepth="$qd" --direct=1 \
              --ioengine=libaio --numjobs=1 --group_reporting \
              --output-format=json "$@" 2>/dev/null)
    echo "$out"
}

# Sequential tests are bounded by SIZE: 32 GiB at these rates is a few seconds.
# Random tests must be bounded by TIME instead — 32 GiB of 4 KiB reads is eight
# million IOs, which at queue depth 1 is a quarter of an hour of doing nothing
# but proving a latency figure that settles in thirty seconds.
RANDOM_LIMIT=(--runtime=30 --time_based --norandommap --randrepeat=0)

echo "# $LABEL"
echo "# device /dev/$DEV — $MODEL — serial $SERIAL"
echo "# fio $(fio --version), $SIZE per job, O_DIRECT, libaio"
T0=$(temp_now); [ -n "$T0" ] && echo "# drive temperature before: ${T0}C"
echo

emit() {  # test-name json
    printf '%s\n' "$2" | python3 -c '
import json, sys
name = sys.argv[1]
j = json.load(sys.stdin)
job = j["jobs"][0]
for direction in ("read", "write"):
    d = job[direction]
    if not d["io_bytes"]:
        continue
    bw = d["bw_bytes"] / 1e9
    iops = d["iops"]
    lat = d["clat_ns"]["percentile"].get("99.000000", 0) / 1e6 if "percentile" in d["clat_ns"] else 0
    mean = d["clat_ns"]["mean"] / 1e6
    print("%-28s %8.2f GB/s %12.0f IOPS   mean %7.3f ms   p99 %7.3f ms"
          % (name, bw, iops, mean, lat))
' "$1"
}

# Write first: it lays the file out, so the read tests that follow have
# something real to read. Each test re-reads the same file.
emit "seq write  1M QD8"   "$(run seqwrite  write   1M 8)"
emit "seq read   1M QD8"   "$(run seqread   read    1M 8)"
emit "rand read  4K QD32"  "$(run randread  randread 4k 32 "${RANDOM_LIMIT[@]}")"
emit "rand read  4K QD1"   "$(run randread1 randread 4k 1 "${RANDOM_LIMIT[@]}")"
emit "rand write 4K QD32"  "$(run randwrite randwrite 4k 32 "${RANDOM_LIMIT[@]}")"

T1=$(temp_now); [ -n "$T1" ] && echo && echo "# drive temperature after: ${T1}C"
