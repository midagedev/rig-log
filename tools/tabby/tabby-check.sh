#!/bin/bash
# tabby-check.sh <tag> <tabbyAPI tree> <requests dir>
# One TabbyAPI load on the workstation for the #454 check: gates (GPUs idle, before 23:30 KST, lease free),
# start the server from <tree> with ~/.venv-tabby, wait for the model, send every <requests dir>/*.json to
# /v1/chat/completions in name order (raw body, headers and timing saved), then stop that pid and confirm
# the GPUs are back. Signals only the pid it started. Sentinel TABBY_CHECK_DONE / TABBY_CHECK_FAILED.
set -u
TAG=$1; TREE=$2; REQ=$3
OUT=/home/user/tabby-check/$TAG; LEASE=/home/user/gpu-lease; PORT=5055; URL=http://127.0.0.1:$PORT
mkdir -p $OUT
say(){ echo "$(date +%H:%M:%S) $*"; }
gpus(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr '\n' ' '; }
SPID=""; SENT=TABBY_CHECK; LEASE_TAG="tabby-$TAG"; UNLOAD_URL="$URL/v1/model/unload"
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
[ "$(date +%H%M)" -lt 2330 ] || { say "refused: after 23:30 KST"; echo TABBY_CHECK_FAILED; exit 1; }
[ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1)" -lt 2000 ] || { say "refused: GPUs busy: $(gpus)"; echo TABBY_CHECK_FAILED; exit 1; }
if [ -f $LEASE ]; then say "refused: lease held: $(cat $LEASE)"; echo TABBY_CHECK_FAILED; exit 1; fi
echo "$LEASE_TAG $$ $(date +%FT%T)" > $LEASE
ls $REQ/*.json > /dev/null 2>&1 || { say "no requests in $REQ"; finish 1; }
say "tree $(git -C $TREE log -1 --format='%h %s' | cut -c1-80); dirty files: $(git -C $TREE status --porcelain | wc -l)"
git -C $TREE diff 53da791 --stat > $OUT/tree-diff-stat.txt
/home/user/.venv-tabby/bin/pip freeze | grep -iE "^(torch|exllamav3|triton)=|tabbyAPI" > $OUT/freeze.txt
cp /home/user/tabbyAPI-config.yml $TREE/config.yml
say "io avg10 $(awk '/some/{print $2}' /proc/pressure/io); gpus before: $(gpus)"
cd $TREE
CUDA_DEVICE_ORDER=PCI_BUS_ID setsid nohup /home/user/.venv-tabby/bin/python main.py > $OUT/server.log 2>&1 < /dev/null &
SPID=$!; echo $SPID > $OUT/server.pid
sleep 1
[ "$(ps -o sid= -p $SPID 2>/dev/null | tr -d ' ')" = "$SPID" ] || { say "launch assertion failed: pid $SPID is not a session leader ($(ps -o pid=,sid=,comm= -p $SPID))"; finish 1; }
say "server pid $SPID (session leader, $(ps -o comm= -p $SPID))"
t0=$(date +%s)
until curl -sf $URL/props > $OUT/props.json 2>/dev/null; do
  kill -0 $SPID 2>/dev/null || { say "server died during load"; tail -n 20 $OUT/server.log; finish 1; }
  [ $(( $(date +%s) - t0 )) -gt 900 ] && { say "model not ready after 900 s"; tail -n 20 $OUT/server.log; finish 1; }
  sleep 5
done
say "model ready in $(( $(date +%s) - t0 )) s; gpus loaded: $(gpus)"
curl -s $URL/v1/model > $OUT/v1-model.json
for f in $(ls $REQ/*.json | sort); do
  n=$(basename $f .json)
  # endpoint: <name>.endpoint when present, else a body with "prompt" and no "messages" is a text completion
  ep=/v1/chat/completions
  if [ -f $REQ/$n.endpoint ]; then ep=$(tr -d ' \n' < $REQ/$n.endpoint)
  elif ! grep -q '"messages"' $f && grep -q '"prompt"' $f; then ep=/v1/completions; fi
  curl -sN -D $OUT/$n.headers.txt -o $OUT/$n.body.txt -w "http %{http_code} total %{time_total}s\n" \
    -H 'Content-Type: application/json' --data-binary @$f $URL$ep > $OUT/$n.curl.txt 2>&1
  say "$n -> $ep: $(cat $OUT/$n.curl.txt); body $(wc -c < $OUT/$n.body.txt) bytes; timings keys: $(grep -o '"timings"' $OUT/$n.body.txt | wc -l)"
done
finish 0
