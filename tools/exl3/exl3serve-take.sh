#!/bin/bash
# exl3serve-take.sh <tag> — load exl3-serve with the serving profile, record one toktape take, stop.
# Gates: GPUs idle, before 23:30 KST, lease free. Signals only the pid it started. Sentinel EXL3SERVE_TAKE_DONE / _FAILED.
set -u
TAG=$1; OUT=/home/user/exl3serve-take/$TAG; LEASE=/home/user/gpu-lease; PORT=8089; URL=http://127.0.0.1:$PORT
RUNS=/home/user/toktape-runs; TOKTAPE=${TOKTAPE:-/home/user/toktape-0719fec}
mkdir -p $OUT
say(){ echo "$(date +%H:%M:%S) $*"; }
gpus(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr '\n' ' '; }
SPID=""; SENT=EXL3SERVE_TAKE; LEASE_TAG="exl3take-$TAG"
finish(){ rc=$1
  # SPID is the server itself (asserted session leader at launch); stop its whole session, never escalate blindly
  if [ -n "$SPID" ] && kill -0 $SPID 2>/dev/null; then
    say "stopping server pid $SPID (session leader) with SIGTERM"; kill -TERM $SPID
    for i in $(seq 120); do kill -0 $SPID 2>/dev/null || break; sleep 1; done
    kill -0 $SPID 2>/dev/null && { say "server $SPID still alive after 120 s; not escalating"; rc=1; }
  fi
  if [ -n "$SPID" ]; then
    members(){ ps -eo pid=,sid= | awk -v s=$SPID '$2==s && $1!=s{printf "%s ", $1}'; }
    for i in $(seq 15); do [ -z "$(members)" ] && break; sleep 1; done
    left=$(members)
    if [ -n "$left" ]; then
      say "session $SPID members still running after leader exit: $left -> SIGTERM"; kill -TERM $left 2>/dev/null
      for i in $(seq 30); do [ -z "$(members)" ] && break; sleep 1; done
      [ -n "$(members)" ] && { say "session $SPID members survived SIGTERM: $(members); not escalating"; rc=1; }
    fi
  fi
  for i in $(seq 45); do [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1)" -lt 2000 ] && break; sleep 2; done
  say "gpus after: $(gpus)"
  if [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1)" -lt 2000 ]; then
    [ -f $LEASE ] && grep -q "^$LEASE_TAG " $LEASE && rm -f $LEASE && say "lease released"
  else
    say "GPUS NOT RELEASED: lease kept ($(cat $LEASE 2>/dev/null)); inspect before anyone else loads"; rc=1
  fi
  [ $rc -eq 0 ] && echo ${SENT}_DONE || echo ${SENT}_FAILED
  exit $rc; }
[ -n "${PROMPT:-}" ] || { say "refused: PROMPT unset"; echo ${SENT}_FAILED; exit 1; }
[ -x "$TOKTAPE" ] || { say "refused: no toktape at $TOKTAPE"; echo ${SENT}_FAILED; exit 1; }
[ "$(date +%H%M)" -lt 2330 ] || { say "refused: after 23:30 KST"; echo ${SENT}_FAILED; exit 1; }
[ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1)" -lt 2000 ] || { say "refused: GPUs busy: $(gpus)"; echo ${SENT}_FAILED; exit 1; }
if [ -f $LEASE ]; then say "refused: lease held: $(cat $LEASE)"; echo ${SENT}_FAILED; exit 1; fi
echo "$LEASE_TAG $$ $(date +%FT%T)" > $LEASE
say "exl3-serve at $(cat /home/user/exl3-serve/.commit 2>/dev/null); toktape $($TOKTAPE version); io avg10 $(awk '/some/{print $2}' /proc/pressure/io); gpus before: $(gpus)"
cd /home/user
setsid nohup /home/user/.venv-exl3/bin/exl3-serve -m /models/GLM-5.3-Flash-exl3-4.05 -gs 44,21 -mcs 185 -mct 32 -cs 32768 -mtp --port $PORT > $OUT/server.log 2>&1 < /dev/null &
SPID=$!; echo $SPID > $OUT/server.pid
sleep 1
[ "$(ps -o sid= -p $SPID 2>/dev/null | tr -d ' ')" = "$SPID" ] || { say "launch assertion failed: pid $SPID is not a session leader ($(ps -o pid=,sid=,comm= -p $SPID))"; finish 1; }
say "server pid $SPID (session leader, $(ps -o comm= -p $SPID))"
t0=$(date +%s)
until [ "$(curl -s -o /dev/null -w '%{http_code}' $URL/props)" = "200" ]; do
  kill -0 $SPID 2>/dev/null || { say "server died during load"; tail -n 20 $OUT/server.log; finish 1; }
  [ $(( $(date +%s) - t0 )) -gt 900 ] && { say "not ready after 900 s"; tail -n 20 $OUT/server.log; finish 1; }
  sleep 5
done
say "ready in $(( $(date +%s) - t0 )) s; gpus loaded: $(gpus)"
# one warm request outside the take, so the take is not the run that pays for lazy CUDA init
curl -s -m 300 -o /dev/null -X POST $URL/v1/chat/completions -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":"hi"}],"max_tokens":8,"temperature":0}' || { say "warm request failed"; finish 1; }
say "warm request done; io avg10 $(awk '/some/{print $2}' /proc/pressure/io)"
$TOKTAPE record --url $URL --out $RUNS --wait 0 \
  --prompt "$PROMPT" -n ${NPRED:-300} --for ${FOR:-60s} --temp 0 \
  --param chat_template_kwargs='{"reasoning_effort":"low"}' \
  --ram-speed DDR4-3600 --ram-channels 8 \
  --tag "$TAG" --note "${NOTE:-}" 2>&1 | tee $OUT/take.txt
rc=${PIPESTATUS[0]}
say "toktape rc $rc"
finish $rc
