#!/bin/bash
# gpu-ddp-round-steps.sh — sample the training step counter once a second.
#
# The arm script measures throughput at its midpoint and at its end, which is the right
# design for a run that finishes. Both DDP attempts on this machine died inside the
# three-minute warm-up, so neither produced a single number: the speedup this
# configuration is supposed to buy has never been measured here. A one-second sampler
# gets a rate out of however long the run survives.
set -u
TLOG=${1:?training log}; SECS=${2:-1800}
end=$(( $(date +%s) + SECS ))
echo "epoch,steps"
while [ "$(date +%s)" -lt $end ]; do
  s=$(tail -c 8000 "$TLOG" 2>/dev/null | tr '\r' '\n' | grep -o 'steps=[0-9]*' | tail -1 | cut -d= -f2)
  echo "$(date +%s.%N),${s}"
  sleep 1
done
