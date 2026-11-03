#!/bin/bash
# Atlas rows on board 2 (Qwen3.6-35B-A3B), 2026-11-03. Atlas only on Qwen3.6: its Qwen3.8 recipe needs
# Inferact/Qwen3.8-Flash-Next-NVFP4 (182.8 GB, its own conversion), which does not fit one Spark beside anything
# (user's no, 11-03 22:12 KST). The commands are `atlasctl run <recipe> --port 18735 --print` from atlas-recipes
# 8a101166 (the recipes qwen3.6-35b-a3b-fp8-mtp and qwen3.6-35b-a3b-nvfp4), with four changes: foreground instead of
# -d (take.sh follows the process), our local folder mounted at /models instead of the HF cache, --host 127.0.0.1,
# and no /dev/infiniband (one node). Rows:
#   atlas-fp8-default    `spark serve <FP8 folder>` and nothing else, image :latest
#   atlas-fp8-rec        the fp8-mtp recipe (MTP K from MODEL.toml, bf16 KV, bf16 lm-head, max batch 2)
#   atlas-fp8-nomtp      the recipe without --speculative
#   atlas-nvfp4-rec      the nvfp4 recipe (image :dev, fp8 KV calibrated, MTP K=1 pinned)
#   atlas-nvfp4-nomtp    the recipe without --speculative / --num-drafts
# usage: rows-atlas.sh <row> ...
set -u
F8=/models/Qwen3.6-35B-A3B-FP8; NV=/models/Qwen3.6-35B-A3B-NVFP4; C=spark-take-atlas; P=18735
dk(){ echo "docker run --entrypoint '' --gpus all --ipc=host --shm-size=32gb --network=host --user 0:0 --security-opt no-new-privileges --security-opt seccomp=unconfined --cap-add=IPC_LOCK --cap-add=SYS_NICE --ulimit memlock=-1:-1 --ulimit stack=67108864 --rm --name $C -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -v /models:/models avarok/atlas-gb10:$1 spark serve"; }
f8rec="--gpu-memory-utilization 0.88 --max-seq-len 262144 --kv-cache-dtype bf16 --max-batch-size 2 --kv-high-precision-layers auto --scheduling-policy slai --max-prefill-tokens 32768 --oom-guard-mb 1024 --ssm-cache-slots 256 --mtp-quantization bf16 --enable-prefix-caching --lm-head-dtype bf16"
nvrec="--gpu-memory-utilization 0.88 --max-seq-len 262144 --kv-cache-dtype fp8 --kv-high-precision-layers auto --tool-call-parser qwen3_coder --disable-tool-grammar true --fp8-kv-calibration-tokens 256 --scheduling-policy slai --ssm-cache-slots 128 --ssm-checkpoint-interval 32 --mtp-quantization bf16 --enable-prefix-caching --disable-thinking"
for row in "$@"; do
  case $row in
    atlas-fp8-default) I=latest; S="$(dk latest) $F8 --port $P --host 127.0.0.1";;
    atlas-fp8-rec)     I=latest; S="$(dk latest) $F8 --port $P --host 127.0.0.1 $f8rec --speculative";;
    atlas-fp8-nomtp)   I=latest; S="$(dk latest) $F8 --port $P --host 127.0.0.1 $f8rec";;
    atlas-nvfp4-rec)   I=dev;    S="$(dk dev) $NV --port $P --host 127.0.0.1 $nvrec --num-drafts 1 --speculative";;
    atlas-nvfp4-nomtp) I=dev;    S="$(dk dev) $NV --port $P --host 127.0.0.1 $nvrec";;
    *) echo "unknown row $row"; continue;;
  esac
  SERVE="$S" PORT=$P CONTAINER=$C LOAD_TIMEOUT=1800 \
    ENGINE="Atlas (avarok/atlas-gb10:$I $(docker image inspect -f '{{index .RepoDigests 0}}' avarok/atlas-gb10:$I 2>/dev/null | cut -c1-80))" \
    /root/health/take.sh "q36-$row"
done
