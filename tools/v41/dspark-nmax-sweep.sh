#!/usr/bin/env bash
# WKS-36 — does a k-token verification pass cost the same as a one-token pass?
#
# It should. That is the whole reason speculative decoding wins on a bandwidth-bound decode:
# k tokens read the same expert weights once. Our numbers say it does not — a ~4-token pass
# costs 1.69x a one-token pass (bloomery docs/roofline.md), which is the same fact as our own
# measurement that ik's MoE decode is slower at batch 2 than batch 1.
#
# The 1.69x has two possible owners and this sweep separates them:
#   * the verification pass re-reading experts per token  -> cost grows with k
#   * the draft model's own forward pass                  -> cost flat in k (DSpark emits the
#     whole block in one pass, unlike EAGLE; host-surplus survey, llama.cpp speculative docs)
#
# Arms: DRAFT=0, then n_max 1, 2, 3. Same prompts, same order, temperature 0.
# The runner owns the quiet-machine protocol (docs/quiet-machine.md) — the caller changes
# arguments, never the rules.
set -euo pipefail
HERE=$(cd "$(dirname "$0")/../.." && pwd)
LEASE="$HERE/tools/quiet/lease.sh"
SERVE="$HERE/configs/v41-serve.sh"
OUT=${OUT:-$HOME/wks36}
PORT=${PORT:-8001}
ARMS=${ARMS:-"draft0 1 2 3"}
NPROMPT=${NPROMPT:-8}
mkdir -p "$OUT"

# The lease must name a pid that outlives acquire. This script is that pid.
export QUIET_LEASE_PID=$$
cleanup() {
  [ -n "${SRV:-}" ] && kill "$SRV" 2>/dev/null || true
  bash "$LEASE" release || true
}
trap cleanup EXIT

bash "$LEASE" wait --timeout "${WAIT:-7200}"
bash "$LEASE" acquire "WKS-36 dspark n_max sweep"

# Eight fixed prompts, greedy. Fixed so every arm answers the same questions; short so the
# decode dominates and prefill does not.
PROMPTS=(
 "Explain in two sentences why a mixture-of-experts model reads fewer bytes per token."
 "What is the difference between memory bandwidth and memory latency?"
 "Write a Rust function that returns the maximum of a slice of f32."
 "Summarise what a page cache does, in three sentences."
 "Name three reasons a GPU kernel can be memory bound."
 "Explain what speculative decoding is, briefly."
 "What does the acronym NUMA stand for and why does it matter?"
 "Describe the difference between a dense and a sparse matrix multiply."
)

ask() {  # $1 = arm label, $2 = prompt index
  local arm=$1 i=$2
  python3 - "$PORT" "${PROMPTS[$i]}" <<'PY'
import json,sys,urllib.request
port,q = sys.argv[1], sys.argv[2]
body = json.dumps({"model":"DeepSeek-V4.1-Flash",
                   "messages":[{"role":"user","content":q}],
                   "max_tokens":200,"temperature":0,"top_k":1,
                   "cache_prompt":False}).encode()
req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
                             body, {"Content-Type":"application/json"})
r = json.load(urllib.request.urlopen(req, timeout=900))
t, u = r.get("timings",{}), r["usage"]
print(json.dumps({
  "decode_tok_s": t.get("predicted_per_second"),
  "predicted_ms": t.get("predicted_ms"),
  "predicted_n":  t.get("predicted_n"),
  "prompt_ms":    t.get("prompt_ms"),
  "prompt_n":     u.get("prompt_tokens"),
  "draft_n":      t.get("draft_n"),
  "draft_accepted": t.get("draft_n_accepted"),
}))
PY
}

for arm in $ARMS; do
  log="$OUT/arm-$arm.jsonl"
  : > "$log"
  if [ "$arm" = "draft0" ]; then env_args=(DRAFT=0); else env_args=(DRAFT=1 "NMAX=$arm"); fi
  echo "=== arm $arm ===" >&2
  echo "{\"witness_start\":$(bash "$LEASE" witness)}" >> "$log"
  # The server holds the cards; start it under our lease, stop it before the next arm.
  env "${env_args[@]}" PORT="$PORT" bash "$SERVE" > "$OUT/serve-$arm.log" 2>&1 &
  SRV=$!
  # Wait for the port, not for a fixed sleep: the load is ~3m40s and varies with page cache.
  for _ in $(seq 1 90); do
    curl -sf -m 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
    kill -0 "$SRV" 2>/dev/null || { echo "server for arm $arm died; see $OUT/serve-$arm.log" >&2; exit 1; }
    sleep 10
  done
  curl -sf -m 2 "http://127.0.0.1:$PORT/health" >/dev/null || { echo "arm $arm never became healthy" >&2; exit 1; }
  # One warm pass that is not recorded: the first prompt after load pays the engram NVMe read
  # (rig-log WKS-20), and mixing a cold row into a decode comparison is how an arm lies.
  ask "$arm" 0 > /dev/null
  for i in $(seq 0 $((NPROMPT-1))); do
    printf '%s\n' "$(ask "$arm" "$i")" >> "$log"
  done
  echo "{\"witness_end\":$(bash "$LEASE" witness)}" >> "$log"
  kill "$SRV" 2>/dev/null || true
  wait "$SRV" 2>/dev/null || true
  SRV=
  sleep 5
done

echo "=== summary ===" 
python3 - "$OUT" $ARMS <<'PY'
import json,sys,glob,os,statistics
out=sys.argv[1]; arms=sys.argv[2:]
print(f"{'arm':>7} {'tok/s med':>10} {'ms/token':>9} {'draft_n':>8} {'acc':>7} "
      f"{'tok/pass':>9} {'ms/pass':>8}")
base=None
rows=[]
for a in arms:
    rs=[json.loads(l) for l in open(f"{out}/arm-{a}.jsonl") if '"decode_tok_s"' in l]
    if not rs: continue
    tps=statistics.median(r["decode_tok_s"] for r in rs)
    mspt=1000.0/tps
    dn=sum(r["draft_n"] or 0 for r in rs); da=sum(r["draft_accepted"] or 0 for r in rs)
    npred=sum(r["predicted_n"] or 0 for r in rs)
    if dn:
        # one pass emits: the always-correct token + the accepted draft tokens
        passes=npred-da
        tok_per_pass=npred/passes if passes else float('nan')
    else:
        tok_per_pass=1.0
    ms_per_pass=mspt*tok_per_pass
    if base is None: base=ms_per_pass
    rows.append((a,tps,mspt,dn,(da/dn if dn else 0),tok_per_pass,ms_per_pass))
    print(f"{a:>7} {tps:10.2f} {mspt:9.2f} {dn:8d} {(da/dn if dn else 0):7.3f} "
          f"{tok_per_pass:9.3f} {ms_per_pass:8.2f}")
print()
print("pass cost relative to the no-draft (1 token) pass:")
for a,tps,mspt,dn,acc,tpp,mpp in rows:
    print(f"  {a:>7}: {mpp/base:5.3f}x  at {tpp:.3f} tokens/pass")
print()
print("Reading: if pass cost is FLAT in k, the verification already amortises and the 1.69x")
print("belongs to the draft's own forward pass. If it GROWS with k, experts are being read")
print("per token and 22.8 -> 38.6 tok/s is real.")
PY
