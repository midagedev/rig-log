#!/bin/bash
# ltx-take.sh <tag> — one LTX-2.5 generation, instrumented.
# Gates: lease free, GPUs idle, before 23:30 KST (webuta takes the A6000 at 00:00).
# Every knob is an argument, never a default that hides: the log names what ran.
# Sentinel LTX_DONE / LTX_FAILED.
set -u
TAG=$1; OUT=/home/user/ltx-runs/$TAG; LEASE=/home/user/gpu-lease
R=/home/user/LTX-2; M=/models/LTX-2.5
PIPE=${PIPE:-distilled}          # distilled | dfr | distilled_mgpu | ti2vid_two_stages[_hq]
FRAMES=${FRAMES:-121}
SEED=${SEED:-42}
# Guided pipelines only. Guidance lives in stage 1: stage 2 upsamples with the distilled
# LoRA on a distilled schedule and has no CFG by design, which is why the LoRA is required
# rather than optional. Left empty, each knob keeps the pipeline's own default (30 steps,
# cfg 3.0, stg 1.0, rescale 0.7, a2v 3.0) and the say line below records that.
STEPS=${STEPS:-}                 # --num-inference-steps
CFG=${CFG:-}                     # --video-cfg-guidance-scale, 1.0 = off
STG=${STG:-}                     # --video-stg-guidance-scale, 0.0 = off
RESCALE=${RESCALE:-}             # --video-rescale-scale
A2V=${A2V:-}                     # --a2v-guidance-scale
LORA_STRENGTH=${LORA_STRENGTH:-1.0}
# The pipeline's own default negative prompt is long, invisible, and tuned for photoreal
# human footage — it pushes away from "cartoonish rendering, 3D CGI look, unrealistic
# materials", which is not neutral for a giant-robot shot. Whatever is used gets written
# to $OUT/neg-prompt.txt, because a guided take is steered as much by this as by PROMPT.
NEG=${NEG:-}                     # --negative-prompt
OFFLOAD=${OFFLOAD:-none}         # none | cpu | disk
QUANT=${QUANT:-}                 # empty | fp8-cast
MBS=${MBS:-}                     # --max-batch-size
WH=${WH:-}                       # e.g. "1024 1536" -> --width 1024 --height 1536
PROMPT=${PROMPT:-"A close-up of a mechanical watch movement on a matte black surface, the balance wheel oscillating steadily. A jeweller in a grey apron lowers a brass tweezer into frame and sets a ruby jewel into its setting with a faint metallic tick. The camera pushes in slowly, shallow depth of field, cold key light from the left and a warm practical lamp behind, the brass catching a highlight as it moves. Dust motes drift through the beam. The room is quiet except for the ticking and one soft breath."}
IMAGE=${IMAGE:-}                 # "PATH FRAME_IDX STRENGTH" for --image conditioning
PLIM=${PLIM:-}                   # board power limit in W for this take (restored on exit)
mkdir -p $OUT
say(){ echo "$(date +%T) $*"; }
gpus(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr "\n" " "; }
maxgpu(){ nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -n1; }
LEASE_TAG="ltx-$TAG"; SPID=""; SMPID=""; PLIM_OLD=""
finish(){ rc=$1
  [ -n "$SMPID" ] && kill $SMPID 2>/dev/null
  if [ -n "$SPID" ] && kill -0 $SPID 2>/dev/null; then
    say "stopping run pid $SPID"; kill -TERM $SPID
    for i in $(seq 60); do kill -0 $SPID 2>/dev/null || break; sleep 1; done
    kill -0 $SPID 2>/dev/null && { say "run $SPID alive after 60 s"; rc=1; }
  fi
  if [ -n "$SPID" ]; then
    # uv spawns python, python spawns nothing we named: the session is what holds the VRAM.
    members(){ ps -eo pid=,sid= | awk -v s=$SPID '$2==s && $1!=s{printf "%s ", $1}'; }
    for i in $(seq 15); do [ -z "$(members)" ] && break; sleep 1; done
    [ -n "$(members)" ] && { say "session members left: $(members) -> SIGTERM"; kill -TERM $(members) 2>/dev/null; sleep 10; }
  fi
  if [ -n "$PLIM_OLD" ]; then
    nvidia-smi -i $A6000_UUID -pl $PLIM_OLD >/dev/null 2>&1 && say "power limit restored to $PLIM_OLD W" || say "POWER LIMIT NOT RESTORED (wanted $PLIM_OLD W)"
  fi
  for i in $(seq 45); do [ "$(maxgpu)" -lt 2000 ] && break; sleep 2; done
  say "gpus after: $(gpus)"
  if [ "$(maxgpu)" -lt 2000 ]; then
    [ -f $LEASE ] && grep -q "^$LEASE_TAG " $LEASE && rm -f $LEASE && say "lease released"
  else
    say "GPUS NOT RELEASED: lease kept ($(cat $LEASE 2>/dev/null))"; rc=1
  fi
  [ $rc -eq 0 ] && echo LTX_DONE || echo LTX_FAILED
  exit $rc; }
trap "finish 1" INT TERM
. /home/user/gpu-order.env
[ -d "$M" ] || { say "refused: no weights at $M"; echo LTX_FAILED; exit 1; }
[ -d "$R" ] || { say "refused: no LTX-2 checkout at $R"; echo LTX_FAILED; exit 1; }
# Which transformer is not a preference: the guided pipelines run the dev checkpoint in
# stage 1, the distilled ones run the distilled checkpoint, and the two are the same size.
LORA=$M/loras/ltx-2.5-22b-distilled-lora-450-bf16.safetensors
case "$PIPE" in
  ti2vid_two_stages|ti2vid_two_stages_hq)
    GUIDED=1; XFORM=$M/diffusion_models/ltx-2.5-22b-dev-transformer-bf16.safetensors
    [ -f "$LORA" ] || { say "refused: guided pipe needs the distilled LoRA at $LORA"; echo LTX_FAILED; exit 1; } ;;
  *)
    GUIDED=0; XFORM=$M/diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors ;;
esac
[ -f "$XFORM" ] || { say "refused: no transformer at $XFORM"; echo LTX_FAILED; exit 1; }
[ "$(date +%H%M)" -lt 2330 ] || { say "refused: after 23:30 KST"; echo LTX_FAILED; exit 1; }
[ "$(maxgpu)" -lt 2000 ] || { say "refused: GPUs busy: $(gpus)"; echo LTX_FAILED; exit 1; }
[ -f $LEASE ] && { say "refused: lease held: $(cat $LEASE)"; echo LTX_FAILED; exit 1; }
echo "$LEASE_TAG $$ $(date +%FT%T)" > $LEASE
say "$TAG: LTX-2 $(git -C $R log -1 --format=%h); pipe=$PIPE frames=$FRAMES offload=$OFFLOAD quant=${QUANT:-none} mbs=${MBS:-1} wh=${WH:-default} seed=$SEED plim=${PLIM:-default}"
[ $GUIDED -eq 1 ] && say "  guided: steps=${STEPS:-30(default)} cfg=${CFG:-3.0(default)} stg=${STG:-1.0(default)} rescale=${RESCALE:-0.7(default)} a2v=${A2V:-3.0(default)} lora_strength=$LORA_STRENGTH neg=$([ -n "$NEG" ] && echo custom || echo model-default)"
say "io avg10 $(awk "/some/{print \$2}" /proc/pressure/io); gpus before: $(gpus); cache $(free -g | awk "/Mem:/{print \$6}") GiB"
if [ -n "$PLIM" ]; then
  PLIM_OLD=$(nvidia-smi -i $A6000_UUID --query-gpu=power.default_limit --format=csv,noheader,nounits | cut -d. -f1)
  nvidia-smi -i $A6000_UUID -pl $PLIM >/dev/null 2>&1 || { say "refused: cannot set power limit $PLIM"; PLIM_OLD=""; finish 1; }
  say "power limit $PLIM W (default $PLIM_OLD W)"
fi
# witness: 1 Hz per-card power, SM clock, temperature, memory, utilisation, active throttle reasons
nvidia-smi --query-gpu=timestamp,uuid,power.draw,clocks.sm,temperature.gpu,memory.used,utilization.gpu,clocks_throttle_reasons.active,clocks.mem,fan.speed \
  --format=csv,noheader,nounits -l 1 > $OUT/dmon.csv 2>&1 &
SMPID=$!
ARGS=(--transformer-path $XFORM
      --text-encoder-path $M/text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors
      --video-vae-path $M/vae/ltx-2.5-video-vae-bf16.safetensors
      --audio-vae-path $M/vae/ltx-2.5-audio-vae-bf16.safetensors
      --spatial-upsampler-path $M/latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors
      --num-frames $FRAMES --seed $SEED --output-path $OUT/out.mp4 --prompt "$PROMPT")
[ "$OFFLOAD" = none ] || ARGS+=(--offload $OFFLOAD)
[ -z "$QUANT" ] || ARGS+=(--quantization $QUANT)
[ -z "$MBS" ] || ARGS+=(--max-batch-size $MBS)
[ -z "$WH" ] || ARGS+=(--width ${WH% *} --height ${WH#* })
if [ $GUIDED -eq 1 ]; then
  ARGS+=(--distilled-lora "$LORA" "$LORA_STRENGTH")
  [ -z "$STEPS" ]   || ARGS+=(--num-inference-steps $STEPS)
  [ -z "$CFG" ]     || ARGS+=(--video-cfg-guidance-scale $CFG)
  [ -z "$STG" ]     || ARGS+=(--video-stg-guidance-scale $STG)
  [ -z "$RESCALE" ] || ARGS+=(--video-rescale-scale $RESCALE)
  [ -z "$A2V" ]     || ARGS+=(--a2v-guidance-scale $A2V)
  [ -z "$NEG" ]     || ARGS+=(--negative-prompt "$NEG")
  # record what actually steered the take, including the default that args.txt would not show
  if [ -n "$NEG" ]; then printf "%s\n" "$NEG" > $OUT/neg-prompt.txt
  else ( cd $R && /usr/local/bin/uv run python -c \
      "from ltx_pipelines.utils.constants import DEFAULT_NEGATIVE_PROMPT as n; print(n)" ) \
      > $OUT/neg-prompt.txt 2>/dev/null || say "could not record the default negative prompt"
  fi
fi
# word-split on purpose: --image takes PATH FRAME_IDX STRENGTH as three arguments
if [ -n "$IMAGE" ]; then
  set -- $IMAGE
  [ $# -eq 3 ] || { say "refused: IMAGE wants exactly \"PATH FRAME_IDX STRENGTH\", got $# word(s)"; echo LTX_FAILED; exit 1; }
  [ -f "$1" ] || { say "refused: no conditioning image at $1"; echo LTX_FAILED; exit 1; }
  ARGS+=(--image "$1" "$2" "$3")
fi
printf "%s\n" "${ARGS[@]}" > $OUT/args.txt
t0=$(date +%s)
cd $R || finish 1
setsid /home/user/ltx-run-inner.sh "$PIPE" "${ARGS[@]}" > $OUT/run.log 2>&1 < /dev/null &
SPID=$!; echo $SPID > $OUT/run.pid
kill -0 $SPID 2>/dev/null || { say "run exited immediately"; tail -20 $OUT/run.log; SPID=""; finish 1; }
[ "$(ps -o sid= -p $SPID | tr -d ' ')" = "$SPID" ] || { say "launch assertion failed (pid $SPID is not a session leader)"; finish 1; }
say "run pid $SPID"
wait $SPID; rc=$?
SPID=""
say "rc=$rc after $(( $(date +%s) - t0 )) s"
kill $SMPID 2>/dev/null; SMPID=""
# the run log is stamped, so /usr/bin/time's fields are shifted by one: take the last.
say "peak host RSS $(awk "/Maximum resident/{print \$NF}" $OUT/run.log) KB"
# numeric coercion is not cosmetic here: awk compared these as strings and reported
# 8022 MiB for a run whose real peak was 48016, because "8022" sorts above "42812".
say "peak VRAM by card:"
awk -F, "{gsub(/ /,\"\",\$2); if(\$6+0>m[\$2])m[\$2]=\$6+0} END{for(u in m) printf \"  %s %d MiB\n\", u, m[u]}" $OUT/dmon.csv
say "A6000 during run: power $(awk -F, -v u=$A6000_UUID "{gsub(/ /,\"\",\$2)} \$2==u{if(\$3+0>p)p=\$3+0; s+=\$3; n++} END{printf \"max %s mean %.0f W\", p, s/n}" $OUT/dmon.csv)"
say "A6000 temp/clock: $(awk -F, -v u=$A6000_UUID "{gsub(/ /,\"\",\$2)} \$2==u{if(\$5+0>t)t=\$5+0; c+=\$4; n++} END{printf \"max %s C, mean SM %.0f MHz\", t, c/n}" $OUT/dmon.csv)"
say "throttle reasons seen: $(awk -F, -v u=$A6000_UUID "{gsub(/ /,\"\",\$2)} \$2==u{print \$8}" $OUT/dmon.csv | sort -u | tr "\n" "|")"
[ -f $OUT/out.mp4 ] && say "output $(stat -c %s $OUT/out.mp4) bytes" || { say "no output file"; rc=1; }
finish $rc
