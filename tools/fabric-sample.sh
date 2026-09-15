#!/usr/bin/env bash
# sample the fabric while something else loads it. one line per tick:
# total corrected errors across every device, the four GPU link speeds, and
# any Xid the driver logged since the previous tick.
set -u
TICKS=${TICKS:-40}
EVERY=${EVERY:-20}
for i in $(seq 1 "$TICKS"); do
  cor=0
  for f in /sys/bus/pci/devices/*/aer_dev_correctable; do
    n=$(awk '$1=="TOTAL_ERR_COR"{print $2}' "$f" 2>/dev/null)
    cor=$((cor + ${n:-0}))
  done
  spd=""
  for s in 00:03.1 01:00.0 40:01.1 41:00.0; do
    v=$(lspci -s "$s" -vv 2>/dev/null | awk -F'Speed ' '/LnkSta:/{split($2,a,","); print a[1]}')
    spd="$spd ${v:-?}"
  done
  xid=$(journalctl -k -b 0 --since "-${EVERY}s" --no-pager 2>/dev/null | grep -c Xid)
  printf '%s corrected=%s links=%s xid=%s\n' "$(date +%H:%M:%S)" "$cor" "$spd" "$xid"
  sleep "$EVERY"
done
