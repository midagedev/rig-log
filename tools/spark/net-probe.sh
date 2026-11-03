#!/bin/bash
# Download-rate probe against the Hugging Face CDN, 2026-11-03: how many parallel range connections the link needs.
# For each N in the list, N curls fetch distinct ranges of one large public file for SECS seconds; the rate is the
# summed bytes over the wall. The NIC's rx counter over the same window is printed beside it, so the curl sum is
# checked by a second instrument (a probe that only trusts its own byte count once misread a closed connection).
# usage: net-probe.sh [iface=enP7s7] [N list="1 2 4 8 16"] ; SECS=15 by default. Writes nothing to disk.
set -u
IF=${1:-enP7s7}; LIST=${2:-"1 2 4 8 16"}; SECS=${SECS:-15}
URL=https://huggingface.co/unsloth/Qwen3.8-Flash-Next-GGUF/resolve/main/UD-Q4_K_XL/Qwen3.8-Flash-Next-UD-Q4_K_XL-00002-of-00004.gguf  # 49.9 GB shard
CDN=$(curl -sI -o /dev/null -w '%{redirect_url}' "$URL")      # resolve once; every worker hits the same CDN object
[ -n "$CDN" ] || { echo "no redirect for $URL (HTTP $(curl -sI -o /dev/null -w '%{http_code}' "$URL"))" >&2; exit 1; }
rx(){ cat /sys/class/net/$IF/statistics/rx_bytes; }
echo "# $(date -u +%FT%TZ) iface $IF link $(cat /sys/class/net/$IF/speed 2>/dev/null) Mb/s  ${SECS}s per row  cdn $(printf %s "$CDN" | sed -E 's#https://([^/]+)/.*#\1#')"
for n in $LIST; do
  tmp=$(mktemp -d); pids=()
  r0=$(rx); t0=$(date +%s.%N)
  for i in $(seq 0 $((n-1))); do
    s=$(( i * (2 << 30) ))                                   # 2 GiB apart, so no two workers share a byte
    curl -s -r "$s-$((s + (2 << 30) - 1))" -o /dev/null --max-time "$SECS" -w '%{http_code} %{size_download}\n' "$CDN" > "$tmp/$i" &
    pids+=($!)
  done
  for p in "${pids[@]}"; do wait "$p"; done
  t1=$(date +%s.%N); r1=$(rx)
  bad=$(cat "$tmp"/* | awk '$1!=206' | wc -l)                 # a worker that got no 206 measured nothing
  sum=$(cat "$tmp"/* | awk '{s+=$2} END{print s+0}'); rm -rf "$tmp"
  [ "$bad" -gt 0 ] && echo "  N=$n: $bad worker(s) without HTTP 206" 
  awk -v n="$n" -v b="$sum" -v r="$((r1 - r0))" -v t0="$t0" -v t1="$t1" \
    'BEGIN{w=t1-t0; printf "  N=%-3d curl %7.1f MB/s   nic rx %7.1f MB/s   (%.1f s)\n", n, b/w/1e6, r/w/1e6, w}'
done
