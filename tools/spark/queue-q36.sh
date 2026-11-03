#!/bin/bash
# The 11-03 evening queue, one job after another (start it behind q-after.sh): the README-method prefill probe, the MTP
# GGUF rows (bloomery and llama.cpp on both Unsloth MTP files), the Qwen3.8 GGUF rows the first pass could not take
# (bloomery rec with the shared MTP draft, llama.cpp at bloomery's 16,896 context), Strata on Qwen3.6, then the SGLang,
# TensorFold and Atlas rows. A job that fails is logged and the next one runs. Sentinel QUEUE_Q36_DONE.
set -u; cd /root/health
G=/models/Qwen3.6-35B-A3B-MTP-GGUF; Q38=/models/Qwen3.8-Flash-Next-GGUF
job(){ echo "$(date -u +%TZ) start $*"; "$@"; echo "$(date -u +%TZ) end rc=$? $1"; }
job ./probes-lag.sh ids
job ./rows-gguf.sh q36mtp-udq4km $G/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf bloomery-default bloomery-rec bloomery-nomtp llamacpp-default llamacpp-rec
job ./rows-gguf.sh q36mtp-udq4kxl $G/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf bloomery-default bloomery-rec bloomery-nomtp llamacpp-default llamacpp-rec
DRAFT=$Q38/MTP/mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf job ./rows-gguf.sh q38-udq4kxl-shared $Q38/UD-Q4_K_XL/Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00004.gguf bloomery-rec
job ./rows-gguf.sh q38-udq4kxl $Q38/UD-Q4_K_XL/Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00004.gguf llamacpp-c16k
run=$(ls -t /root/run-ud-q4_k_xl.sh /opt/engines/strata-data/run-ud-q4_k_xl.sh 2>/dev/null | head -1)
if [ -n "$run" ]; then job ./rows-strata.sh q36mtp-udq4kxl "$run" strata-default strata-nomtp; else echo "no Strata run script yet: skipped"; fi
job ./rows-q36.sh sglang-nvfp4-default sglang-nvfp4-rec sglang-nvfp4-mtp sglang-fp8-default sglang-fp8-mtp tf-nvfp4-default tf-nvfp4-nomtp
[ -f /models/Qwen3.6-35B-A3B-MLX-4bit-MTP/.fetch-verified ] && job ./rows-q36.sh tf-mlx-default tf-mlx-nomtp
job ./rows-atlas.sh atlas-fp8-default atlas-fp8-rec atlas-fp8-nomtp
echo "QUEUE_Q36_DONE"
