#!/bin/bash
# What does one more concurrent request actually buy on V4.1 at this placement?
#
# The batch translation is 140 independent requests in a queue: nothing waits on a stream's
# latency, so the number that decides how long it takes is aggregate decode across slots. This
# box has never measured that on V4.1. What it has is one line in an unrelated entry
# (log/2026-09-14-air-cooler-swap.md: three concurrent 500-token decodes at 21 tok/s each,
# against ~28 for one) and a measurement on a *different* MoE model in a *different* engine that
# says the opposite -- DeepSeek-V2-Lite on ik gives 202 tok/s at batch 1 and **156** at batch 2,
# slower in total, which is the unfiled finding in docs/upstream-contributions.md. Two streams
# costing throughput is a real possibility here, not a theoretical one, so this measures 1, 2
# and 3 rather than assuming the curve.
#
# The serving line is configs/v41-serve.sh unchanged except C and NP, which that file takes from
# the environment and which are what is being measured. The draft is left on: it is part of the
# placement, and a concurrency number taken without it would not describe the server we run.
#
#   tools/v41-concurrency.sh <who approved this>
set -euo pipefail

if [ -z "${V41C_PRIVATE:-}" ]; then
  # Deploying over a running script kills the run: measured 2026-09-16, an scp landed on a
  # script bash was still reading and it died on a syntax error with its EXIT trap unrun,
  # leaving the lease held and a peer's overnight job to give up on it.
  V41C_PRIVATE=$(mktemp "${TMPDIR:-/tmp}/v41-concurrency.XXXXXX.sh")
  cat "$0" > "$V41C_PRIVATE"; export V41C_PRIVATE
  exec bash "$V41C_PRIVATE" "$@"
fi

WHO=${1:?who approved this}
OUT=${OUT:-/home/user/translate/v41-concurrency}
LEASE=/home/user/gpu-lease
PORT=${PORT:-8012}
C=${C:-32768}
NP=${NP:-3}
IO_MAX=${IO_MAX:-5}

mkdir -p "$OUT"
say(){ echo "$(date +%H:%M:%S.%1N) $*" | tee -a "$OUT/run.log"; }

io_avg10(){ awk '/^some/{for(i=1;i<=NF;i++) if($i ~ /^avg10=/){sub("avg10=","",$i); print $i}}' /proc/pressure/io; }
witness(){ { echo "  when=$1"; echo "  load1=$(cut -d' ' -f1 /proc/loadavg)"; grep ^some /proc/pressure/io | sed 's/^/  /'; } | tee -a "$OUT/run.log"; }

say "=== v41 concurrency: C=$C NP=$NP, approved by $WHO ==="
[ -e "$LEASE" ] && { P=$(awk '{print $2}' "$LEASE"); kill -0 "$P" 2>/dev/null \
  && { say "ABORT: lease held by live pid $P: $(cat $LEASE)"; exit 1; } \
  || { say "lease was abandoned (pid $P gone), removing: $(cat $LEASE)"; rm -f "$LEASE"; }; }
awk "BEGIN{exit !($(io_avg10) > $IO_MAX)}" && { say "ABORT: io avg10 $(io_avg10) > $IO_MAX"; exit 1; }
echo "v41-concurrency $$ $(date -Is)" > "$LEASE"
witness start

# B is passed rather than left to the serving script's `${B:-$HOME/...}`: over ssh as root
# $HOME is /root and the default silently resolves to a binary that is not there. The server
# then exits before the health poll starts, which reads as "the model failed to load".
# EXTRA carries `--reasoning off`, which the batch runner passes and this one did not on its
# first attempt. Measured 2026-09-18: without it V4.1 put every token of an 8192-token reply
# into reasoning_content, the answer was empty, and the level reported 21.1 tok/s over 388 s --
# a rate for deliberation, against a cap, with nothing translated. The batch measures the server
# the batch runs, so it gets the batch's flags.
C=$C NP=$NP PORT=$PORT EXTRA="--reasoning off" B=/home/user/llama.cpp-v41-merged/build/bin/llama-server \
  bash /home/user/v41-serve.sh > "$OUT/server.log" 2>&1 &
SPID=$!
# $! is the wrapper until the wrapper execs. Three rounds on this box have signalled a shell
# instead of the program it started, so the pid is not used until /proc says what it is.
for _ in 1 2 3 4 5 6 7 8; do COMM=$(cat /proc/$SPID/comm 2>/dev/null || echo gone); [ "$COMM" = llama-server ] && break; sleep 0.4; done
[ "$COMM" = llama-server ] || { say "ABORT: \$! is $SPID comm=$COMM, not the server"; rm -f "$LEASE"; exit 1; }
say "server pid $SPID comm=$COMM"

# The teardown is the point of the trap, and releasing the lease before the cards come back is
# how a peer lost a night: measured 2026-09-18, repo-batch.sh printed "gpus after: 20112 45892"
# and released the lease over 66 GB it was still holding. So: signal the pid captured at spawn,
# never one found by pattern, wait on kill -0, escalate once, and hold the lease if the memory
# does not return.
cleanup(){
  rc=$?
  say "stopping the server (pid $SPID)"
  kill -TERM "$SPID" 2>/dev/null || true
  for i in $(seq 60); do kill -0 "$SPID" 2>/dev/null || break; sleep 1; done
  if kill -0 "$SPID" 2>/dev/null; then
    say "server still alive ${i}s after SIGTERM; sending SIGKILL"
    kill -KILL "$SPID" 2>/dev/null || true
    for i in $(seq 30); do kill -0 "$SPID" 2>/dev/null || break; sleep 1; done
  else
    say "server exited ${i}s after SIGTERM"
  fi
  V=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr '\n' ' ')
  say "gpus after: $V"
  if awk "BEGIN{exit !($(echo $V | tr ' ' '+' | sed 's/+$//') > 2000)}"; then
    say "HELD: $V MiB still on the cards -- leaving the lease in place on purpose, it is not free"
    witness end; exit 1
  fi
  rm -f "$LEASE"; say "lease released"; witness end
  say "=== done, rc=$rc ==="
}
trap cleanup EXIT

for i in $(seq 1800); do
  curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  kill -0 "$SPID" 2>/dev/null || { say "ABORT: server died while loading"; exit 1; }
  sleep 1
done
curl -sf "http://127.0.0.1:$PORT/health" >/dev/null || { say "ABORT: never healthy"; exit 1; }
say "healthy after ${i}s; vram $(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr '\n' ' ')"
# Do not assume how the build divides -c: it says so itself.
say "slots: $(grep -iE 'n_ctx_per_seq|n_ctx_slot|n_parallel' "$OUT/server.log" | tail -3 | tr '\n' ' | ')"

python3 /home/user/translate/v41-concurrency.py \
  --url "http://127.0.0.1:$PORT/v1/chat/completions" \
  --parts /home/user/translate/concurrency-parts.json \
  --out "$OUT/rows.json" --levels "${LEVELS:-1,2,3}" 2>&1 | tee -a "$OUT/run.log"
