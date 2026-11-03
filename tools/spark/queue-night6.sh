#!/bin/bash
# The sixth night queue, 2026-11-04: two bloomery levers on Qwen3.8 FP4-Local's MTP draft, against the rec row
# (BLOOMERY_DRAFT=mtp, width cost: code 63.9, prose 42.9; its `mtp width` records keep a third draft 21 % of the time
# against 66–75 % for the first two, while TensorFold's MLX 4-bit MTP keeps 73 % of ~5 drafts a round on code):
#   rec-headfull  BLOOMERY_MTP_HEAD_ROWS=full (the draft scores the whole vocabulary, not the shipped 76k list)
#   rec-fixed     BLOOMERY_MTP_WIDTH=fixed (every pass verifies the whole proposal)
# After queue-night5.sh's QUEUE_NIGHT5_DONE. Sentinel QUEUE_NIGHT6_DONE.
export HOME=/root
cd /root/health || exit 1
until grep -q QUEUE_NIGHT5_DONE queue-night5.log 2>/dev/null; do sleep 60; done
B=$(ls -d /opt/engines/bloomery-v0.3.12/*/bin)/bloomery-serve; M=/models/Qwen3.8-Flash-Next-FP4-Local
rec="BLOOMERY_HOST_ROOM=96G $B -m $M --host 127.0.0.1 --port 18731 --parallel 1 --ctx-size 16896"
job(){ echo "$(date -u +%TZ) start $*"; "$@"; echo "$(date -u +%TZ) end rc=$? $1"; }
SERVE="BLOOMERY_DRAFT=mtp BLOOMERY_MTP_WIDTH=cost BLOOMERY_MTP_HEAD_ROWS=full $rec" PORT=18731 ENGINE="bloomery 0.3.12" \
  job ./take.sh q38-fp4-local-bloomery-rec-headfull
SERVE="BLOOMERY_DRAFT=mtp BLOOMERY_MTP_WIDTH=fixed $rec" PORT=18731 ENGINE="bloomery 0.3.12" \
  job ./take.sh q38-fp4-local-bloomery-rec-fixed
echo QUEUE_NIGHT6_DONE
