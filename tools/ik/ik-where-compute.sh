#!/bin/bash
# ik-where-compute.sh — does an offloaded ik expert matmul run on the CPU or on the GPU?
#
# A buffer type name does not answer this. `CUDA_Host` is pinned host memory, which says where the
# weights live, not where ggml schedules the MUL_MAT_ID. Measured 2026-09-17, after an entry was
# pushed claiming "ik never moves the math" on the strength of that name plus a PCIe arithmetic that
# needed a fourfold overlap it cannot have: the eight routed experts are not known until the router
# runs in that same layer, and every later layer depends on it, so there is nothing for the transfer
# to hide behind. Two competing arithmetics fit the measured 0.20 ms per offloaded layer per token:
#
#   19.7 MB over PCIe 4.0 x16 at 25 GB/s   = 0.79 ms   (needs 4x overlap)
#   19.7 MB from DDR4-3600 at 147.7 GB/s   = 0.13 ms   (needs nothing)
#
# So ask the process. cores busy = delta(utime+stime) / (wall * 100) over a decode window: about one
# core is the serving thread, twenty-odd is an expert matmul on the host. GPU utilisation is sampled
# beside it, because a host matmul leaves the card idle while it waits.
#
#   ik-where-compute.sh              # ik, L0 and L10, one lease each, through the usual take runner
#   ENGINE=mrs LEVELS="0 1" ik-where-compute.sh   # the same question of mistral.rs, whose -n moves
#                                                 # the layer to the CPU device explicitly
set -u
M=${M:-/models/Qwen3.6-35B-A3B/Qwen3.6-35B-A3B-UD-Q6_K.gguf}
LEASE=/home/user/gpu-lease
LEVELS=${LEVELS:-"0 10"}
ENGINE=${ENGINE:-ik}
NBLOCKS=${NBLOCKS:-40}
mkdir -p /home/user/offload
for L in $LEVELS; do
  for i in $(seq 180); do [ -f $LEASE ] || break; sleep 5; done
  tag=where-$ENGINE-L$L; LOG=/home/user/offload/$tag.log
  case $ENGINE in
    ik)  [ "$L" -eq 0 ] && XTRA="" || XTRA="-ncmoe $L"; OUT=/home/user/ik-vram/$tag ;;
    mrs) XTRA="-n 0:$((NBLOCKS - L))";                  OUT=/home/user/mrs-take/$tag ;;
    *)   echo "refused: ENGINE must be ik or mrs"; exit 1 ;;
  esac
  echo "$(date +%H:%M:%S) --- $tag  flags '$XTRA'"
  rm -f $OUT/server.pid
  case $ENGINE in
    ik)  env M="$M" CTX=8192 SESSIONS=1 NPRED=${NPRED:-3072} FOR=${FOR:-300s} EXTRA_FLAGS="-np 1 $XTRA" \
             PROMPT_FILES=/home/user/hero5/hl1.txt \
             NOTE="where does the offloaded expert matmul run" \
             /home/user/ik-vram-take.sh $tag > $LOG 2>&1 & ;;
    mrs) env M="$M" MRS=${MRS:-/home/user/mistral.rs/target/release/mistralrs} \
             CTX=8192 MAXSEQS=1 SESSIONS=1 NPRED=${NPRED:-3072} FOR=${FOR:-300s} MRS_EXTRA="$XTRA" \
             PROMPT_FILES=/home/user/hero5/hl1.txt \
             NOTE="where does the offloaded expert matmul run" \
             /home/user/mrs-take.sh $tag > $LOG 2>&1 & ;;
  esac
  RUNNER=$!
  # The pid the runner recorded at spawn is the only one this script ever reads, and it only reads.
  SP=""
  for i in $(seq 240); do
    [ -f $OUT/server.pid ] && SP=$(cat $OUT/server.pid) && break
    kill -0 $RUNNER 2>/dev/null || break
    sleep 1
  done
  if [ -z "$SP" ]; then echo "    no server pid recorded; skipping"; wait $RUNNER; continue; fi
  # sample only once tokens are actually flowing, so the window is decode and not model load
  for i in $(seq 300); do grep -q "tok/s" $LOG 2>/dev/null && break; sleep 1; done
  read -r _ _ _ _ _ _ _ _ _ _ _ _ _ u0 s0 _ < /proc/$SP/stat
  t0=$(date +%s.%N); gsum=0; gn=0
  for i in $(seq 48); do
    g=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits | head -1)
    gsum=$((gsum + g)); gn=$((gn + 1)); sleep 0.25
  done
  t1=$(date +%s.%N)
  # A row is only valid if the server outlived the window; otherwise the sample is of nothing.
  if [ ! -r /proc/$SP/stat ]; then
    echo "    INVALID: server $SP exited during the sampling window, no row"
    wait $RUNNER; continue
  fi
  read -r _ _ _ _ _ _ _ _ _ _ _ _ _ u1 s1 _ < /proc/$SP/stat
  CORES=$(python3 -c "print(f'{(($u1+$s1)-($u0+$s0))/100.0/($t1-$t0):.1f}')")
  GPU=$(python3 -c "print(f'{$gsum/$gn:.0f}')")
  WALL=$(python3 -c "print(f'{$t1-$t0:.1f}')")
  echo "    window ${WALL} s   cores busy ${CORES}   mean GPU util ${GPU} %"
  wait $RUNNER
  echo "    $(grep -aoE "Decode +[0-9.]+ tok/s" $LOG | head -1)"
done
echo WHERE_DONE
