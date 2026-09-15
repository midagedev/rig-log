#!/bin/bash
# run8: mixed-prompt steady state (bench2 alternates 5 prompts), MTP draft, thread count. Sentinel EXL3_RUN8_DONE.
say(){ echo "$(date +%H:%M:%S) $*"; }
until [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1)" -lt 2000 ]; do sleep 30; done
say "gpus free: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader | tr "\n" " ") io $(grep some /proc/pressure/io)"
M=/models/GLM-5.3-Flash-exl3-4.05
P=$HOME/.venv-exl3/bin/python
arm(){ tag=$1; b=$2; shift 2; say "== $tag ($b): $*  io $(grep some /proc/pressure/io | cut -d" " -f2)"; t0=$(date +%s)
  $P $HOME/$b -m $M -cs 32768 "$@" > $HOME/exl3-$tag.log 2>&1; rc=$?
  say "$tag rc=$rc in $(( $(date +%s)-t0 )) s"; grep -E "loaded in|MiB|decode|prefill|EXL3_BENCH_OK|Error|error|Traceback" $HOME/exl3-$tag.log | tail -n 16 | sed "s/^/    /"
  sleep 10; }
arm mix185n1 exl3-bench4.py -gs 44,21 -mcs 185 -mct 32 -mtp --draft_n 1 --runs 10
say EXL3_RUN8_DONE
