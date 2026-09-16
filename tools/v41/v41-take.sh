#!/bin/bash
# v41-take.sh <tag> — DeepSeek-V4.1-Flash on two cards + RAM + NVMe engram, one toktape take.
# Gates: GPUs idle, before 23:30 KST, lease free. Signals only the pid recorded at spawn. Sentinel QWEN38_DONE / _FAILED.
# Placement is an argument (OT), never a default: the first load reports what fits and the next take names it.
set -u
TAG=$1; OUT=/home/user/v41-takes/$TAG; LEASE=/home/user/gpu-lease; PORT=8014; URL=http://127.0.0.1:$PORT
B=${B:-/home/user/llama.cpp-v41-merged/build/bin/llama-server}; RUNS=/home/user/toktape-runs; TOKTAPE=${TOKTAPE:-/home/user/toktape-hero-0f88bd3}
M=${M:-/models/DeepSeek-V4.1-Flash-Q3_K_M-engramQ8-tokembdBF16-attnQ8/DeepSeek-V4.1-Flash-Q3_K_M-00001-of-00009.gguf}
D=${D:-}            # MTP draft file; empty = no speculation
OT=${OT:?OT (tensor override string) required}
mkdir -p $OUT
say(){ echo "$(date +%T) $*"; }
gpus(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr '\n' ' '; }
maxgpu(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1; }
SPID=""; SENT=V41TAKE; LEASE_TAG="v41take-$TAG"
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
[ -z "$D" ] || [ -f "$D" ] || { say "refused: no draft at $D"; echo ${SENT}_FAILED; exit 1; }
[ -x "$TOKTAPE" ] || { say "refused: no toktape at $TOKTAPE"; echo ${SENT}_FAILED; exit 1; }
[ "$(date +%H%M)" -lt 2330 ] || { say "refused: after 23:30 KST"; echo ${SENT}_FAILED; exit 1; }
[ "$(maxgpu)" -lt 2000 ] || { say "refused: GPUs busy: $(gpus)"; echo ${SENT}_FAILED; exit 1; }
[ -f $LEASE ] && { say "refused: lease held: $(cat $LEASE)"; echo ${SENT}_FAILED; exit 1; }
echo "$LEASE_TAG $$ $(date +%FT%T)" > $LEASE
say "$TAG: $(cd $(dirname $B)/../.. && git -c safe.directory='*' log -1 --format='%h %s' | cut -c1-70); toktape $($TOKTAPE version); io avg10 $(awk '/some/{print $2}' /proc/pressure/io); gpus before: $(gpus)"
say "OT=$OT"
DRAFT=(); [ -z "$D" ] || DRAFT=(-md "$D" --spec-type ${SPEC:-draft-dspark} --spec-draft-n-max ${NMAX:-5} ${OTD:+-otd "$OTD"})
. /home/user/gpu-order.env
setsid nohup "$B" -m "$M" --alias DeepSeek-V4.1-Flash -c ${CTX:-16384} -ngl 99 -t ${THREADS:-32} -b 2048 -ub ${UB:-512} --lazy-mode ${LZM:-auto} \
  -ot "$OT" "${DRAFT[@]}" ${EXTRA_FLAGS:-} --jinja --host 127.0.0.1 --port $PORT > $OUT/server.log 2>&1 < /dev/null &
SPID=$!; echo $SPID > $OUT/server.pid; sleep 1
kill -0 $SPID 2>/dev/null || { say "server exited immediately: $(grep -m2 -i "error\|fail" $OUT/server.log | cut -c1-200)"; SPID=""; finish 1; }
[ "$(ps -o sid= -p $SPID | tr -d ' ')" = "$SPID" ] || { say "launch assertion failed (pid $SPID is not a session leader)"; finish 1; }
say "server pid $SPID"
ready=""; t0=$(date +%s)
for i in $(seq 900); do
  kill -0 $SPID 2>/dev/null || { say "server exited during load"; grep -i -m6 "error\|failed\|alloc" $OUT/server.log | cut -c1-220; SPID=""; finish 1; }
  curl -s -m 10 "$URL/completion" -d '{"prompt":"hi","n_predict":1,"temperature":0}' 2>/dev/null | grep -q '"timings"' && { ready=1; break; }
  sleep 2
done
[ -n "$ready" ] || { say "server never answered a completion"; tail -10 $OUT/server.log; finish 1; }
say "ready in $(( $(date +%s) - t0 )) s; gpus loaded: $(gpus)"
nvidia-smi --query-gpu=uuid,name,memory.used --format=csv,noheader | tee $OUT/vram.txt
grep -E "load_tensors:|CPU_Mapped|CUDA0 model|CUDA1 model|KV self size|compute buffer" $OUT/server.log | cut -c1-160 | tee $OUT/placement.txt
[ -n "${NOTAKE:-}" ] && finish 0
for i in $(seq 60); do p=$(awk '/some/{print $2}' /proc/pressure/io | cut -d= -f2); awk -v p="$p" 'BEGIN{exit !(p<3)}' && break; sleep 2; done
if [ -n "${PROMPT_FILES:-}" ]; then
  PARGS=(); OIFS=$IFS; IFS=','
  for f in $PROMPT_FILES; do IFS=$OIFS; PARGS+=(--prompt "$(cat "$f")"); IFS=','; done
  IFS=$OIFS
else PARGS=(--prompt "${PROMPT:?PROMPT or PROMPT_FILES required}"); fi
$TOKTAPE record --url $URL --out $RUNS --wait 0 \
  --sessions ${SESSIONS:-1} --max-sessions ${SESSIONS:-1} \
  "${PARGS[@]}" ${NPRED:+-n $NPRED} --for ${FOR:-60s} --temp ${TEMP:-0} \
  --param chat_template_kwargs="{\"enable_thinking\":${THINK:-false}}" \
  ${RAMFLAGS:---ram-gbs-measured 144.8 --ram-speed DDR4-3600} \
  --tag "$TAG" --note "${NOTE:-}" 2>&1 | tee $OUT/take.txt
rc=${PIPESTATUS[0]}
say "toktape rc $rc"
finish $rc
