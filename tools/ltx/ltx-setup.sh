#!/bin/bash
# ltx-setup.sh — install uv, clone LTX-2, uv sync. No GPU, no lease needed.
set -u
say(){ echo "$(date +%T) $*"; }
say "start"
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh || { say "uv install failed"; echo LTX_SETUP_FAILED; exit 1; }
fi
export PATH=/usr/local/bin:$PATH
say "uv $(uv --version)"
cd /home/user || exit 1
if [ -d /home/user/LTX-2/.git ]; then
  git -C /home/user/LTX-2 fetch --depth 1 origin main && git -C /home/user/LTX-2 reset --hard origin/main
else
  git clone --depth 1 https://github.com/Lightricks/LTX-2.git /home/user/LTX-2 || { say "clone failed"; echo LTX_SETUP_FAILED; exit 1; }
fi
cd /home/user/LTX-2 || exit 1
say "at $(git log -1 --format=%h\ %ci)"
uv sync --extra natten 2>&1 | tail -30
rc=${PIPESTATUS[0]}
[ $rc -eq 0 ] || { say "uv sync rc=$rc"; echo LTX_SETUP_FAILED; exit 1; }
say "torch: $(uv run python -c "import torch;print(torch.__version__, torch.version.cuda, torch.cuda.is_available())" 2>&1 | tail -1)"
say "natten: $(uv run python -c "import natten;print(natten.__version__)" 2>&1 | tail -1)"
echo LTX_SETUP_DONE
