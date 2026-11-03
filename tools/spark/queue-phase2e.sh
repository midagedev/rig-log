#!/bin/bash
# Atlas's width-one MTP window under nsys, again, 2026-11-04. The first try (queue-phase2.sh) ran beside a source
# build, because that queue read the first BUILD_DONE line of a log that held an earlier failed run, and take.sh's
# watchdog killed Atlas at MemAvailable 2.7 GB during its load. Now after queue-phase2d.sh's PHASE2B_DONE, alone, and
# with --gpu-memory-utilization 0.80 instead of the recipe's 0.88 to leave room for nsys's buffers (the KV pool is
# smaller; the kernels a 128-token decode runs are the same). The second try (queue-phase2c.sh) loaded but its
# warm-up was refused: Atlas wants a "model" field, which the probe now sends. Sentinel PHASE2E_DONE.
export HOME=/root
cd /root/health || exit 1
say(){ echo "$(date -u +%TZ) $*"; }
until grep -q PHASE2D_DONE phase2d.log 2>/dev/null; do sleep 30; done
NS=/opt/nvidia/nsight-systems/2025.3.2; NV=/models/Qwen3.6-35B-A3B-NVFP4; C=spark-take-atlas; P=18735
nvrec="--gpu-memory-utilization 0.80 --max-seq-len 262144 --kv-cache-dtype fp8 --kv-high-precision-layers auto --tool-call-parser qwen3_coder --disable-tool-grammar true --fp8-kv-calibration-tokens 256 --scheduling-policy slai --ssm-cache-slots 128 --ssm-checkpoint-interval 32 --mtp-quantization bf16 --enable-prefix-caching --disable-thinking"
for row in rec nomtp; do
  T=nsys-decode-q36-atlas-nvfp4-$row-3; mkdir -p /root/takes/$T
  extra=""; [ $row = rec ] && extra="--num-drafts 1 --speculative"
  S="docker run --entrypoint '' --gpus all --ipc=host --shm-size=32gb --network=host --user 0:0 --security-opt no-new-privileges --security-opt seccomp=unconfined --cap-add=IPC_LOCK --cap-add=SYS_NICE --ulimit memlock=-1:-1 --ulimit stack=67108864 --rm --name $C -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -v /models:/models -v $NS:/nsys -v /root/takes/$T:/out avarok/atlas-gb10:dev /nsys/target-linux-sbsa-armv8/nsys launch --trace=cuda --cuda-graph-trace=node --session-new=atlas spark serve $NV --port $P --host 127.0.0.1 $nvrec $extra"
  say "start $T"
  PROBE=/root/health/atlas-nsys-probe.sh SERVE="$S" PORT=$P CONTAINER=$C LOAD_TIMEOUT=1800 ENGINE="Atlas (avarok/atlas-gb10:dev) under nsys" ./take.sh $T
done
echo PHASE2E_DONE
