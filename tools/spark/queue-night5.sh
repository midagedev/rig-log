#!/bin/bash
# The fifth night queue, 2026-11-04: two tape probes that narrow the gap to juliankang4's tape (bloomery 0.3.0,
# driver 595.84, 2 slots: decode 86.9; ours 0.3.12 on 580 with 1 slot: 80.7–81.1) without touching the driver:
# bloomery 0.3.11 (the oldest release with a GB10 archive) at its defaults, and 0.3.12 with --parallel 2. Same file
# (lmstudio Q4_K_M), same tape-probe.sh. After queue-night4.sh's QUEUE_NIGHT4_DONE. Sentinel QUEUE_NIGHT5_DONE.
export HOME=/root
cd /root/health || exit 1
until grep -q QUEUE_NIGHT4_DONE queue-night4.log 2>/dev/null; do sleep 60; done
LMS=/models/Qwen3.6-35B-A3B-LMS-GGUF/Qwen3.6-35B-A3B-Q4_K_M.gguf
B11=$(ls -d /opt/engines/bloomery-v0.3.11/*/bin)/bloomery-serve; B12=$(ls -d /opt/engines/bloomery-v0.3.12/*/bin)/bloomery-serve
job(){ echo "$(date -u +%TZ) start $*"; "$@"; echo "$(date -u +%TZ) end rc=$? $1"; }
PROBE=/root/health/tape-probe.sh PORT=18731 ENGINE="bloomery 0.3.11" SERVE="$B11 -m $LMS --host 127.0.0.1 --port 18731" \
  job ./take.sh probe-tape-q36lms-q4km-bloomery0311-default
PROBE=/root/health/tape-probe.sh PORT=18731 ENGINE="bloomery 0.3.12" SERVE="$B12 -m $LMS --host 127.0.0.1 --port 18731 --parallel 2" \
  job ./take.sh probe-tape-q36lms-q4km-bloomery-p2
echo QUEUE_NIGHT5_DONE
