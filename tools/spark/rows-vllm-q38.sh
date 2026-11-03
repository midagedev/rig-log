#!/bin/bash
# vLLM rows of board 1 (Qwen3.8-Flash-Next FP4-Local) on the DGX Spark, 2026-11-03, through eugr/spark-vllm-docker's
# B12X runner image (eugr/spark-vllm-b12x, CUDA 13.0 base; the repo's README says it requires driver 580.x).
#   vllm-default  `vllm serve <folder>` on the same image, nothing else
#   vllm-rec      the README's "Single Spark: Qwen3.8 Flash Next FP4 Local" command (repo at fbcc05dc, 2026-11-02),
#                 env and flags as printed there, model path and port ours; docker flags are launch-cluster.sh's
#                 privileged set (memlock unlimited, ipc host, host network)
#   vllm-nomtp    vllm-rec without --speculative-config
# usage: rows-vllm-q38.sh [row ...]
set -u
M=/models/Qwen3.8-Flash-Next-FP4-Local; IMG=${IMG:-eugr/spark-vllm-b12x:latest}; P=18733; C=spark-take-vllm
run="docker run --rm --name $C --privileged --gpus all --network host --ipc=host --ulimit memlock=-1:-1 --ulimit nofile=1048576:1048576 --entrypoint= -v /models:/models -e HF_HUB_OFFLINE=1"
envrec="-e PYTORCH_ALLOC_CONF=per_process_memory_fraction:0.8 -e VLLM_PLE_TABLE_MEMORY=disk -e B12X_DISK_BACKEND=io_uring -e CUTE_DSL_ARCH=sm_121a -e SAFETENSORS_FAST_GPU=1 -e VLLM_WORKER_MULTIPROC_METHOD=spawn -e VLLM_SSM_CONV_STATE_LAYOUT=DS -e VLLM_USE_AOT_COMPILE=1 -e VLLM_USE_MEGA_AOT_ARTIFACT=1 -e VLLM_USE_V2_MODEL_RUNNER=1 -e B12X_POLICY_MODE=auto -e VLLM_MXFP8_LM_HEAD=1 -e VLLM_B12X_MOE_FP4_LAYER_MAX_INPUT_SCALE=w13 -e VLLM_B12X_MOE_FP4_FORCE_A16=1 -e B12X_W4A16_A4_PREFILL=1"
flags="--host 127.0.0.1 --port $P --tensor-parallel-size 1 --pipeline-parallel-size 1 --mamba-cache-mode align --enable-prefix-caching --enable-chunked-prefill --dtype bfloat16 --kv-cache-dtype fp8 --quantization modelopt_mixed --block-size 16 --load-format b12x --max-model-len 262144 --max-num-seqs 8 --max-num-batched-tokens 4096 --gdn-decode-kernel b12x --linear-backend b12x --moe-backend b12x --no-enable-flashinfer-autotune --mm-encoder-tp-mode data --reasoning-parser qwen3 --tool-call-parser qwen3_xml --enable-auto-tool-choice --compilation-config '{\"pass_config\":{\"fuse_act_quant\":true}}' --gpu-memory-utilization 0.8"
spec="--speculative-config '{\"method\":\"mtp\",\"num_speculative_tokens\":4}'"
for r in "${@:-vllm-default vllm-rec vllm-nomtp}"; do for row in $r; do
  case $row in
    vllm-default) S="$run $IMG vllm serve $M --host 127.0.0.1 --port $P";;
    vllm-rec)     S="$run $envrec $IMG vllm serve $M $flags $spec";;
    vllm-nomtp)   S="$run $envrec $IMG vllm serve $M $flags";;
    *) echo "unknown row $row"; continue;;
  esac
  SERVE="$S" PORT=$P CONTAINER=$C LOAD_TIMEOUT=2400 ENGINE="vLLM ($IMG $(docker image inspect -f '{{index .RepoDigests 0}}' $IMG 2>/dev/null | cut -c1-80))" \
    /root/health/take.sh "q38-fp4-local-$row"
done; done
