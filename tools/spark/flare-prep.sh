#!/bin/bash
# Prepare Flare's Qwen3.8 package on the DGX Spark, 2026-11-03 (user's yes to the machine time, 11-03 22:12 KST).
# Flare serves only packages Ignition exports; its qwen3.8-flash recipe pins nvidia/Qwen3.8-Flash-Next-FP4-Local at
# b9ce18a6, the commit /models/Qwen3.8-Flash-Next-FP4-Local was fetched at (and hash-checked against). So the hub
# snapshot Ignition looks for is made of symlinks into that folder, and nothing is downloaded (HF_HUB_OFFLINE=1).
# Export with the recipe's defaults (32 requests, five MTP drafts) on GPU 0, under the quiet lease so no take runs beside
# it. The fetches keep running: an export is not a measurement, and the link is the schedule's bottleneck. Writes /root/health/flare-prep.log; the package path export prints is its last line.
# usage (root): flare-prep.sh   sentinel FLARE_PREP_DONE rc=<n>
set -u
H=/root/health; F=/opt/engines/flare-cc696a6b; M=/models/Qwen3.8-Flash-Next-FP4-Local
REV=b9ce18a6887e18c089fdea8509a33e63429a3300
SNAP=/root/.cache/huggingface/hub/models--nvidia--Qwen3.8-Flash-Next-FP4-Local/snapshots/$REV
say(){ echo "$(date -u +%H:%M:%SZ) $*"; }
mkdir -p "$SNAP" "$(dirname "$SNAP")/../refs"
echo -n $REV > "$(dirname "$SNAP")/../refs/main"
( cd "$M" && find . -type f ! -name '.fetch-verified' ! -path './.fetch/*' ) | while read -r f; do
  mkdir -p "$SNAP/$(dirname "$f")"; ln -sfn "$M/${f#./}" "$SNAP/${f#./}"; done
say "snapshot: $(find "$SNAP" -type l | wc -l) links"
export QUIET_LEASE=/root/spark-lease QUIET_LEASE_PID=$$
"$H/lease.sh" acquire "flare-prep" || { echo "FLARE_PREP_DONE rc=1"; exit 1; }
trap '"$H/lease.sh" release >/dev/null 2>&1' EXIT
sync; echo 3 > /proc/sys/vm/drop_caches
say "export"
cd "$F" && HF_HUB_OFFLINE=1 /usr/bin/time -v .venv/bin/ignition export qwen3.8-flash --gpus 0 2>&1; rc=$?
say "export rc=$rc"
echo "FLARE_PREP_DONE rc=$rc"
