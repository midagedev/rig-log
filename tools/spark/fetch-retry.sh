#!/bin/bash
# The two downloads the night's takes starved, again, 2026-11-04: lmstudio-community/Qwen3.6-35B-A3B-GGUF Q4_K_M
# @68a34855 (21.2 GB) and TensorFold/Qwen3.8-Flash-Next-MLX-4bit-MTP @2b170fa6 (113.2 GB). Both stopped at 01:07 KST
# with every range worker out of its 20 tries: a take SIGSTOPs the fetch for minutes, the connection dies, and a long
# night of takes used the tries up. fetch-gguf.sh resumes the ranges from their bytes on disk, so this re-runs it up
# to 10 times per repo. Run as the spark-fetch4 unit, which take.sh and gpu-job.sh pause like the others.
# usage (root, beside fetch-gguf.sh): fetch-retry.sh   sentinels LMS_DONE rc=<n>, TF38_DONE rc=<n>
set -u
cd "$(dirname "$0")"
say(){ echo "$(date -u +%H:%M:%SZ) $*"; }
again(){ local i; for i in $(seq 10); do "$@" && return 0; say "try $i failed, again in 30 s"; sleep 30; done; return 1; }
again env N=8 REV=68a34855558af61cbef0324d31f411be8a506b08 DEST=/models/Qwen3.6-35B-A3B-LMS-GGUF \
  ./fetch-gguf.sh lmstudio-community/Qwen3.6-35B-A3B-GGUF Qwen3.6-35B-A3B-Q4_K_M.gguf >> fetch-lms-retry.log 2>&1
echo "LMS_DONE rc=$?"
R=2b170fa6309d5d1ee380b35636075fac7945f286
files=$(curl -s "https://huggingface.co/api/models/TensorFold/Qwen3.8-Flash-Next-MLX-4bit-MTP/tree/$R?recursive=1" | jq -r '.[]|select(.type=="file")|.path')
if [ -n "$files" ]; then
  # shellcheck disable=SC2086
  again env N=8 REV=$R DEST=/models/Qwen3.8-Flash-Next-MLX-4bit-MTP KEEP_TREE=1 ./fetch-gguf.sh TensorFold/Qwen3.8-Flash-Next-MLX-4bit-MTP $files \
    >> fetch-tf38-retry.log 2>&1
  echo "TF38_DONE rc=$?"
else echo "TF38_DONE rc=1 (empty file list)"; fi
