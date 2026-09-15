#!/bin/bash
# ik-vram-take.sh <tag> — a model that fits one card: ik llama-server at -ngl 99 on CUDA0, one toktape take.
# Gates: GPUs idle, before 23:30 KST, lease free. Signals only the pid recorded at spawn. Sentinel IK_VRAM_DONE / _FAILED.
set -u
TAG=$1; OUT=/home/user/ik-vram/$TAG; LEASE=/home/user/gpu-lease; PORT=8012; URL=http://127.0.0.1:$PORT
TREE=${TREE:-/home/user/ik_llama.cpp}; RUNS=/home/user/toktape-runs; TOKTAPE=${TOKTAPE:-/home/user/toktape-0.2.2}
M=${M:?model path required}
mkdir -p $OUT
say(){ echo "$(date +%H:%M:%S) $*"; }
gpus(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr '\n' ' '; }
maxgpu(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1; }
SPID=""; SENT=IK_VRAM; LEASE_TAG="ik-vram-$TAG"
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
[ -x "$TOKTAPE" ] || { say "refused: no toktape at $TOKTAPE"; echo ${SENT}_FAILED; exit 1; }
[ "$(date +%H%M)" -lt 2330 ] || { say "refused: after 23:30 KST"; echo ${SENT}_FAILED; exit 1; }
[ "$(maxgpu)" -lt 2000 ] || { say "refused: GPUs busy: $(gpus)"; echo ${SENT}_FAILED; exit 1; }
[ -f $LEASE ] && { say "refused: lease held: $(cat $LEASE)"; echo ${SENT}_FAILED; exit 1; }
echo "$LEASE_TAG $$ $(date +%FT%T)" > $LEASE
cd $TREE || finish 1
say "$TAG at $(git log -1 --format='%h %s' | cut -c1-60); toktape $($TOKTAPE version); io avg10 $(awk '/some/{print $2}' /proc/pressure/io); gpus before: $(gpus)"
# one card, everything resident: no -ot, no CPU tail, nothing streamed from RAM
. /home/user/gpu-order.env; CUDA_VISIBLE_DEVICES=${CVD:-$A6000_UUID} setsid nohup ./build/bin/llama-server -m "$M" \
  -c ${CTX:-32768} -ngl 99 -fa on -t ${THREADS:-32} -b 2048 -ub ${UB:-512} ${EXTRA_FLAGS:-} \
  --host 127.0.0.1 --port $PORT > $OUT/server.log 2>&1 < /dev/null &
SPID=$!; echo $SPID > $OUT/server.pid; sleep 1
kill -0 $SPID 2>/dev/null || { say "server exited immediately: $(head -3 $OUT/server.log)"; SPID=""; finish 1; }
[ "$(ps -o sid= -p $SPID | tr -d ' ')" = "$SPID" ] || { say "launch assertion failed (pid $SPID is not a session leader)"; finish 1; }
say "server pid $SPID"
# readiness is a completion that came back with timings, never a health code
ready=""
for i in $(seq 450); do
  kill -0 $SPID 2>/dev/null || { say "server exited during load"; tail -20 $OUT/server.log; SPID=""; finish 1; }
  curl -s -m 10 "$URL/completion" -d '{"prompt":"hi","n_predict":1,"temperature":0}' 2>/dev/null | grep -q '"timings"' && { ready=1; break; }
  sleep 2
done
[ -n "$ready" ] || { say "server never answered a completion"; tail -10 $OUT/server.log; finish 1; }
say "ready; gpus loaded: $(gpus)"
if [ -n "${PROMPT_FILES:-}" ]; then
  PARGS=(); OIFS=$IFS; IFS=','
  for f in $PROMPT_FILES; do IFS=$OIFS; PARGS+=(--prompt "$(cat "$f")"); IFS=','; done
  IFS=$OIFS
else PARGS=(--prompt "${PROMPT:?PROMPT or PROMPT_FILES required}"); fi
$TOKTAPE record --url $URL --out $RUNS --wait 0 \
  --sessions ${SESSIONS:-1} --max-sessions ${SESSIONS:-1} \
  "${PARGS[@]}" ${NPRED:+-n $NPRED} --for ${FOR:-30s} --temp 0 \
  ${RAMFLAGS:---ram-gbs-measured 147.7 --ram-speed DDR4-3600} \
  --tag "$TAG" --note "${NOTE:-}" 2>&1 | tee $OUT/take.txt
rc=${PIPESTATUS[0]}
say "toktape rc $rc"
finish $rc
