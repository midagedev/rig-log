#!/bin/bash
# toktape's own default run as a take.sh PROBE, to set our Spark beside a contributor's published GB10 tape:
# `toktape record` with nothing but --url (prompts@v2, chat, temperature 0, thinking off, 20 s of wall clock, the
# server's own timings), three runs back to back on the one server, hostname left out of the tape.
#   tape-probe.sh <url> <out dir>      writes <out>/tapes/*.toktape and one summary line per run in <out>/tape-probe.jsonl
set -u
URL=${1:?url}; OUT=${2:?out}; T=/opt/engines/toktape-v0.8.0/toktape
mkdir -p "$OUT/tapes"
for r in 1 2 3; do
  "$T" record --url "$URL" --wait 0 --host-label "" --out "$OUT/tapes" --tag "tape-probe-r$r" || exit 1
done
for f in "$OUT"/tapes/*.toktape; do
  python3 -c 'import gzip,json,sys
s=json.loads(gzip.open(sys.argv[1]).read().split(b"\n")[0])["summary"]; t=s["timings"]
print(json.dumps({"tape":sys.argv[1].rsplit("/",1)[-1],"prompt_set":s.get("prompt_set"),"prompt_n":t["prompt_n"],
 "prefill":round(t["prompt_per_second"],1),"predicted_n":t["predicted_n"],"decode":round(t["predicted_per_second"],2),
 "itl_p50_ms":t.get("itl_p50_ms"),"slots":s["server"].get("n_slots"),"ctx":s["server"].get("ctx_size")}))' "$f"
done | tee "$OUT/tape-probe.jsonl"
