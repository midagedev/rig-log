#!/bin/bash
# Board 2 (Qwen3.6-35B-A3B) rows of the DGX Spark comparison for the engines beyond bloomery and llama.cpp, 2026-11-03,
# one take.sh row after another. Rows (name = engine-format-setting):
#   sglang-nvfp4-default  lmsysorg/sglang:v0.5.23-cu130, `sglang serve --model-path <NVFP4>` and nothing else
#   sglang-nvfp4-rec      the SGLang cookbook's Qwen3.6 RTX Spark recipe as its notes describe it (FlashInfer CUTLASS
#                         MoE runner, extra_buffer mamba radix cache with 64-token pages, --mem-fraction-static 0.8;
#                         no speculative decoding)
#   sglang-nvfp4-mtp      rec plus the cookbook's MTP flags (EAGLE, 3 steps, topk 1, 4 draft tokens)
#   sglang-fp8-default / sglang-fp8-mtp   the same on Qwen/Qwen3.6-35B-A3B-FP8 (mtp = the cookbook's section 4 command)
#   tf-nvfp4-default / tf-nvfp4-nomtp     TensorFold 1.2.1 native CUDA on NVIDIA's NVFP4 (MTP head on; --no-drafts)
#   tf-mlx-default / tf-mlx-nomtp         the same on TensorFold's own MLX 4-bit MTP checkpoint (its README's Qwen3.6 row)
#   atlas-*                               see rows-atlas.sh (its command comes from atlasctl run --print)
# usage: rows-q36.sh <row> ...
set -u
NV=/models/Qwen3.6-35B-A3B-NVFP4; F8=/models/Qwen3.6-35B-A3B-FP8; MLX=/models/Qwen3.6-35B-A3B-MLX-4bit-MTP
TF=$(ls -d /opt/engines/tensorfold-v1.2.1/*/bin)/tensorfold-native
SG=lmsysorg/sglang:v0.5.23-cu130; C=spark-take-sglang; P=18734
mkdir -p /root/.cache/sglang-take
run="docker run --rm --name $C --gpus all --network host --ipc=host --shm-size 16g --ulimit memlock=-1:-1 -v /models:/models -v /root/.cache/sglang-take:/root/.cache -e HF_HUB_OFFLINE=1 $SG"
rec="--moe-runner-backend flashinfer_cutlass --mamba-radix-cache-strategy extra_buffer --page-size 64 --mem-fraction-static 0.8 --reasoning-parser qwen3"
mtp="--speculative-algorithm EAGLE --speculative-num-steps 3 --speculative-eagle-topk 1 --speculative-num-draft-tokens 4"
for row in "$@"; do
  CT=""; E=""
  case $row in
    sglang-nvfp4-default) S="$run sglang serve --model-path $NV --host 127.0.0.1 --port $P"; CT=$C;;
    sglang-nvfp4-rec)     S="$run sglang serve --model-path $NV $rec --host 127.0.0.1 --port $P"; CT=$C;;
    sglang-nvfp4-mtp)     S="$run sglang serve --model-path $NV $rec $mtp --host 127.0.0.1 --port $P"; CT=$C;;
    sglang-fp8-default)   S="$run sglang serve --model-path $F8 --host 127.0.0.1 --port $P"; CT=$C;;
    sglang-fp8-mtp)       S="$run sglang serve --model-path $F8 --reasoning-parser qwen3 $mtp --mem-fraction-static 0.8 --host 127.0.0.1 --port $P"; CT=$C;;
    tf-nvfp4-default)     S="$TF serve $NV --host 127.0.0.1 --port $P --no-update-check"; E="TensorFold 1.2.1";;
    tf-nvfp4-nomtp)       S="$TF serve $NV --host 127.0.0.1 --port $P --no-update-check --no-drafts"; E="TensorFold 1.2.1";;
    tf-mlx-default)       S="$TF serve $MLX --host 127.0.0.1 --port $P --no-update-check"; E="TensorFold 1.2.1";;
    tf-mlx-nomtp)         S="$TF serve $MLX --host 127.0.0.1 --port $P --no-update-check --no-drafts"; E="TensorFold 1.2.1";;
    *) echo "unknown row $row"; continue;;
  esac
  [ -n "$CT" ] && E="SGLang ($SG $(docker image inspect -f '{{index .RepoDigests 0}}' $SG 2>/dev/null | cut -c1-80))"
  SERVE="$S" PORT=$P ENGINE="$E" CONTAINER=$CT LOAD_TIMEOUT=2400 /root/health/take.sh "q36-$row"
done
