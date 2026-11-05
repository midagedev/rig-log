"""Build data.json for the Spark small-room clip.

    .venv/bin/python make_data.py <alone.tape> <spark.tape>                  # the real tapes -> placeholder false
    .venv/bin/python make_data.py --placeholder <tape A> <tape B>            # development stand-ins -> placeholder true

Every number film.html draws comes from this file's output: the sitting literals below (each with the line it was
copied from) and the two toktape tapes (requests[0]). Refusals end with rc 65 and name the failure:
  - a tape whose requests[0].tokens is empty (nothing to replay);
  - a stamp unit that is neither ns nor us (tokens[0].t against timings.ttft_ms; a wrong unit would replay the race
    at the wrong speed);
  - a replayed rate that misses the tape's own predicted_per_second by more than RATE_TOL (a wrong origin or unit);
  - two tapes whose user prompt differs (the race claims "same prompt"; --placeholder only warns);
  - two tapes from different model files (real mode only);
  - a character the copied fonts cannot draw (the browser would fall back to a system face, or draw tofu).
"""
import argparse, gzip, hashlib, json, math, sys
from pathlib import Path

HERE = Path(__file__).parent
RATE_TOL = 0.10

# Race clock: the film's constants (film.html reads them back from data.json, so the two cannot drift apart).
RACE_V0 = 5.9          # video second the request is sent
RACE_REAL_S = 12.0     # tape seconds shown at 1x before any time-lapse (the spec's floor)
RACE_BUDGET_S = 18.3   # video seconds from RACE_V0 to the race's last frame of playback (24.2 s)

# ---- the sitting: rig-log log/2026-11-05.md, section "smallroom" (and the spec's plan print) ----------------------
LOG = "log/2026-11-05.md"
SITTING = {
    "date": ("2026-11-05", f"{LOG}:216"),
    "model": ("DeepSeek V4.1-Flash", f"{LOG}:221"),
    "quant": ("Q3_K_M", f"{LOG}:221"),
    "file_gb": (324, "bloomery docs/cards/sparkroom-decode.card:2"),
    "card": ("RTX A6000", f"{LOG}:221 (A6000 stage)"),
    "P": (512, f"{LOG}:221"),
    "depth": (512, f"{LOG}:221"),
    "n": (96, f"{LOG}:221"),
    "rounds": (3, f"{LOG}:221"),
    "cpu_cores": (64, f"{LOG}:246 (CPU 코어 수(박스 64))"),
    "room_gb": (128, f"{LOG}:230"),
    "ref_gb": (256, f"{LOG}:234"),
    "layers": (40, "spec sparkclip (model facts)"),
    "experts": (384, "spec sparkclip (model facts)"),
    "picks": (6, "spec sparkclip (model facts)"),
    "card_experts": (2662, "spec sparkclip (the plan print, 128 GB room, A6000)"),
    "card_gb": (44.8, "spec sparkclip (the plan print); log 224 rounds it to 45 GB"),
    "host_pinned_gb": (55.5, f"{LOG}:224"),
    "paged_gb": (158, f"{LOG}:225"),
    "arena_gb": (64, f"{LOG}:225"),
    "past_arena_gb": (94, f"{LOG}:225"),
    "past_arena_160_gb": (62, f"{LOG}:225"),
    "spark_host_gb": (97.7, f"{LOG}:225"),
    "spark_node_gb": (116, f"{LOG}:226 (~116 GB)"),
    "card_full": ("RTX A6000", "the stage card's name"),
    "node_chip": ("GB10", "spec sparkclip mechanism item 2 (the Spark's chip)"),
    "act_format": ("q8_1", "spec sparkclip mechanism item 3 (the activation sent per layer)"),
    "row_format": ("f32", "spec sparkclip mechanism item 3 (the rows returned)"),
    "url": ("github.com/midagedev/bloomery", "spec sparkclip END beat"),
    "link_ms": (7, f"{LOG}:130 (the node round trip 7 ms) and :85"),
    "nvme_ms_per_gb": ("0.20–0.26", f"{LOG}:236"),
    "step_fits_ms": (27, f"{LOG}:234 (~27) and :236"),
    "step_160_ms": (39.4, f"{LOG}:236 (39.4 − 27)"),
    "step_128_ms": (51.2, f"{LOG}:236 (51.2 − 27)"),
    "prefill_alone_s": (17.7, f"{LOG}:237"),
    "step_story": ("27 → 39 → 51", "spec sparkclip mechanism item 4 (the step alone at 0, 62, 94 GB short)"),
    "decode_x": ("1.8", f"{LOG}:216"),
    "prefill_x": ("3.6", f"{LOG}:216"),
}
# The table rows, verbatim from log/2026-11-05.md:230-234 (decode tok/s p50, step p50 ms, pp tok/s at P 512).
ROWS = [
    {"key": "alone", "label": "128 GB workstation alone", "short": "128 GB alone", "sub": "missing experts from NVMe",
     "decode": "19.35–19.61", "step": "51.0–51.7", "pp": "28.8–29.2", "src": f"{LOG}:230"},
    {"key": "spark", "label": "128 GB workstation + one DGX Spark", "short": "128 GB + one DGX Spark", "sub": "missing experts on the Spark",
     "decode": "34.69–35.04", "step": "28.5–28.8", "pp": "104.5–108.2", "src": f"{LOG}:231"},
    {"key": "alone160", "label": "160 GB workstation alone", "short": "160 GB alone", "sub": "",
     "decode": "25.23–25.65", "step": "39.0–39.6", "pp": "29.1–30.3", "src": f"{LOG}:232"},
    {"key": "spark160", "label": "160 GB workstation + one DGX Spark", "short": "160 GB + one DGX Spark", "sub": "",
     "decode": "34.57–34.76", "step": "28.8–28.9", "pp": "106.2", "src": f"{LOG}:233"},
    {"key": "ref", "label": "256 GB workstation alone, the model fits", "short": "256 GB alone", "sub": "reference",
     "decode": "~37", "step": "~27", "pp": "210–221", "src": f"{LOG}:234"},
]


def span(s):
    """'19.35–19.61' -> (19.35, 19.61); '34.69, 35.04' -> (34.69, 35.04); '~37' -> (37, 37)."""
    s = s.replace("~", "").replace(",", "–")
    parts = [float(x) for x in s.split("–")]
    return (min(parts), max(parts))


def fail(msg):
    print("make_data: refused:", msg, file=sys.stderr)
    sys.exit(65)


def load_tape(path):
    raw = Path(path).read_bytes()
    try:
        d = json.loads(gzip.decompress(raw))
    except OSError:
        d = json.loads(raw)
    return d, hashlib.sha256(raw).hexdigest()


def user_prompt(req):
    msgs = (req.get("prompt") or {}).get("messages") or []
    users = [m.get("content") for m in msgs if m.get("role") == "user"]
    if not users:
        return None
    c = users[-1]
    if isinstance(c, list):   # content parts
        c = "".join(p.get("text", "") for p in c if isinstance(p, dict))
    return c


def fmt_s(x):
    return f"{x:.2f} s" if x < 1 else f"{x:.1f} s"


def arm(path, key):
    d, sha = load_tape(path)
    reqs = d.get("requests") or []
    if not reqs:
        fail(f"{path}: no requests")
    q = reqs[0]
    toks = q.get("tokens") or []
    if not toks:
        fail(f"{path}: requests[0].tokens is empty")
    tm = dict((d.get("summary") or {}).get("timings") or {})
    tm.update(q.get("timings") or {})
    ttft = tm.get("ttft_ms")
    if not ttft:
        fail(f"{path}: no timings.ttft_ms to fix the stamp unit")
    ratio = toks[0]["t"] / ttft
    if 0.9e6 <= ratio <= 1.1e6:
        unit = 1e-9
    elif 0.9e3 <= ratio <= 1.1e3:
        unit = 1e-6
    else:
        fail(f"{path}: tokens[0].t / ttft_ms = {ratio:.4g}, neither ns (1e6) nor us (1e3)")
    tt = [x["t"] * unit for x in toks]
    if any(b < a for a, b in zip(tt, tt[1:])):
        fail(f"{path}: token stamps go backwards")
    text = [x.get("text", "") for x in toks]
    rflag = [1 if x.get("r") else 0 for x in toks]
    rate = [None] + [f"{i / (tt[i] - tt[0]):.1f}" if tt[i] > tt[0] else None for i in range(1, len(tt))]
    final = (len(tt) - 1) / (tt[-1] - tt[0]) if len(tt) > 1 and tt[-1] > tt[0] else None
    pps = tm.get("predicted_per_second") or tm.get("client_predicted_per_second")
    if final and pps and abs(final / pps - 1) > RATE_TOL:
        fail(f"{path}: the replayed rate {final:.2f} tok/s misses the tape's predicted_per_second {pps:.2f} "
             f"by more than {RATE_TOL:.0%} (unit or origin wrong?)")
    model = ((d.get("summary") or {}).get("model") or {}).get("file_name")
    server = ((d.get("summary") or {}).get("server") or {}).get("kind")
    return {
        "key": key, "tape": Path(path).name, "sha256": sha, "model_file": model, "server": server,
        "n": len(toks), "ttft_s": round(tt[0], 4), "ttft_label": fmt_s(tt[0]),
        "done_s": round(tt[-1], 4), "done_label": fmt_s(tt[-1]),
        "rate_final": f"{final:.1f}" if final else None,
        "prompt_n": tm.get("prompt_n"),
        "tt": [round(x, 4) for x in tt], "tx": text, "r": rflag, "rate": rate,
        "_prompt": user_prompt(q),
    }


def glyph_check(strings):
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        fail("fontTools is missing: run with .venv/bin/python (requirements.txt)")
    cover = set()
    for f in ("Geist-Variable.ttf", "GeistMono-Variable.ttf", "Pretendard-Medium.otf"):
        cover |= set(TTFont(HERE / "fonts" / f).getBestCmap().keys())
    missing = sorted({c for s in strings for c in s if not c.isspace() and ord(c) >= 0x20 and ord(c) not in cover})
    if missing:
        fail("the fonts cannot draw " + " ".join(f"U+{ord(c):04X}({c})" for c in missing[:24]))


def speed_for(t_end, max_speed):
    if t_end <= RACE_BUDGET_S:
        return 1
    need = (t_end - RACE_REAL_S) / (RACE_BUDGET_S - RACE_REAL_S)
    return max(2, min(max_speed, math.ceil(need - 1e-9)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--placeholder", action="store_true")
    ap.add_argument("--max-speed", type=int, default=2, help="the time-lapse cap after the real-time part (spec: 2)")
    ap.add_argument("--out", default=str(HERE / "data.json"), help="where to write (tests only; the film reads data.json)")
    ap.add_argument("alone")
    ap.add_argument("spark")
    a = ap.parse_args()

    A, S = arm(a.alone, "alone"), arm(a.spark, "spark")
    pa, ps = A.pop("_prompt"), S.pop("_prompt")
    if pa != ps:
        if not a.placeholder:
            fail("the two tapes' user prompts differ; the race says 'same prompt'")
        print("make_data: warning: the placeholder tapes' prompts differ", file=sys.stderr)
    if not a.placeholder and A["model_file"] != S["model_file"]:
        fail(f"the tapes name different model files: {A['model_file']} vs {S['model_file']}")
    prompt = (pa or "").strip()
    glyph_check([prompt] + A["tx"] + S["tx"])

    t_end = max(A["done_s"], S["done_s"])
    k = speed_for(t_end, a.max_speed)
    # the tape second reached at the budget's end; an arm whose last stamp lies past it is cut mid-stream
    reach = RACE_BUDGET_S if k == 1 else RACE_REAL_S + k * (RACE_BUDGET_S - RACE_REAL_S)

    facts = {k_: v for k_, (v, _) in SITTING.items()}
    rows = []
    for r in ROWS:
        rr = dict(r)
        rr["decode_span"], rr["pp_span"], rr["step_span"] = span(r["decode"]), span(r["pp"]), span(r["step"])
        rows.append(rr)

    out = {
        "placeholder": bool(a.placeholder),
        "made_by": "make_data.py",
        "sources": {k_: s for k_, (_, s) in SITTING.items()} | {"rows": f"{LOG}:230-234",
                                                                 "tapes": [A["tape"], S["tape"]]},
        "facts": facts,
        "rows": rows,
        "race": {
            "prompt": prompt, "prompt_n": A["prompt_n"] if A["prompt_n"] == S["prompt_n"] else None,
            "v0": RACE_V0, "real_s": RACE_REAL_S, "budget_s": RACE_BUDGET_S, "speed": k,
            "speed_label": f"{k}×", "reach_s": round(reach, 3),
            "cut": [x["key"] for x in (A, S) if x["done_s"] > reach],
            "arms": [A, S],
        },
        "chart": {"ticks_x": [0, 62, 94], "ticks_y": [0, 10, 20], "y_max": 26},
    }
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    ratio = A["done_s"] / S["done_s"]
    print(f"data.json: placeholder={out['placeholder']} speed={k}x reach={reach:.1f} s cut={out['race']['cut']}")
    for x in (A, S):
        print(f"  {x['key']:5s} {x['tape']}: n={x['n']} first token {x['ttft_label']} done {x['done_label']} "
              f"rate {x['rate_final']} tok/s model={x['model_file']} server={x['server']}")
    print(f"  alone/spark done ratio {ratio:.2f} (spec expects about 1.8 on the real tapes)")


if __name__ == "__main__":
    main()
