#!/bin/bash
# 정본 서빙 스크립트 — systemd llm.service 가 이걸 실행한다.
# 구성: DeepSeek-V4-Flash-0731 (unsloth UD-Q4_K_XL 155GB)
#   expert 층 일부 = A6000(CUDA0) / 3090(CUDA1), 나머지 = CPU+RAM
#   DSpark 투기 디코딩(초안 모델 10.9GB, 깊이 3)
set -eu
export CUDA_DEVICE_ORDER=PCI_BUS_ID
M=$HOME/models/DeepSeek-V4-Flash-0731-GGUF/UD-Q4_K_XL/DeepSeek-V4-Flash-0731-UD-Q4_K_XL-00001-of-00005.gguf
D=$HOME/models/DeepSeek-V4-Flash-0731-dspark/dspark-DeepSeek-V4-Flash-0731-Q8_0.gguf
exec $HOME/ik_llama.cpp/build/bin/llama-server \
  -m "$M" --alias DeepSeek-V4-Flash-0731 \
  -c 32768 -ngl 99 -ts 2,1 -mla 3 -t 32 -b 2048 -ub 1024 \
  -ot "blk\.[0-6]\.ffn_.*_exps=CUDA0" \
  -ot "blk\.1[1-4]\.ffn_.*_exps=CUDA1" \
  -ot "exps=CPU" \
  -md "$D" -ngld 99 -cd 8192 --spec-type dspark:n_max=3 \
  --jinja --reasoning-format deepseek \
  --host 127.0.0.1 --port 8000
