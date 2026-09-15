#!/usr/bin/env bash
# Force one PCIe port's maximum link speed and retrain, then put it back.
#
# The port's Link Control 2 register holds a Target Link Speed field; the
# link renegotiates to at most that when the Retrain bit in Link Control is
# set. Lowering it is the no-hands half of a signal-integrity test: if a link
# that logs BadTLP at 16 GT/s stops at 8, the errors are margin rather than
# damage, and the lower speed is also a mitigation you can live on.
#
# The speed is machine state, so it is restored on every exit path including
# a signal -- the same rule tools/ik/gpu-power-sweep.sh follows for the board
# power cap.
#
#   pcie-force-speed.sh 00:03.1 3        # cap at 8 GT/s (Gen3)
#   pcie-force-speed.sh 00:03.1 3 'cmd'  # ... run cmd under it, then restore
#
# Target Link Speed encodings: 1 = 2.5, 2 = 5, 3 = 8, 4 = 16 GT/s.
set -u
PORT=${1:?pci address required, e.g. 00:03.1}
WANT=${2:?target link speed code required (1=2.5 2=5 3=8 4=16)}
LOAD=${3:-}

sta()  { lspci -s "$PORT" -vv 2>/dev/null | awk -F'Speed ' '/LnkSta:/{split($2,a,","); print a[1]}'; }
tgt()  { printf '%d\n' $(( 0x$(setpci -s "$PORT" CAP_EXP+30.w) & 0xf )); }
cor()  { for f in /sys/bus/pci/devices/*/aer_dev_correctable; do
           awk '$1=="TOTAL_ERR_COR"{print $2}' "$f" 2>/dev/null; done |
         awk '{s+=$1} END{print s+0}'; }

ORIG=$(tgt)
restore() {
  setpci -s "$PORT" CAP_EXP+30.w="000$ORIG":000f
  setpci -s "$PORT" CAP_EXP+10.w=0020:0020
  sleep 2
  echo "restored target=$(tgt) LnkSta=$(sta)"
}
trap restore EXIT

echo "before   target=$ORIG  LnkSta=$(sta)  corrected=$(cor)"
setpci -s "$PORT" CAP_EXP+30.w="000$WANT":000f || { echo "could not write LnkCtl2 (root?)"; exit 1; }
setpci -s "$PORT" CAP_EXP+10.w=0020:0020        # Retrain Link
sleep 2
echo "forced   target=$(tgt)  LnkSta=$(sta)  corrected=$(cor)"

if [ -n "$LOAD" ]; then
  C0=$(cor); T0=$(date +%s)
  bash -c "$LOAD" & lpid=$!          # pid recorded at spawn; nothing by pattern
  while kill -0 "$lpid" 2>/dev/null; do
    sleep 20
    echo "  $(date +%H:%M:%S) LnkSta=$(sta) corrected=$(cor)"
  done
  wait "$lpid"; rc=$?
  C1=$(cor); EL=$(( $(date +%s) - T0 ))
  echo "load rc $rc; $((C1-C0)) corrected errors in ${EL}s at target=$(tgt)"
fi
