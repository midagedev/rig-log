#!/bin/bash
# img-take.sh <tag> — one image-generation take, gated and witnessed like a video take.
#
# The gates are not ceremony. This box serves an LLM on both cards, a peer session takes the
# A6000 at midnight, and three Claude sessions share it: a 34 GB model loaded without the
# lease is how another session's measurement gets a contaminated row. So the same contract
# as ltx-take.sh — one lease file, GPUs verified idle, released only after the VRAM comes
# back — and the same 1 Hz witness, because an image take is also a thermal event.
#
#   MODEL=/models/Z-Image-Turbo PROMPT="$(cat p.txt)" bash img-take.sh zimage-kaiju
#   MODEL=/models/Krea-2-Turbo COUNT=4 WH="1536 1024" bash img-take.sh krea-kaiju
#
# Sentinel IMG_DONE / IMG_FAILED.
set -u
TAG=$1; OUT=/home/user/img-runs/$TAG; LEASE=/home/user/gpu-lease
ENVDIR=/home/user/imggen
MODEL=${MODEL:?set MODEL to a local diffusers directory}
PROMPT=${PROMPT:?set PROMPT}
NEG=${NEG:-}
WH=${WH:-1536 1024}
STEPS=${STEPS:-}                 # empty = the model card's own default
GUIDANCE=${GUIDANCE:-0.0}        # both turbo models here specify 0.0
SEED=${SEED:-23}
COUNT=${COUNT:-1}
mkdir -p $OUT
say(){ echo "$(date +%T) $*"; }
gpus(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr "\n" " "; }
# idle means the card THIS runner uses is idle: the 3090 may hold the served LLM (configs/llm-3090.service, 2026-09-16)
maxgpu(){ . /home/user/gpu-order.env; nvidia-smi -i $A6000_UUID --query-gpu=memory.used --format=csv,noheader,nounits; }
LEASE_TAG="img-$TAG"; SPID=""; SMPID=""
finish(){ rc=$1
  [ -n "$SMPID" ] && kill $SMPID 2>/dev/null
  if [ -n "$SPID" ] && kill -0 $SPID 2>/dev/null; then
    say "stopping run pid $SPID"; kill -TERM $SPID
    for i in $(seq 60); do kill -0 $SPID 2>/dev/null || break; sleep 1; done
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
  [ $rc -eq 0 ] && echo IMG_DONE || echo IMG_FAILED
  exit $rc; }
trap "finish 1" INT TERM
. /home/user/gpu-order.env
[ -d "$MODEL" ] || { say "refused: no model at $MODEL"; echo IMG_FAILED; exit 1; }
[ -f "$MODEL/model_index.json" ] || { say "refused: $MODEL has no model_index.json — not a diffusers directory"; echo IMG_FAILED; exit 1; }
[ -d "$ENVDIR" ] || { say "refused: no imggen env at $ENVDIR"; echo IMG_FAILED; exit 1; }
[ "$(date +%H%M)" -lt 2330 ] || { say "refused: after 23:30 KST"; echo IMG_FAILED; exit 1; }
[ "$(maxgpu)" -lt 2000 ] || { say "refused: GPUs busy: $(gpus)"; echo IMG_FAILED; exit 1; }
[ -f $LEASE ] && { say "refused: lease held: $(cat $LEASE)"; echo IMG_FAILED; exit 1; }
echo "$LEASE_TAG $$ $(date +%FT%T)" > $LEASE
say "$TAG: model=$(basename $MODEL) wh=$WH steps=${STEPS:-card-default} guidance=$GUIDANCE seed=$SEED count=$COUNT"
say "io avg10 $(awk "/some/{print \$2}" /proc/pressure/io); gpus before: $(gpus)"
nvidia-smi --query-gpu=timestamp,uuid,power.draw,clocks.sm,temperature.gpu,memory.used,utilization.gpu,clocks_throttle_reasons.active,clocks.mem,fan.speed \
  --format=csv,noheader,nounits -l 1 > $OUT/dmon.csv 2>&1 &
SMPID=$!
ARGS=(--model "$MODEL" --prompt "$PROMPT" --out "$OUT" --wh $WH
      --guidance "$GUIDANCE" --seed "$SEED" --count "$COUNT")
[ -z "$STEPS" ] || ARGS+=(--steps "$STEPS")
[ -z "$NEG" ]   || ARGS+=(--negative-prompt "$NEG")
t0=$(date +%s)
cd $ENVDIR || finish 1
setsid /home/user/img-run-inner.sh "${ARGS[@]}" > $OUT/run.log 2>&1 < /dev/null &
SPID=$!; echo $SPID > $OUT/run.pid
kill -0 $SPID 2>/dev/null || { say "run exited immediately"; tail -20 $OUT/run.log; SPID=""; finish 1; }
[ "$(ps -o sid= -p $SPID | tr -d ' ')" = "$SPID" ] || { say "launch assertion failed (pid $SPID is not a session leader)"; finish 1; }
say "run pid $SPID"
wait $SPID; rc=$?
SPID=""
say "rc=$rc after $(( $(date +%s) - t0 )) s"
kill $SMPID 2>/dev/null; SMPID=""
# +0 everywhere: awk compared these as strings once and reported 8022 MiB for a 48016 peak
say "peak VRAM by card:"
awk -F, "{gsub(/ /,\"\",\$2); if(\$6+0>m[\$2])m[\$2]=\$6+0} END{for(u in m) printf \"  %s %d MiB\n\", u, m[u]}" $OUT/dmon.csv
say "A6000: $(awk -F, -v u=$A6000_UUID "{gsub(/ /,\"\",\$2)} \$2==u{if(\$3+0>p)p=\$3+0; if(\$5+0>t)t=\$5+0} END{printf \"peak %s W, max %s C\", p, t}" $OUT/dmon.csv)"
say "throttle reasons seen: $(awk -F, -v u=$A6000_UUID "{gsub(/ /,\"\",\$2)} \$2==u{print \$8}" $OUT/dmon.csv | sort -u | tr "\n" "|")"
N=$(ls $OUT/*.png 2>/dev/null | wc -l)
[ "$N" -eq "$COUNT" ] && say "$N image(s) written" || { say "wanted $COUNT images, found $N"; rc=1; }
finish $rc
