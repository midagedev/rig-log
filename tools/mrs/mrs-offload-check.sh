#!/bin/bash
# mrs-offload-check.sh <tag> — one lease, one launch, one request: does a GGUF MoE model serve with
# part of it on the host?
#
# This is a boolean, not a rate. mrs-mech-probe.sh answers it too, but only by accident and slowly:
# its readiness loop demands a successful completion, so a server that loads and then fails every
# request keeps it asking for fifteen minutes (measured 2026-09-17: 232 identical dtype errors
# recorded that way). Here readiness is /health, which separates "the weights loaded" from "a forward
# pass works" — the distinction the offload bug lives in.
#
# Verdict is the response body plus the server's own error count, printed as one line each, so a
# before/after pair around a patch reads as two lines.
#
#   M=/models/…/Qwen3.6-35B-A3B-UD-Q6_K.gguf MRS=/home/user/mistral.rs/target/release/mistralrs \
#     MRS_EXTRA="-n 0:39" mrs-offload-check.sh d5ae0f1-unpatched
#
# Same gates as the other runners: model present, binary present, GPUs idle, lease free, before
# 23:30 KST, signals only pids recorded at spawn. Sentinel MRS_CHECK_DONE / _FAILED.
set -u
TAG=${1:?tag required}; OUT=/home/user/mrs-check/$TAG; LEASE=/home/user/gpu-lease
PORT=${PORT:-8014}; URL=http://127.0.0.1:$PORT
MRS=${MRS:-/home/user/.mistralrs/mistralrs}; M=${M:?model path required}
mkdir -p $OUT
say(){ echo "$(date +%H:%M:%S) $*"; }
gpus(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr '\n' ' '; }
maxgpu(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1; }
SPID=""; SENT=MRS_CHECK; LEASE_TAG="mrscheck-$TAG"
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
say "$TAG: $($MRS --version 2>&1 | head -1)"
say "binary $MRS, mtime $(date -r $MRS +%FT%T)"
say "extra '${MRS_EXTRA:-}', io avg10 $(awk '/some/{print $2}' /proc/pressure/io), gpus before: $(gpus)"
. /home/user/gpu-order.env
CUDA_VISIBLE_DEVICES=${CVD:-$A6000_UUID} setsid nohup $MRS -v serve -f "$M" \
  --host 127.0.0.1 --port $PORT --no-ui --paged-attn on --pa-context-len ${CTX:-4096} \
  --max-seq-len ${CTX:-4096} --max-batch-size ${MAXSEQS:-1} ${MRS_EXTRA:-} > $OUT/server.log 2>&1 < /dev/null &
SPID=$!; echo $SPID > $OUT/server.pid; sleep 1
kill -0 $SPID 2>/dev/null || { say "server exited immediately: $(head -20 $OUT/server.log)"; SPID=""; finish 1; }
[ "$(ps -o sid= -p $SPID | tr -d ' ')" = "$SPID" ] || { say "launch assertion failed (pid $SPID is not a session leader)"; finish 1; }
say "server pid $SPID"

# Readiness is /health, not a completion: a server whose forward pass is broken still answers it,
# and that is exactly the state being measured.
loaded=""
for i in $(seq 300); do
  kill -0 $SPID 2>/dev/null || { say "server exited during load"; tail -30 $OUT/server.log; SPID=""; finish 1; }
  [ "$(curl -s -o /dev/null -w '%{http_code}' -m 10 $URL/health 2>/dev/null)" = "200" ] && { loaded=1; break; }
  sleep 2
done
[ -n "$loaded" ] || { say "/health never returned 200"; tail -20 $OUT/server.log; finish 1; }
say "loaded; gpus: $(gpus)"
say "--- the mapping the engine reports"
grep -aE "Layers [0-9-]+:" $OUT/server.log | head -10 | sed 's/^/    /'
grep -aE "DType selected" $OUT/server.log | head -2 | sed 's/^/    /'

# One request, one token. Its body is the verdict.
say "--- one completion, max_tokens=1"
code=$(curl -s -m 180 -o $OUT/reply.json -w '%{http_code}' "$URL/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"model":"default","messages":[{"role":"user","content":"hi"}],"max_tokens":1,"temperature":0}')
say "http $code, body: $(head -c 400 $OUT/reply.json)"
errs=$(grep -ac "dtype mismatch in matmul" $OUT/server.log || true)
say "server log: $errs lines matching 'dtype mismatch in matmul'"
if grep -q '"choices"' $OUT/reply.json; then
  say "VERDICT: SERVES  (http $code, $errs dtype errors)"
else
  say "VERDICT: FAILS   (http $code, $errs dtype errors)"
  grep -aE "Model failed with error" $OUT/server.log | tail -3 | sed 's/^/    /'
fi
finish 0
