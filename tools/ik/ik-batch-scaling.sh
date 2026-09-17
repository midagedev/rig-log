#!/bin/bash
# ik-batch-scaling.sh <tag> — does ik_llama.cpp's decode get faster when a step carries more tokens?
#
# Measured 2026-09-17: on this card ik_llama.cpp gains nothing from concurrent streams on a MoE model
# (DeepSeek-V2-Lite Q3_K_M: 196.8 tok/s at one stream, 150.2 aggregate at two, 201.8 at four) while it
# scales normally on a dense one (Qwen2.5-7B Q3_K_M: 117 → 164 → 196) and mistral.rs scales on the same
# MoE model (105 → 184 → 279 → 324). Two candidate causes were tested and both are out: CUDA graphs
# (`GGML_CUDA_DISABLE_GRAPHS=1` costs 7 % at one stream and the collapse survives) and the fused-MoE
# path (`-no-fmoe` is worse at every stream count).
#
# What is left is the decode step itself, and the server is in the way of seeing it: a take through
# `llama-server` mixes the kernel path with slot scheduling, continuous batching and the KV layout.
# `llama-batched-bench` runs the same decode with N sequences in one process and no server at all, so
# this is the smaller experiment: if the batch=1 → batch=2 curve is flat here too, the cost is in the
# decode path and this command is the reproducer to send upstream; if it scales here, the cost is in
# the server and the reproducer is a four-slot take.
#
# Same gates as the take runners: model present, GPUs idle, lease free, before 23:30 KST.
# Sentinel IK_BATCH_DONE / _FAILED.
#
#   M=/models/small/DeepSeek-V2-Lite-Chat.Q3_K_M.gguf ik-batch-scaling.sh dsv2lite
#   M=… NPL=1,2,4,8 NTG=128 NPP=238 ik-batch-scaling.sh qwen36
set -u
TAG=${1:?tag required}; OUT=/home/user/ik-batch/$TAG; LEASE=/home/user/gpu-lease
TREE=${TREE:-/home/user/ik_llama.cpp}; BIN=$TREE/build/bin/llama-batched-bench
M=${M:?model path required}
NPP=${NPP:-238}; NTG=${NTG:-256}; NPL=${NPL:-1,2,4,8}; CTX=${CTX:-32768}
mkdir -p $OUT
say(){ echo "$(date +%H:%M:%S) $*"; }
gpus(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr '\n' ' '; }
maxgpu(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1; }
SENT=IK_BATCH; LEASE_TAG="ikbatch-$TAG"
finish(){ rc=$1
  for i in $(seq 45); do [ "$(maxgpu)" -lt 2000 ] && break; sleep 2; done
  say "gpus after: $(gpus)"
  [ -f $LEASE ] && grep -q "^$LEASE_TAG " $LEASE && rm -f $LEASE && say "lease released"
  [ $rc -eq 0 ] && echo ${SENT}_DONE || echo ${SENT}_FAILED
  exit $rc; }
[ -f "$M" ] || { say "refused: no model at $M"; echo ${SENT}_FAILED; exit 1; }
[ -x "$BIN" ] || { say "refused: no llama-batched-bench at $BIN"; echo ${SENT}_FAILED; exit 1; }
[ "$(date +%H%M)" -lt 2330 ] || { say "refused: after 23:30 KST"; echo ${SENT}_FAILED; exit 1; }
[ "$(maxgpu)" -lt 2000 ] || { say "refused: GPUs busy: $(gpus)"; echo ${SENT}_FAILED; exit 1; }
[ -f $LEASE ] && { say "refused: lease held: $(cat $LEASE)"; echo ${SENT}_FAILED; exit 1; }
echo "$LEASE_TAG $$ $(date +%FT%T)" > $LEASE
say "launch env: M=$M NPP=$NPP NTG=$NTG NPL=$NPL CTX=$CTX EXTRA=${EXTRA:-} GGML_CUDA_DISABLE_GRAPHS=${GGML_CUDA_DISABLE_GRAPHS:-unset}"
say "$TAG at $(cd $TREE && git log -1 --format='%h' 2>/dev/null); io avg10 $(awk '/some/{print $2}' /proc/pressure/io); gpus before: $(gpus)"

. /home/user/gpu-order.env
CUDA_VISIBLE_DEVICES=${CVD:-$A6000_UUID} $BIN -m "$M" -c $CTX -ngl 99 -fa on -t ${THREADS:-32} \
  -b 2048 -ub ${UB:-512} -npp $NPP -ntg $NTG -npl $NPL ${EXTRA:-} > $OUT/bench.txt 2>&1
rc=$?
say "batched-bench rc $rc; the table it printed:"
sed -n '/PP.*TG.*B.*S_PP/,$p' $OUT/bench.txt | head -20 | sed 's/^/    /'
[ $rc -eq 0 ] || tail -12 $OUT/bench.txt | sed 's/^/    /'
finish $rc
