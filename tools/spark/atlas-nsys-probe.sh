#!/bin/bash
# nsys-probe.sh for an engine in a container (Atlas), 2026-11-04: the server runs under `nsys launch` inside the
# container (the host's Nsight Systems mounted at /nsys, the take directory at /out), and the capture is started and
# stopped with `docker exec`. The same request as nsys-probe.sh: a warm-up, then one prose decode of N tokens (or one
# 4,200-id prompt for KIND=prefill), cuda_gpu_kern_sum to kern.csv. take.sh runs it as PROBE with SERVE from
# rows-atlas.sh's command plus `-v <nsys>:/nsys -v <take dir>:/out` and `/nsys/.../nsys launch ... --session-new=atlas`.
# usage (as take.sh's PROBE): atlas-nsys-probe.sh <url> <outdir>   env CONTAINER, KIND (decode), N (128)
set -u
URL=$1; OUT=$2; N=${N:-128}; KIND=${KIND:-decode}; X="docker exec $CONTAINER /nsys/target-linux-sbsa-armv8/nsys"
case $KIND in decode) P=$(head -1 /root/health/prompts/decode-prose.jsonl | jq -c .prompt);;
  prefill) P=$(head -1 /root/health/prompts/pp4096.jsonl | jq -c .prompt); N=1;; *) echo "KIND?"; exit 1;; esac
req(){ curl -sf "$URL/v1/chat/completions" -H 'Content-Type: application/json' -d "{\"messages\":[{\"role\":\"user\",\"content\":$P}],\"max_tokens\":$1,\"temperature\":0,\"stream\":false,\"chat_template_kwargs\":{\"enable_thinking\":false},\"ignore_eos\":true}"; }
W=$(head -1 /root/health/prompts/decode-code.jsonl | jq -c .prompt)
curl -sf "$URL/v1/chat/completions" -H 'Content-Type: application/json' -d "{\"messages\":[{\"role\":\"user\",\"content\":$W}],\"max_tokens\":32,\"temperature\":0,\"chat_template_kwargs\":{\"enable_thinking\":false}}" > /dev/null || { echo "warm-up failed"; exit 1; }
$X start --session=atlas -o /out/$KIND --force-overwrite=true || exit 1
t0=$(date +%s.%N); req "$N" > "$OUT/req.json"; rc=$?; t1=$(date +%s.%N)
$X stop --session=atlas || exit 1
[ $rc = 0 ] || { echo "request rc $rc"; exit 1; }
for i in $(seq 60); do [ -s "$OUT/$KIND.nsys-rep" ] && break; sleep 2; done
nsys stats -q -r cuda_gpu_kern_sum -f csv -o "$OUT/kern" "$OUT/$KIND.nsys-rep" > /dev/null 2>&1
mv "$OUT"/kern_cuda_gpu_kern_sum.csv "$OUT/kern.csv" 2>/dev/null
echo "{\"wall_s\":$(echo "$t1 - $t0" | bc),\"usage\":$(jq -c .usage "$OUT/req.json")}"
