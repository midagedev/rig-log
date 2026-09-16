#!/bin/bash
# ltx-chain-a.sh — what the offload path costs, four arms, one knob each.
#
# Same seed, same prompt, same frame count: the only thing that moves is where the
# 42 GB transformer lives while it runs. `none` is expected to fail on a 48 GB card
# and that failure is a row, not an accident.
#
# Cooldown between arms is not politeness. This card sits at 86-87 C with
# SW Thermal Slowdown pinned under a sustained load and no chassis fan is on a
# header, so an arm that starts hot is measuring the previous arm.
set -u
LOG=/home/user/ltx-runs/chain-a.txt
mkdir -p /home/user/ltx-runs
say(){ echo "$(date +%T) $*" | tee -a $LOG; }
cool(){ local t
  for i in $(seq 90); do
    t=$(nvidia-smi -i "$A6000_UUID" --query-gpu=temperature.gpu --format=csv,noheader,nounits)
    [ "$t" -le "${COOL_TO:-55}" ] && break
    sleep 10
  done
  say "cooled to ${t} C after $((i*10)) s"; }
. /home/user/gpu-order.env
run(){ local tag=$1; shift
  say "=== $tag  ($*)"
  cool
  env "$@" bash /home/user/ltx-take.sh "$tag" 2>&1 | tee -a $LOG | tail -1
}
say "chain-a start; A6000 $(nvidia-smi -i $A6000_UUID --query-gpu=temperature.gpu,power.limit --format=csv,noheader)"
run a1-offload-none OFFLOAD=none
run a2-offload-cpu  OFFLOAD=cpu
run a3-offload-disk OFFLOAD=disk
run a4-cpu-mbs2     OFFLOAD=cpu MBS=2
say "chain-a done"
echo CHAIN_A_DONE
