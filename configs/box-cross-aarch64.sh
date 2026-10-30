#!/usr/bin/env bash
# The box's cross toolchain for bloomery's GB10 release archive (linux-aarch64, sm_121a), built on this x86_64 box:
# the aarch64 C linker and sysroot (glibc 2.39, the archive's floor) and Rust's aarch64 std for the pinned toolchain.
# bloomery's tools/release/build.sh reads them under BLOOMERY_RELEASE_TARGET=aarch64. Idempotent; run as root.
# Installed 2026-10-30 (gcc-aarch64-linux-gnu 13.3.0-6ubuntu2~24.04.1, rust 1.99.1).
set -euo pipefail
DEBIAN_FRONTEND=noninteractive apt-get install -y -q gcc-aarch64-linux-gnu
rustup target add aarch64-unknown-linux-gnu --toolchain "${1:-1.99.1}"
