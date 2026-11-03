#!/bin/bash
# GGUF rows of the DGX Spark comparison, 2026-11-03: bloomery and mainline llama.cpp on the same file, one take.sh row
# after another. Rows:
#   bloomery-default  `-m <file>` and nothing else (draft on where the file carries an MTP layer)
#   bloomery-rec      bloomery README's Spark servers: BLOOMERY_HOST_ROOM=96G --parallel 1 --ctx-size 16896, BLOOMERY_DRAFT=mtp
#                     (plus BLOOMERY_MTP_DRAFT=<file> when DRAFT names a separate draft GGUF)
#   bloomery-nomtp    rec with BLOOMERY_DRAFT=off
#   llamacpp-default  `llama-server -m <file>` and nothing else (no draft)
#   llamacpp-rec      NVIDIA's dgx-spark-playbooks nvidia/llama-cpp step 4: --spec-type draft-mtp --spec-draft-n-max 3
#                     (playbook's preserve_thinking kwarg left out: the takes ask no-think and carry no history)
# usage: [DRAFT=<draft gguf>] rows-gguf.sh <tag prefix> <first gguf> [row ...]
set -u
PFX=${1:?tag prefix}; M=${2:?gguf}; shift 2
B=$(ls -d /opt/engines/bloomery-v0.3.12/*/bin)/bloomery-serve; L=/opt/engines/llama.cpp-b12069/build/bin/llama-server
D=${DRAFT:+BLOOMERY_MTP_DRAFT=$DRAFT }
rec="BLOOMERY_HOST_ROOM=96G $B -m $M --host 127.0.0.1 --port 18731 --parallel 1 --ctx-size 16896"
for r in "${@:-bloomery-default bloomery-rec bloomery-nomtp llamacpp-default llamacpp-rec}"; do for row in $r; do
  case $row in
    bloomery-default) S="$B -m $M --host 127.0.0.1 --port 18731"; P=18731; E="bloomery 0.3.12";;
    bloomery-rec)     S="${D}BLOOMERY_DRAFT=mtp $rec"; P=18731; E="bloomery 0.3.12";;
    bloomery-nomtp)   S="BLOOMERY_DRAFT=off $rec"; P=18731; E="bloomery 0.3.12";;
    llamacpp-default) S="$L -m $M --host 127.0.0.1 --port 18732"; P=18732; E="llama.cpp b12069";;
    llamacpp-rec)     S="$L -m $M --host 127.0.0.1 --port 18732 --spec-type draft-mtp --spec-draft-n-max 3"; P=18732; E="llama.cpp b12069";;
    *) echo "unknown row $row"; continue;;
  esac
  SERVE="$S" PORT=$P ENGINE="$E" /root/health/take.sh "$PFX-$row"
done; done
