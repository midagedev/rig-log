#!/bin/bash
# The DGX Spark's first model set for the engine comparison (bloomery against Flare, Atlas, Strata, vLLM, SGLang,
# llama.cpp), 2026-11-03. One repo at a time through fetch-gguf.sh with N=8 range workers: net-probe.sh measured the
# office link at 58.8 MB/s on one connection, 101.4 at eight and 64.5 at sixteen, so two repos at once (16) would be
# slower than one. Every repo is pinned to the commit listed here. A sampler writes the NIC's rx counter every 10 s
# (net-rx.log) so the whole download's rate is read from the interface, not from the fetcher's own count.
# usage (root, beside fetch-gguf.sh): fetch-models.sh [dest root=/models]. Sentinel FETCH_DONE rc=<n>.
set -u
cd "$(dirname "$0")"
ROOT=${1:-/models}; IF=enP7s7
say(){ echo "$(date -u +%H:%M:%SZ) $*"; }
rx(){ cat /sys/class/net/$IF/statistics/rx_bytes; }
mkdir -p "$ROOT"
( while :; do echo "$(date -u +%s) $(rx)"; sleep 10; done ) > net-rx.log &
SAMP=$!; echo "$SAMP" > net-rx.pid
trap 'kill "$SAMP" 2>/dev/null' EXIT

rc_all=0
fetch() {  # repo rev dest-name file-regex
  local repo=$1 rev=$2 dest=$ROOT/$3 re=$4 files t0 r0 rc
  files=$(curl -s "https://huggingface.co/api/models/$repo/tree/$rev?recursive=1" |
          jq -r '.[] | select(.type=="file") | .path' | grep -E "$re")
  [ -n "$files" ] || { say "FAIL $repo: empty file list"; rc_all=1; return; }
  say "start $repo @${rev:0:8} -> $dest ($(echo "$files" | wc -l) files)"
  t0=$(date +%s); r0=$(rx)
  # shellcheck disable=SC2086
  N=8 REV=$rev DEST=$dest KEEP_TREE=1 ./fetch-gguf.sh "$repo" $files > "fetch-$3.log" 2>&1; rc=$?
  local dt=$(( $(date +%s) - t0 )) bytes; bytes=$(du -sb --exclude=.fetch "$dest" | cut -f1)
  awk -v b="$bytes" -v r="$(( $(rx) - r0 ))" -v t="$dt" -v rc="$rc" -v n="$repo" \
    'BEGIN{printf "%s done %s rc=%d  %.1f GB in %d s  files %.1f MB/s  nic %.1f MB/s\n", strftime("%H:%M:%SZ", systime(), 1), n, rc, b/1e9, t, b/t/1e6, r/t/1e6}'
  [ "$rc" -eq 0 ] || rc_all=1
}

say "free $(df -h --output=avail "$ROOT" | tail -1 | xargs)"
fetch nvidia/Qwen3.8-Flash-Next-FP4-Local b9ce18a6887e18c089fdea8509a33e63429a3300 Qwen3.8-Flash-Next-FP4-Local '.'
fetch unsloth/Qwen3.6-35B-A3B-GGUF       a483e9e6cbd595906af30beda3187c2663a1118c Qwen3.6-35B-A3B-GGUF '^Qwen3\.6-35B-A3B-UD-Q4_K_(XL|M)\.gguf$'
fetch unsloth/Qwen3.8-Flash-Next-GGUF    766911a6b7369840a91dbcd95f9f997acaab6cd6 Qwen3.8-Flash-Next-GGUF '^UD-Q4_K_XL/|^MTP/mtp-Qwen3\.8-Flash-Next-Q8_0\.gguf$'
fetch nvidia/Qwen3.8-Flash-Next-NVFP4    fc694b54fb0174e0913e6adf86691ef85a4ead47 Qwen3.8-Flash-Next-NVFP4 '.'
fetch nvidia/Qwen3.6-35B-A3B-NVFP4       1355db6a052410cfd62085d94b58866fd0f2c3c5 Qwen3.6-35B-A3B-NVFP4 '.'
fetch Qwen/Qwen3.6-35B-A3B-FP8           95a723d08a9490559dae23d0cff1d9466213d989 Qwen3.6-35B-A3B-FP8 '.'
say "free $(df -h --output=avail "$ROOT" | tail -1 | xargs)"
echo "FETCH_DONE rc=$rc_all"
