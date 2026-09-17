#!/bin/bash
# mrs-take.sh <tag> — mistral.rs (prebuilt ~/.mistralrs/mistralrs) serving one GGUF on CUDA0, one toktape take.
# Same gates as tools/ik/ik-vram-take.sh: GPUs idle, before 23:30 KST, lease free; signals only the pid
# recorded at spawn. Sentinel MRS_TAKE_DONE / _FAILED. First log line is the full launch environment
# (2026-09-17: a take was re-created with the wrong -c because the row and the card could not give it back).
# toktape attaches to tools/mrs/mrs-shim.py on SHIM_PORT, which fronts the mistral.rs port with /props and
# llama-server timings (mistral.rs has no /props — measured 2026-09-17). Both pids are recorded at spawn.
set -u
TAG=$1; OUT=/home/user/mrs-take/$TAG; LEASE=/home/user/gpu-lease; PORT=${PORT:-8013}; URL=http://127.0.0.1:$PORT
SHIM=${SHIM:-/home/user/mrs-shim.py}; SHIM_PORT=${SHIM_PORT:-8014}; SHIM_URL=http://127.0.0.1:$SHIM_PORT
MRS=${MRS:-/home/user/.mistralrs/mistralrs}; RUNS=/home/user/toktape-runs; TOKTAPE=${TOKTAPE:-/home/user/toktape-0.2.4}
M=${M:?model path required}
mkdir -p $OUT
say(){ echo "$(date +%H:%M:%S) $*"; }
say "launch env: M=$M CTX=${CTX:-8192} MAXSEQS=${MAXSEQS:-4} SESSIONS=${SESSIONS:-1} NPRED=${NPRED:-} FOR=${FOR:-30s} TOKTAPE_EXTRA=${TOKTAPE_EXTRA:-} MRS_EXTRA=${MRS_EXTRA:-} PROMPT_FILES=${PROMPT_FILES:-} TOKTAPE=$TOKTAPE MRS=$MRS PORT=$PORT SHIM=$SHIM SHIM_PORT=$SHIM_PORT"
gpus(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr '\n' ' '; }
maxgpu(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1; }
SPID=""; HPID=""; SENT=MRS_TAKE; LEASE_TAG="mrs-$TAG"
finish(){ rc=$1
  if [ -n "$HPID" ] && kill -0 $HPID 2>/dev/null; then say "stopping shim pid $HPID"; kill -TERM $HPID; fi
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
[ -x "$TOKTAPE" ] || { say "refused: no toktape at $TOKTAPE"; echo ${SENT}_FAILED; exit 1; }
[ -f "$SHIM" ] || { say "refused: no shim at $SHIM"; echo ${SENT}_FAILED; exit 1; }
[ "$(date +%H%M)" -lt 2330 ] || { say "refused: after 23:30 KST"; echo ${SENT}_FAILED; exit 1; }
[ "$(maxgpu)" -lt 2000 ] || { say "refused: GPUs busy: $(gpus)"; echo ${SENT}_FAILED; exit 1; }
[ -f $LEASE ] && { say "refused: lease held: $(cat $LEASE)"; echo ${SENT}_FAILED; exit 1; }
echo "$LEASE_TAG $$ $(date +%FT%T)" > $LEASE
say "$TAG: $($MRS --version); toktape $($TOKTAPE version); io avg10 $(awk '/some/{print $2}' /proc/pressure/io); gpus before: $(gpus)"
. /home/user/gpu-order.env; CUDA_VISIBLE_DEVICES=${CVD:-$A6000_UUID} setsid nohup $MRS serve -f "$M" \
  --host 127.0.0.1 --port $PORT --no-ui --paged-attn on --pa-context-len ${CTX:-8192} \
  --max-seq-len ${CTX:-8192} --max-batch-size ${MAXSEQS:-4} ${MRS_EXTRA:-} > $OUT/server.log 2>&1 < /dev/null &
SPID=$!; echo $SPID > $OUT/server.pid; sleep 1
kill -0 $SPID 2>/dev/null || { say "server exited immediately: $(head -3 $OUT/server.log)"; SPID=""; finish 1; }
[ "$(ps -o sid= -p $SPID | tr -d ' ')" = "$SPID" ] || { say "launch assertion failed (pid $SPID is not a session leader)"; finish 1; }
say "server pid $SPID"
# readiness is a completion that came back with a choice, never a health code
ready=""
for i in $(seq 450); do
  kill -0 $SPID 2>/dev/null || { say "server exited during load"; tail -20 $OUT/server.log; SPID=""; finish 1; }
  curl -s -m 30 "$URL/v1/chat/completions" -H 'Content-Type: application/json' \
    -d '{"model":"default","messages":[{"role":"user","content":"hi"}],"max_tokens":1,"temperature":0}' 2>/dev/null | grep -q '"choices"' && { ready=1; break; }
  sleep 2
done
[ -n "$ready" ] || { say "server never answered a completion"; tail -10 $OUT/server.log; finish 1; }
say "ready; gpus loaded: $(gpus)"
KV=$(grep -o "Allocating [0-9]* MB for PagedAttention KV cache" $OUT/server.log | grep -o "[0-9]*" | head -1)
MRS_UPSTREAM=$URL SHIM_PORT=$SHIM_PORT MRS_MODEL="$M" MRS_PID_FILE=$OUT/server.pid MRS_SLOTS=${MAXSEQS:-4} MRS_NCTX=${CTX:-8192} \
  MRS_VERSION="$($MRS --version | awk '{print $2}')" MRS_KV_BYTES=$(( ${KV:-0} * 1024 * 1024 )) \
  setsid nohup python3 $SHIM > $OUT/shim.log 2>&1 < /dev/null &
HPID=$!; echo $HPID > $OUT/shim.pid; sleep 1
kill -0 $HPID 2>/dev/null || { say "shim exited: $(tail -3 $OUT/shim.log)"; HPID=""; finish 1; }
curl -s -m 5 -o /dev/null -w "" $SHIM_URL/props || { say "shim not answering /props"; finish 1; }
say "shim pid $HPID; /props $(curl -s -m 5 $SHIM_URL/props | head -c 160)"
if [ -n "${PROMPT_FILES:-}" ]; then
  PARGS=(); OIFS=$IFS; IFS=','
  for f in $PROMPT_FILES; do IFS=$OIFS; PARGS+=(--prompt "$(cat "$f")"); IFS=','; done
  IFS=$OIFS
else PARGS=(--prompt "${PROMPT:?PROMPT or PROMPT_FILES required}"); fi
$TOKTAPE record --url $SHIM_URL --out $RUNS --wait 0 \
  --sessions ${SESSIONS:-1} --max-sessions ${SESSIONS:-1} \
  "${PARGS[@]}" ${NPRED:+-n $NPRED} --for ${FOR:-30s} --temp 0 \
  ${RAMFLAGS:---ram-gbs-measured 147.7 --ram-speed DDR4-3600} ${TOKTAPE_EXTRA:-} \
  --tag "$TAG" --note "${NOTE:-}" 2>&1 | tee $OUT/take.txt
rc=${PIPESTATUS[0]}
TAPE=$(grep -o "toktape-runs/[0-9][^ ]*\.tape" $OUT/take.txt | head -1)
[ -n "$TAPE" ] && TAPE=$(dirname $RUNS)/$TAPE
if [ $rc -eq 0 ] && [ -f /home/user/check-take-nothink.py ]; then
  [ -n "$TAPE" ] || { say "no tape path in take.txt: the no-think check could not run"; rc=1; }
fi
if [ $rc -eq 0 ] && [ -n "$TAPE" ]; then
  python3 /home/user/check-take-nothink.py "$TAPE" || { say "no-think was requested and the model thought: the take is mislabelled"; rc=1; }
fi
say "toktape rc $rc"
finish $rc
