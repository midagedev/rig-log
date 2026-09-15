#!/bin/bash
# Install TabbyAPI main (53da791) into ~/.venv-tabby with the SAME torch and exllamav3 builds as ~/.venv-exl3.
# No GPU use. Sentinel TABBY_INSTALL_OK / TABBY_INSTALL_FAILED.
set -u
say(){ echo "$(date +%H:%M:%S) $*"; }
fail(){ say "FAILED: $*"; echo TABBY_INSTALL_FAILED; exit 1; }
cd /home/user
mkdir -p /home/user/tabby-check
if [ ! -d /home/user/tabbyAPI/.git ]; then
  git clone -q https://github.com/theroyallab/tabbyAPI /home/user/tabbyAPI || fail clone
fi
git -C /home/user/tabbyAPI checkout -q 53da791 || fail checkout
say "tabbyAPI at $(git -C /home/user/tabbyAPI log -1 --format='%h %ad' --date=short)"
[ -x /home/user/.venv-tabby/bin/python ] || python3 -m venv /home/user/.venv-tabby || fail venv
P=/home/user/.venv-tabby/bin/pip
$P install -q --upgrade pip || fail pip-upgrade
$P install -q "torch==2.10.0+cu128" --index-url https://download.pytorch.org/whl/cu128 || fail torch
$P install -q "https://github.com/turboderp-org/exllamav3/releases/download/v1.5.0/exllamav3-1.5.0+cu128.torch2.10.0-cp312-cp312-linux_x86_64.whl" || fail exllamav3
$P install -q -e /home/user/tabbyAPI || fail tabbyapi-base
say "installed"
$P freeze | grep -iE "^(torch|exllamav3|triton|tabbyapi|-e )|tabbyAPI" > /home/user/tabby-check/freeze-main.txt
cat /home/user/tabby-check/freeze-main.txt
cmp <(/home/user/.venv-exl3/bin/pip show torch exllamav3 | grep -E "^(Name|Version)") <(/home/user/.venv-tabby/bin/pip show torch exllamav3 | grep -E "^(Name|Version)") && say "torch/exllamav3 builds identical to ~/.venv-exl3" || fail "builds differ from ~/.venv-exl3"
cd /home/user/tabbyAPI && /home/user/.venv-tabby/bin/python -c "import torch, exllamav3; from exllamav3.version import __version__ as v; import backends.exllamav3.model as m; print('import ok', torch.__version__, v)" || fail import
echo TABBY_INSTALL_OK
