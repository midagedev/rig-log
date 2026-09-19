#!/usr/bin/env bash
# One measured decode rate from the server's own timings. No wall-clock guessing.
# usage: tps.sh [base-url] [prompt]
#
# 2026-09-19: the default prompt's own description of speculative decoding was wrong and is
# corrected below. It used to say the batched verification pass is "nearly free because
# reading a layer of experts out of DRAM costs the same for two tokens as for one" -- WKS-36
# measured that it is not (log/2026-09-19-verification-does-not-amortise.md): the dense 65 %
# amortizes, the routed 35 % does not, because each token routes to its own experts. The
# sentence is the premise the model is asked to review, so a false one buys a worse answer.
# Rows measured before this date used the old wording; the decode rate is not sensitive to
# it (same length class, 400-token cap), but the prompt is not byte-identical across that line.
set -euo pipefail
URL=${1:-${RIG_URL:-http://127.0.0.1:8000}}
Q=${2:-"Review this plan and reply in two short paragraphs. We serve a 284B-parameter mixture-of-experts model on one workstation: 43 layers, 256 routed experts per layer, six of them active per token, 155 GB of four-bit weights. Eleven layers of experts are pinned to GPU memory across a 48 GB card and a 24 GB card; the other 32 layers stay in 256 GB of eight-channel DDR4 and are computed by 32 CPU cores. A 10.9 GB draft model proposes two tokens ahead and the large model verifies both in a single batched pass. That pass is cheaper per token but not free: the dense two thirds of the bytes are read once for the whole batch, while the routed experts are read again for every token, because each token selects its own six. Tell us which part of this arrangement is most likely to become the bottleneck as the context grows, and what to measure first."}
printf '\033[1mDeepSeek-V4-Flash-0731\033[0m  284 B params · 155 GB GGUF · 43 layers × 256 experts\n'
printf 'experts: layers 0-6 → A6000 48G   layers 11-14 → 3090 24G   other 32 layers → 256 GB DDR4\n\n'
curl -s -m 600 "$URL/v1/chat/completions" -H 'Content-Type: application/json' \
  -d "$(python3 -c 'import json,sys;print(json.dumps({"model":"DeepSeek-V4-Flash-0731","messages":[{"role":"user","content":sys.argv[1]}],"max_tokens":400}))' "$Q")" \
| python3 -c '
import json,sys
r=json.load(sys.stdin); t=r.get("timings",{}); u=r["usage"]
d=t.get("predicted_per_second",0); p=t.get("prompt_per_second",0)
print("  decode   \033[1;31m%5.1f tok/s\033[0m   (%d tokens generated)" % (d,u["completion_tokens"]))
print("  prompt   %5d tokens in %.1fs" % (u["prompt_tokens"], t.get("prompt_ms",0)/1000))
dr=t.get("draft_n") or 0; da=t.get("draft_n_accepted") or 0
if dr: print("  draft    %5.0f%% accepted   (DSpark, depth 2)" % (100*da/dr))
'
