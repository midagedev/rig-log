#!/bin/bash
# A take.sh PROBE: one greedy decode request under Nsight Systems, for a kernel breakdown per decode token. The server
# was started by take.sh as SERVE="nsys launch --session-new=$NSYS_SESSION --trace=cuda --cuda-graph-trace=node <server>",
# so the trace holds only the window between `nsys start` and `nsys stop`: one warm-up outside it, then the request.
# The request is the decode-prose prompt of make-prompts.py (chat route, no-think, temperature 0, N tokens), the same on
# every engine. Writes <out>/decode.nsys-rep, kern.csv (cuda_gpu_kern_sum) and req.json (the response's usage/timings).
# usage: NSYS_SESSION=<name> [N=128] nsys-probe.sh <url> <out dir>
set -u
URL=$1; OUT=$2; S=${NSYS_SESSION:?}; N=${N:-128}
P=$(head -1 /root/health/prompts/decode-prose.jsonl | jq -c .prompt)
req(){ curl -sf "$URL/v1/chat/completions" -H 'Content-Type: application/json' -d "{\"messages\":[{\"role\":\"user\",\"content\":$P}],\"max_tokens\":$1,\"temperature\":0,\"stream\":false,\"chat_template_kwargs\":{\"enable_thinking\":false},\"ignore_eos\":true}"; }
req 32 > /dev/null || { echo "warm-up failed"; exit 1; }
nsys start --session="$S" -o "$OUT/decode" --force-overwrite=true || exit 1
t0=$(date +%s.%N); req "$N" > "$OUT/req.json"; rc=$?; t1=$(date +%s.%N)
nsys stop --session="$S" || exit 1
[ $rc = 0 ] || { echo "request rc $rc"; exit 1; }
nsys stats -q -r cuda_gpu_kern_sum -f csv -o "$OUT/kern" "$OUT/decode.nsys-rep" > /dev/null 2>&1
mv "$OUT"/kern_cuda_gpu_kern_sum.csv "$OUT/kern.csv" 2>/dev/null
echo "{\"wall_s\":$(echo "$t1 - $t0" | bc),\"usage\":$(jq -c .usage "$OUT/req.json"),\"timings\":$(jq -c '.timings // null' "$OUT/req.json")}"
