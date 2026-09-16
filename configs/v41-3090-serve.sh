#!/bin/bash
# DeepSeek-V4.1-Flash served from the 24 GB card alone, so the 48 GB card is free for diffusion work.
# Measured 2026-09-16 (tools/v41/v41-3090-only.sh): attention, hyper-connections, KV and the DSpark
# draft on the 3090 (22.5 GB at 64k context), all forty expert layers on the host; warm decode
# 19.8 / 25.4 tok/s against 21.6 / 25.9 with the A6000 alone. Context 64k because Hermes Agent
# refuses less. The chat template is passed as a file because the one embedded in the GGUF is the
# V4 template: V4.1 renders the DSML tag names with a leading space ("<｜DSML｜ calls>"), so with the
# embedded template the server returned every tool call as content (measured 2026-09-16, 19:40).
# GGML_CUDA_NO_PINNED_WEIGHTS: -ot to CPU drops mmap and 283 GiB of pinned weights
# do not fit 251 GB of RAM (ik #2444).
set -eu
B=${B:-$HOME/llama.cpp-v41-merged/build/bin/llama-server}
M=${M:-/models/DeepSeek-V4.1-Flash-Q3_K_M-engramQ8-tokembdBF16-attnQ8/DeepSeek-V4.1-Flash-Q3_K_M-00001-of-00009.gguf}
D=${D:-/models/DeepSeek-V4.1-Flash-DSpark/DeepSeek-V4.1-Flash-Fp8-128x742M-MXFP4_MOE.tl37.gguf}
. /home/user/gpu-order.env               # UUIDs; configs/gpu-order.env
export CUDA_VISIBLE_DEVICES=$GF3090_UUID  # CUDA0 = the 3090, the only device this server may see
export GGML_CUDA_NO_PINNED_WEIGHTS=1
exec "$B" -m "$M" --alias DeepSeek-V4.1-Flash \
  -c 65536 -ngl 99 -t 32 -b 2048 -ub 512 \
  --lazy-mode auto \
  -ot "exps=CPU" \
  -md "$D" --spec-type draft-dspark --spec-draft-n-max 3 -otd "output_norm=CUDA0" \
  --jinja --chat-template-file "${TMPL:-$HOME/llama.cpp-v41-merged/models/templates/deepseek-ai-DeepSeek-V4.1-Flash.jinja}" \
  --host 127.0.0.1 --port 8001
