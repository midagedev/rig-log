#!/bin/bash
# ltx-chain-s.sh — is a denoise step compute-bound or bandwidth-bound? Two locked axes.
#
# README queue question #1, and the question every "which GPU" answer rests on. The
# LLM answer on this same card is already in hand and is the bandwidth-bound shape:
# 281 W -> 141 tok/s, 150 W -> 120, so 47 % less power cost 15 % of the rate, which
# is rate proportional to about P^0.26.
#
# A power sweep cannot answer it here. At the default 300 W an LTX-2.5 denoise runs
# with SwPowerCap AND SwThermal both active at 87-88 C, so the cap moves two things.
# Locking one clock moves one thing, and the two locks are orthogonal:
#
#   graphics axis   gr in {1500,1200,900,600}, memory at 7601 — its achieved clock under
#                   load, measured; 8001 is a boost state the card does not hold, so a
#                   row labelled 8001 would duplicate the default one
#   memory axis     mem in {7601,5001,810}, graphics locked at 1200 so the power cap
#                   cannot make the achieved graphics clock a function of the memory one
#
# 1500 is the top of the graphics axis on purpose: the unlocked run achieved 1530 MHz
# mean in the stage-2 window, so a lock above that would be overridden and two rows
# would sit at the same achieved clock under different labels.
#
# offload=none throughout, so the transformer is resident and PCIe streaming is not in
# the loop: this chain prices the card, not the bus.
#
# The metric is stage-2 s/step (1536x1024, 121 frames, 3 steps), stage 1 beside it.
# Wall time is not the metric: 40 s of VAE decode and 18 s of transformer building are
# 43 % of the unlocked run and are not the denoising loop.
set -u
STAMP=$(date +%H%M%S)
LOG=/home/user/ltx-runs/f6-chain-s-$STAMP.txt
mkdir -p /home/user/ltx-runs
say(){ echo "$(date +%T) $*" | tee -a $LOG; }
# bash reads a script incrementally, so overwriting a runner while it is executing can
# resume inside a statement. Measured 2026-09-16: an scp during one arm killed it at
# line 88 and its stale lease then refused the next arm. A chain therefore runs its own
# snapshot of every script it calls, and a push mid-chain reaches only the next chain.
SNAP=/home/user/ltx-snap-$STAMP; mkdir -p $SNAP
for f in ltx-take.sh ltx-run-inner.sh gpu-clock-lock.sh; do
  cp /home/user/$f $SNAP/$f || { echo "cannot snapshot $f"; exit 1; }
done
chmod +x $SNAP/*.sh
sed -i "s|/home/user/ltx-run-inner.sh|$SNAP/ltx-run-inner.sh|" $SNAP/ltx-take.sh
. /home/user/gpu-order.env
cool(){ local t
  for i in $(seq 90); do
    t=$(nvidia-smi -i "$A6000_UUID" --query-gpu=temperature.gpu --format=csv,noheader,nounits)
    [ "$t" -le "${COOL_TO:-55}" ] && break
    sleep 10
  done
  say "cooled to ${t} C"; }
row(){ local gr=$1 mem=$2 tag="s-gr$1-mem$2"
  say "=== $tag"
  cool
  bash $SNAP/gpu-clock-lock.sh "$gr" "$mem" -- \
    env OFFLOAD=none FRAMES=${FRAMES:-121} bash $SNAP/ltx-take.sh "$tag" 2>&1 | tee -a $LOG | tail -4
}
say "chain-s start; A6000 $(nvidia-smi -i $A6000_UUID --query-gpu=temperature.gpu,power.limit,clocks.max.gr,clocks.max.mem --format=csv,noheader)"
row 1500 7601
row 1200 7601
row  900 7601
row  600 7601
row 1200 5001
row 1200  810
say "chain-s done; A6000 max clocks back to $(nvidia-smi -i $A6000_UUID --query-gpu=clocks.max.gr,clocks.max.mem --format=csv,noheader)"
echo CHAIN_S_DONE
