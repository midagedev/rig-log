#!/bin/bash
# The probes behind "where bloomery trails" (docs/spark-engines.md), 2026-11-03, each a take.sh PROBE row:
#   nsys-decode   Qwen3.6 UD-Q4_K_M (no MTP layer in the file), bloomery draft off and llama.cpp default: one 128-token
#                 greedy decode under nsys each, for kernel time per token
#   nsys-prefill  Qwen3.8 FP4-Local, bloomery rec with and without the MTP draft: one 4,200-token prompt under nsys
#                 each, for what the draft adds to the prompt pass
#   ids           bloomery FP4-Local rec, the README's method (ids-probe.py), three fresh servers
# usage: probes-lag.sh <set> ...
set -u
B=$(ls -d /opt/engines/bloomery-v0.3.12/*/bin)/bloomery-serve; L=/opt/engines/llama.cpp-b12069/build/bin/llama-server
Q36=/models/Qwen3.6-35B-A3B-GGUF/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf; Q38=/models/Qwen3.8-Flash-Next-FP4-Local
NS="nsys launch --trace=cuda --cuda-graph-trace=node --session-new"
brec="--host 127.0.0.1 --port 18731 --parallel 1 --ctx-size 16896"
for set in "$@"; do case $set in
  nsys-decode)
    NSYS_SESSION=bl36 PROBE=/root/health/nsys-probe.sh PORT=18731 ENGINE="bloomery 0.3.12" \
      SERVE="BLOOMERY_DRAFT=off BLOOMERY_HOST_ROOM=96G $NS=bl36 $B -m $Q36 $brec" /root/health/take.sh probe-nsys-decode-q36-bloomery-nomtp
    NSYS_SESSION=lc36 PROBE=/root/health/nsys-probe.sh PORT=18732 ENGINE="llama.cpp b12069" \
      SERVE="$NS=lc36 $L -m $Q36 --host 127.0.0.1 --port 18732" /root/health/take.sh probe-nsys-decode-q36-llamacpp-default;;
  nsys-prefill)
    NSYS_SESSION=blm KIND=prefill PROBE=/root/health/nsys-probe.sh PORT=18731 ENGINE="bloomery 0.3.12" \
      SERVE="BLOOMERY_DRAFT=mtp BLOOMERY_MTP_WIDTH=cost BLOOMERY_HOST_ROOM=96G $NS=blm $B -m $Q38 $brec" /root/health/take.sh probe-nsys-prefill-q38-bloomery-rec
    NSYS_SESSION=bln KIND=prefill PROBE=/root/health/nsys-probe.sh PORT=18731 ENGINE="bloomery 0.3.12" \
      SERVE="BLOOMERY_DRAFT=off BLOOMERY_HOST_ROOM=96G $NS=bln $B -m $Q38 $brec" /root/health/take.sh probe-nsys-prefill-q38-bloomery-nomtp;;
  ids)
    for r in 1 2 3; do PROBE=/root/health/ids-probe.py PORT=18731 ENGINE="bloomery 0.3.12" \
      SERVE="BLOOMERY_DRAFT=mtp BLOOMERY_MTP_WIDTH=cost BLOOMERY_HOST_ROOM=96G $B -m $Q38 $brec" /root/health/take.sh probe-ids-q38-fp4-local-bloomery-rec-r$r; done;;
  *) echo "unknown set $set";;
esac; done
