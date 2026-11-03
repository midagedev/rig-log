#!/bin/bash
# take.sh <tag> — one row of the DGX Spark engine comparison (2026-11-03): start one engine's server, record the row's
# takes with toktape, stop it. The server command comes in SERVE (a shell string run with setsid, so the whole session
# is stopped by its leader's pid) and listens on PORT. Each row is the same five takes, so engines differ only by server:
#   decode-code, decode-prose   short prompt, -n 256, greedy, no-think; three rounds each (one --prompts file line each)
#   pp512, pp4096               three different prompts of about 512 / 4,096 tokens, -n 32; different texts so no round
#                               reads another's prefix from a prompt cache
# Every take is client-timed (--engine-kind openai) so every engine is read by the same clock; a server's own timings,
# where it reports them, stay in the tape beside it. Witnesses per take (load1, io some avg10, GPU compute apps,
# MemAvailable, page cache) go to witness.jsonl. Before the load: drop_caches (unified memory: page cache competes with
# the GPU's allocations). The lease is tools/quiet/lease.sh with QUIET_LEASE=/root/spark-lease.
# A running model fetch is paused (SIGSTOP on the spark-fetch and spark-fetch2 units) for the takes and resumed on every exit path, and
# the row records that it did. Sentinel TAKE_DONE / TAKE_FAILED.
# usage: SERVE='...' PORT=8000 ENGINE='bloomery 0.3.12' [MODEL_ID=..] [CONTAINER=<docker name>] take.sh <tag>
set -u
TAG=${1:?tag}; PORT=${PORT:?PORT}; SERVE=${SERVE:?SERVE}; URL=http://127.0.0.1:$PORT
H=/root/health; OUT=/root/takes/$TAG; TT=/opt/engines/toktape-v0.8.0/toktape; P=$H/prompts
export QUIET_LEASE=/root/spark-lease QUIET_SERVE_PORT=$PORT
mkdir -p "$OUT"; exec > >(tee -a "$OUT/take.log") 2>&1
say(){ echo "$(date +%H:%M:%S) $*"; }
gpuapps(){ nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -c . ; }
memavail(){ awk '/^MemAvailable:/{print $2}' /proc/meminfo; }
wit(){ printf '{"tag":"%s","at":"%s","t":"%s","load1":%s,"io_some_avg10":%s,"gpu_apps":%s,"memavail_kb":%s,"cached_kb":%s,"fetch":"%s"}\n' \
  "$TAG" "$1" "$(date -Is)" "$(awk '{print $1}' /proc/loadavg)" \
  "$(awk '/^some/{sub("avg10=","",$2);print $2}' /proc/pressure/io)" "$(gpuapps)" "$(memavail)" \
  "$(awk '/^Cached:/{print $2}' /proc/meminfo)" "$FETCH" >> "$OUT/witness.jsonl"; }
SPID=""; FETCH=none
FETCH_UNITS="spark-fetch spark-fetch2"; PAUSED=""
fetch_pause(){ for u in $FETCH_UNITS; do systemctl is-active -q $u && { systemctl kill -s SIGSTOP $u; PAUSED="$PAUSED $u"; }; done
  [ -n "$PAUSED" ] && { FETCH="paused:${PAUSED# }"; say "paused$PAUSED"; }; }
fetch_resume(){ [ -n "$PAUSED" ] && { for u in $PAUSED; do systemctl kill -s SIGCONT $u; done; FETCH="resumed:${PAUSED# }"; say "resumed$PAUSED"; PAUSED=""; }; }
finish(){ rc=$1
  if [ -n "$SPID" ] && kill -0 "$SPID" 2>/dev/null; then
    say "stopping server session $SPID"; kill -TERM -- -"$SPID" 2>/dev/null
    for i in $(seq 90); do kill -0 "$SPID" 2>/dev/null || break; sleep 1; done
    kill -0 "$SPID" 2>/dev/null && { say "server alive after 90 s: SIGKILL to the session"; kill -KILL -- -"$SPID"; }
  fi
  # a Docker engine: SERVE runs `docker run --rm --name $CONTAINER ...` in the foreground; stop it by name as well
  [ -n "${CONTAINER:-}" ] && docker stop -t 30 "$CONTAINER" >/dev/null 2>&1
  fetch_resume; wit end
  for i in $(seq 30); do [ "$(gpuapps)" = 0 ] && break; sleep 2; done
  say "after: gpu apps $(gpuapps), MemAvailable $(memavail) kB"
  "$H/lease.sh" release >/dev/null 2>&1
  [ "$rc" = 0 ] && echo TAKE_DONE || echo TAKE_FAILED; exit "$rc"; }
trap 'finish 1' INT TERM
[ -x "$TT" ] || { say "no toktape"; echo TAKE_FAILED; exit 1; }
# driver 580 is the comparison's fixed condition (vLLM via eugr's image requires 580.x; 590.x deadlocks CUDA graph
# capture on GB10, per eugr/spark-vllm-docker's README); a row on any other driver is refused, not recorded
DRV=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)
[ "${DRV%%.*}" = "${WANT_DRIVER:-580}" ] || { say "refused: driver $DRV, the comparison runs on ${WANT_DRIVER:-580}"; echo TAKE_FAILED; exit 1; }
[ -n "${CONTAINER:-}" ] && docker ps -q --filter "name=^$CONTAINER\$" | grep -q . && { say "refused: container $CONTAINER exists"; echo TAKE_FAILED; exit 1; }
ss -ltn | grep -q ":$PORT " && { say "refused: port $PORT already has a listener"; echo TAKE_FAILED; exit 1; }
[ "$(gpuapps)" = 0 ] || { say "refused: GPU compute apps running"; echo TAKE_FAILED; exit 1; }
QUIET_LEASE_PID=$$ "$H/lease.sh" acquire "take $TAG" || { echo TAKE_FAILED; exit 1; }
export QUIET_LEASE_PID=$$
fetch_pause
sync; echo 3 > /proc/sys/vm/drop_caches; sleep 2
say "row $TAG; engine ${ENGINE:-?}; driver $DRV; MemAvailable $(memavail) kB after drop_caches"; wit before-load
echo "$SERVE" > "$OUT/serve.cmd"
setsid bash -c "$SERVE" > "$OUT/server.log" 2>&1 < /dev/null &
SPID=$!; T0=$(date +%s)
ready=""
for i in $(seq ${LOAD_TIMEOUT:-900}); do
  kill -0 "$SPID" 2>/dev/null || { say "server exited during load"; tail -30 "$OUT/server.log"; SPID=""; finish 1; }
  if curl -sf -m 5 "$URL/v1/models" > "$OUT/models.json" 2>/dev/null; then
    curl -sf -m 120 "$URL/v1/chat/completions" -H 'Content-Type: application/json' \
      -d "{\"model\":\"$(jq -r '.data[0].id' "$OUT/models.json")\",\"messages\":[{\"role\":\"user\",\"content\":\"2+2=?\"}],\"max_tokens\":8,\"temperature\":0}" \
      > "$OUT/smoke.json" 2>/dev/null && { ready=1; break; }
  fi
  sleep 1
done
[ -n "$ready" ] || { say "never ready"; tail -30 "$OUT/server.log"; finish 1; }
say "ready after $(( $(date +%s) - T0 )) s; MemAvailable $(memavail) kB; smoke: $(jq -c '.choices[0].message' "$OUT/smoke.json" | cut -c1-200)"
wit loaded
# settle: the load's own reads keep io pressure up for a while after the first answer (measured on the first row:
# some avg10 12.5 at ready, 0.9 forty seconds later), so takes start only once it has fallen or after 180 s
for i in $(seq 180); do
  [ $i -ge ${SETTLE_MIN:-20} ] && awk '/^some/{sub("avg10=","",$2); exit !($2<2.0)}' /proc/pressure/io && break; sleep 1
done
wit settled
[ "${SMOKE_ONLY:-0}" = 1 ] && finish 0
rc=0
for k in decode-code decode-prose pp512 pp4096; do
  case $k in decode-*) n=256;; *) n=32;; esac
  wit "$k"
  "$TT" record --url "$URL" --engine-kind openai --engine "${ENGINE:-?}" --wait 0 --for 0 -n $n --temp 0 --no-think \
    --prompts "$P/$k.jsonl" --sessions 1 --host-label "" --out "$OUT/tapes" --tag "$TAG $k" --no-card --quiet -o json \
    ${MODEL_ID:+--model "$MODEL_ID"} > "$OUT/$k.json" 2> "$OUT/$k.err" || { say "$k: toktape rc $?: $(tail -2 "$OUT/$k.err")"; rc=1; }
  say "$k: $(jq -c '{decode:.timings.client_predicted_per_second, ttft_ms:.timings.ttft_ms, pp:.timings.prompt_per_second}' "$OUT/$k.json" 2>/dev/null)"
done
finish $rc
