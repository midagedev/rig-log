#!/bin/bash
# Phase 2, last queue, 2026-11-04. queue-phase2d.sh's baseline build died: it started while another build container
# of the same name was still up (rc=125) and was then stopped by hand (rc=137), so only the two patched builds' repeat
# takes ran. Here, alone: build scratch-base (unpatched v0.3.12), take its Qwen3.8 FP4-Local rec row twice, then
# Atlas's width-one MTP window under nsys (model field sent, gpu-memory-utilization 0.80). Sentinel PHASE2F_DONE.
export HOME=/root
cd /root/health || exit 1
say(){ echo "$(date -u +%TZ) $*"; }
docker rm -f spark-bloomery-build >/dev/null 2>&1
./bloomery-build.sh /opt/build/scratch-base /opt/build/out-base > build-base.log 2>&1; say "base $(tail -1 build-base.log)"
M=/models/Qwen3.8-Flash-Next-FP4-Local
for tag in base base-r2; do
  [ -x /opt/build/out-base/bloomery-serve ] || break
  SERVE="BLOOMERY_DRAFT=mtp BLOOMERY_MTP_WIDTH=cost BLOOMERY_HOST_ROOM=96G /opt/build/out-base/bloomery-serve -m $M --host 127.0.0.1 --port 18731 --parallel 1 --ctx-size 16896" \
    PORT=18731 ENGINE="bloomery 0.3.12 source build (base)" ./take.sh q38-fp4-local-bloomery-src-$tag-rec
done
NS=/opt/nvidia/nsight-systems/2025.3.2; NV=/models/Qwen3.6-35B-A3B-NVFP4; C=spark-take-atlas; P=18735
nvrec="--gpu-memory-utilization 0.80 --max-seq-len 262144 --kv-cache-dtype fp8 --kv-high-precision-layers auto --tool-call-parser qwen3_coder --disable-tool-grammar true --fp8-kv-calibration-tokens 256 --scheduling-policy slai --ssm-cache-slots 128 --ssm-checkpoint-interval 32 --mtp-quantization bf16 --enable-prefix-caching --disable-thinking"
for row in rec nomtp; do
  T=nsys-decode-q36-atlas-nvfp4-$row-4; mkdir -p /root/takes/$T
  extra=""; [ $row = rec ] && extra="--num-drafts 1 --speculative"
  S="docker run --entrypoint '' --gpus all --ipc=host --shm-size=32gb --network=host --user 0:0 --security-opt no-new-privileges --security-opt seccomp=unconfined --cap-add=IPC_LOCK --cap-add=SYS_NICE --ulimit memlock=-1:-1 --ulimit stack=67108864 --rm --name $C -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -v /models:/models -v $NS:/nsys -v /root/takes/$T:/out avarok/atlas-gb10:dev /nsys/target-linux-sbsa-armv8/nsys launch --trace=cuda --cuda-graph-trace=node --session-new=atlas spark serve $NV --port $P --host 127.0.0.1 $nvrec $extra"
  say "start $T"
  PROBE=/root/health/atlas-nsys-probe.sh SERVE="$S" PORT=$P CONTAINER=$C LOAD_TIMEOUT=1800 ENGINE="Atlas (avarok/atlas-gb10:dev) under nsys" ./take.sh $T
done
echo PHASE2F_DONE
