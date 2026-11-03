#!/usr/bin/env python3
"""The bloomery README's Spark method as a take.sh PROBE: token ids to /completion, streaming, cache_prompt false,
temperature 0, top_k 1, 128 tokens, two warm-up requests first, the server's own timings. take.sh starts a fresh server
for every call, so three calls are the README's three rounds.

    ids-probe.py <url> <out dir> [prompts jsonl=/root/health/prompts/pp4096.jsonl]

The ids are the server's own /tokenize of each passage in the prompts file, cut to 512 and 4,096 (the README's sizes),
so the corpus is ours and only the method is the README's. Writes <out>/ids-probe.jsonl, one line per request.
"""
import json, sys, time, urllib.request

url, out = sys.argv[1], sys.argv[2]
src = sys.argv[3] if len(sys.argv) > 3 else "/root/health/prompts/pp4096.jsonl"

def post(path, body, stream=False):
    req = urllib.request.Request(url + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=600)

def complete(ids, n=128):
    t0 = time.time(); first = None; last = None; toks = 0
    with post("/completion", {"prompt": ids, "stream": True, "cache_prompt": False, "temperature": 0, "top_k": 1,
                              "n_predict": n}) as r:
        for line in r:
            line = line.strip()
            if not line.startswith(b"data:"): continue
            d = json.loads(line[5:])
            if d.get("content") and first is None: first = time.time()
            toks += 1 if d.get("content") is not None and not d.get("stop") else 0
            last = d
    t = (last or {}).get("timings") or {}
    return {"prompt_n": t.get("prompt_n"), "prompt_per_second": t.get("prompt_per_second"),
            "predicted_n": t.get("predicted_n"), "predicted_per_second": t.get("predicted_per_second"),
            "draft_n": t.get("draft_n"), "draft_n_accepted": t.get("draft_n_accepted"),
            "first_token_ms": round((first - t0) * 1000, 1) if first else None}

texts = [json.loads(l)["prompt"] for l in open(src) if l.strip()]
ids = [post("/tokenize", {"content": x}).read() for x in texts]
ids = [json.loads(b)["tokens"] for b in ids]
assert all(len(x) >= 4096 for x in ids), [len(x) for x in ids]
for i in range(2): complete(ids[0][:512], 32)              # the README's two warm-ups
with open(f"{out}/ids-probe.jsonl", "w") as f:
    for size in (512, 4096):
        for k, x in enumerate(ids):
            r = complete(x[:size]); r.update(size=size, passage=k)
            f.write(json.dumps(r) + "\n"); f.flush()
            print(json.dumps(r))
