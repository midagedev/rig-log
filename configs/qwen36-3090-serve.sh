#!/bin/bash
# Qwen3.6-35B-A3B whole on the 3090, for the phone-facing agent: a fast model where V4.1 is the slow one.
# Measured on the A6000 2026-09-15: 140 tok/s at UD-Q4_K_XL (20.8 GiB). On the 24 GB card the file plus a
# 64k KV cache (q8_0) plus compute buffers is the budget; the A6000 stays free for diffusion work.
# Thinking is off by template kwarg: an agent turn pays for every reasoning token, and Hermes drives the
# reasoning itself. Same binary as the V4.1 profile (mainline fork with the current chat parsers).
set -eu
B=${B:-$HOME/llama.cpp-v41-merged/build/bin/llama-server}
M=${M:-/models/Qwen3.6-35B-A3B/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf}
. /home/user/gpu-order.env
export CUDA_VISIBLE_DEVICES=$GF3090_UUID
exec "$B" -m "$M" --alias Qwen3.6-35B-A3B \
  -c ${CTX:-65536} -ngl 99 -fa on -t 16 -b 2048 -ub 512 \
  -ctk q8_0 -ctv q8_0 \
  --jinja --chat-template-kwargs '{"enable_thinking": false}' \
  --host 127.0.0.1 --port 8001
