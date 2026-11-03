#!/bin/bash
# The bloomery rows of board 1 (Qwen3.8-Flash-Next) on the DGX Spark, 2026-11-03, one take.sh row after another.
# default = `-m <folder>` and nothing else; rec = the servers of bloomery docs/dgx-spark.md section 6 (the README Spark
# table's); nomtp = rec with BLOOMERY_DRAFT=off, so the draft's share of decode is read on the same settings.
# usage: rows-bloomery-q38.sh <folder name under /models> [row ...]   rows: default rec nomtp (default: all three)
set -u
F=${1:?folder}; shift; M=/models/$F; B=$(ls -d /opt/engines/bloomery-v0.3.12/*/bin)/bloomery-serve
short=$(echo "$F" | sed 's/Qwen3.8-Flash-Next-/q38-/; s/Qwen3.6-35B-A3B-/q36-/' | tr 'A-Z' 'a-z')
common="--host 127.0.0.1 --port 18731"
rec="BLOOMERY_HOST_ROOM=96G BLOOMERY_MTP_WIDTH=cost $B -m $M $common --parallel 1 --ctx-size 16896"
for r in "${@:-default rec nomtp}"; do for row in $r; do
  case $row in
    default) S="$B -m $M $common";;
    rec)     S="BLOOMERY_DRAFT=mtp $rec";;
    nomtp)   S="BLOOMERY_DRAFT=off $rec";;
  esac
  SERVE="$S" PORT=18731 ENGINE="bloomery 0.3.12" /root/health/take.sh "$short-bloomery-$row"
done; done
