#!/bin/bash
# WKS-22 window: host read bandwidth vs threads at the 2.7 and 3.6 GHz caps, then drafted decode vs -t at the served
# placement (fused build, attnQ8 seven layers). Waits CW_DONE. Coolant gate <= 50 C (guard is 59). Restores 8001.
say(){ echo "$(date +%H:%M:%S) $*"; }
io(){ grep some /proc/pressure/io | sed 's/ total=.*//'; }
liq(){ sudo -n liquidctl status 2>/dev/null | awk '/Liquid temperature/{print int($4)}'; }
cool(){ for i in $(seq 1 80); do t=$(liq); [ "${t:-99}" -le 50 ] && break; sleep 15; done; say "coolant $(liq) C"; }
until grep -q CW_DONE ~/cache-window.log 2>/dev/null; do sleep 30; done
gcc -O2 -mavx2 -fopenmp -o ~/bw ~/bw.c || { say "bw build failed"; exit 1; }
say "window start  $(io)"
for pid in $(pgrep -x llama-server); do say "stopping llama-server $pid"; kill "$pid"; while kill -0 "$pid" 2>/dev/null; do sleep 2; done; done
echo $$ > /tmp/cpu-busy.flag
revert(){ sudo -n /usr/local/sbin/cpu-clockcap 2700000 >/dev/null; rm -f /tmp/cpu-busy.flag; }
trap revert EXIT
say "THP: $(cat /sys/kernel/mm/transparent_hugepage/enabled)  numa: $(numactl -H 2>/dev/null | head -1)"
for cap in 2700000 3600000; do
  cool
  sudo -n /usr/local/sbin/cpu-clockcap $cap >/dev/null; say "cap $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq)"
  for t in 4 8 16 24 32 48 64; do echo "  cap $cap  $(OMP_PROC_BIND=spread OMP_PLACES=cores ~/bw $t 16 5)"; done
  echo "  cap $cap  no-bind $(~/bw 32 16 5)"
  echo "  cap $cap  numa-interleave $(numactl --interleave=all ~/bw 32 16 5 2>/dev/null || echo n/a)"
done
sudo -n /usr/local/sbin/cpu-clockcap 2700000 >/dev/null; say "cap back to 2.7 GHz"
B=~/llama.cpp-v41-merged/build/bin/llama-server
G=/models/DeepSeek-V4.1-Flash-Q3_K_M-engramQ8-tokembdBF16-attnQ8/DeepSeek-V4.1-Flash-Q3_K_M-00001-of-00009.gguf
D=/models/DeepSeek-V4.1-Flash-DSpark/DeepSeek-V4.1-Flash-Fp8-128x742M-MXFP4_MOE.tl37.gguf
OT7='blk\.[0-3]\.ffn_.*_exps=CUDA0,blk\.6\.ffn_down_exps=CUDA0,blk\.[4-5]\.ffn_.*_exps=CUDA1,blk\.6\.ffn_(gate|up)_exps=CUDA1,exps=CPU'
P=8099
export CUDA_DEVICE_ORDER=PCI_BUS_ID
for t in 16 24 48 64; do
  say "== decode -t $t  $(io)"
  "$B" -m "$G" -c 16384 -ngl 99 -t $t -b 2048 -ub 512 --lazy-mode auto -ot "$OT7" -md "$D" --spec-type draft-dspark --spec-draft-n-max 3 -otd "output_norm=CUDA0" --host 127.0.0.1 --port $P > ~/bw-t$t.log 2>&1 &
  pid=$!; echo $pid > ~/bw-t$t.pid
  until curl -s -m 2 localhost:$P/health | grep -q ok; do if ! kill -0 $pid 2>/dev/null; then say "-t $t died"; break; fi; sleep 5; done
  kill -0 $pid 2>/dev/null || continue
  for pass in 1 2; do
    cool
    python3 - "$t" "$pass" "$P" <<'PY'
import json, sys, urllib.request, statistics
t, pss, port = sys.argv[1], sys.argv[2], sys.argv[3]
rates=[]
for line in open("/home/user/rig-log-prompts.jsonl"):
    p=json.loads(line)["prompt"]
    body={"prompt":p,"n_predict":200,"temperature":0,"cache_prompt":False}
    r=json.load(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/completion", json.dumps(body).encode(), {"Content-Type":"application/json"}), timeout=900))
    rates.append(r["timings"]["predicted_per_second"])
print("  == -t %s pass %s: median %.2f (min %.2f max %.2f)" % (t, pss, statistics.median(rates), min(rates), max(rates)), flush=True)
PY
  done
  kill $pid; while kill -0 $pid 2>/dev/null; do sleep 2; done
done
say "restoring 8001"
nohup bash ~/rig-log-v41-serve.sh > /tmp/llm-serve.log 2>&1 < /dev/null & echo $! > /tmp/llm-serve.pid
until curl -s -m 2 localhost:8001/health | grep -q ok; do sleep 10; done
say "8001 back"; say BW_DONE
