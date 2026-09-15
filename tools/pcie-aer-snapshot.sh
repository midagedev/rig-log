#!/usr/bin/env bash
# One PCIe fabric snapshot: corrected-error counters, link state, memory clock.
#
# The counters in /sys/bus/pci/devices/*/aer_dev_correctable are cumulative
# since boot, so a snapshot is only worth anything next to another one. Take
# it right after a boot, take it again after a window, and the difference is
# the error rate that window produced. Run it with --load to hold the link
# busy while LnkSta is read: at idle this board's GPU ports sit at 2.5 GT/s
# against a 16 GT/s LnkCap, and an idle reading cannot tell ASPM downclocking
# from a link that fell back after errors.
#
#   sudo tools/pcie-aer-snapshot.sh boot0            # counters + idle link
#   sudo tools/pcie-aer-snapshot.sh after-decode     # again, later
#   sudo tools/pcie-aer-snapshot.sh under-load --load 'python3 h2d.py'
#
# Writes <outdir>/<label>.txt (default ~/incident-*/ if one exists, else cwd)
# and prints the counter block, which is the part you compare by eye.
set -u

LABEL=${1:?label required (e.g. boot0, after-decode)}; shift || true
LOAD=""
OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --load) LOAD=$2; shift 2 ;;
    --out)  OUT=$2; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 64 ;;
  esac
done

if [ -z "$OUT" ]; then
  OUT=$(ls -d "$HOME"/incident-* 2>/dev/null | tail -1)
  [ -n "$OUT" ] || OUT=.
fi
mkdir -p "$OUT"
F="$OUT/aer-$LABEL.txt"

# every NVIDIA function and the bridge directly above it -- the errors on this
# board have never been on the same device twice, so the port is not optional
gpu_paths() {
  for d in /sys/bus/pci/devices/*; do
    [ -e "$d/vendor" ] || continue
    [ "$(cat "$d/vendor")" = "0x10de" ] || continue
    echo "${d##*/}"
    up=$(readlink -f "$d/.." ); up=${up##*/}
    case "$up" in [0-9a-f]*:*) echo "$up" ;; esac
  done | sort -u
}

counters() {
  for f in /sys/bus/pci/devices/*/aer_dev_correctable \
           /sys/bus/pci/devices/*/aer_dev_nonfatal \
           /sys/bus/pci/devices/*/aer_dev_fatal; do
    [ -r "$f" ] || continue
    d=$(dirname "$f"); d=${d##*/}
    tot=$(awk '$1=="TOTAL_ERR_COR"||$1=="TOTAL_ERR_NONFATAL"||$1=="TOTAL_ERR_FATAL"{print $2}' "$f")
    [ "${tot:-0}" -gt 0 ] 2>/dev/null || continue
    printf '%-14s %-22s' "$d" "$(basename "$f")"
    awk '$2>0 && $1!~/^TOTAL/{printf " %s=%s", $1, $2} END{print ""}' "$f"
  done
}

links() {
  for s in $(gpu_paths); do
    echo "== $s  $(lspci -s "$s" 2>/dev/null | cut -d' ' -f2- | cut -c1-60)"
    lspci -s "$s" -vv 2>/dev/null | grep -E 'LnkCap:|LnkSta:|LnkCtl:.*ASPM' | sed 's/^/   /'
  done
}

{
  echo "=== $LABEL  $(date -Is)"
  echo "boot    $(cat /proc/sys/kernel/random/boot_id)  up $(cut -d. -f1 /proc/uptime)s"
  echo "memory  $(dmidecode -t memory 2>/dev/null | awk -F': ' '/Configured Memory Speed/{print $2}' | sort | uniq -c | tr '\n' ' ')"
  echo
  echo "--- corrected / nonfatal / fatal counters (nonzero devices only) ---"
  counters
  echo
  echo "--- link state (idle) ---"
  links
  if [ -n "$LOAD" ]; then
    echo
    echo "--- link state under load: $LOAD ---"
    # the load's pid is recorded at spawn; nothing here is found by pattern
    bash -c "$LOAD" >"$OUT/aer-$LABEL.load.log" 2>&1 &
    lpid=$!
    for i in 1 2 3 4 5; do
      kill -0 "$lpid" 2>/dev/null || break
      sleep 2
      echo "   t+$((i*2))s"; links | sed 's/^/   /'
    done
    wait "$lpid"; echo "   load rc $?"
    echo
    echo "--- counters after load ---"
    counters
  fi
} > "$F" 2>&1

echo "wrote $F"
sed -n '/--- corrected/,/--- link state (idle)/p' "$F"
