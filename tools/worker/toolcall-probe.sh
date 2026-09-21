#!/bin/bash
# toolcall-probe.sh <port> <outdir> — three requests that decide whether a llama-server
# build can drive an agent: plain chat, a chat with a `tools` array that must be called,
# and the follow-up turn that returns the tool result.
#
# Written for round WORKER (2026-09-21). `pi` (and every other agent harness here) speaks
# /v1/chat/completions with native tool calling and has no /completions fallback, so a
# build that answers HTTP 500 — as the merged-mainline build did for Qwen3-Coder-Next on
# 2026-09-18, "the model produced output that does not match the expected peg-native
# format" (log/2026-09-18-c-a-local-model-translates-the-log.md) — is disqualified no
# matter how fast it decodes. This script is the gate, not a benchmark: it records HTTP
# status and the raw body, never a timing.
#
# Each request writes <outdir>/<n>-<name>.{json,http}; the summary goes to stdout.
set -u
PORT=${1:?usage: toolcall-probe.sh <port> <outdir>}
OUT=${2:?outdir}
mkdir -p "$OUT"
URL=http://127.0.0.1:$PORT/v1/chat/completions

post(){ # post <name> <json file>
  local n=$1 f=$2
  local code
  code=$(curl -s -m 600 -o "$OUT/$n.json" -w '%{http_code}' \
         -H 'Content-Type: application/json' --data-binary @"$f" "$URL")
  echo "$code" > "$OUT/$n.http"
  echo "== $n: HTTP $code"
  head -c 2000 "$OUT/$n.json"; echo
}

TOOLS='[{"type":"function","function":{"name":"read_file","description":"Read a file from disk and return its contents.","parameters":{"type":"object","properties":{"path":{"type":"string","description":"Absolute path of the file to read"}},"required":["path"]}}}]'

# (i) plain chat — no tools array at all. This is the request shape that 500'd on 09-18.
cat > "$OUT/req-1.json" <<EOF
{"model":"local","messages":[{"role":"user","content":"Reply with exactly the word: PONG"}],
 "max_tokens":64,"temperature":0,"stream":false}
EOF
post 1-plain "$OUT/req-1.json"

# (ii) a tools array plus a prompt that cannot be answered without calling it.
cat > "$OUT/req-2.json" <<EOF
{"model":"local","messages":[
  {"role":"system","content":"You are a file assistant. Use the tools provided."},
  {"role":"user","content":"What is in /tmp/worker-marker.txt? Use the read_file tool; do not guess."}],
 "tools":$TOOLS,"max_tokens":256,"temperature":0,"stream":false}
EOF
post 2-toolcall "$OUT/req-2.json"

# (iii) the follow-up turn: the assistant's tool_calls echoed back with a tool result.
# The id and arguments are lifted from the answer to (ii) so the turn is the real one the
# server just produced, not a hand-written approximation of it.
python3 - "$OUT" "$TOOLS" <<'PY'
import json, sys
out, tools = sys.argv[1], sys.argv[2]
try:
    a = json.load(open(f"{out}/2-toolcall.json"))
    msg = a["choices"][0]["message"]
    tc = msg.get("tool_calls") or []
except Exception as e:
    print(f"(iii) skipped: cannot read tool_calls from step (ii): {e}")
    sys.exit(3)
if not tc:
    print("(iii) skipped: step (ii) returned no tool_calls")
    sys.exit(3)
req = {"model": "local", "messages": [
    {"role": "system", "content": "You are a file assistant. Use the tools provided."},
    {"role": "user", "content": "What is in /tmp/worker-marker.txt? Use the read_file tool; do not guess."},
    {"role": "assistant", "content": msg.get("content") or "", "tool_calls": tc},
    {"role": "tool", "tool_call_id": tc[0].get("id", "call_0"),
     "name": tc[0]["function"]["name"], "content": "WORKER-MARKER-7391"}],
    "tools": json.loads(tools), "max_tokens": 256, "temperature": 0, "stream": False}
json.dump(req, open(f"{out}/req-3.json", "w"))
PY
if [ -f "$OUT/req-3.json" ]; then post 3-followup "$OUT/req-3.json"; else echo "== 3-followup: SKIPPED"; fi

echo "== verdict inputs"
for n in 1-plain 2-toolcall 3-followup; do
  [ -f "$OUT/$n.http" ] || continue
  printf '%s http=%s ' "$n" "$(cat "$OUT/$n.http")"
  python3 - "$OUT/$n.json" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("unparseable body"); raise SystemExit
if "error" in d:
    print("error:", json.dumps(d["error"])[:300]); raise SystemExit
m = d["choices"][0]["message"]
tc = m.get("tool_calls") or []
ok = all(isinstance(t.get("function", {}).get("arguments"), str) and
         json.loads(t["function"]["arguments"]) is not None for t in tc) if tc else None
print(f"content={(m.get('content') or '')[:80]!r} tool_calls={len(tc)}"
      + (f" name={tc[0]['function']['name']} args={tc[0]['function']['arguments'][:120]} args_json_ok={ok}" if tc else ""))
PY
done
