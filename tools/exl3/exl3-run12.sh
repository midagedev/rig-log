#!/bin/bash
# run12: routing profile (mixed 10 runs, no sweeps) -> static placement from stats vs dynamic; CPU worker knobs (slots, staging threads); faster swap interval. Sentinel EXL3_RUN12_DONE.
say(){ echo "$(date +%H:%M:%S) $*"; }
until grep -q "EXL3_RUN11_DONE" /home/user/exl3-run11.log; do sleep 15; done
until [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1)" -lt 2000 ]; do sleep 30; done
say "gpus free: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader | tr "\n" " ") io $(grep some /proc/pressure/io)"
M=/models/GLM-5.3-Flash-exl3-4.05
P=$HOME/.venv-exl3/bin/python
arm(){ tag=$1; b=$2; shift 2; say "== $tag ($b) [$E]: $*  io $(grep some /proc/pressure/io | cut -d" " -f2)"; t0=$(date +%s)
  env $E $P $HOME/$b -m $M -cs 32768 "$@" > $HOME/exl3-$tag.log 2>&1; rc=$?
  say "$tag rc=$rc in $(( $(date +%s)-t0 )) s"; grep -E "loaded in|MiB|decode|prefill|stats dumped|ignored|unpermuted|EXL3_BENCH_OK|Error|error|Traceback" $HOME/exl3-$tag.log | tail -n 16 | sed "s/^/    /"
  sleep 10; }
E="EXL3_MOE_CPU_SWAP=0 EXL3_MOE_CPU_SPLIT_STATS=$HOME/exl3-stats-mixed.json" arm staticfix250 exl3-bench6.py -gs 44,21 -mcs 250 -mct 32 -mtp --draft_n 1 --runs 3 --no_prefill --patch_defer
E="EXL3_MOE_CPU_SPLIT=250 EXL3_MOE_CPU_SWAP=0 EXL3_MOE_CPU_SPLIT_STATS=$HOME/exl3-stats-mixed.json" arm staticenv250 exl3-bench5.py -gs 44,21 -mcs 250 -mct 32 -mtp --draft_n 1 --runs 3 --no_prefill
E="EXL3_MOE_CPU_SWAP=0 EXL3_MOE_CPU_SPLIT_STATS=$HOME/exl3-stats-mixed.json" arm staticbug250 exl3-bench5.py -gs 44,21 -mcs 250 -mct 32 -mtp --draft_n 1 --runs 3 --no_prefill
say "answers tail:"; tail -n 9 $HOME/exl3-ans2.txt | cut -c1-120
say EXL3_RUN12_DONE
