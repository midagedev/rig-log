#!/bin/bash
# comfy-fetch.sh — the Qwen-Image-2.1 bf16 trio for ComfyUI, into /models' top-level layout
# (the one extra_model_paths.yaml already maps). Same contract as ltx-fetch.sh: every file is
# accepted only if its byte count equals the size the OFFICIAL repo API reports, so a re-saved
# tensor anywhere in the chain fails instead of passing. The bf16 set and not int8_convrot
# because this box has 48 GB and no FP8 hardware — full precision is the free choice here.
# Sentinel COMFY_FETCH_DONE / COMFY_FETCH_FAILED.
set -u
M=/models; SRC=${SRC:-Comfy-Org/Qwen-Image-2.1}
say(){ echo "$(date +%T) $*"; }
# official-repo sizes, read 2026-10-03 from huggingface.co/api/models/Comfy-Org/Qwen-Image-2.1?blobs=true
declare -A WANT=(
 [diffusion_models/qwen_image_2.1_bf16.safetensors]=14230280616
 [text_encoders/qwen3vl_8b_bf16.safetensors]=17534334616
 [vae/qwen_image_2.1_vae_bf16.safetensors]=675509688
)
mkdir -p $M/diffusion_models $M/text_encoders $M/vae
export HF_HUB_ENABLE_HF_TRANSFER=1
cd /home/user/ComfyUI || exit 1
rc=0
for dest in "${!WANT[@]}"; do
  want=${WANT[$dest]}; base=$(basename $dest)
  if [ -f "$M/$dest" ] && [ "$(stat -c %s "$M/$dest")" = "$want" ]; then say "have $base"; continue; fi
  say "fetch $base ($want bytes) from $SRC"
  got=""
  /usr/local/bin/uv run --with hf_transfer hf download "$SRC" "$dest" --local-dir /models/qwen21-dl >/dev/null 2>>$M/fetch.err && got=/models/qwen21-dl/$dest
  [ -n "$got" ] && [ -f "$got" ] || { say "FETCH FAILED $base"; rc=1; continue; }
  have=$(stat -c %s "$got")
  if [ "$have" != "$want" ]; then say "SIZE MISMATCH $base: got $have want $want -- rejected"; rc=1; continue; fi
  mv "$got" "$M/$dest"; say "ok $base $have bytes"
done
say "sha256, for the record:"
for dest in "${!WANT[@]}"; do [ -f "$M/$dest" ] && (cd $M && sha256sum "$dest"); done
[ $rc -eq 0 ] && echo COMFY_FETCH_DONE || echo COMFY_FETCH_FAILED
exit $rc
