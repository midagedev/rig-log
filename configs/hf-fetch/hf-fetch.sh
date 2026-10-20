#!/usr/bin/env bash
# One download worker (hf-worker.sh) as a `fill` grant of the box's resource ledger (boxres). The ledger refuses it,
# rc 75 and naming the holder, while a toktape recording holds nvme0 for its row table, while a timing sitting or a
# rig-log lease is up; otherwise the worker runs in boxres-fill.slice with
# the caps of its grant, and the grant is released when it ends. A download no longer runs outside the ledger.
#
#   usage: hf-fetch.sh <repo> <dir> [rate]        (hf-manifest.py <repo> <dir> first, as for hf-worker.sh)
#
# Run it as many times as the line supports, one grant each. <dir> names the drive: /models is nvme0, anything under /
# else is nvme1 (box-resources.json, nvme.*.mount). BOXRES is the boxres command (default: boxres on PATH; install
# with `ln -s /home/user/signalbox/boxres.py /usr/local/bin/boxres`).
#
# --need ram.anon=2G is a chosen number, not a measured one: curl and bash hold tens of MB. What it sets is the unit's
# MemoryHigh (2.2 GB) and MemoryMax (5 GB), and so how much of the download's page cache stays charged to its own
# cgroup instead of growing the global one (boxres-fill.slice says why that matters).
set -euo pipefail
usage="usage: hf-fetch.sh <repo> <dir> [rate]"
REPO=${1:?$usage}
DIR=${2:?$usage}
RATE=${3:-}
HERE=$(cd "$(dirname "$0")" && pwd)
BOXRES=${BOXRES:-boxres}

command -v "$BOXRES" > /dev/null || {
  echo "hf-fetch: $BOXRES is not on PATH (ln -s /home/user/signalbox/boxres.py /usr/local/bin/boxres)" >&2
  exit 66
}
[ -d "$DIR" ] || { echo "hf-fetch: $DIR is not a directory (run hf-manifest.py $REPO $DIR first)" >&2; exit 66; }
REAL=$(cd "$DIR" && pwd -P)

exec "$BOXRES" run --class fill --holder "hf-${REPO//\//_}" --io "$REAL:bulk" --need ram.anon=2G \
  -- "$HERE/hf-worker.sh" "$REPO" "$DIR" ${RATE:+"$RATE"}
