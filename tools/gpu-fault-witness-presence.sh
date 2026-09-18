#!/bin/bash
# presence-loop.sh — how many cards the driver can still enumerate, and when that changed.
# `nvidia-smi -L` costs 30-40 ms on this box, so this is a far finer clock than the
# driver's own detection, which the source says is a 1 Hz poll plus an opportunistic
# check on any register read that comes back all-ones.
set -u
OUT=${1:?}; SECS=${2:-1200}
end=$(( $(date +%s) + SECS ))
echo "epoch,n_gpus,ms"
base=""
while [ "$(date +%s)" -lt $end ]; do
  t0=$(date +%s%3N)
  n=$(timeout 4 nvidia-smi -L 2>/dev/null | grep -c '^GPU')
  t1=$(date +%s%3N)
  echo "$(date +%s.%N),${n},$((t1-t0))"
  [ -z "$base" ] && base=$n
  if [ "$n" -lt "$base" ] && [ ! -f "$OUT/FAULT" ]; then
    date +%s.%N > "$OUT/FAULT"
    echo "card count $base -> $n" >> "$OUT/FAULT"
  fi
done
