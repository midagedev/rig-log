#!/bin/bash
# exl3serve-check.sh <tag> — load exl3-serve from ~/.venv-exl3 with the serving profile, verify, stop.
# Gates: GPUs idle, before 23:30 KST, lease free. Signals only the pid it started. Sentinel EXL3SERVE_CHECK_DONE / _FAILED.
set -u
TAG=$1; OUT=/home/user/exl3serve-check/$TAG; LEASE=/home/user/gpu-lease; PORT=8089; URL=http://127.0.0.1:$PORT
mkdir -p $OUT
say(){ echo "$(date +%H:%M:%S) $*"; }
gpus(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr '\n' ' '; }
SPID=""; SENT=EXL3SERVE_CHECK; LEASE_TAG="exl3serve-$TAG"; UNLOAD_URL=""
finish(){ rc=$1
  # SPID is the server itself (asserted session leader at launch); stop its whole session, never escalate blindly
  if [ -n "$SPID" ] && kill -0 $SPID 2>/dev/null; then
    [ -n "${UNLOAD_URL:-}" ] && { curl -s -m 60 -X POST $UNLOAD_URL -o /dev/null -w "unload http %{http_code}\n"; sleep 3; }
    # SIGTERM, not SIGINT: a non-interactive bash starts background jobs with SIGINT ignored, and Python keeps it ignored
    say "stopping server pid $SPID (session leader) with SIGTERM"; kill -TERM $SPID
    for i in $(seq 120); do kill -0 $SPID 2>/dev/null || break; sleep 1; done
    kill -0 $SPID 2>/dev/null && { say "server $SPID still alive after 120 s; not escalating"; rc=1; }
  fi
  if [ -n "$SPID" ]; then
    # members of the session we created (e.g. exllamav3's spawned CPU worker) may outlive the leader
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
[ "$(date +%H%M)" -lt 2330 ] || { say "refused: after 23:30 KST"; echo EXL3SERVE_CHECK_FAILED; exit 1; }
[ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1)" -lt 2000 ] || { say "refused: GPUs busy: $(gpus)"; echo EXL3SERVE_CHECK_FAILED; exit 1; }
if [ -f $LEASE ]; then say "refused: lease held: $(cat $LEASE)"; echo EXL3SERVE_CHECK_FAILED; exit 1; fi
echo "$LEASE_TAG $$ $(date +%FT%T)" > $LEASE
say "exl3-serve at $(cat /home/user/exl3-serve/.commit 2>/dev/null); io avg10 $(awk '/some/{print $2}' /proc/pressure/io); gpus before: $(gpus)"
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
/home/user/.venv-exl3/bin/python /home/user/exl3serve-verify.py $URL $OUT 2>&1 | tee $OUT/verify.txt
rc=${PIPESTATUS[0]}
finish $rc
