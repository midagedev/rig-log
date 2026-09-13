#!/bin/bash
# ik_llama.cpp vs mainline llama.cpp: same file, same placement, same raw
# prompts, on a quiet machine. Raw /completion on both, because ik's --jinja
# renders the V4.1 template without </think> for reasoning_effort none, which
# would make the two engines answer different prompts.
#
# Gates itself on a quiet box first: no perplexity run, no repack, coolant at
# or below 42 C. The guard stops llama-server at 52 C after about five minutes
# of 32-thread decode, so a hot start would truncate the second engine.
set -u
M=/models/DeepSeek-V4.1-Flash-Q3_K_M-engramQ8/DeepSeek-V4.1-Flash-Q3_K_M-00001-of-00009.gguf
OT='blk\.[0-3]\.ffn_.*_exps=CUDA0,blk\.[4-5]\.ffn_.*_exps=CUDA1,exps=CPU'
PROMPTS=(
 "Explain in detail how a write-ahead log lets a database survive a crash."
 "Describe step by step what happens when a process touches a swapped-out page."
 "Why is floating point addition not associative? Give a worked example."
)
liq() { sudo -n liquidctl status | awk '/Liquid temperature/{print int($4)}'; }

# Never pgrep -f: the pattern would match this script's own command line and
# the wait would never end. -x matches the 15-char comm name instead, and the
# repack check reads /proc/<pid>/cmdline for pids that are already python.
# Everything that makes a throughput number meaningless. The first version of
# this script checked only for perplexity and repack, and so it happily ran
# during a 472 GB sha256sum -c and against a llama-server it did not start.
busy_reason() {
  local p pid cmd
  for p in llama-perplexit llama-server sha256sum; do
    pid=$(pgrep -x "$p" | head -1 || true)
    [ -n "$pid" ] && { echo "$p $pid"; return; }
  done
  for pid in $(pgrep -x python || true) $(pgrep -x python3 || true); do
    cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)
    case "$cmd" in *repack_variant*|*repack.py*) echo "repack $pid"; return ;; esac
  done
  echo ""
}
wait_quiet() {
  local b l
  while :; do
    b=$(busy_reason); l=$(liq)
    [ -z "$b" ] && [ -n "$l" ] && [ "$l" -le 42 ] && break
    echo "$(date +%T) waiting: ${b:-cooling} liq=${l}C"
    sleep 30
  done
  echo "$(date +%T) quiet: liq=$(liq)C load=$(cut -d' ' -f1 /proc/loadavg)"
}
measure() {  # $1 label, $2 port
  local p
  for p in "${PROMPTS[@]}"; do
    python3 -c 'import json,sys; print(json.dumps({"prompt":"<｜User｜>"+sys.argv[1]+"<｜Assistant｜></think>","n_predict":200,"temperature":0,"cache_prompt":False}))' "$p" > /tmp/ab-req.json
    curl -s "127.0.0.1:$2/completion" -d @/tmp/ab-req.json > /tmp/ab-resp.json
    python3 -c '
import json,sys
r=json.load(open("/tmp/ab-resp.json")); t=r["timings"]
print("  %s: prefill %d @ %.1f | decode %d @ %.2f tok/s" % (sys.argv[1], t["prompt_n"], t["prompt_per_second"], t["predicted_n"], t["predicted_per_second"]))' "$1"
  done
  echo "  after: liq=$(liq)C load=$(cut -d' ' -f1 /proc/loadavg)"
}
run() {  # $1 label, $2 port, $3.. server argv
  local label=$1 port=$2 SP i ready=""; shift 2
  # A free port is a precondition, not a detail: a stranger already listening
  # answers /health and the measurement silently becomes a measurement of it.
  if ss -ltn | grep -q ":$port "; then
    echo "ABORT: port $port already has a listener; refusing to measure someone else's server"
    ss -ltnp 2>/dev/null | grep ":$port " | sed 's/^/  /'
    return 1
  fi
  if [ -n "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)" ]; then
    echo "ABORT: another process holds a GPU; $label would load into what is left"
    nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader | sed 's/^/  /'
    return 1
  fi
  "$@" > "/tmp/ab-srv-$label.log" 2>&1 & SP=$!
  # Wait for THIS server's own log to say it is serving, then confirm health.
  for i in $(seq 1 180); do
    kill -0 $SP 2>/dev/null || { echo "$label server died after $((i*5))s"; tail -4 "/tmp/ab-srv-$label.log"; return 1; }
    if grep -q -E "server is listening|HTTP server listening|listening on http|main loop" "/tmp/ab-srv-$label.log" 2>/dev/null; then
      curl -sf "127.0.0.1:$port/health" >/dev/null && { ready=1; break; }
    fi
    sleep 5
  done
  [ -n "$ready" ] || { echo "$label never became ready"; tail -4 "/tmp/ab-srv-$label.log"; kill $SP 2>/dev/null; return 1; }
  echo "$(date +%T) $label up as pid $SP"
  curl -s "127.0.0.1:$port/completion" -d '{"prompt":"hi","n_predict":4,"temperature":0}' >/dev/null
  echo "== $label"
  grep -E "fused_moe|flash_attn|mla_attn|^.*ser +=" "/tmp/ab-srv-$label.log" | sed 's/^/  /' | head -4
  measure "$label" "$port"
  kill $SP; while kill -0 $SP 2>/dev/null; do sleep 2; done
  echo "$(date +%T) $label stopped"
}
wait_quiet
run mainline 8001 "$HOME/llama.cpp-v41/build/bin/llama-server" -m "$M" -c 16384 -ngl 99 -t 32 -b 2048 -ub 2048 --lazy-mode auto -ot "$OT" --host 127.0.0.1 --port 8001
wait_quiet
GGML_CUDA_NO_PINNED=1 run ik 8099 "$HOME/ik_llama.cpp/build/bin/llama-server" -m "$M" -c 16384 -ngl 99 -t 32 -b 2048 -ub 2048 -ot "$OT" --host 127.0.0.1 --port 8099
echo AB_DONE
