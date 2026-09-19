#!/usr/bin/env bash
# ik PR #2455 의 V4.1 포트에서, 갈라지는 프리픽스가 앞 요청의 답을 내는지 본다.
# 설계는 stale-compressed-state.py 독스트링이 원본. 엔진은 ik(= PR 헤드 c10fbbcc 빌드),
# 배치는 PR 본문의 것(-c 16384 -ngl 99 -t 32 -b 2048 -ub 512, expert 여섯 층만 카드).
# 이 박스에서는 CPU 쪽 -ot 에 GGML_CUDA_NO_PINNED_WEIGHTS=1 이 필요하다(#2444).
set -euo pipefail
IKHOME=${IKHOME:-/home/user}
B=${B:-$IKHOME/ik_llama.cpp/build/bin/llama-server}
M=${M:-/models/DeepSeek-V4.1-Flash-Q3_K_M/DeepSeek-V4.1-Flash-Q3_K_M-00001-of-00009.gguf}
PORT=${PORT:-8021}
OUT=${OUT:-$IKHOME/stale-state}
LEASE=${LEASE:-$IKHOME/lease.sh}
mkdir -p "$OUT"
STAMP=$(date +%Y%m%d-%H%M%S)
LOG="$OUT/server-$STAMP.log"; ROWS="$OUT/rows-$STAMP.json"
echo "ik build: $(git -C "$IKHOME/ik_llama.cpp" rev-parse --short HEAD)"

export QUIET_LEASE_PID=$$
"$LEASE" wait --timeout 900
"$LEASE" acquire "stale-compressed-state $STAMP"
cleanup() {
  [ -n "${SRV:-}" ] && kill "$SRV" 2>/dev/null || true
  [ -n "${SRV:-}" ] && { for _ in $(seq 90); do kill -0 "$SRV" 2>/dev/null || break; sleep 1; done; }
  "$LEASE" release || true
}
trap cleanup EXIT
. "$IKHOME/gpu-order.env"

GGML_CUDA_NO_PINNED_WEIGHTS=1 "$B" -m "$M" --alias v41-ik \
  -c 16384 -np 1 -ngl 99 -t 32 -b 2048 -ub 512 -mla 3 \
  -ot "blk\.[0-3]\.ffn_.*_exps=CUDA0" \
  -ot "blk\.[4-5]\.ffn_.*_exps=CUDA1" \
  -ot "exps=CPU" \
  --jinja --reasoning-format none --verbosity 3 --host 127.0.0.1 --port "$PORT" > "$LOG" 2>&1 &
SRV=$!
echo "server pid $SRV  log $LOG"
for i in $(seq 1 1200); do
  kill -0 "$SRV" 2>/dev/null || { echo "server died during load:" >&2; tail -40 "$LOG" >&2; exit 1; }
  [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/health" || true)" = "200" ] \
    && { echo "ready after ${i}s"; break; }
  sleep 1
done

python3 "$IKHOME/stale-compressed-state.py" --port "$PORT" --out "$ROWS"

echo
echo "=== server log: cache / checkpoint decisions ==="
grep -E "diverges at|context checkpoint|restore|compressed-stream state|Cache: cache_size" "$LOG" | tail -30
echo
echo "rows: $ROWS   log: $LOG"
