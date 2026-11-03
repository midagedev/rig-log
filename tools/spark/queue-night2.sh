#!/bin/bash
# The second night queue, 2026-11-04: after queue-night.sh's QUEUE_NIGHT_DONE, the Flare rows again (the first pass was
# refused for an unapproved package key, rows-flare.sh now passes it) and q8gemv-bench with variant D (split-K for the
# 512-row tensors), each under the lease; and bloomery on the MLX 4-bit folder with MTP (the one Qwen3.6 safetensors form
# bloomery 0.3.12 opens: its NVFP4 and FP8 folders were refused, README "mlx-community's 4-bit folders"). Sentinel QUEUE_NIGHT2_DONE.
export HOME=/root
cd /root/health || exit 1
until grep -q QUEUE_NIGHT_DONE queue-night.log 2>/dev/null; do sleep 60; done
st(){ echo "$(date -u +%H:%M:%SZ) start $*"; "$@"; echo "$(date -u +%H:%M:%SZ) end rc=$? $1"; }
st ./gpu-job.sh bench-q8gemv2 /root/health/bench/q8gemv-bench2 300
st ./rows-bloomery-q38.sh Qwen3.6-35B-A3B-MLX-4bit-MTP default rec nomtp
st ./rows-flare.sh q38-fp4-local /root/.cache/flare/packages/models/nvidia_2FQwen3.8-Flash-Next-FP4-Local/gb10-tp1-202611031432 flare-default flare-nomtp
echo QUEUE_NIGHT2_DONE
