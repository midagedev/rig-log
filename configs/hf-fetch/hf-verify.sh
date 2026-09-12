#!/usr/bin/env bash
# The gate. "510 GB downloaded" is not a claim worth making; "510 GB whose
# sha256 matches what the publisher stored" is. Sizes were right on a file
# that turned out to be two interleaved streams, so size is not the test.
#
#   usage: hf-verify.sh <dir>
set -uo pipefail
DIR=${1:?usage: hf-verify.sh <dir>}
cd "$DIR"

missing=0
while read -r sha size path; do
    case "$sha" in '#'*|'') continue;; esac
    have=$(stat -c%s "$path" 2>/dev/null || echo 0)
    if [ "$have" -ne "$size" ]; then
        echo "INCOMPLETE  $path ($have of $size)"; missing=$((missing+1))
    fi
done < MANIFEST
[ "$missing" -eq 0 ] || { echo "$missing file(s) incomplete; not hashing"; exit 1; }

sha256sum -c SHA256SUMS
