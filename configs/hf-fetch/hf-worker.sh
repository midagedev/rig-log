#!/usr/bin/env bash
# One download worker. Run as many as the line supports; they share the
# MANIFEST and divide the work by taking locks, so no two ever open the same
# file and no argument list has to be split by hand.
#
#   usage: hf-worker.sh <repo> <dir> [rate]
#
# Written after losing 89 GB to two curls on one file. curl opens a resumed
# output in APPEND mode, so a second writer does not overwrite — it interleaves,
# and the result is the byte-exact sum of both downloads. The file looked
# healthy and was not. Three guards, in the order they fire:
#
#   flock   a second worker on the same file skips it instead of joining
#   size    a file larger than the manifest says is truncated, never resumed
#   set -e  a failed curl stops this worker rather than walking to the next
#           file, which is how an orphaned downloader survived a kill and
#           shadowed its replacement for half an hour
set -euo pipefail

REPO=${1:?usage: hf-worker.sh <repo> <dir> [rate]}
DIR=${2:?usage: hf-worker.sh <repo> <dir> [rate]}
RATE=${3:-}
BASE="https://huggingface.co/$REPO/resolve/main"

[ -f "$DIR/MANIFEST" ] || { echo "no $DIR/MANIFEST — run hf-manifest.py first" >&2; exit 1; }

while read -r sha size path; do
    case "$sha" in '#'*|'') continue;; esac

    mkdir -p "$DIR/$(dirname "$path")"
    lockfile="$DIR/$(dirname "$path")/.$(basename "$path").lock"

    exec {lk}>"$lockfile"
    flock -n $lk || { exec {lk}>&-; continue; }   # someone else has it

    have=$(stat -c%s "$DIR/$path" 2>/dev/null || echo 0)
    if [ "$have" -eq "$size" ]; then
        exec {lk}>&-; continue
    fi
    if [ "$have" -gt "$size" ]; then
        echo "$(date +%H:%M:%S) $path — $have > $size, damaged; truncating" >&2
        : > "$DIR/$path"; have=0
    fi

    echo "$(date +%H:%M:%S) $path — $have of $size"
    curl -sL -C - --retry 20 --retry-delay 5 --retry-all-errors \
         ${RATE:+--limit-rate "$RATE"} \
         -o "$DIR/$path" "$BASE/$path" \
         -w "  %{size_download} new bytes at %{speed_download} B/s\n"

    got=$(stat -c%s "$DIR/$path")
    [ "$got" -eq "$size" ] || { echo "FAIL $path: $got, expected $size" >&2; exit 1; }
    exec {lk}>&-
done < "$DIR/MANIFEST"

echo "$(date +%H:%M:%S) worker done"
