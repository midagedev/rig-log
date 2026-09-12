#!/usr/bin/env python3
# PopQA probe: greedy, no thinking, exact-match on any alias. usage: popqa.py <port> <out.json> <sample.json>
import json, sys, time, urllib.request, re
port, out, sample = sys.argv[1:4]
rows = json.load(open(sample))
def norm(s): return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()
res=[]; hit=0
for i,r in enumerate(rows,1):
    body={"model":"x","messages":[{"role":"system","content":"Answer with the fact only, in a few words."},{"role":"user","content":r["question"]}],
          "temperature":0,"max_tokens":32,"reasoning_effort":"none","chat_template_kwargs":{"reasoning_effort":"none"}}
    req=urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",data=json.dumps(body).encode(),headers={"Content-Type":"application/json"})
    ans=json.load(urllib.request.urlopen(req,timeout=600))["choices"][0]["message"]["content"].strip()
    ok=any(norm(a) and norm(a) in norm(ans) for a in r["answers"])
    hit+=ok
    res.append({"id":r["id"],"pop":r["pop"],"q":r["question"],"answers":r["answers"],"answer":ans,"ok":ok})
    if i%25==0: print(f"[{i}] acc so far {hit/i:.3f}",flush=True)
json.dump(res,open(out,"w"),indent=1,ensure_ascii=False)
print("ACC",hit,len(rows),round(hit/len(rows),4))
