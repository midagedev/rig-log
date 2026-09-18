#!/usr/bin/env python3
"""Fire N real translation requests at once and report what the server produced in total.

Aggregate decode is the number the batch cares about, and it is not the sum of what each stream
reports: streams start together and finish apart, so summing per-stream rates credits the server
with a parallelism it no longer had at the end. This measures the wall clock from the first
request going out to the last one coming back, and divides the tokens *all* of them produced by
it. Per-stream rates are recorded too, because a level where one stream is starved and another
runs at full speed is a different finding from one where all of them slow down evenly.

Every request is a real part of this repo at temperature 0, not a synthetic prompt: the
concurrency question here is about the queue we actually intend to run.
"""
import argparse, json, statistics, sys, threading, time, urllib.request


def one(url, system, text, out, idx, timeout):
    body = {"model": "local", "temperature": 0.0, "max_tokens": 8192, "stream": True,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}]}
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time(); t_first = None; n = 0; usage = None; n_think = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                d = line[5:].strip()
                if d == "[DONE]":
                    break
                try:
                    ev = json.loads(d)
                except json.JSONDecodeError:
                    continue
                if ev.get("usage"):
                    usage = ev["usage"]
                for ch in ev.get("choices") or []:
                    d = ch.get("delta") or {}
                    # Reasoning deltas are counted, not dropped: a level whose tokens were all
                    # deliberation reports a rate that looks like throughput and translated
                    # nothing. Measured 2026-09-18, on this harness's first run.
                    if d.get("reasoning_content") or d.get("reasoning"):
                        n_think += 1
                    if d.get("content"):
                        if t_first is None:
                            t_first = time.time()
                        n += 1
    except Exception as e:                      # a level that fails is a result, not a crash
        out[idx] = {"error": f"{type(e).__name__}: {e}", "t0": t0, "t_end": time.time()}
        return
    t_end = time.time()
    # completion_tokens is preferred but is not always a completion count -- TabbyAPI echoed the
    # prompt count back on 2026-09-18 -- so it is used only when it differs from prompt_tokens.
    u_out = (usage or {}).get("completion_tokens")
    n_in = (usage or {}).get("prompt_tokens")
    tok = u_out if (u_out and u_out != n_in) else n
    out[idx] = {"t0": t0, "t_first": t_first, "t_end": t_end, "deltas": n,
                "reasoning_deltas": n_think,
                "prompt_tokens": n_in, "tokens": tok,
                "ttft_s": round((t_first - t0), 3) if t_first else None,
                "own_decode_tok_s": round((tok - 1) / (t_end - t_first), 1)
                                    if t_first and tok > 1 and t_end > t_first else None}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--parts", required=True, help="JSON {system: str, parts: [str, ...]}")
    p.add_argument("--out", required=True)
    p.add_argument("--levels", default="1,2,3")
    p.add_argument("--timeout", type=float, default=1800.0)
    a = p.parse_args()

    spec = json.load(open(a.parts, encoding="utf-8"))
    system, parts = spec["system"], spec["parts"]
    rows = []
    for lvl in [int(x) for x in a.levels.split(",")]:
        if lvl > len(parts):
            print(f"level {lvl}: only {len(parts)} parts available, skipped"); continue
        out = [None] * lvl
        # Each level uses the same first `lvl` parts, so the levels differ in concurrency and in
        # nothing else. Level 1 therefore runs part 0 alone and is the baseline every other
        # level's part 0 is compared against.
        ts = [threading.Thread(target=one, args=(a.url, system, parts[i], out, i, a.timeout))
              for i in range(lvl)]
        t0 = time.time()
        for t in ts: t.start()
        for t in ts: t.join()
        wall = time.time() - t0
        ok = [r for r in out if r and "error" not in r]
        tok = sum(r["tokens"] for r in ok)
        # Wall from the first send to the last return: what the queue actually paid.
        agg = round(tok / wall, 1) if wall else None
        empty = [i for i, r in enumerate(out) if r and "error" not in r and not r["deltas"]]
        if empty:
            print(f"level {lvl}: stream(s) {empty} produced no answer at all "
                  f"(reasoning deltas {[out[i]['reasoning_deltas'] for i in empty]}) -- "
                  f"this level is not a throughput measurement", file=sys.stderr)
        row = {"streams": lvl, "wall_s": round(wall, 2), "total_tokens": tok,
               "answered": len(ok) - len(empty),
               "aggregate_tok_s": agg,
               "per_stream_tok_s": [r.get("own_decode_tok_s") for r in out if r],
               "ttft_s": [r.get("ttft_s") for r in out if r],
               "errors": [r["error"] for r in out if r and "error" in r]}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
        json.dump(rows, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    base = next((r for r in rows if r["streams"] == 1), None)
    if base and base["aggregate_tok_s"]:
        print("\nstreams  aggregate tok/s   x single")
        for r in rows:
            if r["aggregate_tok_s"]:
                print(f"{r['streams']:>7}  {r['aggregate_tok_s']:>15}   "
                      f"{r['aggregate_tok_s'] / base['aggregate_tok_s']:.2f}x")


if __name__ == "__main__":
    main()
