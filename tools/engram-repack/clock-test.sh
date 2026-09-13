#!/bin/bash
# Decode tok/s and heat vs CPU P-state. Short runs: 3 x 200 tokens per setting, guard-safe.
set -u
M=/models/DeepSeek-V4.1-Flash-Q3_K_M-engramQ8/DeepSeek-V4.1-Flash-Q3_K_M-00001-of-00009.gguf
setmax() { for p in /sys/devices/system/cpu/cpufreq/policy*; do echo $1 | sudo -n tee $p/scaling_max_freq >/dev/null; done; }
liq() { sudo -n liquidctl status | awk '/Liquid temperature/{print $4}'; }
cput() { sensors | awk '/Tctl/{gsub(/[+°C]/,"",$2); print $2}'; }
PROMPTS=("Explain in detail how a write-ahead log lets a database survive a crash." "Describe step by step what happens when a process touches a swapped-out page." "Why is floating point addition not associative? Give a worked example.")
for f in 3600000 2700000 1800000; do
  setmax $f
  M=$M bash "$(dirname "$0")/../../configs/v41-serve.sh" > /tmp/clock-srv-$f.log 2>&1 & SP=$!
  for i in $(seq 1 120); do curl -sf 127.0.0.1:8001/health >/dev/null && break; sleep 5; done
  # one warm-up so the first sample is not the cold one
  curl -s 127.0.0.1:8001/v1/chat/completions -d '{"messages":[{"role":"user","content":"Say hi."}],"max_tokens":8,"reasoning_effort":"none"}' >/dev/null
  echo "== max=$f  before: liq=$(liq)C cpu=$(cput)C  mhz=$(grep MHz /proc/cpuinfo | awk '{s+=$4} END{printf "%.0f", s/NR}')"
  for p in "${PROMPTS[@]}"; do
    curl -s 127.0.0.1:8001/v1/chat/completions -d "{\"messages\":[{\"role\":\"user\",\"content\":\"$p\"}],\"max_tokens\":200,\"temperature\":0,\"reasoning_effort\":\"none\",\"cache_prompt\":false}" \
      | python3 -c 'import json,sys; t=json.load(sys.stdin)["timings"]; print(f"  prompt {t[\"prompt_n\"]} tok @ {t[\"prompt_per_second\"]:.1f} tok/s   decode {t[\"predicted_n\"]} tok @ {t[\"predicted_per_second\"]:.2f} tok/s")'
    echo "    liq=$(liq)C cpu=$(cput)C"
  done
  kill $SP; while kill -0 $SP 2>/dev/null; do sleep 2; done
  while [ "$(liq | cut -d. -f1)" -gt 40 ]; do sleep 15; done
done
setmax 3600000; echo "restored max=$(cat /sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq)"
echo CLOCK_DONE
