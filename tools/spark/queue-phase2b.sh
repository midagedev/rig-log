#!/bin/bash
# Phase 2 again, 2026-11-04: both scratch builds were refused at load by the placement plan's count of the MTP
# program's arena (`mtp_arena_bytes` in crates/model/src/arch/qwen35moe/place.rs, a sum of literal word counts):
# w5 holds 16 bytes more (793 -> 797 words), s512 141,399,832 bytes more (5,049,938 -> 40,399,896 words). With the plan
# patched to the refused counts, build both, then (no build beside a take) the two Qwen3.8 FP4-Local rec rows.
# Sentinel PHASE2B_DONE.
export HOME=/root
cd /root/health || exit 1
say(){ echo "$(date -u +%TZ) $*"; }
for b in w5 s512; do ./bloomery-build.sh /opt/build/scratch-$b /opt/build/out-$b > build-$b-2.log 2>&1; say "$b $(tail -1 build-$b-2.log)"; done
M=/models/Qwen3.8-Flash-Next-FP4-Local
for b in w5 s512; do
  grep -q "^BUILD_DONE rc=0" build-$b-2.log || continue
  SERVE="BLOOMERY_DRAFT=mtp BLOOMERY_MTP_WIDTH=cost BLOOMERY_HOST_ROOM=96G /opt/build/out-$b/bloomery-serve -m $M --host 127.0.0.1 --port 18731 --parallel 1 --ctx-size 16896" \
    PORT=18731 ENGINE="bloomery 0.3.12 source build ($b)" ./take.sh q38-fp4-local-bloomery-src-$b-rec
done
echo PHASE2B_DONE
