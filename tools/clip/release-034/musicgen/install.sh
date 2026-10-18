#!/usr/bin/env bash
# Install ACE-Step 1.5 and its weights under /root/musicgen on the box. No card is opened. Downloads are anonymous
# (HF_HOME points at an empty directory here, so no stored token is read or sent); every repo used is MIT and not
# gated. Writes /root/musicgen/install.rc (0 = done) as the completion sentinel.
set -euo pipefail
R=/root/musicgen
REV=ca1e85fe9430179831e6bc6be790c332190a3866          # ACE-Step-1.5 main, 2026-08-29
export HF_HOME=$R/hf UV_CACHE_DIR=$R/uv-cache HF_HUB_DISABLE_TELEMETRY=1
rm -f $R/install.rc
mkdir -p $R/hf
if [ ! -d $R/src/.git ]; then
  git clone -q https://github.com/ace-step/ACE-Step-1.5.git $R/src
fi
git -C $R/src fetch -q origin $REV
git -C $R/src checkout -q $REV
[ "$(git -C $R/src rev-parse HEAD)" = $REV ] || { echo "install: src is not at $REV" >&2; exit 1; }
cd $R/src
uv sync --python 3.12 2>&1 | tail -5
.venv/bin/python -c 'import torch, acestep; print("torch", torch.__version__, "cuda", torch.version.cuda)'
# the main bundle (turbo DiT, 1.7B LM, VAE, text encoder), then the XL-sft DiT and the 4B LM
.venv/bin/acestep-download -d $R/src/checkpoints
.venv/bin/acestep-download -d $R/src/checkpoints --skip-main -m acestep-v15-xl-sft
.venv/bin/acestep-download -d $R/src/checkpoints --skip-main -m acestep-5Hz-lm-4B
du -sh $R/src/checkpoints/* $R/src/.venv
echo 0 > $R/install.rc
