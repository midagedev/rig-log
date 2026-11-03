#!/bin/bash
# Phase 2 of the night, 2026-11-04: the proposals measured on bloomery built from source (bloomery-build.sh, scratch
# clones of v0.3.12 a44384d2, never pushed) and Atlas's width-one MTP window under nsys. In order, nothing beside a
# build or a take:
#   1. wait for the w5 build (DELTA_VERIFY_ROWS 4 -> 6: Qwen3.8's verify and so its MTP width up to 5)
#   2. Atlas nvfp4 rec and nomtp under nsys (atlas-nsys-probe.sh, one prose decode of 128 tokens each)
#   3. the w5 binary: Qwen3.8 FP4-Local rec row (code, prose, pp512, pp4096)
#   4. build s512 (MTP_STORE_ROWS 64 -> 512), then its rec row: pp4096 for the store walk, and its decode as our own
#      build's baseline at DELTA_VERIFY_ROWS 4
# Sentinel PHASE2_DONE.
export HOME=/root
cd /root/health || exit 1
say(){ echo "$(date -u +%TZ) $*"; }
until grep -q "^BUILD_DONE" build-w5.log 2>/dev/null; do sleep 30; done
say "w5 $(grep '^BUILD_DONE' build-w5.log | tail -1)"
NS=/opt/nvidia/nsight-systems/2025.3.2; NV=/models/Qwen3.6-35B-A3B-NVFP4; C=spark-take-atlas; P=18735
nvrec="--gpu-memory-utilization 0.88 --max-seq-len 262144 --kv-cache-dtype fp8 --kv-high-precision-layers auto --tool-call-parser qwen3_coder --disable-tool-grammar true --fp8-kv-calibration-tokens 256 --scheduling-policy slai --ssm-cache-slots 128 --ssm-checkpoint-interval 32 --mtp-quantization bf16 --enable-prefix-caching --disable-thinking"
for row in rec nomtp; do
  T=nsys-decode-q36-atlas-nvfp4-$row; mkdir -p /root/takes/$T
  extra=""; [ $row = rec ] && extra="--num-drafts 1 --speculative"
  S="docker run --entrypoint '' --gpus all --ipc=host --shm-size=32gb --network=host --user 0:0 --security-opt no-new-privileges --security-opt seccomp=unconfined --cap-add=IPC_LOCK --cap-add=SYS_NICE --ulimit memlock=-1:-1 --ulimit stack=67108864 --rm --name $C -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -v /models:/models -v $NS:/nsys -v /root/takes/$T:/out avarok/atlas-gb10:dev /nsys/target-linux-sbsa-armv8/nsys launch --trace=cuda --cuda-graph-trace=node --session-new=atlas spark serve $NV --port $P --host 127.0.0.1 $nvrec $extra"
  say "start $T"
  PROBE=/root/health/atlas-nsys-probe.sh SERVE="$S" PORT=$P CONTAINER=$C LOAD_TIMEOUT=1800 ENGINE="Atlas (avarok/atlas-gb10:dev) under nsys" ./take.sh $T
done
M=/models/Qwen3.8-Flash-Next-FP4-Local
row(){ # <binary> <tag>
  SERVE="BLOOMERY_DRAFT=mtp BLOOMERY_MTP_WIDTH=cost BLOOMERY_HOST_ROOM=96G $1 -m $M --host 127.0.0.1 --port 18731 --parallel 1 --ctx-size 16896" \
    PORT=18731 ENGINE="bloomery 0.3.12 source build ($2)" ./take.sh "$2"; }
if grep -q "^BUILD_DONE rc=0" build-w5.log; then say "start w5 row"; row /opt/build/out-w5/bloomery-serve q38-fp4-local-bloomery-src-w5-rec; fi
say "start s512 build"
./bloomery-build.sh /opt/build/scratch-s512 /opt/build/out-s512 >> build-s512.log 2>&1
say "s512 $(grep '^BUILD_DONE' build-s512.log | tail -1)"
if grep -q "^BUILD_DONE rc=0" build-s512.log; then say "start s512 row"; row /opt/build/out-s512/bloomery-serve q38-fp4-local-bloomery-src-s512-rec; fi
echo PHASE2_DONE
