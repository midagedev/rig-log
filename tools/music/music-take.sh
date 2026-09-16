#!/bin/bash
# music-take.sh <tag> — one YuE2 take, under the same lease and witness as every other take.
# A 7 GB model on a shared box still needs the lease: a peer session's thermal row is spoiled
# by an unannounced load just as surely by a music model as by a 42 GB video one.
set -u
TAG=$1; OUT=/home/user/music-runs/$TAG; LEASE=/home/user/gpu-lease
ENVDIR=/home/user/yue2
STYLE=${STYLE:?set STYLE}
LYRICS_FILE=${LYRICS_FILE:-}
SEED=${SEED:-23}
COT=${COT:-full}
ABC=${ABC:-}
PLAN_ONLY=${PLAN_ONLY:-}
mkdir -p $OUT
say(){ echo "$(date +%T) $*"; }
maxgpu(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1; }
gpus(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr "\n" " "; }
LEASE_TAG="music-$TAG"; SPID=""; SMPID=""
finish(){ rc=$1
  [ -n "$SMPID" ] && kill $SMPID 2>/dev/null
  if [ -n "$SPID" ] && kill -0 $SPID 2>/dev/null; then
    say "stopping run pid $SPID"; kill -TERM $SPID
    for i in $(seq 60); do kill -0 $SPID 2>/dev/null || break; sleep 1; done
  fi
  if [ -n "$SPID" ]; then
    members(){ ps -eo pid=,sid= | awk -v s=$SPID '$2==s && $1!=s{printf "%s ", $1}'; }
    for i in $(seq 15); do [ -z "$(members)" ] && break; sleep 1; done
    [ -n "$(members)" ] && { kill -TERM $(members) 2>/dev/null; sleep 10; }
  fi
  for i in $(seq 45); do [ "$(maxgpu)" -lt 2000 ] && break; sleep 2; done
  say "gpus after: $(gpus)"
  if [ "$(maxgpu)" -lt 2000 ]; then
    [ -f $LEASE ] && grep -q "^$LEASE_TAG " $LEASE && rm -f $LEASE && say "lease released"
  else say "GPUS NOT RELEASED: lease kept"; rc=1; fi
  [ $rc -eq 0 ] && echo MUSIC_DONE || echo MUSIC_FAILED
  exit $rc; }
trap "finish 1" INT TERM
. /home/user/gpu-order.env
[ -d /models/YuE2-3B ] || { say "refused: no YuE2 weights"; echo MUSIC_FAILED; exit 1; }
[ -d "$ENVDIR" ] || { say "refused: no yue2 env"; echo MUSIC_FAILED; exit 1; }
[ "$(date +%H%M)" -lt 2330 ] || { say "refused: after 23:30 KST"; echo MUSIC_FAILED; exit 1; }
[ "$(maxgpu)" -lt 2000 ] || { say "refused: GPUs busy: $(gpus)"; echo MUSIC_FAILED; exit 1; }
[ -f $LEASE ] && { say "refused: lease held: $(cat $LEASE)"; echo MUSIC_FAILED; exit 1; }
echo "$LEASE_TAG $$ $(date +%FT%T)" > $LEASE
say "$TAG: seed=$SEED cot=$COT abc=${ABC:-none} plan_only=${PLAN_ONLY:-no}"
nvidia-smi --query-gpu=timestamp,uuid,power.draw,clocks.sm,temperature.gpu,memory.used,utilization.gpu,clocks_throttle_reasons.active,clocks.mem,fan.speed \
  --format=csv,noheader,nounits -l 1 > $OUT/dmon.csv 2>&1 &
SMPID=$!
ARGS=(--style "$STYLE" --out "$OUT" --seed "$SEED" --cot "$COT")
[ -z "$LYRICS_FILE" ] || ARGS+=(--lyrics-file "$LYRICS_FILE")
[ -z "$ABC" ] || ARGS+=(--abc "$ABC")
[ -z "$PLAN_ONLY" ] || ARGS+=(--plan-only)
t0=$(date +%s)
cd $ENVDIR || finish 1
setsid /home/user/music-run-inner.sh "${ARGS[@]}" > $OUT/run.log 2>&1 < /dev/null &
SPID=$!; echo $SPID > $OUT/run.pid
kill -0 $SPID 2>/dev/null || { say "run exited immediately"; tail -20 $OUT/run.log; SPID=""; finish 1; }
say "run pid $SPID"
wait $SPID; rc=$?
SPID=""
say "rc=$rc after $(( $(date +%s) - t0 )) s"
kill $SMPID 2>/dev/null; SMPID=""
say "peak VRAM: $(awk -F, -v u=$A6000_UUID "{gsub(/ /,\"\",\$2)} \$2==u{if(\$6+0>m)m=\$6+0} END{printf \"%d MiB\", m}" $OUT/dmon.csv)"
say "A6000: $(awk -F, -v u=$A6000_UUID "{gsub(/ /,\"\",\$2)} \$2==u{if(\$3+0>p)p=\$3+0; if(\$5+0>t)t=\$5+0} END{printf \"peak %s W, max %s C\", p, t}" $OUT/dmon.csv)"
ls -l $OUT/*.flac 2>/dev/null || say "(no audio; plan-only run?)"
finish $rc
