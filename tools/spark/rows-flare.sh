#!/bin/bash
# Flare rows of the DGX Spark comparison, 2026-11-03: NVIDIA spark-local-inference @cc696a6b serving the package
# `ignition export qwen3.8-flash --gpus 0` built (flare-prep.sh), the way its README starts one. Rows:
#   flare-default  `flare run <package> --gpus 0 --host 127.0.0.1 --port P` (package defaults: its MTP drafts on)
#   flare-nomtp    the same with --mtp-draft-tokens 0
# An unattended first run of a package asks for its signing key: the package is signed by the local development key
# `flare` made at export (~/.config/flare), so the fingerprint is that key's (sha256 of its raw public key; it matched the
# one the refused run printed, 2026-11-04); namespace local-development.
# usage: rows-flare.sh <tag prefix> <package> [row ...]
set -u
PFX=${1:?tag prefix}; PKG=${2:?package}; shift 2; P=18737
F=/opt/engines/flare-cc696a6b/flare/target/release/flare
KEY=$(openssl pkey -in /root/.config/flare/development-signing-key.pem -pubout -outform DER | tail -c 32 | sha256sum | cut -d' ' -f1)
APPROVE="--dangerously-approve-key $KEY --dangerously-accept-publisher local-development"
ver="Flare $(git -C /opt/engines/flare-cc696a6b rev-parse --short=8 HEAD)"
[ $# -gt 0 ] || set -- flare-default flare-nomtp
for row in "$@"; do
  case $row in
    flare-default) S="$F run $PKG --gpus 0 --host 127.0.0.1 --port $P $APPROVE";;
    flare-nomtp)   S="$F run $PKG --gpus 0 --host 127.0.0.1 --port $P --mtp-draft-tokens 0 $APPROVE";;
    *) echo "unknown row $row"; continue;;
  esac
  SERVE="$S" PORT=$P ENGINE="$ver" /root/health/take.sh "$PFX-$row"
done
