#!/usr/bin/env bash
# Build hostread.cu with the box's nvcc and run it on the A6000 (the timing card), under the bloomery tree's lease:
#   (from a bloomery tree) BLOOMERY_BOX_ENV=... ./tools/box.sh 'bash tools/ref/lease-hold.sh --card docs/cards/hostread-e2.card -- bash /root/hostread/run.sh'
# The source is copied to /root/hostread first (scp). Args: buffer MiB, row bytes, reps for each run.
set -euo pipefail
cd "${0%/*}"
/usr/local/cuda/bin/nvcc -O3 -arch=sm_86 -o hostread hostread.cu
for row in 1536 576 4096; do
  CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=1 timeout 300 ./hostread 4096 "$row" 9
done
