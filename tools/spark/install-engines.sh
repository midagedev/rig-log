#!/bin/bash
# Engines for the DGX Spark comparison that install without Docker, 2026-11-03: bloomery's GB10 release archive,
# Strata's linux-aarch64 engine package and llama.cpp built here for sm_121a with the host's CUDA 13.0 (the
# release's arm64 CUDA build is 13.4, newer than driver 580's CUDA 13.0). Each goes to /opt/engines/<name>-<version>,
# nothing is linked onto PATH, and a checksum is checked wherever the release publishes one.
# Docker engines (vLLM via eugr/spark-vllm-docker, SGLang lmsysorg/sglang:*-cu130, Atlas avarok/atlas-gb10) are pulled
# separately so their gigabytes do not share the 1 Gb/s link with a model fetch.
# usage (root): install-engines.sh [bloomery|strata|llamacpp|toktape]...   default: all four
set -euo pipefail
E=/opt/engines; mkdir -p "$E"; cd "$E"
say(){ echo "$(date -u +%H:%M:%SZ) $*"; }
BLOOMERY=v0.3.12
STRATA=v0.2.10 STRATA_ENGINE=0.1.56
LLAMA=b12069   # ggml-org/llama.cpp tag, 2026-11-03
TOKTAPE=v0.8.0 # the recorder, not an engine; linux_arm64 build

bloomery(){
  local a=bloomery-${BLOOMERY#v}-linux-aarch64-cuda-sm121a.tar.gz u=https://github.com/midagedev/bloomery/releases/download/$BLOOMERY
  [ -d bloomery-$BLOOMERY ] && { say "bloomery $BLOOMERY already here"; return; }
  curl -fsSLO "$u/$a"; curl -fsSLO "$u/$a.sha256"
  sha256sum -c "$a.sha256"
  mkdir bloomery-$BLOOMERY; tar -xzf "$a" -C bloomery-$BLOOMERY; rm -f "$a" "$a.sha256"
  say "bloomery $BLOOMERY: $(find bloomery-$BLOOMERY -name 'bloomery-serve*' -type f | head -3 | tr '\n' ' ')"
}
strata(){
  local a=strata-engine-$STRATA_ENGINE-linux-aarch64-cuda-cuda13.tar.gz u=https://github.com/Niko1221/Strata/releases/download/$STRATA
  [ -d strata-$STRATA ] && { say "strata $STRATA already here"; return; }
  curl -fsSLO "$u/$a"; curl -fsSL "$u/strata-feed-linux-aarch64.json" -o strata-feed-$STRATA.json
  # the feed names each package's sha256, build (CUDA 13.0, sm_121) and min_driver (580.65). Its .sig is not checked
  # here (that is strata's own installer's job); the sha256 only proves the archive is the one the feed lists.
  want=$(jq -r --arg a "$a" '.engine.packages[] | select(.url==$a) | .sha256' strata-feed-$STRATA.json)
  jq -r --arg a "$a" '.engine.packages[] | select(.url==$a) | "strata feed: \(.build_id) archs \(.archs|join(",")) min_driver \(.min_driver.nvidia)"' strata-feed-$STRATA.json
  echo "$want  $a" | sha256sum -c
  mkdir strata-$STRATA; tar -xzf "$a" -C strata-$STRATA; rm -f "$a"
  say "strata $STRATA: $(find strata-$STRATA -maxdepth 3 -type f -perm -u+x | head -5 | tr '\n' ' ')"
}
llamacpp(){
  [ -x llama.cpp-$LLAMA/build/bin/llama-server ] && { say "llama.cpp $LLAMA already built"; return; }
  [ -d llama.cpp-$LLAMA ] || git clone -q --depth 1 --branch $LLAMA https://github.com/ggml-org/llama.cpp llama.cpp-$LLAMA
  cd llama.cpp-$LLAMA
  # the playbook's flags (NVIDIA dgx-spark-playbooks nvidia/llama-cpp, step 3) with the host nvcc named
  cmake -B build -DGGML_CUDA=ON -DGGML_NATIVE=ON -DCMAKE_CUDA_ARCHITECTURES=121a-real \
    -DCMAKE_CUDA_COMPILER=/usr/local/cuda-13.0/bin/nvcc -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF > ../llama.cpp-$LLAMA.cmake.log 2>&1
  cmake --build build -j 20 --target llama-server llama-bench llama-cli > ../llama.cpp-$LLAMA.build.log 2>&1
  cd ..; say "llama.cpp $LLAMA: $(llama.cpp-$LLAMA/build/bin/llama-server --version 2>&1 | tail -1)"
}
toktape(){
  local v=${TOKTAPE#v} u=https://github.com/midagedev/toktape/releases/download/$TOKTAPE a
  a=toktape_${v}_linux_arm64.tar.gz
  [ -x toktape-$TOKTAPE/toktape ] && { say "toktape $TOKTAPE already here"; return; }
  curl -fsSLO "$u/$a"; curl -fsSL "$u/checksums.txt" | grep " $a\$" | sha256sum -c
  mkdir toktape-$TOKTAPE; tar -xzf "$a" -C toktape-$TOKTAPE; rm -f "$a"
  say "toktape: $(toktape-$TOKTAPE/toktape version 2>&1 | head -1)"
}
for x in "${@:-bloomery strata llamacpp toktape}"; do for y in $x; do $y; done; done
