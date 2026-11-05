#!/usr/bin/env bash
# hf-pull.sh REPO SUBDIR DEST [STREAMS] — pull a Hugging Face directory of GGUF shards into DEST with STREAMS (default 8)
# parallel range reads, each part written in place with dd (no extra space), resumable: a part with its .done marker is
# skipped. The box's uplink reads ~1 MB/s on one stream and ~23 MB/s on six (2026-11-05), so the streams are the speed.
set -u
REPO=$1; SUB=$2; DEST=$3; STREAMS=${4:-8}
PART=$((2 * 1024 * 1024 * 1024))   # 2 GiB a part, 1 MiB aligned for dd seek
mkdir -p "$DEST/.parts"
api="https://huggingface.co/api/models/$REPO/tree/main/$SUB"
files=$(curl -sL "$api" | python3 -c 'import json,sys
for x in json.load(sys.stdin):
    if x["type"]=="file": print(x["path"].split("/")[-1], x["size"])')
[ -n "$files" ] || { echo "hf-pull: no files at $api"; exit 65; }
jobs_file="$DEST/.parts/jobs"; : > "$jobs_file"
while read -r name size; do
  [ -n "$name" ] || continue
  [ -f "$DEST/$name" ] || truncate -s "$size" "$DEST/$name"
  n=$(( (size + PART - 1) / PART ))
  for ((i=0; i<n; i++)); do
    a=$((i * PART)); b=$(( (i + 1) * PART - 1 )); [ $b -lt $size ] || b=$((size - 1))
    [ -f "$DEST/.parts/$name.$i.done" ] || echo "$name $i $a $b" >> "$jobs_file"
  done
done <<< "$files"
total=$(wc -l < "$jobs_file"); echo "hf-pull: $total parts to fetch into $DEST ($STREAMS streams), $(date)"
pull_one() {
  local name=$1 i=$2 a=$3 b=$4
  # a second local: bash expands every word of one `local` before any of its assignments, so $name is empty there
  local url="https://huggingface.co/$REPO/resolve/main/$SUB/$name"
  local got tries=0
  while [ $tries -lt 20 ]; do
    # curl (-f) ends non-zero on an HTTP error and 18 on a body shorter than the range's content-length, so rc 0 means every byte of the part arrived;
    # dd writes them in place at the part's offset
    got=$(curl -sfL --retry 3 -r "$a-$b" "$url" | dd of="$DEST/$name" bs=1M seek=$((a / 1048576)) conv=notrunc status=none iflag=fullblock 2>/dev/null; echo "${PIPESTATUS[0]}")
    if [ "$got" = 0 ]; then touch "$DEST/.parts/$name.$i.done"; echo "ok $name part $i $(date +%H:%M:%S)"; return 0; fi
    tries=$((tries + 1)); sleep $((5 * tries))
  done
  echo "FAIL $name part $i"; return 1
}
export -f pull_one; export REPO SUB DEST
xargs -P "$STREAMS" -L 1 bash -c 'pull_one "$@"' _ < "$jobs_file"
left=$(grep -c . "$jobs_file"); done_n=$(ls "$DEST/.parts" | grep -c '\.done$')
echo "hf-pull: done parts $done_n, $(date)"
