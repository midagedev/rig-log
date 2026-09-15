#!/bin/bash
# fetch-gguf.sh <repo> <file>... — fetch Hugging Face files with N parallel range workers.
#
#   tools/fetch-gguf.sh unsloth/Qwen3.6-35B-A3B-GGUF Qwen3.6-35B-A3B-UD-Q6_K.gguf
#   N=12 DEST=/models/my-dir tools/fetch-gguf.sh <repo> shard-1.gguf shard-2.gguf
#
# Measured on this machine 2026-09-15: one connection 28 MB/s, eight 80 MB/s on the
# same file and the same link, so a 29 GB file is 6 minutes rather than 17.
#
# Three rules this follows, each from an incident in docs/quiet-machine.md:
#  - every worker's pid is recorded at spawn and waited on by pid; nothing is ever
#    matched by command line (a /proc scan once froze the session's own ssh)
#  - a file only appears at its final path when its byte count matches the API's,
#    so a loader can never open a partial download
#  - the expected size comes from the API rather than from the header of the
#    redirect, which is the CDN's and has been 1036 bytes of policy JSON
set -u
REPO=${1:?usage: fetch-gguf.sh <repo> <file>...}; shift
DEST=${DEST:-/models/$(basename "$REPO" | sed 's/-GGUF$//')}
N=${N:-8}
API=https://huggingface.co/api/models/$REPO/tree/main
mkdir -p "$DEST"
say(){ echo "$(date +%H:%M:%S) $*"; }

# One worker, one range, resumed until its byte count is exactly right.
# curl exits 0 on a connection the server closes early (measured 2026-09-15: a
# chunk came back 365 MB of 3.66 GB with rc 0), so a worker is not done when
# curl returns -- it is done when the bytes are there.
range_worker(){
  local w=$1 i=$2 s=$3 e=$4 u=$5 want=$(( $4 - $3 + 1 )) got attempt
  for attempt in 1 2 3 4 5 6; do
    got=$(stat -c%s "$w/c$i" 2>/dev/null || echo 0)
    [ "$got" = "$want" ] && return 0
    if [ "$got" -gt "$want" ]; then echo "chunk $i overshot: $got > $want"; return 1; fi
    curl -sfL --retry 5 --retry-delay 2 -r $(( s + got ))-$e "$u" >> "$w/c$i" || true
  done
  got=$(stat -c%s "$w/c$i" 2>/dev/null || echo 0)
  [ "$got" = "$want" ]
}

sizes=$(curl -sf "$API") || { say "cannot read $API"; echo FETCH_FAILED; exit 1; }

for FILE in "$@"; do
  TOTAL=$(printf '%s' "$sizes" | python3 -c "
import json,sys
want=sys.argv[1]
for f in json.load(sys.stdin):
    if f['path']==want: print(f.get('size') or f.get('lfs',{}).get('size') or 0); break
else: print(0)" "$FILE")
  [ "${TOTAL:-0}" -gt 0 ] || { say "$FILE: no size in the API listing"; echo FETCH_FAILED; exit 1; }
  DST=$DEST/$(basename "$FILE")
  if [ -f "$DST" ] && [ "$(stat -c%s "$DST")" = "$TOTAL" ]; then
    say "$FILE: already here, $TOTAL bytes"; continue
  fi
  URL=https://huggingface.co/$REPO/resolve/main/$FILE
  WORK=$DEST/.fetch/$(basename "$FILE")
  mkdir -p "$WORK"; : > "$WORK/pids"
  CHUNK=$(( (TOTAL + N - 1) / N ))
  for i in $(seq 0 $((N-1))); do
    S=$(( i * CHUNK )); E=$(( S + CHUNK - 1 )); [ $E -ge $TOTAL ] && E=$((TOTAL-1))
    [ $S -ge $TOTAL ] && break
    range_worker "$WORK" $i $S $E "$URL" &
    echo "$! $i $S $E" >> "$WORK/pids"
  done
  say "$FILE: $N workers on $TOTAL bytes"
  rc=0
  while read -r pid i s e; do
    wait "$pid" || { say "worker $i (pid $pid) failed"; rc=1; }
    want=$(( e - s + 1 )); got=$(stat -c%s "$WORK/c$i" 2>/dev/null || echo 0)
    [ "$got" = "$want" ] || { say "chunk $i: $got bytes, wanted $want"; rc=1; }
  done < "$WORK/pids"
  [ $rc -eq 0 ] || { say "$FILE: incomplete, nothing moved into place"; echo FETCH_FAILED; exit 1; }
  cat $(awk '{print "'"$WORK"'/c" $2}' "$WORK/pids") > "$DST.assembled"
  GOT=$(stat -c%s "$DST.assembled")
  [ "$GOT" = "$TOTAL" ] || { say "$FILE: assembled $GOT, wanted $TOTAL"; echo FETCH_FAILED; exit 1; }
  mv "$DST.assembled" "$DST"; rm -rf "$WORK"
  say "$FILE: $GOT bytes"
done
rmdir "$DEST/.fetch" 2>/dev/null
echo FETCH_DONE
