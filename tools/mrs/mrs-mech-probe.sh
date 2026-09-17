#!/bin/bash
# mrs-mech-probe.sh <tag> — one lease, mistral.rs: which kernels and which decode path a take actually took.
#
# The 09-17 WKS-32 measurement left an open question: mistral.rs gains 170 % from four streams where
# ik_llama.cpp gains 13 %, and the two candidate causes (a fixed per-step cost being amortised vs. an
# expert gather batched across streams) predict the same sweep shape. This probe asks the engine
# instead of guessing. Two sources, both the engine's own:
#
#   * `-v` on the server, which prints the backend it selected for the MoE experts and the KV cache;
#   * the Prometheus endpoint, which counts CUDA-graph dispatches by reason
#     (`mistralrs_cuda_graph_dispatch_total{reason=...}` — eager, cache_hit, batch_unsupported, …).
#
# If decode runs on a captured CUDA graph at one stream and at four, a per-launch overhead story is
# weaker; if the reason changes with the stream count, that *is* the story. Either way the answer is a
# counter, not a code read (2026-09-17: a code read produced a wrong upstream claim the same day).
#
# Same gates as mrs-take.sh: model present, GPUs idle, lease free, before 23:30 KST, signals only pids
# recorded at spawn. Sentinel MRS_PROBE_DONE / _FAILED.
#
#   M=/models/…/Qwen3.6-35B-A3B-UD-Q6_K.gguf mrs-mech-probe.sh mech
#   M=… MRS_EXTRA="-n 0:8" mrs-mech-probe.sh partial-gpu     # does device mapping put the rest on CPU?
set -u
TAG=${1:?tag required}; OUT=/home/user/mrs-probe/$TAG; LEASE=/home/user/gpu-lease
PORT=${PORT:-8013}; URL=http://127.0.0.1:$PORT
MRS=${MRS:-/home/user/.mistralrs/mistralrs}; M=${M:?model path required}
STREAMS=${STREAMS:-"1 4"}; NPRED=${NPRED:-200}
mkdir -p $OUT
say(){ echo "$(date +%H:%M:%S) $*"; }
gpus(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr '\n' ' '; }
maxgpu(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1; }
SPID=""; SENT=MRS_PROBE; LEASE_TAG="mrsprobe-$TAG"
finish(){ rc=$1
  if [ -n "$SPID" ] && kill -0 $SPID 2>/dev/null; then
    say "stopping server pid $SPID (session leader) with SIGTERM"; kill -TERM $SPID
    for i in $(seq 120); do kill -0 $SPID 2>/dev/null || break; sleep 1; done
    kill -0 $SPID 2>/dev/null && { say "server $SPID alive after 120 s; not escalating"; rc=1; }
  fi
  if [ -n "$SPID" ]; then
    members(){ ps -eo pid=,sid= | awk -v s=$SPID '$2==s && $1!=s{printf "%s ", $1}'; }
    for i in $(seq 15); do [ -z "$(members)" ] && break; sleep 1; done
    [ -n "$(members)" ] && { say "session members left: $(members) -> SIGTERM"; kill -TERM $(members) 2>/dev/null; sleep 10; }
  fi
  for i in $(seq 45); do [ "$(maxgpu)" -lt 2000 ] && break; sleep 2; done
  say "gpus after: $(gpus)"
  if [ "$(maxgpu)" -lt 2000 ]; then
    [ -f $LEASE ] && grep -q "^$LEASE_TAG " $LEASE && rm -f $LEASE && say "lease released"
  else
    say "GPUS NOT RELEASED: lease kept ($(cat $LEASE 2>/dev/null))"; rc=1
  fi
  [ $rc -eq 0 ] && echo ${SENT}_DONE || echo ${SENT}_FAILED
  exit $rc; }
[ -f "$M" ] || { say "refused: no model at $M"; echo ${SENT}_FAILED; exit 1; }
[ -x "$MRS" ] || { say "refused: no mistralrs at $MRS"; echo ${SENT}_FAILED; exit 1; }
[ "$(date +%H%M)" -lt 2330 ] || { say "refused: after 23:30 KST"; echo ${SENT}_FAILED; exit 1; }
[ "$(maxgpu)" -lt 2000 ] || { say "refused: GPUs busy: $(gpus)"; echo ${SENT}_FAILED; exit 1; }
[ -f $LEASE ] && { say "refused: lease held: $(cat $LEASE)"; echo ${SENT}_FAILED; exit 1; }
echo "$LEASE_TAG $$ $(date +%FT%T)" > $LEASE
say "launch env: M=$M CTX=${CTX:-8192} MAXSEQS=${MAXSEQS:-8} STREAMS=$STREAMS NPRED=$NPRED MRS_EXTRA=${MRS_EXTRA:-} MRS=$MRS PORT=$PORT"
say "$TAG: $($MRS --version); io avg10 $(awk '/some/{print $2}' /proc/pressure/io); gpus before: $(gpus)"

. /home/user/gpu-order.env
CUDA_VISIBLE_DEVICES=${CVD:-$A6000_UUID} setsid nohup $MRS -v serve -f "$M" \
  --host 127.0.0.1 --port $PORT --no-ui --paged-attn on --pa-context-len ${CTX:-8192} \
  --max-seq-len ${CTX:-8192} --max-batch-size ${MAXSEQS:-8} ${MRS_EXTRA:-} > $OUT/server.log 2>&1 < /dev/null &
SPID=$!; echo $SPID > $OUT/server.pid; sleep 1
kill -0 $SPID 2>/dev/null || { say "server exited immediately: $(head -20 $OUT/server.log)"; SPID=""; finish 1; }
[ "$(ps -o sid= -p $SPID | tr -d ' ')" = "$SPID" ] || { say "launch assertion failed (pid $SPID is not a session leader)"; finish 1; }
say "server pid $SPID"
ready=""
for i in $(seq 450); do
  kill -0 $SPID 2>/dev/null || { say "server exited during load"; tail -30 $OUT/server.log; SPID=""; finish 1; }
  curl -s -m 30 "$URL/v1/chat/completions" -H 'Content-Type: application/json' \
    -d '{"model":"default","messages":[{"role":"user","content":"hi"}],"max_tokens":1,"temperature":0}' 2>/dev/null | grep -q '"choices"' && { ready=1; break; }
  sleep 2
done
[ -n "$ready" ] || { say "server never answered a completion"; tail -20 $OUT/server.log; finish 1; }
say "ready; gpus loaded: $(gpus)"

# What the engine says it chose. Grepped, not guessed — the full verbose log stays in $OUT.
say "--- backend lines the server printed"
grep -aiE "moe|expert|grouped|cutlass|cutile|flash|kv cache|graph|device|mapped|layer" $OUT/server.log \
  | grep -avi "chat template" | head -40 | sed 's/^/    /'

metrics(){ curl -s -m 10 $URL/metrics; }
metrics > $OUT/metrics-idle.txt
say "--- metric families the server exposes"
grep -oE "^[a-z_]+" $OUT/metrics-idle.txt | sort -u | tr '\n' ' ' | fold -w 160 | sed 's/^/    /'

burst(){ # burst <n> <npred> — n concurrent streaming completions, distinct prompts, wall clock and token count
  # `wait` with no argument would also wait on the server, which is a background job of this shell
  # (measured 2026-09-17: the first run of this probe hung there until the server was killed by hand),
  # so the curl pids are collected and waited on by name.
  local n=$1 np=$2 i; local pids=()
  for i in $(seq $n); do
    curl -s -N -m 300 "$URL/v1/chat/completions" -H 'Content-Type: application/json' -d "{
      \"model\":\"default\",\"stream\":true,\"temperature\":0,\"max_tokens\":$np,
      \"chat_template_kwargs\":{\"enable_thinking\":false},
      \"messages\":[{\"role\":\"user\",\"content\":\"Explain in detail, with examples, why problem number $i in distributed systems is hard. Be thorough.\"}]}" \
      > $OUT/burst-$n-$i.txt 2>&1 &
    pids+=($!); echo $! >> $OUT/burst.pids
  done
  wait "${pids[@]}"
}

for n in $STREAMS; do
  metrics > $OUT/metrics-before-$n.txt
  t0=$(date +%s.%N); burst $n $NPRED; t1=$(date +%s.%N)
  metrics > $OUT/metrics-after-$n.txt
  toks=$(grep -o '"content":"' $OUT/burst-$n-*.txt | wc -l)
  say "streams=$n wall $(echo "$t1 - $t0" | bc) s, content deltas $toks, aggregate $(echo "scale=1; $toks / ($t1 - $t0)" | bc) tok/s (curl-side, not a tape)"
  say "    cuda graph counters, delta over the burst:"
  python3 - "$OUT/metrics-before-$n.txt" "$OUT/metrics-after-$n.txt" <<'PY' | sed 's/^/    /'
import re, sys
def read(p):
    d = {}
    for line in open(p):
        if line.startswith('#') or not line.strip():
            continue
        m = re.match(r'^(\S+?)(\{.*\})?\s+(\S+)$', line.strip())
        if m and ('graph' in m.group(1) or 'memory' in m.group(1)):
            d[m.group(1) + (m.group(2) or '')] = float(m.group(3))
    return d
a, b = read(sys.argv[1]), read(sys.argv[2])
rows = [(k, b[k] - a.get(k, 0.0), b[k]) for k in sorted(b)]
rows = [r for r in rows if r[1] or 'graph' in r[0]]
if not rows:
    print("no graph or memory counters moved")
for k, d, v in rows:
    print(f"{k:<78} +{d:g}  (now {v:g})")
PY
done

say "--- new backend lines after the bursts"
grep -aiE "graph|moe|expert|batch|eager" $OUT/server.log | tail -20 | sed 's/^/    /'
finish 0
