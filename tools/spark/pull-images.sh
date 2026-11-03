#!/bin/bash
# Pull the engine images for the DGX Spark comparison one after another, each retried, with the rc of
# docker itself. The first loop (inline, 2026-11-03) printed rc=0 for two pulls that had failed on a
# TLS handshake timeout during a network drop, because the rc it printed was a pipe's.
# usage (root): pull-images.sh [image...]   default: the vLLM, SGLang and Atlas images   sentinel PULLS_DONE fails=<n>
set -u
say(){ echo "$(date -u +%H:%M:%SZ) $*"; }
IMAGES=("$@"); [ ${#IMAGES[@]} -gt 0 ] || IMAGES=(eugr/spark-vllm-b12x:latest eugr/spark-vllm:latest \
  lmsysorg/sglang:v0.5.23-cu130 lmsysorg/sglang:dev-qwen38-next-local avarok/atlas-gb10:latest)
fails=0
for img in "${IMAGES[@]}"; do
  ok=0
  for attempt in 1 2 3 4 5; do
    say "pull $img (try $attempt)"
    if docker pull -q "$img"; then ok=1; break; fi
    sleep 30
  done
  if [ $ok = 1 ]; then say "ok $img $(docker image inspect -f '{{.Id}} {{.Size}}' "$img")"
  else say "FAILED $img"; fails=$((fails+1)); fi
done
echo "PULLS_DONE fails=$fails"
