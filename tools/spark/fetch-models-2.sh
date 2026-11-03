#!/bin/bash
# The DGX Spark's second model set, 2026-11-03: what engines need beyond fetch-models.sh's six folders. Waits for that
# fetch's FETCH_DONE so the two never share the link, then fetches, one at a time:
#   unsloth/Qwen3.6-35B-A3B-MTP-GGUF UD-Q4_K_M and UD-Q4_K_XL (45.5 GB): the first fetch's Qwen3.6 GGUF carries no MTP
#     layers (llama.cpp b12069, 11-03: "model doesn't contain MTP layers"), so its MTP-on rows need these; XL is NVIDIA's
#     playbook checkpoint, M is the same quant as the MTP-less file
#   ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF IQ3_S (2 shards, 83.6 GB) at the revision Strata's setup.py pins —
#     Strata's own Qwen3.8 weights, and the same file through llama.cpp (and bloomery, if it loads) for the
#     same-GGUF pairing the user asked for
#   lmsysorg/sglang:dev-qwen38-next-local, the image SGLang's cookbook names for Qwen3.8 on a DGX Spark (CUDA 13.0.3)
# usage (root, beside fetch-gguf.sh): fetch-models-2.sh   sentinel FETCH2_DONE rc=<n>
set -u
cd "$(dirname "$0")"
say(){ echo "$(date -u +%H:%M:%SZ) $*"; }
until grep -q '^FETCH_DONE' fetch.log 2>/dev/null || ! systemctl is-active -q spark-fetch; do sleep 30; done
say "after: $(grep -E '^FETCH_DONE' fetch.log || echo 'spark-fetch inactive')"
rc=0
say "start unsloth/Qwen3.6-35B-A3B-MTP-GGUF @5bc3e238"
N=8 REV=5bc3e238d916f48a861bac2f8a1990a0e9b7e98d DEST=/models/Qwen3.6-35B-A3B-MTP-GGUF ./fetch-gguf.sh unsloth/Qwen3.6-35B-A3B-MTP-GGUF \
  Qwen3.6-35B-A3B-UD-Q4_K_M.gguf Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf > fetch-q36-mtp-gguf.log 2>&1 || rc=1
say "done unsloth/Qwen3.6-35B-A3B-MTP-GGUF rc=$rc"
REPO=ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF REV=ed59f92082b1e93c0e96d60a8b11aab089b52f09
say "start $REPO IQ3_S @${REV:0:8}"
N=8 REV=$REV DEST=/models/Qwen3.8-Flash-Next-GSQ-RCO-GGUF ./fetch-gguf.sh $REPO \
  IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00002-of-00002.gguf \
  > fetch-gsq-iq3s.log 2>&1 || rc=1
say "done $REPO rc=$rc $(du -sb /models/Qwen3.8-Flash-Next-GSQ-RCO-GGUF | cut -f1) B"
say "pull lmsysorg/sglang:dev-qwen38-next-local"; docker pull -q lmsysorg/sglang:dev-qwen38-next-local || rc=1
echo "FETCH2_DONE rc=$rc"
