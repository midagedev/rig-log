# The environment of the DGX Spark's bloomery builds: tools/box.sh's local mode sources it there as ~/bloomery-env.sh
# (BLOOMERY_ENV_FILE). Installed by `tools/bloomery-follow/spark-box.sh --install-env`; docs/spark-hold.md says how the machine is shared.
#
# Toolchain, one line each, with the fact each is held to:
#   Rust 1.99.1     rustup's own (~/.rustup, the tree's rust-toolchain.toml picks it, rust-src rustc-dev llvm-tools installed)
#   LLVM 21.1.8     the release tarball the Spark's bench sessions unpacked at /opt/build/llvm-21.1.8, used read-only: its llc is
#                   CUDA_OXIDE_LLC and its lib/ is bindgen's libclang. tools/oxide-host.sh refuses by name a llc that is gone or is
#                   not LLVM 21 (llc sha256 7c7bdaa67e180b5cb855ebc7666324314028014cc2b9333bc1e148ce85f95039, 2026-11-04)
#   CUDA 13.3.1     the toolkit of NVIDIA's nvidia/cuda:13.3.1-devel-ubuntu24.04 image (nvcc 13.3.73), copied out of it by
#                   `spark-box.sh --setup`: the tree's bindings need 13.3's headers, and the host's own 13.0 packages lack them
#                   (bindgen ends E0425 on cuGraphNodeGetParams). The driver stays R580; the binary loads libcuda at run time
# cargo-oxide and the patched backend are the tree's own, installed under ~/.cargo/cuda-oxide-bloomery/<rev>/ (spark-box.sh --setup).
[ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"
export PATH=/opt/build/llvm-21.1.8/bin:/root/bloomery-cuda/cuda-13.3.1/bin:$PATH
export CUDA_TOOLKIT_PATH=/root/bloomery-cuda/cuda-13.3.1
export LIBCLANG_PATH=/opt/build/llvm-21.1.8/lib
export CUDA_OXIDE_LLC=/opt/build/llvm-21.1.8/bin/llc
