#!/bin/bash
# Runs repack.py for both shards, serially, at idle I/O priority.
set -uo pipefail
export PYTHONPATH=$HOME/llama.cpp-v41/gguf-py
cd /models/DeepSeek-V4.1-Flash-Q3_K_M-engramQ8
mkdir -p logs
for n in 2 5; do
  nice -n 19 ionice -c3 ~/.venv-gguf/bin/python repack.py --shard $n 2>&1 | tee logs/repack-0000$n.log
  if [ ${PIPESTATUS[0]} -ne 0 ]; then echo "FAIL: repack shard $n"; exit 1; fi
done
echo "=== $(date -Is) repack_all done"
