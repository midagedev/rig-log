#!/bin/bash
# run5: does dynamic placement keep converging past 3 runs, and how far can -mcs go down using the 3090. Sentinel EXL3_RUN5_DONE.
say(){ echo "$(date +%H:%M:%S) $*"; }
until [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1)" -lt 2000 ]; do sleep 30; done
say "gpus free: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader | tr "\n" " ") io $(grep some /proc/pressure/io)"
M=/models/GLM-5.3-Flash-exl3-4.05
P=~/.venv-exl3/bin/python
arm(){ tag=$1; shift; say "== $tag: $*  io $(grep some /proc/pressure/io | cut -d" " -f2)"; t0=$(date +%s)
  $P ~/exl3-bench.py -m $M -cs 32768 "$@" > ~/exl3-$tag.log 2>&1; rc=$?
  say "$tag rc=$rc in $(( $(date +%s)-t0 )) s"; grep -E "loaded in|MiB|decode|prefill|EXL3_BENCH_OK|Error|error|Traceback" ~/exl3-$tag.log | tail -n 16 | sed "s/^/    /"
  sleep 10; }
arm mcs195r10 -gs 44,21 -mcs 195 -mct 32 --runs 10 --no_prefill
arm mcs185 -gs 44,21 -mcs 185 -mct 32 --runs 6
arm mcs175 -gs 44,21 -mcs 175 -mct 32 --runs 6
say EXL3_RUN5_DONE
