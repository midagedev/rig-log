#!/usr/bin/env bash
# Build probe_mainline against an existing ggml-org/llama.cpp tree. Mirrors bloomery's
# tools/ref/build-kvclear.sh, which builds the same probe against ik_llama.cpp.
#
# The tree is only read: mainline here is a BUILD_SHARED_LIBS=ON Release build, so one g++
# against build/bin/*.so is enough and nothing in the engine is rebuilt.
# LC points at the llama.cpp tree; the binary lands outside it.
set -euo pipefail
: "${LC:=/home/user/llama.cpp}"
OUT=${WWIDTH_OUT:-/root/wwidth/bin}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$OUT"
g++ -std=c++17 -O2 -o "$OUT/probe_mainline" "$HERE/probe_mainline.cpp" \
  -I"$LC/ggml/include" -I"$LC/include" -I"$LC/common" -I"$LC/vendor" \
  -L"$LC/build/bin" \
  -lllama-common -lllama -lggml -lggml-base \
  -Wl,-rpath,"$LC/build/bin"
echo "built $OUT/probe_mainline (LC=$LC)"
