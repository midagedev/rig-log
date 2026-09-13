#!/bin/bash
# Lead takeover of the engram-attrib embd phase. The delegate hit its session
# limit; its driver is still alive but will abort at finalize, because shard 05
# is being written by a process it does not own (the lead started it to run the
# two shards in parallel). Wait for both, finalize, measure with the driver's
# own command line so the number is comparable.
set -u
A=$HOME/engram-attrib
D=/models/DeepSeek-V4.1-Flash-Q3_K_M-engram-embdQ8
for p in 1019936 1033592; do
  while kill -0 $p 2>/dev/null; do sleep 20; done
  echo "$(date +%T) repack pid $p finished"
done
for i in 02 05; do
  [ -f "$D/logs/done-$i.json" ] || { echo "MISSING marker done-$i.json — not finalizing"; exit 1; }
done
echo "$(date +%T) both markers present; finalizing"
bash "$A/finalize_variant.sh" "$D" 2>&1 | tee "$A/logs/finalize-embd.lead.log" | tail -3
# Never pgrep -f here: -x matches the 15-char comm name, not this shell's args.
while p=$(pgrep -x llama-perplexit | head -1); [ -n "$p" ]; do
  echo "$(date +%T) waiting for llama-perplexity pid $p"
  while kill -0 "$p" 2>/dev/null; do sleep 20; done
done
echo "$(date +%T) ppl start; liq=$(sudo -n liquidctl status | awk '/Liquid/{print $4}')C"
cd "$HOME/llama.cpp-v41" && CUDA_VISIBLE_DEVICES="" nice -n 10 build/bin/llama-perplexity \
  -m "$D/DeepSeek-V4.1-Flash-Q3_K_M-00001-of-00009.gguf" \
  -f "$HOME/eval/wiki.test.raw" -c 2048 --chunks 4 -b 2048 -ngl 0 -t 32 > /tmp/ppl-attrib-embd.log 2>&1
cp /tmp/ppl-attrib-embd.log "$A/logs/ppl-attrib-embd.log"
grep -E "^\[|Final estimate" /tmp/ppl-attrib-embd.log
du -sh "$D"; df -h /models | tail -1
echo EMBD_DONE
