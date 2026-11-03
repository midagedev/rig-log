#!/bin/bash
# The third night queue, 2026-11-04: queue-night.sh's last two blocks, which found their downloads failed (01:07 KST),
# once fetch-retry.sh has each and queue-night2.sh is done. lmstudio Q4_K_M: the tape probes (toktape, prompts@v2, as
# juliankang4's tapes) and the default rows of bloomery and llama.cpp; TensorFold on its Qwen3.8 MLX 4-bit MTP folder.
# A row runs only on a fetch that ended rc=0. Sentinel QUEUE_NIGHT3_DONE.
export HOME=/root
cd /root/health || exit 1
B=$(ls -d /opt/engines/bloomery-v0.3.12/*/bin)/bloomery-serve; L=/opt/engines/llama.cpp-b12069/build/bin/llama-server
LMS=/models/Qwen3.6-35B-A3B-LMS-GGUF/Qwen3.6-35B-A3B-Q4_K_M.gguf
job(){ echo "$(date -u +%TZ) start $*"; "$@"; echo "$(date -u +%TZ) end rc=$? $1"; }
until grep -q QUEUE_NIGHT2_DONE queue-night2.log 2>/dev/null; do sleep 60; done
until grep -q "^LMS_DONE" fetch-retry.log 2>/dev/null; do sleep 30; done
if grep -q "^LMS_DONE rc=0" fetch-retry.log; then
  PROBE=/root/health/tape-probe.sh PORT=18731 ENGINE="bloomery 0.3.12" SERVE="$B -m $LMS --host 127.0.0.1 --port 18731" \
    job ./take.sh probe-tape-q36lms-q4km-bloomery-default
  PROBE=/root/health/tape-probe.sh PORT=18732 ENGINE="llama.cpp b12069" SERVE="$L -m $LMS --host 127.0.0.1 --port 18732" \
    job ./take.sh probe-tape-q36lms-q4km-llamacpp-default
  job ./rows-gguf.sh q36lms-q4km $LMS bloomery-default llamacpp-default
fi
until grep -q "^TF38_DONE" fetch-retry.log 2>/dev/null; do sleep 30; done
TF=$(ls -d /opt/engines/tensorfold-v1.2.1/*/bin)/tensorfold-native; Q38M=/models/Qwen3.8-Flash-Next-MLX-4bit-MTP
if grep -q "^TF38_DONE rc=0" fetch-retry.log; then
  SERVE="$TF serve $Q38M --host 127.0.0.1 --port 18738 --no-update-check" PORT=18738 ENGINE="TensorFold 1.2.1" job ./take.sh q38-tf-mlx-default
  SERVE="$TF serve $Q38M --host 127.0.0.1 --port 18738 --no-update-check --no-drafts" PORT=18738 ENGINE="TensorFold 1.2.1" job ./take.sh q38-tf-mlx-nomtp
fi
echo "QUEUE_NIGHT3_DONE"
