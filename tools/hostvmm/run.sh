#!/usr/bin/env bash
# Build hostvmm.cu with the box's nvcc and run it on the A6000 (the timing card), under the bloomery tree's lease:
#   (from a bloomery tree) BLOOMERY_BOX_ENV=... ./tools/box.sh 'bash tools/ref/lease-hold.sh --card docs/cards/hostvmm-e7.card -- bash /root/hostvmm/run.sh'
# The source is copied to /root/hostvmm first (scp). Args: pages a half (2 MiB), row bytes, reps.
set -euo pipefail
cd "${0%/*}"
/usr/local/cuda/bin/nvcc -O3 -arch=sm_86 -o hostvmm hostvmm.cu -lcuda
for row in 1536 2048; do
  CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=1 timeout 300 ./hostvmm 1024 "$row" 9
done
