#!/bin/bash
# The fourth night queue, 2026-11-04: SGLang's single-Spark Qwen3.8 cells (rows-sglang-q38.sh) after
# queue-night3.sh's QUEUE_NIGHT3_DONE. Sentinel QUEUE_NIGHT4_DONE.
export HOME=/root
cd /root/health || exit 1
until grep -q QUEUE_NIGHT3_DONE queue-night3.log 2>/dev/null; do sleep 60; done
echo "$(date -u +%TZ) start rows-sglang-q38.sh"
./rows-sglang-q38.sh sglang-nvfp4-mtp sglang-nvfp4-nomtp
echo "$(date -u +%TZ) end rc=$? rows-sglang-q38.sh"
echo QUEUE_NIGHT4_DONE
