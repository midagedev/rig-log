#!/bin/bash
# A take.sh PROBE: one greedy request under Nsight Systems, for a kernel breakdown. The server was started by take.sh
# as SERVE="nsys launch --session-new=$NSYS_SESSION --trace=cuda --cuda-graph-trace=node <server>", so the trace holds
# only the window between `nsys start` and `nsys stop`: one warm-up outside it (a different text, so the traced
# request reads nothing from a prompt cache), then the request. KIND=decode (default) sends the decode-prose prompt of
# make-prompts.py with N tokens; KIND=prefill the first pp4096 prompt with max_tokens 1, for the prompt pass. Chat
# route, no-think, temperature 0, the same on every engine.
# Writes <out>/<kind>.nsys-rep, kern.csv (cuda_gpu_kern_sum) and req.json (the response's usage/timings).
# usage: NSYS_SESSION=<name> [KIND=decode|prefill] [N=128] nsys-probe.sh <url> <out dir>
set -u
URL=$1; OUT=$2; S=${NSYS_SESSION:?}; N=${N:-128}; KIND=${KIND:-decode}
case $KIND in decode) P=$(head -1 /root/health/prompts/decode-prose.jsonl | jq -c .prompt);;
  prefill) P=$(head -1 /root/health/prompts/pp4096.jsonl | jq -c .prompt); N=1;; *) echo "KIND?"; exit 1;; esac
req(){ curl -sf "$URL/v1/chat/completions" -H 'Content-Type: application/json' -d "{\"messages\":[{\"role\":\"user\",\"content\":$P}],\"max_tokens\":$1,\"temperature\":0,\"stream\":false,\"chat_template_kwargs\":{\"enable_thinking\":false},\"ignore_eos\":true}"; }
W=$(head -1 /root/health/prompts/decode-code.jsonl | jq -c .prompt)
curl -sf "$URL/v1/chat/completions" -H 'Content-Type: application/json' -d "{\"messages\":[{\"role\":\"user\",\"content\":$W}],\"max_tokens\":32,\"temperature\":0,\"chat_template_kwargs\":{\"enable_thinking\":false}}" > /dev/null || { echo "warm-up failed"; exit 1; }
nsys start --session="$S" -o "$OUT/$KIND" --force-overwrite=true || exit 1
t0=$(date +%s.%N); req "$N" > "$OUT/req.json"; rc=$?; t1=$(date +%s.%N)
nsys stop --session="$S" || exit 1
[ $rc = 0 ] || { echo "request rc $rc"; exit 1; }
nsys stats -q -r cuda_gpu_kern_sum -f csv -o "$OUT/kern" "$OUT/$KIND.nsys-rep" > /dev/null 2>&1
mv "$OUT"/kern_cuda_gpu_kern_sum.csv "$OUT/kern.csv" 2>/dev/null
echo "{\"wall_s\":$(echo "$t1 - $t0" | bc),\"usage\":$(jq -c .usage "$OUT/req.json"),\"timings\":$(jq -c '.timings // null' "$OUT/req.json")}"
