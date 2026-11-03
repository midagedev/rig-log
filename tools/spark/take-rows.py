#!/usr/bin/env python3
"""One table row per take directory of tools/spark/take.sh, read from the tapes and nothing else.

    take-rows.py /root/takes/<tag> [...]

Columns: decode tok/s on the code and prose prompts (median over the three requests of each, the server's figure
where the engine reports one, else the client's; `c` marks a client-only figure), draft acceptance where the server
reports draft counts, and prefill tok/s at the pp512 / pp4096 prompts (server figure where reported, else prompt
tokens over TTFT; `c` marks the latter, which includes the request's overhead and the first decode step) with the
engine's own count of prompt tokens.

CLIENT=1 takes the client's figures for every row, so an engine that reports server timings can sit beside one that
does not on the same clock.
"""
import glob, gzip, json, statistics, sys, os
CLIENT = os.environ.get("CLIENT") == "1"

def take(d, k):
    for f in sorted(glob.glob(f"{d}/tapes/*.toktape")):
        t = json.load(gzip.open(f))
        rs = t.get("requests") or []
        if rs and (rs[0].get("prompt") or {}).get("name", "").startswith(k + "-"):
            return rs
    return []

def med(xs):
    xs = [x for x in xs if x]
    return statistics.median(xs) if xs else None

def dec(rs):
    srv = None if CLIENT else med([(r.get("timings") or {}).get("predicted_per_second") for r in rs if (r.get("timings") or {}).get("prompt_ms")])
    cli = med([(r.get("timings") or {}).get("client_predicted_per_second") for r in rs])
    n = [(r.get("timings") or {}).get("predicted_n") or (r.get("timings") or {}).get("tokens_observed") for r in rs]
    dn = sum((r.get("timings") or {}).get("draft_n") or 0 for r in rs)
    da = sum((r.get("timings") or {}).get("draft_n_accepted") or 0 for r in rs)
    v = f"{srv:.1f}" if srv else (f"{cli:.1f}c" if cli else "—")
    return v, (f"{da/dn:.2f}" if dn else "—"), "/".join(str(x) for x in n)

def pre(rs):
    srv = None if CLIENT else med([(r.get("timings") or {}).get("prompt_per_second") for r in rs if (r.get("timings") or {}).get("prompt_ms")])
    pn = med([(r.get("timings") or {}).get("prompt_n") for r in rs])
    if srv: return f"{srv:.0f}", pn
    cl = med([((r.get("timings") or {}).get("prompt_n") or 0) / ((r.get("timings") or {}).get("ttft_ms") or 1e9) * 1000 for r in rs])
    return (f"{cl:.0f}c" if cl else "—"), pn

print("| row | decode code | decode prose | n (code; prose) | accept code/prose | pp512 | pp4096 | prompt tokens |")
print("|---|---:|---:|---|---|---:|---:|---|")
for d in sys.argv[1:]:
    c, ac, nc = dec(take(d, "decode-code")); p, ap, np_ = dec(take(d, "decode-prose"))
    p5, n5 = pre(take(d, "pp512")); p4, n4 = pre(take(d, "pp4096"))
    print(f"| {os.path.basename(d.rstrip('/'))} | {c} | {p} | {nc}; {np_} | {ac}/{ap} | {p5} | {p4} | {n5}, {n4} |")
