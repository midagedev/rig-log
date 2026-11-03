#!/bin/bash
# Flare rows of the DGX Spark comparison, 2026-11-03: NVIDIA spark-local-inference @cc696a6b serving the package
# `ignition export qwen3.8-flash --gpus 0` built (flare-prep.sh), the way its README starts one. Rows:
#   flare-default  `flare run <package> --gpus 0 --host 127.0.0.1 --port P` (package defaults: its MTP drafts on)
#   flare-nomtp    the same with --mtp-draft-tokens 0
# usage: rows-flare.sh <tag prefix> <package> [row ...]
set -u
PFX=${1:?tag prefix}; PKG=${2:?package}; shift 2; P=18737
F=/opt/engines/flare-cc696a6b/flare/target/release/flare
ver="Flare $(git -C /opt/engines/flare-cc696a6b rev-parse --short=8 HEAD)"
for row in "${@:-flare-default flare-nomtp}"; do
  case $row in
    flare-default) S="$F run $PKG --gpus 0 --host 127.0.0.1 --port $P";;
    flare-nomtp)   S="$F run $PKG --gpus 0 --host 127.0.0.1 --port $P --mtp-draft-tokens 0";;
    *) echo "unknown row $row"; continue;;
  esac
  SERVE="$S" PORT=$P ENGINE="$ver" /root/health/take.sh "$PFX-$row"
done
