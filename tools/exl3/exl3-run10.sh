#!/bin/bash
# run10: routing profile (mixed 10 runs, no sweeps) -> static placement from stats vs dynamic; CPU worker knobs (slots, staging threads); faster swap interval. Sentinel EXL3_RUN10_DONE.
say(){ echo "$(date +%H:%M:%S) $*"; }
until grep -q "llama-server stopped" /home/user/hero-take4.log; do sleep 15; done
until [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1)" -lt 2000 ]; do sleep 30; done
say "gpus free: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader | tr "\n" " ") io $(grep some /proc/pressure/io)"
M=/models/GLM-5.3-Flash-exl3-4.05
P=$HOME/.venv-exl3/bin/python
arm(){ tag=$1; b=$2; shift 2; say "== $tag ($b) [$E]: $*  io $(grep some /proc/pressure/io | cut -d" " -f2)"; t0=$(date +%s)
  env $E $P $HOME/$b -m $M -cs 32768 "$@" > $HOME/exl3-$tag.log 2>&1; rc=$?
  say "$tag rc=$rc in $(( $(date +%s)-t0 )) s"; grep -E "loaded in|MiB|decode|prefill|stats dumped|ignored|unpermuted|EXL3_BENCH_OK|Error|error|Traceback" $HOME/exl3-$tag.log | tail -n 16 | sed "s/^/    /"
  sleep 10; }
E="EXL3_MOE_CPU_SPLIT=185 EXL3_MOE_CPU_SWAP=0 EXL3_MOE_CPU_SPLIT_STATS=$HOME/exl3-stats-mixed.json" arm static185env exl3-bench5.py -gs 44,21 -mcs 185 -mct 32 -mtp --draft_n 1 --runs 5 --no_prefill
E="EXL3_MOE_CPU_SWAP=0" arm static185nostats exl3-bench5.py -gs 44,21 -mcs 185 -mct 32 -mtp --draft_n 1 --runs 5 --no_prefill
E="X=1" arm mcl30d3 exl3-bench3.py -gs 44,21 -mcl 30 -mct 32 -mtp --runs 4 --no_prefill
E="X=1" arm mcl30d1 exl3-bench3.py -gs 44,21 -mcl 30 -mct 32 -mtp --draft_n 1 --runs 4 --no_prefill
say "answers tail:"; tail -n 10 $HOME/exl3-ans2.txt | cut -c1-120; tail -n 8 $HOME/exl3-ans.txt | cut -c1-120
say EXL3_RUN10_DONE
