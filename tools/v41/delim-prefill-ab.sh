#!/usr/bin/env bash
# 구분자가 콜드 프리필을 느리게 하는가 — ggml-org/llama.cpp#29008 에 달린 반론을 잰다.
# 설계와 팔의 정의는 delim-prefill-ab.py 의 독스트링이 원본이다. 이 파일은 조용한
# 기계 임대를 잡고, 서버를 한 번만 띄우고, 증인을 남긴다.
#
# 모델은 DeepSeek-V4-Flash-0731 이다 — #25320 의 보고자가 쓴 그 모델이고,
# V4.1 445 GB 는 로드 3분 40초에 프리필 46 tok/s 라 같은 표를 만드는 데 한 시간이 든다.
# 엔진은 mainline 포크(vcruz305)다. ik 가 아니다 — 이 반론이 달린 PR 이 mainline 것이다.
set -euo pipefail

IKHOME=${IKHOME:-/home/user}
B=${B:-$IKHOME/llama.cpp-v41-merged/build/bin/llama-server}
M=${M:-$IKHOME/models/DeepSeek-V4-Flash-0731-GGUF/UD-Q4_K_XL/DeepSeek-V4-Flash-0731-UD-Q4_K_XL-00001-of-00005.gguf}
PORT=${PORT:-8011}
UB=${UB:-2048}
TURNS=${TURNS:-120}
MINSTEP=${MINSTEP:-}          # 비우면 서버 기본값 8192
LV=${LV:-2}                   # 청크 경계를 보려면 3 이상이 필요하다
OUT=${OUT:-$IKHOME/delim-ab}
LEASE=${LEASE:-$IKHOME/lease.sh}

mkdir -p "$OUT"
STAMP=$(date +%Y%m%d-%H%M%S)
LOG="$OUT/server-$STAMP-ms${MINSTEP:-8192}.log"
ROWS="$OUT/rows-$STAMP-ms${MINSTEP:-8192}.json"

BUILD=$(git -C "$IKHOME/llama.cpp-v41-merged" rev-parse --short HEAD 2>/dev/null || echo unknown)
echo "build=$BUILD  ub=$UB  turns=$TURNS  min_step=${MINSTEP:-default(8192)}"

# 임대. 이 스크립트가 살아 있는 동안만 유효해야 하므로 자기 pid 를 적는다.
export QUIET_LEASE_PID=$$
"$LEASE" wait --timeout 600
"$LEASE" acquire "delim-prefill-ab $STAMP"
cleanup() {
  [ -n "${SRV:-}" ] && kill "$SRV" 2>/dev/null || true
  [ -n "${SRV:-}" ] && { for _ in $(seq 60); do kill -0 "$SRV" 2>/dev/null || break; sleep 1; done; }
  "$LEASE" release || true
}
trap cleanup EXIT

. "$IKHOME/gpu-order.env"

# llm-serve.sh 의 배치를 그대로 옮긴다. mainline 은 -ot 를 반복하면 마지막 것만
# 남기므로 쉼표 하나로 붙이고, 받아 가는 exps=CPU 를 맨 뒤에 둔다.
args=( -m "$M" --alias v4-flash-0731
       -c 65536 -np 1 -ngl 99 -ts 2,1 -t 32 -b "$UB" -ub "$UB"
       -ot "blk\.[0-6]\.ffn_.*_exps=CUDA0,blk\.1[1-4]\.ffn_.*_exps=CUDA1,exps=CPU"
       --jinja -lv "$LV" --host 127.0.0.1 --port "$PORT" )
[ -n "$MINSTEP" ] && args+=( --checkpoint-min-step "$MINSTEP" )

"$B" "${args[@]}" > "$LOG" 2>&1 &
SRV=$!
echo "server pid $SRV  log $LOG"

# /health 가 200 을 줄 때까지. pgrep 패턴 대기 루프는 자기 자신에 걸리므로 쓰지 않는다.
for i in $(seq 1 900); do
  kill -0 "$SRV" 2>/dev/null || { echo "server died during load — see $LOG" >&2; tail -30 "$LOG" >&2; exit 1; }
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/health" || true)
  [ "$code" = "200" ] && { echo "ready after ${i}s"; break; }
  sleep 1
done

python3 "$IKHOME/delim-prefill-ab.py" \
  --port "$PORT" --lease "$LEASE" --log "$LOG" --turns "$TURNS" --out "$ROWS"

echo
echo "rows: $ROWS"
python3 - "$ROWS" "$BUILD" "${MINSTEP:-8192}" "$UB" <<'PY'
import json, sys
rows = json.load(open(sys.argv[1]))
print(f"\nbuild={sys.argv[2]}  min_step={sys.argv[3]}  ub={sys.argv[4]}\n")
print(f"{'shape':8} {'arm':4} {'prompt_n':>9} {'prompt_ms':>11} {'tok/s':>9} {'chunks':>7} {'min':>7} {'median':>7}")
for r in rows:
    print(f"{r['shape']:8} {r['arm']:4} {r['prompt_n']:>9} {r['prompt_ms']:>11.1f} "
          f"{r['prompt_per_second']:>9.2f} {r['n_chunks']:>7} {str(r['min_chunk']):>7} {str(r['median_chunk']):>7}")
by = {}
for r in rows: by.setdefault(r['shape'], {})[r['arm']] = r
print()
for s, d in by.items():
    if 'on' in d and 'off' in d:
        same = d['on']['prompt_n'] == d['off']['prompt_n']
        ratio = d['on']['prompt_ms'] / d['off']['prompt_ms'] if d['off']['prompt_ms'] else 0
        print(f"{s:8} same prompt_n: {same} ({d['on']['prompt_n']} vs {d['off']['prompt_n']})   "
              f"on/off prefill time = {ratio:.3f}x")
PY
