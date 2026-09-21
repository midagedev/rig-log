#!/usr/bin/env bash
# quant-kt.sh — 같은 원본·같은 imatrix에서 대조군(Q3_K_M)과 트렐리스 혼합(Q3_K 자리 → IQ3_KT)을 만든다. 박스에서 실행.
#
#   SRC=/models/v2lite-src bash quant-kt.sh [--dry-run]
#
# 막는 실패: 기존 Q3_K_M 파일(정적 양자화, imatrix 없음)과 imatrix를 쓴 IQ3_KT를 비교해 "트렐리스가 낫다"고 읽는 것.
# 두 파일의 차이는 Q3_K였던 텐서의 타입 하나여야 한다. --custom-q의 정규식은 라우터(ffn_gate_inp, F32)에
# 걸리지 않게 이름을 끝까지 쓴다. 양자화는 CPU를 다 쓰므로 CPU 측정 임대를 잡고 돈다.
set -euo pipefail
SRC=${SRC:-/models/v2lite-src}
IK=${IK:-/home/user/ik_llama.cpp}
Q="$IK/build/bin/llama-quantize"
F16="$SRC/DeepSeek-V2-Lite-Chat-f16.gguf"
IMAT="$SRC/imatrix.dat"
DRY=${1:-}
[ -f "$F16" ] && [ -f "$IMAT" ] || { echo "missing $F16 or $IMAT" >&2; exit 2; }
# ik의 Q3_K_M 레시피는 attn_kv_a_mqa·attn_kv_b를 q8_0로 둔다(--dry-run으로 확인, 2026-09-21) — 그 둘은 대조군과
# 같게 두려고 매핑에서 뺐다. token_embd는 imatrix 항목이 없고 디코드에서 gemv가 아니라 행 조회라 역시 뺐다.
# 남는 133개가 대조군에서 q3_K인 텐서 전부다.
KT='blk\.[0-9]+\.attn_q\.weight=iq3_kt,blk\.[0-9]+\.ffn_gate\.weight=iq3_kt,blk\.[0-9]+\.ffn_up\.weight=iq3_kt,blk\.[0-9]+\.ffn_(gate|up)_(exps|shexp)\.weight=iq3_kt'
exec 9>/root/bloomery-cpu.lock
flock -w 3600 9 || { echo "[lease] timed out" >&2; exit 75; }
run() { # <out> <extra args...>
  local out=$1; shift
  echo "=== $out"
  # 로더 눈에 보이는 반쪽 .gguf를 막는다(fetch-gguf.sh와 같은 계약): .part에 쓰고 rc 0일 때만 이름을 준다.
  "$Q" --imatrix "$IMAT" "$@" $DRY "$F16" "$out.part" Q3_K_M 32 || { echo "quantize failed: $out" >&2; rm -f "$out.part"; exit 1; }
  [ -n "$DRY" ] || mv "$out.part" "$out"
}
run "$SRC/v2lite-q3km-imat.gguf"
run "$SRC/v2lite-iq3kt-mix.gguf" --custom-q "$KT"
ls -l "$SRC"/*.gguf
