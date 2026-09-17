#!/usr/bin/env python3
"""Print one table row per tape, read from the tape.

    tools/tape-row.py <tape> [<tape> ...]
    tools/tape-row.py --md <tape> ...      # markdown, ready for a log entry

Measured 2026-09-17, the reason this exists: four figures in a published entry were copied from
the runner's progress lines instead of the tapes, and three of them were wrong (41.1 against a real
40.9, 297 W against 284.53, "201 tokens out" for a take whose streams ended between 157 and 248).
The card rounds, the progress lines round differently, and a table assembled by eye mixes both. So
the row comes from the tape's own summary and nothing else.

Columns: the stream count, whether the take asked for thinking and whether it got it, the server's
and the client's per-stream rate, the aggregate, TTFT p50, the engine's prefill, GPU watts at the
end, the per-stream output range, and the inter-token latency the tape measured. `thinking` reads
what the request asked, and for a no-think take what the answer did: `off/no` is honest, `off/YES` is
the mislabelling that [`check-take-nothink.py`](check-take-nothink.py) fails a take for. A thinking
take reads plain `on` — there is nothing to check, and no tag to find either, since on the jinja path
the template emits the opening `<think>` itself as the tail of the prompt.
"""
import gzip
import json
import sys

TAGS = ("<think>", "<thinking>", "<|thinking|>", "◁think▷")


def thought(req, n=64):
    out = []
    for t in req.get("tokens") or []:
        out.append(t.get("text", "") if isinstance(t, dict) else str(t))
        if sum(map(len, out)) >= n:
            break
    head = "".join(out)[:n]
    return any(tag in head for tag in TAGS) or bool(req.get("reasoning_n"))


def row(path):
    t = json.load(gzip.open(path))
    s = t["summary"]
    reqs = t.get("requests") or []
    tim = s.get("timings") or {}
    agg = s.get("aggregate") or {}
    kw = ((s.get("template") or {}).get("template_kwargs")) or {}
    asked = "off" if str(kw.get("enable_thinking", "")).lower() == "false" else "on"
    # Only a no-think take is judged. A thinking take on the jinja path has no literal tag to find:
    # the template itself emits `<think>\n` as the tail of the prompt, so the answer's first tokens
    # are thinking content with no opening tag (measured 2026-09-17 — the eight sweep tapes all read
    # "no" here while every stream ran 512 thinking tokens).
    if asked == "off":
        observed = "/YES" if any(thought(r) for r in reqs) else "/no"
    else:
        observed = ""
    ns = [(r.get("timings") or {}).get("predicted_n") or 0 for r in reqs] or [tim.get("predicted_n") or 0]
    gpu = (s.get("gpus_at_end") or [{}])[0]
    streams = agg.get("streams") or s.get("concurrency") or 1
    return {
        "tape": path.split("/")[-1],
        "engine": (s.get("server") or {}).get("engine_label")
        or ((s.get("server") or {}).get("engine") or {}).get("name")
        or (s.get("server") or {}).get("kind")
        or "?",
        "streams": streams,
        "thinking": f"{asked}{observed}",
        "srv_each": tim.get("predicted_per_second"),
        "cli_each": tim.get("client_predicted_per_second"),
        "aggregate": agg.get("aggregate_predicted_per_second") or tim.get("predicted_per_second"),
        "ttft_p50_ms": agg.get("ttft_p50_ms") or tim.get("ttft_ms"),
        "prefill_ms": tim.get("prompt_ms"),
        "prompt_n": tim.get("prompt_n"),
        "watt": gpu.get("power_w"),
        "out": f"{min(ns)}–{max(ns)}" if min(ns) != max(ns) else str(ns[0]),
        "itl_p50_ms": tim.get("itl_p50_ms"),
        "eff_bw_gbps": (tim.get("effective_bw_bps") or 0) / 1e9 or None,
        "contended": (s.get("contention") or {}).get("contended"),
    }


def fmt(v, nd=1):
    if v is None:
        return "?"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


if __name__ == "__main__":
    args = sys.argv[1:]
    md = "--md" in args
    paths = [a for a in args if not a.startswith("--")]
    if not paths:
        sys.exit(__doc__)
    rows = []
    for p in paths:
        try:
            rows.append(row(p))
        except Exception as e:  # noqa: BLE001 — name the tape that could not be read, keep going
            print(f"UNREADABLE {p}: {e}", file=sys.stderr)
    cols = [
        ("streams", "streams", 0), ("thinking", "thinking", 0), ("srv_each", "srv each", 1),
        ("cli_each", "cli each", 1), ("aggregate", "aggregate", 1), ("ttft_p50_ms", "TTFT p50 ms", 0),
        ("prefill_ms", "prefill ms", 0), ("watt", "GPU W", 0), ("out", "tokens out", 0),
        ("itl_p50_ms", "ITL p50 ms", 1), ("eff_bw_gbps", "eff GB/s", 0), ("contended", "contended", 0),
    ]
    if md:
        print("| tape | " + " | ".join(h for _, h, _ in cols) + " |")
        print("|---|" + "|".join("---" for _ in cols) + "|")
        for r in rows:
            print(f"| `{r['tape']}` | " + " | ".join(fmt(r[k], nd) for k, _, nd in cols) + " |")
    else:
        w = max((len(r["tape"]) for r in rows), default=4)
        print(f"{'tape':<{w}}  " + "  ".join(f"{h:>11}" for _, h, _ in cols))
        for r in rows:
            print(f"{r['tape']:<{w}}  " + "  ".join(f"{fmt(r[k], nd):>11}" for k, _, nd in cols))
