#!/bin/bash
# Downloads for building bloomery from source on the Spark (contrib/dgx-spark.md section 2.1), 2026-11-04: network
# only, so it may run beside takes; the build itself (bloomery-build.sh) holds the lease. Gets
#   /opt/build/bloomery-<tag>          a clone at the release tag (default v0.3.12)
#   /opt/build/llvm-21.1.8             LLVM 21.1.8's ARM64 release (its llc is CUDA_OXIDE_LLC)
#   the tree's Rust toolchain (rust-toolchain.toml) through rustup, and `cargo fetch` of the workspace
# Sentinel BUILD_PREP_DONE rc=<n>.
set -u
TAG=${1:-v0.3.12}; B=/opt/build; mkdir -p $B; cd $B || exit 1
export PATH=$HOME/.cargo/bin:$PATH
rc=0
[ -d bloomery-$TAG ] || git clone -q --branch $TAG https://github.com/midagedev/bloomery bloomery-$TAG || rc=1
if [ ! -x llvm-21.1.8/bin/llc ]; then
  curl -fsSL -o llvm.tar.xz https://github.com/llvm/llvm-project/releases/download/llvmorg-21.1.8/LLVM-21.1.8-Linux-ARM64.tar.xz &&
  mkdir -p llvm-21.1.8 && nice -n 19 tar -xJf llvm.tar.xz -C llvm-21.1.8 --strip-components=1 && rm -f llvm.tar.xz || rc=1
fi
cd bloomery-$TAG && rustup show active-toolchain >/dev/null 2>&1 || rustup toolchain install "$(sed -n 's/^channel = "\(.*\)"/\1/p' rust-toolchain.toml)" || rc=1
nice -n 19 cargo fetch -q || rc=1
echo "llc: $($B/llvm-21.1.8/bin/llc --version 2>/dev/null | sed -n 2p)"
echo "BUILD_PREP_DONE rc=$rc"
