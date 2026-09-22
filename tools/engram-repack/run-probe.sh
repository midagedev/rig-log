#!/bin/bash
# Serve each engram variant in turn on port 8001 with the production flags
# (configs/v41-serve.sh), run one probe script against it, stop it by PID.
# Usage: run-probe.sh <probe.py> <out-prefix> [sample.json] [Q3 Q8 ...]
# The thermal guard on this machine stops llama-server after ~5 min of
# 32-thread decode (see log/2026-09-13.md#engram-q8-repack); keep probes short
# or let the coolant fall back to ~43 C between variants.
set -u
PROBE=${1:?probe script}; OUT=${2:?output prefix}; SAMPLE=${3:-}; shift 3 2>/dev/null || shift $#
TAGS=${*:-Q3 Q8}
SERVE=$(dirname "$0")/../../configs/v41-serve.sh
for tag in $TAGS; do
  case $tag in
    Q3) M=/models/DeepSeek-V4.1-Flash-Q3_K_M/DeepSeek-V4.1-Flash-Q3_K_M-00001-of-00009.gguf ;;
    Q8) M=/models/DeepSeek-V4.1-Flash-Q3_K_M-engramQ8/DeepSeek-V4.1-Flash-Q3_K_M-00001-of-00009.gguf ;;
    *) echo "unknown tag $tag"; exit 2 ;;
  esac
  M=$M bash "$SERVE" > /tmp/probe-srv-$tag.log 2>&1 &
  SP=$!
  echo "$(date +%T) $tag server pid=$SP"
  for i in $(seq 1 120); do curl -sf 127.0.0.1:8001/health >/dev/null && break; kill -0 $SP 2>/dev/null || { echo "server died"; exit 1; }; sleep 5; done
  echo "$(date +%T) $tag healthy"
  python3 "$PROBE" 8001 "$OUT-$tag.json" $SAMPLE
  kill $SP; while kill -0 $SP 2>/dev/null; do sleep 2; done
  echo "$(date +%T) $tag stopped"
done
echo PROBE_DONE
