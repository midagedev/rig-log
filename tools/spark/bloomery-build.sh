#!/bin/bash
# A bloomery source build on the Spark inside nvidia/cuda:13.3.1-devel-ubuntu24.04, the container bloomery's
# docs/contrib/dgx-spark.md section 2.1 names; the host's driver (580) and kernel are not touched. The tree is a scratch
# clone under /opt/build (never pushed); the toolchains (rustup 1.99.1, cargo-oxide at the pinned rev, the patched
# backend) persist in /opt/build/cargo-home across runs; LLVM 21.1.8 (llc for CUDA_OXIDE_LLC, clang and libclang for
# bindgen) is the release tarball bloomery-build-prep.sh unpacked. Builds the GB10 release's bloomery-serve shape.
# usage: bloomery-build.sh <tree under /opt/build> <out dir>   sentinel BUILD_DONE rc=<n>
set -u
T=${1:?tree}; O=${2:?out}; mkdir -p /opt/build/cargo-home /opt/build/rustup-home "$O"
docker run --rm --name spark-bloomery-build --network host -v /opt/build:/opt/build -w "$T" \
  -e CARGO_HOME=/opt/build/cargo-home -e RUSTUP_HOME=/opt/build/rustup-home -e OUT="$O" \
  nvidia/cuda:13.3.1-devel-ubuntu24.04 bash -c '
set -eu
export PATH=$CARGO_HOME/bin:/opt/build/llvm-21.1.8/bin:/usr/local/cuda/bin:$PATH
export CUDA_OXIDE_LLC=/opt/build/llvm-21.1.8/bin/llc LIBCLANG_PATH=/opt/build/llvm-21.1.8/lib CUDA_HOME=/usr/local/cuda
command -v git >/dev/null || { apt-get update -qq && apt-get install -y -qq git curl pkg-config libssl-dev build-essential >/dev/null; }
command -v rustup >/dev/null || curl -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path --default-toolchain none
rustup toolchain list | grep -q 1.99.1 || rustup toolchain install 1.99.1 --profile minimal -c rust-src,rustc-dev,llvm-tools
command -v cargo-oxide >/dev/null || cargo +1.99.1 install --locked --git https://github.com/NVIDIA/cuda-rust.git --rev 9df9e7cef561e03a066230b3bb433b3d8285da81 cargo-oxide
tools/oxide-backend.sh
tools/oxide-host.sh
time cargo oxide build --arch sm_121a -- -p bloomery-gpu-gates --features glm5next,clef,vision,mimo2,solar2,minimaxm3,flint,mistrallarge4,gemma-embedding2,hf,checkpoint --release --bin bloomery-serve
cp target/release/bloomery-serve "$OUT/"
'
echo "BUILD_DONE rc=$?"
