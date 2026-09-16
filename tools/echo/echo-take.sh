#!/bin/bash
# echo-take.sh <tag> — one JoyAI-Echo 1.5 stage, gated and witnessed like every other take here.
#
# Echo runs in two stages by design, and on a 48 GB card the split is not optional: the Gemma
# conditioner is 24 GB bf16 and the DiT is 46 GB bf16, so they never share the device. Stage one
# (`MODE=encode`) runs Gemma, the video VAE encoder, MSST voice filtering and the audio VAE over
# every request and writes one .safetensors bundle per request; stage two (`MODE=generate`)
# loads the DiT — streamed block by block from pinned host RAM under the consumer profile — and
# renders one request from that cache. This is the pipeline's own `--condition-encode`
# boundary (docs/R2V_CONDITIONING.md), not something added here.
#
#   MODE=encode   REQDIR=examples/the_last_visa/requests CACHE=cache/last-visa bash echo-take.sh lv-encode
#   MODE=generate REQUEST=examples/the_last_visa/requests/009_01_shot_008_nathan_replies_to_elena_r2v.json \
#                 CACHE=cache/last-visa bash echo-take.sh lv-shot8
#
# CONFIG defaults to the repo's consumer BF16 profile (DiT layerwise offload on), because
# Ampere has no FP8 or FP4 path and 46 GB of bf16 does not fit beside activations in 48 GB.
# Paths in REQDIR/REQUEST/CACHE are relative to the Echo repo. Sentinel ECHO_DONE / ECHO_FAILED.
set -u
TAG=$1; OUT=/home/user/echo-runs/$TAG; LEASE=/home/user/gpu-lease
REPO=/home/user/echo/echo_longvideo
MODE=${MODE:?set MODE=encode or MODE=generate}
CONFIG=${CONFIG:-configs/inference.consumer.bf16.yaml}
CACHE=${CACHE:?set CACHE to the conditioning cache dir (relative to the Echo repo)}
REQDIR=${REQDIR:-}; REQUEST=${REQUEST:-}
EXTRA=${EXTRA:-}                 # passed through to inference.py verbatim, e.g. "--dit-resident-blocks 8"
mkdir -p $OUT
say(){ echo "$(date +%T) $*"; }
gpus(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr "\n" " "; }
# idle means the card THIS runner uses is idle: the 3090 may hold the served LLM (configs/llm-3090.service, 2026-09-16)
maxgpu(){ . /home/user/gpu-order.env; nvidia-smi -i $A6000_UUID --query-gpu=memory.used --format=csv,noheader,nounits; }
LEASE_TAG="echo-$TAG"; SPID=""; SMPID=""
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
  [ $rc -eq 0 ] && echo ECHO_DONE || echo ECHO_FAILED
  exit $rc; }
trap "finish 1" INT TERM
. /home/user/gpu-order.env
export CUDA_VISIBLE_DEVICES=$A6000_UUID   # the config says `cuda`; that must be the 48 GB card
[ -d "$REPO/.venv" ] || { say "refused: no env at $REPO/.venv"; echo ECHO_FAILED; exit 1; }
[ -f "$REPO/$CONFIG" ] || { say "refused: no config $REPO/$CONFIG"; echo ECHO_FAILED; exit 1; }
[ -f "$REPO/checkpoints/echo15_full_dmd/model.safetensors" ] || { say "refused: no Echo weight under checkpoints/"; echo ECHO_FAILED; exit 1; }
[ -f "$REPO/checkpoints/gemma-3-12b/model-00005-of-00005.safetensors" ] || { say "refused: Gemma incomplete under checkpoints/"; echo ECHO_FAILED; exit 1; }
case "$MODE" in
  encode)   [ -d "$REPO/$REQDIR" ] || { say "refused: no REQDIR $REPO/$REQDIR"; echo ECHO_FAILED; exit 1; }
            ARGS=(--config "$CONFIG" --condition-encode --requests-dir "$REQDIR" --conditioning-cache-dir "$CACHE") ;;
  generate) [ -f "$REPO/$REQUEST" ] || { say "refused: no REQUEST $REPO/$REQUEST"; echo ECHO_FAILED; exit 1; }
            [ -d "$REPO/$CACHE" ] || { say "refused: no cache at $REPO/$CACHE — run MODE=encode first"; echo ECHO_FAILED; exit 1; }
            ARGS=(--config "$CONFIG" --request "$REQUEST" --conditioning-cache-dir "$CACHE" --output-root "$OUT/result") ;;
  *) say "refused: MODE must be encode or generate"; echo ECHO_FAILED; exit 1 ;;
esac
[ -z "$EXTRA" ] || ARGS+=($EXTRA)
[ "$(date +%H%M)" -lt 2330 ] || { say "refused: after 23:30 KST"; echo ECHO_FAILED; exit 1; }
[ "$(maxgpu)" -lt 2000 ] || { say "refused: GPUs busy: $(gpus)"; echo ECHO_FAILED; exit 1; }
[ -f $LEASE ] && { say "refused: lease held: $(cat $LEASE)"; echo ECHO_FAILED; exit 1; }
echo "$LEASE_TAG $$ $(date +%FT%T)" > $LEASE
say "$TAG: mode=$MODE config=$CONFIG cache=$CACHE ${REQDIR:+reqdir=$REQDIR }${REQUEST:+request=$REQUEST }${EXTRA:+extra=$EXTRA}"
say "io avg10 $(awk "/some/{print \$2}" /proc/pressure/io); gpus before: $(gpus); host free $(free -g | awk '/Mem/{print $7}') GB"
nvidia-smi --query-gpu=timestamp,uuid,power.draw,clocks.sm,temperature.gpu,memory.used,utilization.gpu,clocks_throttle_reasons.active,clocks.mem,fan.speed \
  --format=csv,noheader,nounits -l 1 > $OUT/dmon.csv 2>&1 &
SMPID=$!
t0=$(date +%s)
setsid /home/user/echo-run-inner.sh "${ARGS[@]}" > $OUT/run.log 2>&1 < /dev/null &
SPID=$!; echo $SPID > $OUT/run.pid
kill -0 $SPID 2>/dev/null || { say "run exited immediately"; tail -20 $OUT/run.log; SPID=""; finish 1; }
[ "$(ps -o sid= -p $SPID | tr -d ' ')" = "$SPID" ] || { say "launch assertion failed (pid $SPID is not a session leader)"; finish 1; }
say "run pid $SPID"
wait $SPID; rc=$?
SPID=""
say "rc=$rc after $(( $(date +%s) - t0 )) s"
kill $SMPID 2>/dev/null; SMPID=""
say "peak VRAM by card (1 Hz witness — misses sub-second peaks):"
awk -F, "{gsub(/ /,\"\",\$2); if(\$6+0>m[\$2])m[\$2]=\$6+0} END{for(u in m) printf \"  %s %d MiB\n\", u, m[u]}" $OUT/dmon.csv
say "A6000: $(awk -F, -v u=$A6000_UUID "{gsub(/ /,\"\",\$2)} \$2==u{if(\$3+0>p)p=\$3+0; if(\$5+0>t)t=\$5+0} END{printf \"peak %s W, max %s C\", p, t}" $OUT/dmon.csv)"
say "throttle reasons seen: $(awk -F, -v u=$A6000_UUID "{gsub(/ /,\"\",\$2)} \$2==u{print \$8}" $OUT/dmon.csv | sort -u | tr "\n" "|")"
say "host peak RSS: $(grep -m1 'Maximum resident' $OUT/run.log | awk '{printf "%.1f GB", $NF/1e6}')"
if [ "$MODE" = generate ]; then
  R=$(find $OUT/result -name result.mp4 | head -1)
  if [ -n "$R" ]; then
    say "result: $R  $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$R") s  $(stat -c%s "$R") bytes"
    M=$(dirname "$R")/run_metadata.json
    [ -f "$M" ] && say "timing: $(python3 -c "import json;t=json.load(open('$M'))['timing'];print(f\"denoise {t['denoise_seconds']} s, decode {t['decode_seconds']} s, total {t['total_seconds']} s\")")"
  else say "no result.mp4 under $OUT/result"; rc=1; fi
else
  N=$(ls $REPO/$CACHE/*.safetensors 2>/dev/null | wc -l); say "$N conditioning bundle(s) in $CACHE"
  [ "$N" -gt 0 ] || rc=1
fi
finish $rc
