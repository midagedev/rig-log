#!/usr/bin/env python3
"""Stream a completion from the local server and report the measured decode rate.

Tokens are printed as they arrive, so the terminal shows the real pace rather
than a progress bar. The rate at the end comes from the server's own timings
block; the client-side wall clock is printed next to it as a cross-check.
"""
import json, sys, time, urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "") or "https://ws.mogera-goblin.ts.net:8443"
PROMPT = sys.argv[2] if len(sys.argv) > 2 else (
    "Write a complete, production-quality Rust implementation of a thread-safe "
    "LRU cache: the struct, the public API, the eviction logic, and unit tests. "
    "Then explain the locking strategy and where it would become a bottleneck."
)
MAXTOK = int(sys.argv[3]) if len(sys.argv) > 3 else 1600

B, DIM, RED, OFF = "\033[1m", "\033[2m", "\033[1;31m", "\033[0m"
print(f"{B}DeepSeek-V4-Flash-0731{OFF}  284 B params · 155 GB GGUF · 43 layers × 256 experts, 6 active")
print(f"{DIM}experts  layers 0-6 → A6000 48G · layers 11-14 → 3090 24G · other 32 layers → 256 GB DDR4{OFF}")
print(f"{DIM}engine   ik_llama.cpp + DSpark draft, depth 2 · one stream over Tailscale{OFF}\n")

req = urllib.request.Request(
    f"{BASE}/v1/chat/completions",
    data=json.dumps({
        "model": "DeepSeek-V4-Flash-0731",
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": MAXTOK, "stream": True,
    }).encode(),
    headers={"Content-Type": "application/json"},
)

n, t0, timings = 0, None, {}
with urllib.request.urlopen(req, timeout=900) as resp:
    for raw in resp:
        if not raw.startswith(b"data: "):
            continue
        body = raw[6:].strip()
        if body == b"[DONE]":
            break
        chunk = json.loads(body)
        timings = chunk.get("timings") or timings
        for choice in chunk.get("choices", []):
            piece = (choice.get("delta") or {}).get("content") or ""
            if piece:
                if t0 is None:
                    t0 = time.time()
                n += 1
                sys.stdout.write(piece)
                sys.stdout.flush()

wall = time.time() - (t0 or time.time())
server = timings.get("predicted_per_second") or 0
print(f"\n\n{B}──{OFF}")
print(f"  decode    {RED}{server:5.1f} tok/s{OFF}   server timings"
      f"{DIM}   ({wall:.1f}s wall, {n} chunks){OFF}")
drafted, accepted = timings.get("draft_n") or 0, timings.get("draft_n_accepted") or 0
if drafted:
    print(f"  drafted   {100*accepted/drafted:5.0f}% accepted   {DIM}{accepted} of {drafted} tokens taken from the draft model{OFF}")
