"""Part A of the 0.3.6 film (parta.js): how schemajump writes the same answer in fewer engine calls, in plain sentences.
The request card; one token's trip through the model's 40 layers (8 of 256 experts a layer, + 1 shared); plain
structured output writing the answer a token a call, the schema's fixed text spotlighted; a rewind and schemajump
writing it again, each call's ids fed together and each decision picked among the schema's options; both answers the
same text; one decision's percentage. build() returns the block data.json keeps under `a`, Part A's strings (each
with its source) and its shots in make_data.py's form; make_data.py lays them on the track with Part B's.

  python3 make_data_a.py --preview OUT.json      Part A alone on its own clock (no track), for probe/parta-preview.html

The calls: plain structured output feeds the answer's ids one a call (the tokenizer's pieces, sources/tokens-qwen36.json);
schemajump's calls are the program's plan over the same ids (its jump_plan: [kind, ids fed] a call). A decision is
picked by the call that feeds the id just before the decision's first id (its logits pick among the options' ids);
the picked option's other ids are fed with the fixed text after it. A plan whose calls do not meet the decisions so is
a named error.
"""
import json, math, sys
from pathlib import Path

HERE = Path(__file__).parent

# The beats of each shot, from its cut (the picture's clock is make_data.py's period).
TR_DOWN = 1          # the trip: the token goes down the stack from this beat, five layers a 16th
TR_ZOOM = None       # one layer opens into its 256 experts on this beat (None: the trip alone, the film's budget)
TR_LAYER = 20        # the layer the picture opens (any layer: the routing is a picture)
PL_AT = 1            # plain structured output: its first token a beat after the cut, one token a 16th
PL_SPOT = 2.5        # the spotlight this many beats after the last token (the counter's last value holds >= 1 s)
REW = 4              # schemajump's rewind takes the shot's first four beats (the track's rest bar before P's hit);
                     # its first call lands on beat REW, the hit
JP_STEP = 1          # schemajump: one call a beat
DN_JSON = 2          # the decision: the line completes on this beat
QS_AT = 2            # the request: its questions land on this beat

# key -> (string, [(doc, line, quote)], why): make_data.py's CITED rule (line n of doc holds quote; with no why, every
# word of the string is a word of its lines).
CITED_A = {
    "a_tr_head": ("ONE TOKEN, ONE TRIP", [("genloop", 41, "[`Engine::next`] a token")],
                  "an engine call takes a token through the whole model: the shot's head"),
    "a_tr_cap1": ("one engine call: all 40 layers", [("q36", 439, "(40 layers at interval 4)")],
                  "the real file's 40 layers, each a token passes"),
    "a_tr_cap2": ("each layer: 8 of 256 experts", [("moe", 2, "softmax over 256 experts"), ("moe", 2, "the top 8")],
                  "the router's top 8 of its 256 experts, in each layer"),
    "a_tr_sh":   ("+1 shared", [("moe", 3, "as a ninth slot")], "the shared expert, the ninth slot every token reads"),
    "a_dn_pl":   ("probability among the options", [("answer", 3, "the softmax runs in f32 over the options")],
                  "a label: the body's percentage is a softmax over the question's options alone, not a confidence"),
    "a_pl_cap":  ("one engine call per token", [("genloop", 41, "[`Engine::next`] a token"), ("runner", 16, "BLOOMERY_SCHEMAJUMP=off")],
                  "the step arm (the jump off) takes one Engine::next a token"),
}
FIXED_A = {   # labels of the picture that claim nothing on their own
    "a_tr_l": f"L{TR_LAYER}", "a_ax_l0": "L0", "a_ax_l39": "L39",
}
# The strings Part A draws that make_data.py owns (its CITED and FIXED): build() refuses by name when one is missing.
SHARED = ["name", "version", "claim1", "claim2", "rq_post", "q_model", "rq_served", "st_head", "jp_head",
          "calls_label", "spot", "bo_head", "q_step", "lg_jump", "leg_fixed", "leg_dec", "dn_head", "dn_stamp"]


def die(msg):
    print(f"make_data_a.py: refused: {msg}", file=sys.stderr)
    sys.exit(4)


def cite_a(md, src):
    copy, cites = {}, {}
    for key, (s, quotes, why) in CITED_A.items():
        qw = set()
        for doc, n, q in quotes:
            line = src[doc][n - 1] if 0 < n <= len(src[doc]) else ""
            if q not in line: die(f"{key}: {doc}:{n} does not say {q!r} (it says {line[:120]!r})")
            qw |= set(md.words_of(line))
        if why is None and not set(md.words_of(s)) <= qw: die(f"{key} {s!r} has words its source lines do not")
        copy[key] = s
        cites[key] = [f"{doc}:{n}" for doc, n, _ in quotes] + ([f"why: {why}"] if why else [])
    for k, v in FIXED_A.items(): copy[k] = v; cites[k] = ["label: a picture's axis (no routing measured)"]
    return copy, cites


def plan_calls(pieces, plan):
    """The schemajump calls over the answer's ids: [{first, n, kind, pick}], pick the decision run (D1, D2) the call's
    logits choose, else None; and each decision's run {first, n}."""
    runs = {}
    for i, p in enumerate(pieces):
        if p[2][0] == "D": r = runs.setdefault(p[2], {"first": i, "n": 0}); r["n"] += 1
    if sum(n for _, n in plan) != len(pieces): die(f"the plan feeds {sum(n for _, n in plan)} ids, the answer has {len(pieces)}")
    calls, at = [], 0
    for kind, n in plan:
        calls.append({"first": at, "n": n, "kind": kind, "pick": None}); at += n
    for d, r in runs.items():
        hit = [c for c in calls if c["first"] + c["n"] == r["first"]]
        if len(hit) != 1: die(f"no schemajump call ends at decision {d}'s first id {r['first']}: its logits pick nothing")
        hit[0]["pick"] = d
    return calls, runs


def engine_calls(pieces, jc):
    """The schemajump calls in the order the engine runs them (bloomery genloop.rs, struct Jump), from the jump row's
    counts jc: the lead's ids ride in the prompt call, whose logits pick decision 1; each call after it feeds a
    decision's id and the fixed run after it, and its logits pick the next decision; the last decision and the tail
    (its ids and the stop) are written with no call. Returns (calls, prompt, tail, runs): calls [{first, n, d, pick}],
    prompt {first, n, pick}, tail {first, n}; each run of the answer {first, n}. A count the pieces do not give is a
    named error."""
    runs, order = {}, []
    for i, p in enumerate(pieces):
        k = p[2]
        if k not in runs: runs[k] = {"first": i, "n": 0}; order.append(k)
        runs[k]["n"] += 1
    ds = [k for k in order if k[0] == "D"]
    fixed_after = lambda d: runs.get(f"F{d[1:]}", {"first": runs[d]["first"] + runs[d]["n"], "n": 0})
    lead = runs.get("F0", {"first": 0, "n": 0})
    calls = [{"first": runs[d]["first"], "n": runs[d]["n"] + fixed_after(d)["n"], "d": [runs[d]["first"], runs[d]["n"]],
              "pick": nxt} for d, nxt in zip(ds, ds[1:])]
    tail = {"first": runs[ds[-1]]["first"], "n": runs[ds[-1]]["n"] + fixed_after(ds[-1])["n"]}
    want = {"lead": lead["n"], "decisions": len(ds), "spans": len(calls), "span_ids": sum(c["n"] for c in calls),
            "tail": fixed_after(ds[-1])["n"] + 1}           # the tail's ids and the stop
    bad = {k: (v, jc.get(k)) for k, v in want.items() if jc.get(k) != v}
    if bad: die(f"the jump row's calls {bad} (pieces, row) are not the engine's order the pieces give")
    return calls, {"first": 0, "n": lead["n"], "pick": ds[0]}, tail, {k: runs[k] for k in ds}


def build(md, src, req, pieces, plan, counts, count_src, pct, pct_src, copy, P, dq=0):
    """Part A's block, strings, cites and shots. md: make_data; src: md.sources()[0]; req: md.request(); pieces:
    md.pieces_of(); plan: the request's jump_plan; counts: {"step", "jump"} engine calls; count_src: their cite; pct:
    the pick's percentage string ("94%", or "··%" with no saved body) and its cite; copy: make_data.py's strings so
    far (the shared keys are read from it, never written); P: the beat period (the same-text line lands after the
    program's reading time); dq: the index of the question A DECISION shows (its options by the request's labels)."""
    miss = [k for k in SHARED if k not in copy]
    if miss: die(f"make_data.py's copy has no {miss}: Part A draws them")
    C, cites = cite_a(md, src)
    n_step, n_jump = counts["step"], counts["jump"]
    if n_step != len(pieces): die(f"{req['id']}: {n_step} plain calls, the answer has {len(pieces)} ids")
    prompt = tail = None
    if counts.get("jump_calls"):         # the server's counts: the engine's order (Addition 7)
        calls, prompt, tail, runs = engine_calls(pieces, counts["jump_calls"])
        if n_jump != len(calls): die(f"{req['id']}: {n_jump} schemajump calls, the engine's order runs {len(calls)}")
    else:                                # the program's plan (sources/tokens-qwen36.json), PLACEHOLDER
        if n_jump != len(plan): die(f"{req['id']}: {n_jump} schemajump calls, the program's plan has {len(plan)}")
        calls, runs = plan_calls(pieces, plan)
    q1 = req["picks"][dq]
    pick_l = q1["labels"][q1["options"].index(q1["pick"])] if q1["kind"] != "choice" else q1["pick"]
    C.update({
        "state": req["state"], "answer": req["answer"],
        "options1": q1["labels"] if q1["kind"] != "choice" else q1["options"], "rq_q1": q1["qid"],
        "rq_qs": [p["qid"] for p in req["picks"]], "rq_opts": [p["labels"] for p in req["picks"]],
        "options": [p["options"] for p in req["picks"]], "pieces": pieces,
        "count_step": str(n_step), "count_jump": str(n_jump), "ticks": [str(i) for i in range(max(n_step, n_jump) + 1)],
        "bo_step": f"{n_step} calls", "bo_jump": f"{n_jump} calls",
        "dn_pick": pick_l, "dn_pct": pct,
    })
    doc = {"en": "suite.jsonl", "ko": "suite-ko.jsonl"}[md.REQ_SUITE]
    req_src = [f"{doc}:{req['line']} ({req['id']})", "rows (the jump arm's tops)"]
    for k in ("state", "answer", "options", "options1", "rq_q1", "rq_qs", "rq_opts"): cites[k] = req_src
    for k in ("count_step", "count_jump", "ticks", "bo_step", "bo_jump"): cites[k] = [count_src]
    cites["pieces"] = ["make_data.py pieces_of: the answer as the tokenizer cuts it (inputs.json tokens)"]
    cites["dn_pick"] = [f"rows (the jump arm's tops: {req['id']} {q1['qid']})"] + ([f"{pct_src} (its legend)"] if q1["kind"] == "score" else [])
    cites["dn_pct"] = [pct_src]
    plain_last = PL_AT + (n_step - 1) / 4
    # the events on beats from the hit: the prompt call's pick, each call, the tail (no call)
    jump_last = REW + (len(calls) - 1 + (prompt is not None) + (tail is not None)) * JP_STEP
    C["a_jp_same"] = ["the same text as", "plain structured output"]
    cites["a_jp_same"] = ["rows: the jump and step arms' tops agree (make_data.py's verdict check)"]
    if prompt:
        C.update({"leg_lead": "in the prompt call", "leg_none": "no call"})
        cites["leg_lead"] = ["genloop.rs:177-200 (struct Jump: the lead rides in the prompt call)"]
        cites["leg_none"] = ["genloop.rs:177-200 (struct Jump: the tail is written with no call)"]
    prog = [x for k in ("answer", "count_jump", "leg_fixed", "leg_dec") + (("leg_lead", "leg_none") if prompt else ())
            for x in md.flat({**copy, **C}[k]) if not md.PUNCT.match(x)]
    same_at = math.ceil(jump_last + md.read_s(prog)[0] / P - 1e-9)     # after the program's reading time
    a = {"tr": {"down": TR_DOWN, "zoom": TR_ZOOM, "layer": TR_LAYER},
         "pl": {"at": PL_AT, "last": plain_last, "spot": plain_last + PL_SPOT},
         "jp": {"rew": REW, "step": JP_STEP, "last": jump_last, "calls": calls, "runs": runs, "same": same_at,
                "prompt": prompt, "tail": tail},
         "dn": {"json": DN_JSON, "d": f"D{dq + 1}"}, "rq": {"qs": QS_AT}}
    shots = [
        ("title", [("lockup", 1, "rise", ["name", "version", "claim1", "claim2"])], []),
        ("areq", [("ask", 0, "cut", ["rq_post", "state"]),
                  ("qs", QS_AT, "cut", ["rq_qs", "rq_opts", "rq_served", "q_model"])], []),
        ("atrip", [("stack", 0, "cut", ["a_tr_head", "a_tr_cap1"])] + ([("zoom", TR_ZOOM, "cut", ["a_tr_cap2", "a_tr_sh"])] if TR_ZOOM else []), []),
        ("aplain", [("stage", 0, "cut", ["st_head", "calls_label", "a_pl_cap"]), ("answer", plain_last, "cut", ["pieces", "count_step"]),
                    ("spot", plain_last + PL_SPOT, "cut", ["spot"])], []),
        ("ajump", [("stage", 0, "cut", ["jp_head", "calls_label"]),
                   ("program", jump_last, "cut", ["pieces", "count_jump", "leg_fixed", "leg_dec"] + (["leg_lead", "leg_none"] if prompt else [])),
                   ("same", same_at, "cut", ["a_jp_same"])], []),
        ("adec", [("row", 0, "cut", ["dn_head", "rq_q1", "options1", "dn_pick", "dn_pct", "a_dn_pl"]), ("json", DN_JSON, "cut", ["answer"])], []),
    ]
    return {"a": a, "copy": C, "cites": cites, "shots": shots, "anchor": ("P", "ajump", REW)}


# ---- the preview: Part A alone on its own clock --------------------------------------------------------------------
def preview(out):
    import make_data as md
    beats = json.loads((HERE / "beats.json").read_text())[md.MUSIC_ID]
    P = beats["period_s"]
    m = md.measure()
    src, _ = md.sources()
    copy, cites = md.cite(src)
    copy.update(md.FIXED)
    for k in md.FIXED: cites[k] = ["label"]
    copy["version"] = md.INPUTS["version"]
    req = md.request(src, m["jump_tops"])
    tokdoc = json.loads((HERE / md.INPUTS["tokens"]).read_text())
    tok = tokdoc["requests"][md.INPUTS["request"]]
    pieces = md.pieces_of(req["answer"], tok)
    C = m["calls"]
    cr = next(x for x in C["per"] if x["key"] == md.INPUTS["request"])
    placeholder = C["source"] != "rows"
    body = md.INPUTS.get("answer_body", "")
    pct, pct_src = "··%", "PLACEHOLDER: no saved body (inputs.json answer_body)"
    qids = [x["qid"] for x in req["picks"]]
    dq = qids.index(md.INPUTS.get("dn_question") or qids[0])
    if body:
        pb = json.loads((HERE / body).read_text())["answers"][qids[dq]]["probabilities"]
        pct, pct_src = f"{100 * pb[req['picks'][dq]['pick']]:.0f}%", f"inputs.json answer_body {body}"
    csrc = "rows" if not placeholder else f"PLACEHOLDER: {md.INPUTS['tokens']} (sjcmp.py's predicted calls)"
    pa = build(md, src, req, pieces, [tuple(x) for x in tok["jump_plan"]], cr, csrc, pct, pct_src, copy, P, dq)
    copy.update(pa["copy"]); cites.update(pa["cites"])
    L = md.lengths(pa["shots"], copy, P, 0.0, 0)
    on = lambda x: max(0.0, x * P - md.LEAD)
    segs, b0 = [], 0
    for S0 in L:
        nb = max(S0["min"], 4)
        S = {"id": S0["id"], "kind": "card", "b0": b0, "len": nb, "b1": b0 + nb, "t0": round(on(b0), 6), "t1": round(on(b0 + nb), 6),
             "groups": [], "carry": S0["carry"]}
        for g in S0["groups"]:
            t_land = on(b0 + g["at"])
            still = t_land + md.SETTLE[g["how"]]
            if S["t1"] - still + 1e-9 < g["read_s"]: die(f"{S['id']}.{g['name']} holds {S['t1'] - still:.2f} s, needs {g['read_s']:.2f}")
            S["groups"].append({"name": g["name"], "keys": g["keys"], "at": g["at"], "land": round(t_land, 6), "still": round(still, 6),
                                "how": g["how"], "read_s": round(g["read_s"], 3), "words": g["words"], "numbers": g["numbers"]})
        segs.append(S); b0 += nb
    T = round(b0 * P, 4)
    data = {"film": "release-036", "timeline": {"T": T, "period": P, "lead": md.LEAD, "segments": segs, "fade_out_s": 0.0,
                                                "nbeats": b0, "beats": [round(k * P, 4) for k in range(b0 + 1)],
                                                "ticks": [round(on(k / 4), 4) for k in range(4 * b0) if k % 4]},
            "copy": copy, "sources": cites, "a": pa["a"], "placeholder": placeholder, "fixture": False, "draft_body": not body}
    Path(out).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    hit = next(S for S in segs if S["id"] == "ajump")["b0"] + REW
    print(f"{out}: T {T} s, {b0} beats of {P} s; P's hit (ajump beat {REW}) on film beat {hit}")
    print("shot     group    beats words nums  read  holds")
    for S in segs:
        for g in S["groups"]: print(f"{S['id']:8} {g['name']:8} {S['len']:5} {g['words']:5} {g['numbers']:4} {g['read_s']:5.2f} {S['t1'] - g['still']:6.2f}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) != 2 or a[0] != "--preview": die("usage: make_data_a.py --preview OUT.json")
    preview(a[1])
