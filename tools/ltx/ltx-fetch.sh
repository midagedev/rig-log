#!/bin/bash
# ltx-fetch.sh — the five files DistilledPipeline needs, into the layout the CLI expects.
# Source is a mirror (the official repo is gated); every file is accepted only if its byte
# count equals the size the OFFICIAL repo API reports. Sizes are written here, not read from
# the mirror, so a mirror that re-saved a tensor fails instead of passing.
set -u
M=/models/LTX-2.5; SRC=${SRC:-yuvraj108c/LTX-2.5}
say(){ echo "$(date +%T) $*"; }
# official-repo sizes, read 2026-09-16 from huggingface.co/api/models/Lightricks/LTX-2.5?blobs=true
declare -A WANT=(
 [diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors]=42018190584
 [text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors]=26263858182
 [vae/ltx-2.5-video-vae-bf16.safetensors]=1472223346
 [vae/ltx-2.5-audio-vae-bf16.safetensors]=364866540
 [latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors]=995778752
)
mkdir -p $M/diffusion_models $M/text_encoders $M/vae $M/latent_upscale_models
export HF_HUB_ENABLE_HF_TRANSFER=1 HF_TOKEN=$(cat /home/user/.cache/huggingface/token)
cd /home/user/LTX-2 || exit 1
rc=0
for dest in "${!WANT[@]}"; do
  want=${WANT[$dest]}; base=$(basename $dest)
  if [ -f "$M/$dest" ] && [ "$(stat -c %s "$M/$dest")" = "$want" ]; then say "have $base"; continue; fi
  say "fetch $base ($want bytes) from $SRC"
  # the mirror is flat for some repos and foldered for others: try the foldered path, then the bare name
  got=""
  for p in "$dest" "$base"; do
    /usr/local/bin/uv run --with hf_transfer hf download "$SRC" "$p" --local-dir /models/LTX-2.5-dl >/dev/null 2>>$M/fetch.err && { got=/models/LTX-2.5-dl/$p; break; }
  done
  [ -n "$got" ] && [ -f "$got" ] || { say "FETCH FAILED $base"; rc=1; continue; }
  have=$(stat -c %s "$got")
  if [ "$have" != "$want" ]; then say "SIZE MISMATCH $base: got $have want $want -- rejected"; rc=1; continue; fi
  mv "$got" "$M/$dest"; say "ok $base $have bytes"
done
say "sha256, for the record:"
for dest in "${!WANT[@]}"; do [ -f "$M/$dest" ] && (cd $M && sha256sum "$dest"); done
du -sh $M
[ $rc -eq 0 ] && echo LTX_FETCH_DONE || echo LTX_FETCH_FAILED
exit $rc
