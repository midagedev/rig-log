#!/usr/bin/env bash
# sample the fabric while something else loads it. one line per tick:
# total corrected errors across every device, the four GPU link speeds, and
# any Xid the driver logged since the previous tick.
set -u
TICKS=${TICKS:-40}
EVERY=${EVERY:-20}

# every NVIDIA function and the bridge above it, discovered rather than
# hardcoded -- a card that moves slot changes both its address and its port,
# and a sampler watching the old ones reports silence instead of an error
gpu_ports() {
  for d in /sys/bus/pci/devices/*; do
    [ -e "$d/vendor" ] || continue
    [ "$(cat "$d/vendor")" = "0x10de" ] || continue
    dd=${d##*/}; echo "${dd#0000:}"
    up=$(readlink -f "$d/.."); up=${up##*/}
    case "$up" in [0-9a-f]*:*) echo "${up#0000:}" ;; esac
  done | sort -u
}
for i in $(seq 1 "$TICKS"); do
  cor=0
  for f in /sys/bus/pci/devices/*/aer_dev_correctable; do
    n=$(awk '$1=="TOTAL_ERR_COR"{print $2}' "$f" 2>/dev/null)
    cor=$((cor + ${n:-0}))
  done
  spd=""
  for s in $(gpu_ports); do
    v=$(lspci -s "$s" -vv 2>/dev/null | awk -F'Speed ' '/LnkSta:/{split($2,a,","); print a[1]}')
    spd="$spd ${v:-?}"
  done
  xid=$(journalctl -k -b 0 --since "-${EVERY}s" --no-pager 2>/dev/null | grep -c Xid)
  printf '%s corrected=%s links=%s xid=%s\n' "$(date +%H:%M:%S)" "$cor" "$spd" "$xid"
  sleep "$EVERY"
done
