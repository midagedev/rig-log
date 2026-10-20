#!/usr/bin/env bash
# Generate under a 40-minute bound on one card, write OUTDIR.rc. On the RTX 3090 the run holds the card's gate lock
# for its whole length (gates queue behind it) and counts Xid lines in the kernel log before and after: a new one
# ends the run with 70 (the card has fallen off the bus under load before).
# Installed beside 0.3.4's scripts as gen036.py, run036.sh and prompts036.json (034's stay as they are).
# Usage: bash /root/musicgen/run036.sh <A6000|3090> <run name> [gen.py flags…]
set -uo pipefail
R=/root/musicgen; CARD=${1:?card}; RUN=${2:?run name}; shift 2
OUT=$R/out/$RUN; mkdir -p $OUT; rm -f $OUT.rc
idx=$(nvidia-smi --query-gpu=index,name --format=csv,noheader | awk -F', ' -v c="$CARD" '$2 ~ c {print $1}')
[ -n "$idx" ] || { echo "run.sh: no RTX $CARD" >&2; echo 69 > $OUT.rc; exit 69; }
case $CARD in
  3090) LOCK=/root/bloomery-gate.lock ;;
  A6000) LOCK=/root/bloomery-gate-a6000.lock ;;
  *) echo "run.sh: card $CARD is neither A6000 nor 3090" >&2; echo 64 > $OUT.rc; exit 64 ;;
esac
xid0=$(dmesg | grep -c Xid)
exec 8>>$LOCK
flock 8
echo "run.sh: $LOCK held, Xid lines before: $xid0"
export CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=$idx HF_HOME=$R/hf HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false
nvidia-smi --query-gpu=index,name,memory.used,power.limit --format=csv,noheader -i $idx
cd $R/src
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader -i $idx -l 5 > $OUT/smi.log 2>&1 &
smi=$!
timeout --kill-after=10 2400 .venv/bin/python $R/gen036.py $OUT --card $CARD --prompts prompts036.json "$@"
rc=$?
kill $smi 2>/dev/null
xid1=$(dmesg | grep -c Xid)
echo "run.sh: Xid lines after: $xid1"
[ "$xid1" -gt "$xid0" ] && { echo "run.sh: new Xid line(s) during the run" >&2; rc=70; }
echo $rc > $OUT.rc
exit $rc
