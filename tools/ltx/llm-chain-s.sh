#!/bin/bash
# llm-chain-s.sh — the other half of the chart: the same two locked axes, on an LLM.
#
# A diffusion sweep alone says how a denoise step responds to clocks. It becomes an
# answer to "which card" only beside the same sweep on the workload this box already
# serves, taken on the same card with the same instrument on the same afternoon.
#
# Qwen3.6-35B-A3B at UD-Q4_K_XL, resident on the A6000 alone, no draft, no -ot: the
# configuration that measured 140 tok/s on 2026-09-15 and whose ceiling was a flat
# ~390 GB/s, half the card's 768. That flat ceiling is the second question this chain
# answers. 5001 MHz memory is 480 GB/s theoretical, still above 390: if decode drops
# there anyway the ceiling is coupled to the memory clock after all, and if it does not,
# it never was — and a card with more bandwidth would not deliver it either.
#
# Same points as ltx-chain-s.sh so the two tables can sit side by side.
set -u
STAMP=$(date +%H%M%S)
LOG=/home/user/ik-vram/f6-llm-chain-s-$STAMP.txt
mkdir -p /home/user/ik-vram
say(){ echo "$(date +%T) $*" | tee -a $LOG; }
# a chain runs its own snapshot of what it calls; see the note in ltx-chain-s.sh
SNAP=/home/user/llm-snap-$STAMP; mkdir -p $SNAP
for f in ik-vram-take.sh gpu-clock-lock.sh; do
  cp /home/user/$f $SNAP/$f || { echo "cannot snapshot $f"; exit 1; }
done
chmod +x $SNAP/*.sh
. /home/user/gpu-order.env
export M=${M:-/models/Qwen3.6-35B-A3B/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf}
export TOKTAPE=${TOKTAPE:-/home/user/toktape-0.2.3-5-g9bf4e52}
export PROMPT_FILES=${PROMPT_FILES:-/home/user/s1.txt}
export FOR=${FOR:-30s}
cool(){ local t
  for i in $(seq 90); do
    t=$(nvidia-smi -i "$A6000_UUID" --query-gpu=temperature.gpu --format=csv,noheader,nounits)
    [ "$t" -le "${COOL_TO:-55}" ] && break
    sleep 10
  done
  say "cooled to ${t} C"; }
row(){ local gr=$1 mem=$2 tag="l-gr$1-mem$2"
  say "=== $tag"
  cool
  NOTE="clock-locked gr=$gr mem=$mem" bash $SNAP/gpu-clock-lock.sh "$gr" "$mem" -- \
    bash $SNAP/ik-vram-take.sh "$tag" 2>&1 | tee -a $LOG | grep -E "Decode|achieved|lock held|LOCK NOT|_DONE|_FAILED"
}
say "llm-chain-s start on $(basename $M); A6000 $(nvidia-smi -i $A6000_UUID --query-gpu=temperature.gpu,power.limit --format=csv,noheader)"
row 1500 7601
row 1200 7601
row  900 7601
row  600 7601
row 1200 5001
row 1200  810
say "llm-chain-s done; A6000 max clocks back to $(nvidia-smi -i $A6000_UUID --query-gpu=clocks.max.gr,clocks.max.mem --format=csv,noheader)"
echo LLM_CHAIN_S_DONE
