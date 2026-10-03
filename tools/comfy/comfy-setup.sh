#!/bin/bash
# comfy-setup.sh — clone ComfyUI, venv, requirements, extra_model_paths -> /models. No GPU, no lease.
# The weights are already on disk in ComfyUI's own layout (ltx-fetch.sh put /models/LTX-2.5 under
# diffusion_models/ text_encoders/ vae/ latent_upscale_models/), so the media side of the box needs
# no new downloads for LTX. Sentinel COMFY_SETUP_DONE / COMFY_SETUP_FAILED.
set -u
say(){ echo "$(date +%T) $*"; }
fail(){ say "$*"; echo COMFY_SETUP_FAILED; exit 1; }
C=/home/user/ComfyUI

say "start"
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh || fail "uv install failed"
fi
export PATH=/usr/local/bin:$PATH
say "uv $(uv --version)"

cd /home/user || exit 1
if [ -d $C/.git ]; then
  git -C $C fetch --depth 1 origin master && git -C $C reset --hard origin/master
else
  git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git $C || fail "clone failed"
fi
cd $C || exit 1
say "at $(git log -1 --format=%h\ %ci)"

# venv + requirements (torch wheels on Linux bundle CUDA; nothing to pick manually)
if [ ! -x $C/.venv/bin/python ]; then
  uv venv $C/.venv || fail "uv venv failed"
fi
uv pip install --python $C/.venv/bin/python -r requirements.txt 2>&1 | tail -15
rc=${PIPESTATUS[0]}
[ $rc -eq 0 ] || fail "requirements rc=$rc"
say "torch: $($C/.venv/bin/python -c "import torch;print(torch.__version__, torch.version.cuda, torch.cuda.is_available())" 2>&1 | tail -1)"

# /models in ComfyUI's vocabulary. Z-Image-Turbo/YuE2-3B live there as *diffusers* trees which
# ComfyUI does not read as-is; their ComfyUI-layout files are a later fetch if ever needed.
cat > $C/extra_model_paths.yaml <<'YAML'
models_on_disk:
  base_path: /models
  diffusion_models: diffusion_models
  text_encoders: text_encoders
  vae: vae
  latent_upscale_models: latent_upscale_models
  loras: loras
ltx_25:
  base_path: /models/LTX-2.5
  diffusion_models: diffusion_models
  text_encoders: text_encoders
  vae: vae
  latent_upscale_models: latent_upscale_models
YAML
say "extra_model_paths -> /models"

# music nodes (ACE-Step pack; LTX-2 and Z-Image are core). Failure here is loud, not silent.
mkdir -p $C/custom_nodes
if [ -d $C/custom_nodes/ComfyUI_ACE-Step/.git ]; then
  git -C $C/custom_nodes/ComfyUI_ACE-Step fetch --depth 1 origin && git -C $C/custom_nodes/ComfyUI_ACE-Step reset --hard origin/main
else
  git clone --depth 1 https://github.com/billwuhao/ComfyUI_ACE-Step.git $C/custom_nodes/ComfyUI_ACE-Step || fail "ACE-Step clone failed"
fi
if [ -f $C/custom_nodes/ComfyUI_ACE-Step/requirements.txt ]; then
  uv pip install --python $C/.venv/bin/python -r $C/custom_nodes/ComfyUI_ACE-Step/requirements.txt 2>&1 | tail -5
  [ ${PIPESTATUS[0]} -eq 0 ] || fail "ACE-Step requirements failed"
fi

echo COMFY_SETUP_DONE
