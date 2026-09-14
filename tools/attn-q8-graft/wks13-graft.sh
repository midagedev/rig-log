#!/bin/bash
# WKS-13: after prefill window 4 closes, graft attention/shexp/indexer Q8_0 tensors into a new shard set
# (idle IO priority, 8001 keeps serving), then a quiet perplexity window on the grafted file with the same
# command as the baseline, then a load test of the grafted file with the served placement, then 8001 back.
say(){ echo "$(date +%H:%M:%S) $*"; }
io(){ grep some /proc/pressure/io | sed 's/ total=.*//'; }
export PYTHONPATH=$HOME/llama.cpp-v41/gguf-py
PY=$HOME/.venv-gguf/bin/python
$PY -c "import gguf, numpy" || { say "python env broken"; exit 1; }
until grep -q PREFILL4_DONE ~/prefill-window4.log 2>/dev/null; do sleep 30; done
say "prefill window 4 closed  $(io)"
$PY ~/graft-attn-q8.py --dry-run || exit 1
say "graft start  $(io)"
nice -n 19 ionice -c3 $PY ~/graft-attn-q8.py || { say "GRAFT FAILED"; exit 1; }
say "graft done  $(io)"
ls -la /models/DeepSeek-V4.1-Flash-Q3_K_M-engramQ8-tokembdBF16-attnQ8/
say "stopping 8001 for the perplexity window"
for pid in $(pgrep -x llama-server); do kill "$pid"; while kill -0 "$pid" 2>/dev/null; do sleep 2; done; done
G=/models/DeepSeek-V4.1-Flash-Q3_K_M-engramQ8-tokembdBF16-attnQ8/DeepSeek-V4.1-Flash-Q3_K_M-00001-of-00009.gguf
say "perplexity attnQ8  $(io)"
~/llama.cpp-v41/build/bin/llama-perplexity -m $G -f ~/eval/wiki.test.raw -c 2048 --chunks 4 -b 2048 -ngl 0 -t 32 > ~/ppl-attnQ8.log 2>&1
say "ppl done  $(io)  $(grep -o 'Final estimate.*' ~/ppl-attnQ8.log)"
say "load test: served placement on the grafted file"
export CUDA_DEVICE_ORDER=PCI_BUS_ID
M=$G nohup bash ~/rig-log-v41-serve.sh > ~/serve-attnQ8.log 2>&1 < /dev/null & spid=$!; echo $spid > ~/serve-attnQ8.pid
for i in $(seq 1 120); do curl -s -m 2 localhost:8001/health | grep -q ok && break; kill -0 $spid 2>/dev/null || break; sleep 5; done
if curl -s -m 2 localhost:8001/health | grep -q ok; then
  say "attnQ8 up  $(grep -o 'CUDA[01] compute buffer size = *[0-9.]* MiB' ~/serve-attnQ8.log | tr '\n' ' ')"; nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
  for pass in 1 2; do
    python3 -c 'import json; print(json.dumps({"prompt":"Write a short essay on why memory bandwidth, not compute, bounds decoding for mixture-of-experts models on consumer hardware.","n_predict":200,"temperature":0,"cache_prompt":False}))' > /tmp/aq-req.json
    curl -s -m 600 localhost:8001/completion -d @/tmp/aq-req.json | python3 -c 'import json,sys; t=json.load(sys.stdin)["timings"]; print("  attnQ8 decode pass '$pass': %.2f tok/s (%d tok)" % (t["predicted_per_second"], t["predicted_n"]))'
  done
  say "attnQ8 decode rows above  $(io)"
  kill $spid; while kill -0 $spid 2>/dev/null; do sleep 2; done
else
  say "attnQ8 did not come up: $(grep -m1 -iE 'out of memory|error' ~/serve-attnQ8.log | cut -c1-200)"; kill $spid 2>/dev/null
fi
say "restoring 8001 (served file)"
nohup bash ~/rig-log-v41-serve.sh > /tmp/llm-serve.log 2>&1 < /dev/null & echo $! > /tmp/llm-serve.pid
until curl -s -m 2 localhost:8001/health | grep -q ok; do sleep 10; done
say "8001 back"; say WKS13_DONE
