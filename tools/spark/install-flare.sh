#!/bin/bash
# Flare (NVIDIA/spark-local-inference, formerly flare-local-inference) on the DGX Spark, 2026-11-03. There is no
# release artifact: the Rust server (`flare`) is built with cargo and the preparation side (Ignition) is a uv
# environment with PyTorch 2.14.1+cu132, FlashInfer/b12x and Heliopause, per its docs/model-preparation.md
# "Environment setup". The host has no Rust or uv, so this installs rustup's stable toolchain under /root/.cargo and
# uv under /root/.local/bin, plus the apt build dependencies that page lists. Nothing is linked onto the system PATH.
# The open question on driver 580: the preparation wheels are CUDA 13.2 builds (cu132), newer than the driver's 13.0;
# the last step here is a one-tensor CUDA check in that environment, and its output is the answer.
# usage (root): install-flare.sh   log: stdout
set -euo pipefail
REV=cc696a6bf828deeb04b09533c64c5cc5b26b0ab5   # main, 2026-11-02
D=/opt/engines/flare-${REV:0:8}
say(){ echo "$(date -u +%H:%M:%SZ) $*"; }
say "apt build deps"
DEBIAN_FRONTEND=noninteractive apt-get install -y -q build-essential cmake ninja-build pkg-config protobuf-compiler libssl-dev python3-dev liburing-dev nasm > /dev/null
[ -x /root/.cargo/bin/cargo ] || { say "rustup stable"; curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable > /dev/null; }
[ -x /root/.local/bin/uv ] || { say "uv"; curl -fsSL https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh > /dev/null; }
export PATH=/root/.cargo/bin:/root/.local/bin:/usr/local/cuda/bin:$PATH
[ -d "$D" ] || { git clone -q https://github.com/NVIDIA/spark-local-inference "$D"; git -C "$D" checkout -q $REV; }
cd "$D"
say "cargo $(cargo --version); uv $(uv --version)"
say "cargo build --release (flare)"
cargo build -q --release --manifest-path flare/Cargo.toml
say "flare: $(flare/target/release/flare --version 2>&1 | head -1)"
say "uv sync --locked --extra prepare"
uv sync -q --locked --extra prepare
say "torch on this driver:"
.venv/bin/python - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.version.cuda, "available", torch.cuda.is_available())
x = torch.ones(1024, device="cuda"); print("device", torch.cuda.get_device_name(0), "capability", torch.cuda.get_device_capability(0), "sum", float(x.sum()))
PY
say "FLARE_INSTALL_DONE"
