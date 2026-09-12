#!/bin/bash
# Load a model's shard 1 with -ngl 0 just far enough to print the tensor
# type summary ("model loaded"), then stop. Port 8098 only; never touches
# the served server on 8001 or whatever runs on 8099.
# Usage: load_check.sh <model-00001-file> <log-path>
set -uo pipefail
model=$1; log=$2
while [ -e /tmp/rig-quiet ]; do echo "$(date -Is) PAUSEWAIT load_check"; sleep 60; done
# Never stack a second full load on the lead's 8099 check if it is running.
for i in $(seq 1 120); do ss -ltn | grep -q ":8099 " || break; sleep 10; done

timeout 600 $HOME/llama.cpp-v41/build/bin/llama-server \
  -m "$model" -c 512 -ngl 0 -lv 4 --host 127.0.0.1 --port 8098 >"$log.stdout" 2>"$log" &
pid=$!
for i in $(seq 1 590); do
  grep -q "model loaded" "$log" 2>/dev/null && { echo "loaded after ${i}s"; break; }
  grep -qi "listening" "$log" 2>/dev/null && { echo "listening after ${i}s"; break; }
  kill -0 "$pid" 2>/dev/null || { echo "server exited after ${i}s"; break; }
  sleep 1
done
kill "$pid" 2>/dev/null
sleep 2
kill -9 "$pid" 2>/dev/null || true
for c in $(pgrep -P "$pid" 2>/dev/null); do kill "$c" 2>/dev/null; done
wait "$pid" 2>/dev/null
if ss -ltn | grep -q ":8098 "; then echo "WARN: 8098 still listening"; else echo "port 8098 freed"; fi
