#!/bin/bash
# The baseline for proposals ② and ⑦, 2026-11-04: the unpatched scratch clone built by the same container and
# toolchain as the patched two, so a patch's figure is read against a build that differs from it only by the patch,
# not against the 0.3.12 release binary. Then a second take of each patched build, to see the take-to-take spread.
# After queue-phase2c.sh's PHASE2C_DONE, one engine at a time. Sentinel PHASE2D_DONE.
export HOME=/root
cd /root/health || exit 1
say(){ echo "$(date -u +%TZ) $*"; }
until grep -q PHASE2C_DONE phase2c.log 2>/dev/null; do sleep 30; done
./bloomery-build.sh /opt/build/scratch-base /opt/build/out-base > build-base.log 2>&1; say "base $(tail -1 build-base.log)"
M=/models/Qwen3.8-Flash-Next-FP4-Local
for t in base:base w5:w5-r2 s512:s512-r2 base:base-r2; do
  b=${t%%:*}; tag=${t#*:}
  [ -x /opt/build/out-$b/bloomery-serve ] || continue
  SERVE="BLOOMERY_DRAFT=mtp BLOOMERY_MTP_WIDTH=cost BLOOMERY_HOST_ROOM=96G /opt/build/out-$b/bloomery-serve -m $M --host 127.0.0.1 --port 18731 --parallel 1 --ctx-size 16896" \
    PORT=18731 ENGINE="bloomery 0.3.12 source build ($b)" ./take.sh q38-fp4-local-bloomery-src-$tag-rec
done
echo PHASE2D_DONE
