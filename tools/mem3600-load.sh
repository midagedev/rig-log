#!/usr/bin/env bash
# DDR4-3600 + the moved A6000: does the link stay clean under the load that used to break it?
# Same hammer as 2026-09-16 (two ranks, 256 MB all-reduce, NCCL staged through host memory),
# now with GPU temperature and the throttle COUNTERS sampled alongside -- the flags are
# duty-cycled and a single sample of one says nothing.
set -u
SECS=${SECS:-480}
OUT=/home/user/mem3600-$(date +%H%M%S); mkdir -p "$OUT"

. /home/user/gpu-order.env   # A6000_UUID; nvidia-smi ignores CUDA_VISIBLE_DEVICES, so sample by UUID
ports() {   # every NVIDIA function and the bridge above it, discovered, never hardcoded
  for d in /sys/bus/pci/devices/*; do
    [ -e "$d/vendor" ] || continue
    [ "$(cat "$d/vendor")" = "0x10de" ] || continue
    echo "${d##*/}"
    up=$(readlink -f "$d/.."); up=${up##*/}
    case "$up" in [0-9a-f]*:*) echo "$up" ;; esac
  done | sort -u
}
cor() { for f in /sys/bus/pci/devices/*/aer_dev_correctable; do
          awk '/TOTAL_ERR_COR/{s+=$2} END{print s+0}' "$f"; done | paste -sd+ | bc; }
ctr() { nvidia-smi -i "$A6000_UUID" -q -d PERFORMANCE | grep -A8 "Clocks Event Reasons Counters" \
        | grep "$1" | grep -oE '[0-9]+'; }

echo "ports:"; ports | tr '\n' ' '; echo
echo "memory: $(dmidecode -t memory | grep -m1 'Configured Memory Speed')  VDDIO: $(ipmitool sdr type voltage 2>/dev/null | awk -F'|' '/VDDIO_ABCD/{print $5}')"
C0=$(cor); T0=$(ctr "SW Thermal Slowdown"); P0=$(ctr "SW Power Capping")
echo "before: corrected=$C0"

setsid env SECS="$SECS" /webuta/venv/bin/torchrun --nproc_per_node=2 \
  --master_port=29577 /root/nccl-hammer.py > "$OUT/hammer.log" 2>&1 &
PG=$!; echo "$PG" > "$OUT/hammer.pid"; echo "hammer pgid $PG"

end=$((SECONDS+SECS+90))
while kill -0 "$PG" 2>/dev/null && [ $SECONDS -lt $end ]; do
  sleep 20
  lnk=$(nvidia-smi --query-gpu=index,pcie.link.gen.current,pcie.link.width.current --format=csv,noheader | tr '\n' ';')
  tmp=$(nvidia-smi --query-gpu=index,temperature.gpu,power.draw,clocks.sm --format=csv,noheader | tr '\n' ';')
  slot=$(ipmitool sdr type temperature 2>/dev/null | awk -F'|' '/PCIE0[15] Temp/{gsub(/ /,"",$1); gsub(/degrees C/,"",$5); print $1"="$5}' | tr '\n' ' ')
  xid=$(journalctl -k -b 0 --since "-25s" --no-pager | grep -c Xid)
  echo "$(date +%H:%M:%S) cor=$(cor) xid=$xid | $lnk | $tmp | $slot"
done
kill -0 "$PG" 2>/dev/null && { echo "deadline, stopping pgid $PG"; kill -TERM -"$PG" 2>/dev/null; }
wait "$PG" 2>/dev/null

C1=$(cor); T1=$(ctr "SW Thermal Slowdown"); P1=$(ctr "SW Power Capping")
echo
echo "RESULT over ${SECS}s at DDR4-3600, A6000 in the moved slot:"
echo "  corrected errors: $((C1-C0))   (the old slot produced 27 in 483 s of the same load)"
echo "  SW thermal slowdown: $(( (T1-T0)/1000000 ))s of ${SECS}s"
echo "  SW power capping:    $(( (P1-P0)/1000000 ))s of ${SECS}s"
echo "  Xid lines this boot: $(journalctl -k -b 0 --no-pager | grep -c Xid)"
tail -3 "$OUT/hammer.log"
echo "MEM3600_DONE"
