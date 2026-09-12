#!/bin/bash
# DeepSeek-V4.1-Flash on two GPUs, system RAM, and NVMe.
#
# The model is 347 GB at Q3_K_M against 72 GB of VRAM, so the question is not
# whether it fits but what goes where. Three tiers:
#
#   GPU   every layer's attention and hyper-connection tensors (60 MB a layer,
#         2.5 GB for all forty), plus as many expert layers as the cards hold.
#   RAM   the remaining expert layers, about 6.5 GB each.
#         An expert layer is about 6.5 GB here (three [5120, 2304, 384] tensors),
#         so the counts below are deliberately low for a first boot: four layers
#         on the 48 GB card, two on the 24 GB, and raise them once a run has
#         reported how much VRAM is actually left.
#   NVMe  the two engram tables, 42.2 GB each. These are conditional memory:
#         384 M rows read through ggml_get_rows, 24 rows per token per layer
#         and only two layers carry one, so a token touches 48 rows -- 5.2 KiB.
#         --lazy-mode leaves them on the file and serves rows on demand.
#
# Run it on a machine with nothing else holding VRAM.
set -eu

B=${B:-$HOME/llama.cpp-v41/build/bin/llama-server}
M=${M:-/models/DeepSeek-V4.1-Flash-Q3_K_M/DeepSeek-V4.1-Flash-Q3_K_M-00001-of-00009.gguf}

export CUDA_DEVICE_ORDER=PCI_BUS_ID

exec "$B" -m "$M" --alias DeepSeek-V4.1-Flash \
  -c 32768 -ngl 99 -t 32 -b 2048 -ub 512 \
  --lazy-mode auto \
  -ot "blk\.[0-3]\.ffn_.*_exps=CUDA0" \
  -ot "blk\.[4-5]\.ffn_.*_exps=CUDA1" \
  -ot "exps=CPU" \
  --jinja \
  --host 127.0.0.1 --port 8001
