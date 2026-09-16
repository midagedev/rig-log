#!/bin/bash
# fetch-gguf.sh <repo> <file>... — fetch Hugging Face files with N parallel range workers.
#
#   tools/fetch-gguf.sh unsloth/Qwen3.6-35B-A3B-GGUF Qwen3.6-35B-A3B-UD-Q6_K.gguf
#   N=12 DEST=/models/my-dir tools/fetch-gguf.sh <repo> shard-1.gguf shard-2.gguf
#   KEEP_TREE=1 DEST=/models/Z-Image-Turbo tools/fetch-gguf.sh <repo> transformer/config.json …
#
# KEEP_TREE writes each file at its repo-relative path instead of flattening to DEST.
# Default stays flat because that is what a GGUF loader wants — shards from a
# `UD-Q4_K_XL/` subdirectory belong beside each other. But a **diffusers** repo is not
# flat and cannot be flattened: measured 2026-09-16, fetching Z-Image-Turbo without this
# left one 726-byte `config.json` in DEST because `transformer/config.json`,
# `text_encoder/config.json` and `vae/config.json` all became the same name and overwrote
# each other in listing order. The large shards survived only because their names happen
# to differ. Use KEEP_TREE for anything with a `model_index.json`.
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

# Gated repos: a Hugging Face token, passed to curl through a config file rather than a
# -H argument, because this box runs several sessions and a bearer token on a command line
# is readable in `ps` by all of them. The token is never printed; only whether one was found.
# Measured 2026-09-16: without it a gated file returns an HTML error page with rc 0 from
# `curl -sL`, so the bytes would have failed the size gate with a confusing message instead
# of an honest "you have no access".
TOKEN=${HF_TOKEN:-}
if [ -z "$TOKEN" ]; then
  for f in "${HF_HOME:-/nonexistent}/token" ~/.cache/huggingface/token /home/user/.cache/huggingface/token; do
    [ -f "$f" ] && { TOKEN=$(tr -d '\r\n' < "$f"); break; }
  done
fi
CURLRC=""
if [ -n "$TOKEN" ]; then
  CURLRC=$(mktemp); chmod 600 "$CURLRC"
  printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" > "$CURLRC"
  trap 'rm -f "$CURLRC"' EXIT INT TERM
  say "authenticated (token found; value not logged)"
else
  say "anonymous (no token — a gated repo will refuse)"
fi
# every curl in this script goes through this, so auth can never be added in one place
# and forgotten in the other
CURL=(curl); [ -n "$CURLRC" ] && CURL=(curl -K "$CURLRC")

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
    "${CURL[@]}" -sfL --retry 5 --retry-delay 2 -r $(( s + got ))-$e "$u" >> "$w/c$i" || true
  done
  got=$(stat -c%s "$w/c$i" 2>/dev/null || echo 0)
  [ "$got" = "$want" ]
}

# The tree API lists one directory at a time, so a file under UD-Q4_K_XL/ is not in the
# root listing (measured 2026-09-16: "no size in the API listing" for every sharded unsloth
# quant). Ask for the file's own directory.
declare -A sizes_by_dir
for FILE in "$@"; do
  D=$(dirname "$FILE")   # "." for a root-level file; bash refuses an empty subscript, so "." stays the key
  if [ -z "${sizes_by_dir[$D]+x}" ]; then
    SUB=""; [ "$D" = "." ] || SUB="/$D"
    sizes_by_dir[$D]=$("${CURL[@]}" -sf "$API$SUB") || { say "cannot read $API$SUB"; echo FETCH_FAILED; exit 1; }
  fi
  sizes=${sizes_by_dir[$D]}
  TOTAL=$(printf '%s' "$sizes" | python3 -c "
import json,sys
want=sys.argv[1]
for f in json.load(sys.stdin):
    if f['path']==want: print(f.get('size') or f.get('lfs',{}).get('size') or 0); break
else: print(0)" "$FILE")
  [ "${TOTAL:-0}" -gt 0 ] || { say "$FILE: no size in the API listing"; echo FETCH_FAILED; exit 1; }
  if [ "${KEEP_TREE:-0}" = 1 ]; then DST=$DEST/$FILE; mkdir -p "$(dirname "$DST")"
  else DST=$DEST/$(basename "$FILE"); fi
  if [ -f "$DST" ] && [ "$(stat -c%s "$DST")" = "$TOTAL" ]; then
    say "$FILE: already here, $TOTAL bytes"; continue
  fi
  URL=https://huggingface.co/$REPO/resolve/main/$FILE
  WORK=$DEST/.fetch/$(printf %s "$FILE" | tr / _)
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
