#!/bin/bash
# DSpark draft gate on ik_llama.cpp, quiet box, 8001 stopped first and restarted at the end.
#   A. ik, no draft            -> reference greedy text per prompt (from the same binary)
#   B. ik + V4.1 draft (tl37)  -> text must be token-identical to A (speculation is lossless), plus
#                                 draft_n / draft_n_accepted and tok/s
#   C. ik + original draft (target_layers [38,39,40], the off-by-one file) -> the FAIL-first arm:
#                                 acceptance should be visibly worse, text still identical
set -u
# exported once: an env prefix on the function call was seen missing from one of three
# otherwise identical launches (the pinned-host hint printed, the target lost its mmap)
export GGML_CUDA_NO_PINNED=1
source <(sed -n "/^M=/p; /^OT=/p; /^PROMPTS=/,/^)/p; /^liq()/p; /^busy_reason()/,/^}/p; /^wait_quiet()/,/^}/p" ~/engine-ab.sh)
IK=$HOME/ik_llama.cpp/build/bin/llama-server
D37=/models/DeepSeek-V4.1-Flash-DSpark/DeepSeek-V4.1-Flash-Fp8-128x742M-MXFP4_MOE.tl37.gguf
D38=/models/DeepSeek-V4.1-Flash-DSpark/DeepSeek-V4.1-Flash-Fp8-128x742M-MXFP4_MOE.gguf
NPRED=${NPRED:-200}
say() { echo "$(date +%T) $*"; }

for pid in $(pgrep -x llama-server); do say "stopping llama-server $pid"; kill "$pid"; while kill -0 "$pid" 2>/dev/null; do sleep 2; done; done

measure_arm() {  # $1 label $2 port
  local label=$1 port=$2 i=0 p
  for p in "${PROMPTS[@]}"; do
    i=$((i+1))
    python3 -c 'import json,sys; print(json.dumps({"prompt":"<｜User｜>"+sys.argv[1]+"<｜Assistant｜></think>","n_predict":int(sys.argv[2]),"temperature":0,"cache_prompt":False}))' "$p" "$NPRED" > /tmp/dspark-req.json
    curl -s "127.0.0.1:$port/completion" -d @/tmp/dspark-req.json > "/tmp/dspark-resp-$label-$i.json"
    python3 - "$label" "$i" <<'PY'
import json, sys
label, i = sys.argv[1], sys.argv[2]
r = json.load(open(f"/tmp/dspark-resp-{label}-{i}.json"))
t = r.get("timings", {})
extra = ""
if "draft_n" in t:
    dn, da = t.get("draft_n", 0), t.get("draft_n_accepted", 0)
    extra = " | draft %d accepted %d (%.0f%%)" % (dn, da, 100.0 * da / dn if dn else 0)
print("  %s #%s: prefill %d @ %.1f | decode %d @ %.2f tok/s%s" % (label, i, t.get("prompt_n", 0), t.get("prompt_per_second", 0), t.get("predicted_n", 0), t.get("predicted_per_second", 0), extra))
open(f"/tmp/dspark-text-{label}-{i}.txt", "w").write(r.get("content", ""))
PY
  done
  echo "  after: liq=$(liq)C load=$(cut -d' ' -f1 /proc/loadavg)"
}

run_arm() {  # $1 label $2 port $3.. command
  local label=$1 port=$2; shift 2
  wait_quiet
  if ss -ltn | grep -q ":$port "; then echo "ABORT: port $port has a listener"; return 1; fi
  if [ -n "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)" ]; then echo "ABORT: GPU held"; return 1; fi
  "$@" > "/tmp/dspark-srv-$label.log" 2>&1 & local SP=$! ready=""
  for i in $(seq 1 200); do
    kill -0 $SP 2>/dev/null || { echo "$label died"; grep -i "error\|fail\|assert" "/tmp/dspark-srv-$label.log" | tail -5; return 1; }
    if grep -q -E "HTTP server listening|listening on http" "/tmp/dspark-srv-$label.log"; then curl -sf "127.0.0.1:$port/health" >/dev/null && { ready=1; break; }; fi
    sleep 5
  done
  [ -n "$ready" ] || { echo "$label never ready"; kill $SP; return 1; }
  say "$label up pid $SP"
  grep -E "draft flavor|spec|dspark|dflash" "/tmp/dspark-srv-$label.log" | grep -v "^.*override" | head -6 | sed 's/^/  /'
  curl -s "127.0.0.1:$port/completion" -d '{"prompt":"hi","n_predict":4,"temperature":0}' >/dev/null
  echo "== $label"
  measure_arm "$label" "$port"
  kill $SP; while kill -0 $SP 2>/dev/null; do sleep 2; done; say "$label stopped"
}

ARMS=${ARMS:-"nodraft tl37 tl38"}
COMMON=(-m "$M" -c 16384 -ngl 99 -t 32 -b 2048 -ub 2048 -ot "$OT" --host 127.0.0.1 --port 8099)
case " $ARMS " in *" nodraft "*) run_arm nodraft 8099 $IK "${COMMON[@]}";; esac
case " $ARMS " in *" tl37 "*) run_arm tl37 8099 $IK "${COMMON[@]}" --model-draft "$D37" --spec-type "dspark:n_max=${NMAX:-5}";; esac
case " $ARMS " in *" tl38 "*) run_arm tl38 8099 $IK "${COMMON[@]}" --model-draft "$D38" --spec-type "dspark:n_max=${NMAX:-5}";; esac

echo "== text identity vs nodraft"
for arm in tl37 tl38; do for i in 1 2 3; do
  if cmp -s "/tmp/dspark-text-nodraft-$i.txt" "/tmp/dspark-text-$arm-$i.txt"; then echo "  $arm #$i identical"; else echo "  $arm #$i DIFFERS"; python3 -c "
a=open('/tmp/dspark-text-nodraft-$i.txt').read(); b=open('/tmp/dspark-text-$arm-$i.txt').read()
k=next((j for j in range(min(len(a),len(b))) if a[j]!=b[j]), min(len(a),len(b))); print('    first diff at char', k, repr(a[k:k+40]), 'vs', repr(b[k:k+40]))"; fi
done; done

nohup bash ~/rig-log-v41-serve.sh > /tmp/llm-serve.log 2>&1 < /dev/null &
for i in $(seq 1 120); do curl -sf 127.0.0.1:8001/health >/dev/null && { say "8001 back"; break; }; sleep 5; done
say DSPARK_DONE
