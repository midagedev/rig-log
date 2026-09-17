#!/usr/bin/env python3
"""Replay a captured chat-completion request against llama-server and print what the
prompt cache did: prompt_n (tokens actually prefilled), cache_n (tokens reused), prompt_ms.

    python3 tools/cache/replay-cache.py req.json                      # as captured
    python3 tools/cache/replay-cache.py req.json --user "new question" # swap the last user message
    python3 tools/cache/replay-cache.py req.json --sys-replace OLD NEW # edit the system prompt
    python3 tools/cache/replay-cache.py req.json --tool-desc NAME " (probe)"  # append to a tool description
    python3 tools/cache/replay-cache.py req.json --tokenize           # also print the rendered prompt length

Every replay is non-streaming, temperature 0, max_tokens 8, so the number that moves is the
prefill. Capture requests with tools/cache/logproxy.py in front of the server. Measured
2026-09-17 on DeepSeek-V4.1-Flash: any edit before the last user message re-prefilled all
13 167 tokens until the parser published message delimiters (log/2026-09-17-*)."""
import argparse, json, sys, time, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("req"); ap.add_argument("--url", default="http://127.0.0.1:8001")
ap.add_argument("--user"); ap.add_argument("--sys-replace", nargs=2, metavar=("OLD", "NEW"))
ap.add_argument("--tool-desc", nargs=2, metavar=("NAME", "SUFFIX")); ap.add_argument("--tokenize", action="store_true")
ap.add_argument("--tag", default="")
a = ap.parse_args()

body = json.load(open(a.req))
if a.user:
    idx = max(i for i, m in enumerate(body["messages"]) if m["role"] == "user"); body["messages"][idx]["content"] = a.user
if a.sys_replace:
    assert a.sys_replace[0] in body["messages"][0]["content"], "OLD not in system prompt"
    body["messages"][0]["content"] = body["messages"][0]["content"].replace(*a.sys_replace, 1)
if a.tool_desc:
    hit = [t for t in body.get("tools", []) if t["function"]["name"] == a.tool_desc[0]]
    assert hit, "no such tool"; hit[0]["function"]["description"] += a.tool_desc[1]
body.update(stream=False, max_tokens=8, temperature=0); body.pop("stream_options", None)

def post(path, payload):
    r = urllib.request.urlopen(urllib.request.Request(a.url + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}), timeout=3600)
    return json.load(r)

if a.tokenize:
    p = post("/apply-template", {k: v for k, v in body.items() if k not in ("stream", "max_tokens", "temperature")})["prompt"]
    print("rendered prompt:", len(p), "chars,", len(post("/tokenize", {"content": p})["tokens"]), "tokens")
t0 = time.time(); o = post("/v1/chat/completions", body); wall = time.time() - t0
t = o.get("timings", {})
print(a.tag or a.req, "wall %.1f s" % wall, "prompt_n", t.get("prompt_n"), "cache_n", t.get("cache_n"), "prompt_ms %.0f" % t.get("prompt_ms", 0))
