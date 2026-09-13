#!/bin/bash
# Package power (RAPL energy_uj delta) and prefill/decode rate vs P-state. One long prompt + 200 decode per clock.
set -u
M=/models/DeepSeek-V4.1-Flash-Q3_K_M-engramQ8/DeepSeek-V4.1-Flash-Q3_K_M-00001-of-00009.gguf
E=/sys/class/powercap/intel-rapl:0/energy_uj
setmax() { for p in /sys/devices/system/cpu/cpufreq/policy*; do echo $1 | sudo -n tee $p/scaling_max_freq >/dev/null; done; }
liq() { sudo -n liquidctl status | awk '/Liquid temperature/{print $4}'; }
cput() { sensors 2>/dev/null | awk '/Tctl/{gsub(/[+°C]/,"",$2); print $2}'; }
LONG=$(python3 -c "print(' '.join(open('/home/user/eval/wiki.test.raw').read().split()[:1100]))")
python3 - "$LONG" > /tmp/power-req.json <<'PY'
import json,sys; json.dump({"messages":[{"role":"user","content":"Summarize the following text in one paragraph.\n\n"+sys.argv[1]}],"max_tokens":200,"temperature":0,"reasoning_effort":"none","cache_prompt":False},open("/tmp/power-req.json","w"))
PY
for f in 3600000 2700000 1800000; do
  setmax $f
  while [ "$(liq | cut -d. -f1)" -gt 39 ]; do sleep 15; done
  M=$M bash "$(dirname "$0")/../../configs/v41-serve.sh" > /tmp/power-srv-$f.log 2>&1 & SP=$!
  for i in $(seq 1 120); do curl -sf 127.0.0.1:8001/health >/dev/null && break; sleep 5; done
  sleep 5
  e0=$(sudo -n cat $E); t0=$(date +%s.%N)
  IDLE=$(python3 -c "import time;time.sleep(5);print('x')")
  e1=$(sudo -n cat $E); t1=$(date +%s.%N)
  idle_w=$(python3 -c "print(round(($e1-$e0)/1e6/($t1-$t0),1))")
  echo "== max=$f idle: ${idle_w} W  liq=$(liq)C cpu=$(cput)C"
  for rep in 1 2; do
    e0=$(sudo -n cat $E); t0=$(date +%s.%N)
    curl -s 127.0.0.1:8001/v1/chat/completions -d @/tmp/power-req.json -o /tmp/power-resp-$f-$rep.json
    e1=$(sudo -n cat $E); t1=$(date +%s.%N)
    python3 - $f $rep $e0 $e1 $t0 $t1 <<'PY'
import json,sys; f,rep,e0,e1,t0,t1=sys.argv[1:]; t=json.load(open(f"/tmp/power-resp-{f}-{rep}.json"))["timings"]
w=(float(e1)-float(e0))/1e6/(float(t1)-float(t0))
print(f"  rep{rep}: prefill {t['prompt_n']} tok @ {t['prompt_per_second']:.1f} tok/s | decode {t['predicted_n']} tok @ {t['predicted_per_second']:.2f} tok/s | avg pkg {w:.0f} W over {float(t1)-float(t0):.1f}s")
PY
    echo "    liq=$(liq)C cpu=$(cput)C"
  done
  kill $SP; while kill -0 $SP 2>/dev/null; do sleep 2; done
done
setmax 3600000; echo "restored max=$(cat /sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq)"
echo POWER_DONE
