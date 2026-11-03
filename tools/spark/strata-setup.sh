#!/bin/bash
# Strata's own setup on the DGX Spark, 2026-11-03: a source checkout of v0.2.10 (the release whose engine 0.1.56
# install-engines.sh put in /opt/engines/strata-v0.2.10), and its setup.py writing the run config for a model whose
# GGUFs are already here (--gguf-dir: setup checks their size and SHA-256 and fetches nothing it has). The run config
# is what `strata serve --profile` starts, so the rows run Strata as its users do. Setup's own choices stay (the
# Spark settings its DGX_SPARK_LINUX.md lists); the context is the 65,536 that page's commands use.
#   strata-setup.sh qwen36   Qwen3.6-35B-A3B UD-Q4_K_XL from unsloth/Qwen3.6-35B-A3B-MTP-GGUF @5bc3e238 (setup's pin)
#   strata-setup.sh iq3s     Qwen3.8-Flash-Next GSQ-RCO IQ3_S from ISTA-DASLab @ed59f920 (setup's pin)
# Writes /root/health/strata-setup-<model>.log; prints the run config's path at the end.
set -u
S=/opt/engines/strata-src-v0.2.10; D=/opt/engines/strata-data
[ -d "$S" ] || git clone -q --depth 1 --branch v0.2.10 https://github.com/Niko1221/Strata "$S" || exit 1
mkdir -p "$D"; cd "$S" || exit 1
case ${1:?qwen36|iq3s} in
  qwen36) a=(--family qwen36 --model UD-Q4_K_XL --gguf-dir /models/Qwen3.6-35B-A3B-MTP-GGUF);;
  iq3s)   a=(--family qwen --model IQ3_S --gguf-dir /models/Qwen3.8-Flash-Next-GSQ-RCO-GGUF);;
  *) echo "unknown $1"; exit 1;;
esac
./setup.sh --setup "${a[@]}" --context 65536 --vision no --yes --no-start --data-dir "$D"; rc=$?
echo "run scripts: $(ls -t "$S"/run-*.sh 2>/dev/null | tr "\n" " ")"
echo "STRATA_SETUP_DONE rc=$rc"
