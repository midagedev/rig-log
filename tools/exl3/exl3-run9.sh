#!/bin/bash
# run9: routing profile (mixed 10 runs, no sweeps) -> static placement from stats vs dynamic; CPU worker knobs (slots, staging threads); faster swap interval. Sentinel EXL3_RUN9_DONE.
say(){ echo "$(date +%H:%M:%S) $*"; }
until [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1)" -lt 2000 ]; do sleep 30; done
say "gpus free: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader | tr "\n" " ") io $(grep some /proc/pressure/io)"
M=/models/GLM-5.3-Flash-exl3-4.05
P=$HOME/.venv-exl3/bin/python
arm(){ tag=$1; b=$2; shift 2; say "== $tag ($b) [$E]: $*  io $(grep some /proc/pressure/io | cut -d" " -f2)"; t0=$(date +%s)
  env $E $P $HOME/$b -m $M -cs 32768 "$@" > $HOME/exl3-$tag.log 2>&1; rc=$?
  say "$tag rc=$rc in $(( $(date +%s)-t0 )) s"; grep -E "loaded in|MiB|decode|prefill|stats dumped|ignored|unpermuted|EXL3_BENCH_OK|Error|error|Traceback" $HOME/exl3-$tag.log | tail -n 16 | sed "s/^/    /"
  sleep 10; }
E="EXL3_MOE_CPU_SWAP_INTERVAL=1000000" arm prof185 exl3-bench5.py -gs 44,21 -mcs 185 -mct 32 -mtp --draft_n 1 --runs 10 --no_prefill --dump_stats $HOME/exl3-stats-mixed.json
E="EXL3_MOE_CPU_SWAP=0 EXL3_MOE_CPU_SPLIT_STATS=$HOME/exl3-stats-mixed.json" arm static185 exl3-bench5.py -gs 44,21 -mcs 185 -mct 32 -mtp --draft_n 1 --runs 10
E="EXL3_MOE_CPU_SLOTS=8" arm slots8 exl3-bench3.py -gs 44,21 -mcs 185 -mct 32 -mtp --draft_n 1 --runs 4 --no_prefill
E="EXL3_MOE_CPU_STAGE_THREADS=8" arm stage8 exl3-bench3.py -gs 44,21 -mcs 185 -mct 32 -mtp --draft_n 1 --runs 4 --no_prefill
E="EXL3_MOE_CPU_SWAP_INTERVAL=32" arm swap32 exl3-bench4.py -gs 44,21 -mcs 185 -mct 32 -mtp --draft_n 1 --runs 10 --no_prefill
say EXL3_RUN9_DONE
