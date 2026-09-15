#!/bin/bash
# exllamav3 1.5.0 on turboderp GLM-5.3-Flash-exl3 4.05bpw, first arms. Waits for both GPUs under 2000 MiB (webuta's run ends ~14:30). Sentinel EXL3_RUN4_DONE.
say(){ echo "$(date +%H:%M:%S) $*"; }
until [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1)" -lt 2000 ]; do sleep 30; done
say "gpus free: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader | tr '\n' ' ') io avg10=$(awk '/some/{print $2}' /proc/pressure/io)"
M=/models/GLM-5.3-Flash-exl3-4.05
P=~/.venv-exl3/bin/python
arm(){ tag=$1; shift; say "== $tag: $*"; t0=$(date +%s)
  $P ~/exl3-bench.py -m $M -cs 32768 "$@" > ~/exl3-$tag.log 2>&1; rc=$?
  say "$tag rc=$rc in $(( $(date +%s)-t0 )) s"; grep -E "loaded in|MiB|decode|prefill|EXL3_BENCH_OK|Error|error|Traceback" ~/exl3-$tag.log | tail -n 12 | sed 's/^/    /'
  sleep 10; }
arm mcs230 -gs 44,21 -mcs 230 -mct 32
arm mcs210 -gs 44,21 -mcs 210 -mct 32
arm mcs195 -gs 44,21 -mcs 195 -mct 32
say EXL3_RUN4_DONE
