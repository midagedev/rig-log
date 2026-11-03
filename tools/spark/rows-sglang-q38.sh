#!/bin/bash
# Board 1 (Qwen3.8-Flash-Next) SGLang rows of the DGX Spark comparison, 2026-11-04: lmsysorg/sglang:dev-qwen38-next-local
# (SGLang 4ccff141db), the image the SGLang cookbook names for nvidia/Qwen3.8-Flash-Next-NVFP4 (ModelOpt
# MIXED_PRECISION) on one DGX Spark. One GB10 holds the checkpoint only with the 47.7 GiB FP8 N-gram table file-backed
# on NVMe (--ple-offload-embedding --ple-offload-backend file); the cookbook says to delete the table file before each
# boot (a rewrite of a populated file runs ~17 MB/s, ~55 min; a fresh sparse file ~10 min), so each row does. Rows:
#   sglang-nvfp4-mtp    the cookbook's single-Spark MTP cell: 8 requests, 40 mamba slots, NEXTN 3 steps, 4 draft tokens
#   sglang-nvfp4-nomtp  its no-MTP cell: 24 requests, 96 slots on extra_buffer_lazy
# Both pin --moe-runner-backend flashinfer_cutlass (the auto pick on GB10 is rejected at autotune) and
# --mem-fraction-static 0.85. The cookbook measured 27.5 tok/s (MTP) and 15.9 tok/s (no MTP) single-stream.
# usage: rows-sglang-q38.sh <row> ...
set -u
NV=/models/Qwen3.8-Flash-Next-NVFP4; SG=lmsysorg/sglang:dev-qwen38-next-local; C=spark-take-sglang; P=18734
PLE=/root/.cache/sglang-ple; mkdir -p $PLE /root/.cache/sglang-take
run="docker run --rm --name $C --gpus all --network host --ipc=host --shm-size 16g --ulimit memlock=-1:-1 -v /models:/models -v /root/.cache/sglang-take:/root/.cache -v $PLE:/ple-cache -e HF_HUB_OFFLINE=1 $SG"
base="--tp 1 --moe-runner-backend flashinfer_cutlass --ple-offload-embedding --ple-offload-backend file --ple-offload-dir /ple-cache --mem-fraction-static 0.85 --reasoning-parser qwen3"
mtp="--max-running-requests 8 --max-mamba-cache-size 40 --speculative-algorithm NEXTN --speculative-num-steps 3 --speculative-eagle-topk 1 --speculative-num-draft-tokens 4"
nomtp="--max-running-requests 24 --max-mamba-cache-size 96 --mamba-radix-cache-strategy extra_buffer_lazy"
E="SGLang ($SG $(docker image inspect -f '{{.Id}}' $SG 2>/dev/null | cut -c1-19))"
for row in "$@"; do
  case $row in
    sglang-nvfp4-mtp)   S="$run sglang serve --model-path $NV $base $mtp --host 127.0.0.1 --port $P";;
    sglang-nvfp4-nomtp) S="$run sglang serve --model-path $NV $base $nomtp --host 127.0.0.1 --port $P";;
    *) echo "unknown row $row"; continue;;
  esac
  find $PLE -name 'ple_table_*.bin' -delete
  SERVE="$S" PORT=$P ENGINE="$E" CONTAINER=$C LOAD_TIMEOUT=3000 /root/health/take.sh "q38-$row"
done
find $PLE -name 'ple_table_*.bin' -delete
