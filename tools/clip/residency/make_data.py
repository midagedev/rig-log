"""Write data.json for film.html.

  placeholder   invented numbers shaped like the sitting's records, flagged "placeholder": true
                (film.html stamps every frame PLACEHOLDER while the flag is set)

The measured version replaces this from the sitting's logs (resvideo-v41.card on the box).
Hit per step = 1 - host_slots / (layers * top_k), the formula line3 gave for `stat step` records.
"""
import json, math, random, sys
from pathlib import Path

HERE = Path(__file__).parent


def placeholder():
    L, K, STEPS = 40, 6, 96
    rnd = random.Random(7)

    def steps(h0, h1, tau):
        out = []
        for i in range(STEPS):
            h = h1 - (h1 - h0) * math.exp(-i / tau) if tau else h0
            h = min(.95, max(.02, h + rnd.gauss(0, .025)))
            out.append({"i": i, "host_slots": round((1 - h) * L * K)})
        return out

    arm = lambda tg, pp, st, bd, flips: {"tg_tps": tg, "pp_tps": pp, "steps": st, "boundaries": bd, "flips": flips}
    bd = {"p512": list(range(4, STEPS, 4)), "p4096": list(range(4, STEPS, 4))}
    flips = {"p512": [rnd.choice([16, 20, 24, 24, 28, 30]) for _ in bd["p512"]], "p4096": []}   # all layers together
    return {
        "placeholder": True,
        "meta": {"tree": "placeholder", "on_main": False, "placement": "a", "cards": "a6000",
                 "layers": L, "topk": K, "n_experts": 384,
                 "card_slots_per_layer": 70, "pinned_P": 40, "churn": 30, "spare_S": 1, "expert_bytes": 16773120},
        "arms": {
            "off": arm({"p512": [30.9, 31.0], "p4096": [28.4, 28.6]}, {"p512": [193.3], "p4096": [363.0]},
                       {"p512": steps(.19, .19, 0), "p4096": []}, {"p512": [], "p4096": []}, {"p512": [], "p4096": []}),
            "rule": arm({"p512": [36.0, 36.1], "p4096": [31.8, 31.8]}, {"p512": [193.3], "p4096": [363.0]},
                        {"p512": steps(.19, .46, 38), "p4096": []}, bd, flips),
            "stream": arm({"p512": [43.3, 43.3], "p4096": [36.8, 36.8]}, {"p512": [192.0], "p4096": [376.7]},
                          {"p512": steps(.56, .62, 40), "p4096": []}, bd, flips),
        },
        "call_stream_end": {"p512": {"bytes": 485 * 16773120, "pick_us": 12800, "admitted": 485, "kept": 1},
                            "p4096": {"bytes": 0, "pick_us": 17500, "admitted": 0, "kept": 1}},
        "majflt": {"off": 0, "rule": 0, "stream": 0},
        "logs": [],
    }


def tape_text(path):
    """Prompt and answer tokens from a toktape file (gzip JSON), first request."""
    import gzip
    raw = Path(path).read_bytes()
    d = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
    r = d["requests"][0]
    return r["prompt"]["messages"][0]["content"], [t["text"] for t in r["tokens"]]


def from_pack(pack):
    """data.json from a resvideo sitting's data pack (bloomery specs/release/resvideo/pack, README there)."""
    import csv, re
    pack = Path(pack)
    rows = lambda f: list(csv.DictReader(open(pack / f), delimiter="\t", quoting=csv.QUOTE_NONE))
    L, K = 40, 6
    # decode tok/s after 96 steps: the sitting's table (two rounds at P 512 were reported by the runner; see README)
    TG = {"off": {"p512": [29.48], "p4096": [29.12]}, "rule": {"p512": [35.70], "p4096": [31.71]}, "stream": {"p512": [43.86], "p4096": [36.90]}}
    # prompt tok/s, P 4096: the two rounds' means from the sitting's `time prompt` rows (P 512 kept as one row each)
    PP = {"off": {"p512": [193.11], "p4096": [367.19]}, "rule": {"p512": [192.65], "p4096": [367.19]}, "stream": {"p512": [190.52], "p4096": [373.64]}}
    arms = {}
    for arm in ("off", "rule", "stream"):
        st = [r for r in rows(f"{arm}-stats-p512-r1.tsv") if r["host_slots"]]
        tm = rows(f"{arm}-p512-r2.tsv")
        ms = [float(r["step_ms"]) for r in tm if r["step_ms"]]
        toks = [json.loads(r["text"]) for r in tm][1:]          # row 0 is the prompt's last position
        res = (pack / f"{arm}-p512-r2.residency.txt").read_text()
        flights = []
        made = {}
        for m in re.finditer(r"residency pass pass=step boundary=(\d+) .*?landed=(\d+) .*?made=(\d+)", res):
            b, landed, mk = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if mk: made[b] = mk
            if landed: flights.append({"made": max(0, max([x for x in made if x < b], default=b - 4) - 1), "land": b - 1, "n": landed})
        arms[arm] = {"tg_tps": TG[arm], "pp_tps": PP[arm],
                     "steps": {"p512": [{"i": int(r["i"]), "host_slots": int(r["host_slots"])} for r in st], "p4096": []},
                     "step_ms": ms, "tokens": toks, "flights": flights,
                     "boundaries": {"p512": [f["land"] for f in flights]}, "flips": {"p512": [f["n"] for f in flights]}}
    cse = re.search(r"call stream end picks=(\d+) admitted=(\d+) bytes=(\d+) pick_us=(\d+)", (pack / "stream-p512-r2.residency.txt").read_text())
    host = re.search(r"pinned=(\d+) churn_experts=(\d+)", (pack / "residency-host.txt").read_text())   # the load's record
    pinned, churn = int(host.group(1)), int(host.group(2))
    return {
        "placeholder": False,
        "meta": {"tree": "bloomery 8e13720e, landed as main 4e77f89b (same content, rebased over one docs-only commit)", "defaults_on_main": "2c49dd6a",
                 "placement": "a", "cards": "a6000", "layers": L, "topk": K, "n_experts": 384,
                 "card_slots_per_layer": round(pinned + churn / L + 1), "pinned_P": pinned, "churn": round(churn / L), "spare_S": 1,
                 "expert_bytes": 16773120, "sitting": "resvideo-v41, 2026-09-30 08:53-09:01 UTC"},
        "arms": arms,
        "call_stream_end": {"p512": {"picks": int(cse.group(1)), "admitted": int(cse.group(2)), "bytes": int(cse.group(3)), "pick_us": int(cse.group(4))}},
        "majflt": {"off": 0, "rule": 0, "stream": 0},
        "prompt_text": (pack / "prose-prompt-first80-ids.txt").read_text(), "prompt_tokens": 512,
        "text_source": "the sitting's prose P 512 arms: the first 512 ids of corpus-prose.ids (llama.cpp docs, MIT), greedy",
    }


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "pack":
        (HERE / "data.json").write_text(json.dumps(from_pack(sys.argv[2]), indent=1))
        print("data.json (measured, from the pack)")
        sys.exit(0)
    if len(sys.argv) != 3 or sys.argv[1] != "placeholder":
        sys.exit("usage: make_data.py placeholder <toktape for the stand-in words>")
    d = placeholder()
    prompt, toks = tape_text(sys.argv[2])
    d["prompt_text"], d["prompt_tokens"] = prompt, 507
    d["text_source"] = "stand-in: tape.midagedev.com/r/6w4t9r5nqwtt5c9sagn3 (draft on, place bp)"
    rnd = random.Random(9)
    for arm, (a0, a1, tau) in {"off": (31.0, 31.0, 0), "rule": (31.0, 40.5, 30), "stream": (42.5, 43.8, 30)}.items():
        ms = []
        for i in range(96):
            tps = a1 - (a1 - a0) * math.exp(-i / tau) if tau else a0
            ms.append(round(1000 / tps * (1 + rnd.gauss(0, .06)), 2))
        d["arms"][arm]["step_ms"] = ms
        d["arms"][arm]["tokens"] = toks[:96]
    (HERE / "data.json").write_text(json.dumps(d, indent=1))
    print("data.json (placeholder)")
