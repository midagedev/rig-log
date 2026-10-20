"""Part B of the 0.3.6 film (partb.js): real requests as Isotype grids, the answers kept, the hard suite, DeepSeek-V4.1-Flash's
two arms, the timed requests, Solar and the end. part_b() reads the sitting's rows and saved bodies and returns the
block data.json keeps under `b`, its strings (each with its source) and its shots in make_data.py's form; make_data.py
lays the shots on the track with Part A's.

  python3 make_data_b.py --preview OUT.json [--rows DIR] [--bodies DIR] [--hard-rows DIR]
                    Part B alone on its own clock (no track), for probe/partb-preview.html

The rows: every rows.json under the rows dir (sj-vs-clef.sh's windows), a row (arm, kind, suite, id, round, dropped,
bucket, wall_ms, prompt_ms, prompt_n, tops). A clef-kind row is Clef-Flash's decide seat; the other arms go through
ARMS. A dropped row is not counted; p50 is the median of the counted rows. Short = the requests under 1,000 prompt
tokens, long = the two long requests (the rows' bucket).

The bodies: bodies/<dir>/<suite>-<id>.json, each a SystemOne body (bloomery crates/decision/src/answer.rs: a choice
answer's choice, confidence and probabilities in criteria order, a score's score, confidence, legend and
probabilities by level, a noul's P(yes)). BODY_DIRS names whose body each dir holds. Every percentage on screen is
100 x a body's probability rounded to the integer, and the grid shows that many squares; a confidence line is the
body's confidence; a yes/no answer carries no confidence on the wire and gets no line. A body whose pick is not the
pick its arm's rows recorded is a named error.

The requests shown (REQUESTS, inputs.json b.requests the first n, default 2): five whose answers read at a glance,
the first two one English and one Korean; never route-01 (Part A's), guard-04 (its answer is a miss), sentiment-07 or
long-08 (their text says "new" or "first", which no frame shows), or review-05 (its state line wraps past three
lines). A confidence is a line with no label.
HARD is one shot: correct/N per head model, then DeepSeek-V4.1-Flash's schemajump against its plain structured output
(the speed and whether the answers agree). The hard examples (inputs.json b.examples, default 3), a shot each with no
figures: questions where the models' picks differ, first one the smallest model gets right and another misses and one
the other way round, then the rest that differ, then all-right ones; a request once before twice; within a tier the
quickest to read (the reading rule's words and numbers), HX_PREFER first among equals.
LONG (inputs.json b.long): "off" (default), "line" (one line in SHORT: the gap's prompt-reading share) or "shot" (the
race of two long requests, the L hit on its GO; else the L hit lands on SHORT's cut).
"""
import json, math, re, statistics, subprocess, sys
from pathlib import Path

HERE = Path(__file__).parent
HANGUL = re.compile(r"[가-힣]")
SUITE_FILE = {"en": "suite.jsonl", "ko": "suite-ko.jsonl", "hard": "suite-hard.jsonl"}   # tools/ref/clef/ in bloomery
FIXTURE = set()             # the made-up bodies read (probe/bfx.py marks each "fixture": true)

# The sitting runner's arm names -> (model, arm). A row of kind clef is Clef-Flash's decide seat whatever its arm.
ARMS = {"A": ("Clef-Flash", "A"), "jump": ("Qwen3.6-35B-A3B", "jump"), "step": ("Qwen3.6-35B-A3B", "step"),
        "qwen-jump": ("Qwen3.6-35B-A3B", "jump"), "qwen-step": ("Qwen3.6-35B-A3B", "step"),
        "ds41-jump": ("DeepSeek-V4.1-Flash", "jump"), "ds41-step": ("DeepSeek-V4.1-Flash", "step")}
# bodies/<dir>: whose SystemOne bodies it holds, (model, route). The request shots read the Qwen3.6 /v1/systemone
# bodies (schemajump on, untimed); the hard examples read each model's first dir that holds the request.
BODY_DIRS = {"clef": ("Clef-Flash", "seat"), "A": ("Clef-Flash", "seat"),
             "qwen-sys1": ("Qwen3.6-35B-A3B", "systemone"), "qwen-jump": ("Qwen3.6-35B-A3B", "jump"),
             "jump-systemone": ("Qwen3.6-35B-A3B", "systemone"), "jump": ("Qwen3.6-35B-A3B", "jump"),
             "step-systemone": ("Qwen3.6-35B-A3B", "systemone-step"), "step": ("Qwen3.6-35B-A3B", "step"),
             "ds41-jump-systemone": ("DeepSeek-V4.1-Flash", "systemone"), "ds41-jump": ("DeepSeek-V4.1-Flash", "jump"),
             "ds41-step-systemone": ("DeepSeek-V4.1-Flash", "systemone-step"), "ds41-step": ("DeepSeek-V4.1-Flash", "step")}
REQ_BODY = ("Qwen3.6-35B-A3B", "systemone")
REQ_ARM = ("Qwen3.6-35B-A3B", "jump")          # the rows whose picks the request bodies must agree with
# The requests, in the order shown (suite, id): an agent's tool, a Korean customer, an invoice as JSON, a mixed review
# in Korean, a Korean mail. b.requests shows the first n (default 2: one English, one Korean).
REQUESTS = [("en", "tool-03"), ("en", "ko-06"), ("en", "invoice-02"), ("ko", "ko-review-04"), ("ko", "ko-mail-06")]
HX_PREFER = [("hard-01-alerts", "alert_1"), ("ko-hard-12-history", "강"), ("ko-hard-12-history", "제도")]
# The hard suite's models, smallest first: (model, copy key of the name, of the short name, the arm that is scored).
HARD_HEAD = [("Clef-Flash", "clef", "clef", "A"), ("Qwen3.6-35B-A3B", "q_model", "q_s", "jump"),
             ("DeepSeek-V4.1-Flash", "v41", "v41_s", "jump")]

# Type at 1080 (partb.js draws them): a request's text and the widths it wraps to.
REQ_SIZE, REQ_MIN, REQ_LINES, WIDTH = 48, 46, 3, 936
CAP_SIZE = 44
# The shots' beats: a request's text lands on the cut, its grids count up from GRID_AT in four 16ths, the picks and
# figures land on ANS_AT; the long race's GO on GO_BEAT (make_data.py's).
GRID_AT, ANS_AT, GO_BEAT = 2, 3, 3
HD_V41_AT = 8        # the hard shot: the V4.1-Flash line lands on this beat, under the counts
EX_MAX = 4           # b.examples at most
LONG_MODES = ("off", "line", "shot")
QTY = re.compile(r"^([−-]?\d[\d,]*(\.\d+)?(×|%)?|\d+/\d+)$")
UNITS_MS = [5, 10, 20, 25, 50, 100, 200, 250, 500, 1000]

FIXED_B = {
    "b_hd_ex": "HARD QUESTIONS",
    "b_sh_head": "SHORT REQUESTS", "b_lg_head": "LONG REQUESTS", "b_sa_head": "SAME ANSWERS",
    "b_sa_t": ["schemajump and", "plain structured output"], "b_lg_leg_p": "reading the prompt", "b_lg_leg_r": "the rest",
    "b_hd_head": "HARD QUESTIONS", "b_fx": "PLACEHOLDER: fixture rows and bodies, not measured",
    "b_yes": "yes", "b_no_a": "no",
}


def die(msg):
    print(f"make_data_b: {msg}", file=sys.stderr)
    sys.exit(3)


# ---- metrics: the advances partb.js draws with (Martian Mono at wdth 75 is 0.6 em a glyph; Noto Sans KR at 800) -----
_KR = None


def kr_adv():
    global _KR
    if _KR is None:
        from fontTools.ttLib import TTFont
        from fontTools.varLib import instancer
        g = instancer.instantiateVariableFont(TTFont(str(HERE / "fonts/NotoSansKR-subset.ttf")), {"wght": 800})
        cm, upm = g.getBestCmap(), g["head"].unitsPerEm
        _KR = {chr(c): g["hmtx"][n][0] / upm for c, n in cm.items() if c < 0x3000}
    return _KR


def em(s, face):
    if face == "mono": return 0.6 * len(s)
    A = kr_adv()
    return sum(0.92 if HANGUL.match(c) else A.get(c, 0.6) for c in s)


def face_of(s):
    return "kr" if HANGUL.search(s) else "mono"


def wrap(s, size, width=WIDTH, face=None):
    """s wrapped at spaces (and at its own line breaks) to width px at size px; a word wider than the line is an error."""
    face = face or face_of(s)
    out = []
    for para in s.split("\n"):
        cur = ""
        for w in para.split(" "):
            nxt = (cur + " " + w).strip()
            if cur and em(nxt, face) * size > width: out.append(cur); cur = w
            else: cur = nxt
            if em(cur, face) * size > width: die(f"{w!r} is wider than {width} px at {size} px")
        if cur: out.append(cur)
    return out


# ---- the rows ------------------------------------------------------------------------------------------------------
def load_rows(rows_dir):
    files = sorted(Path(rows_dir).glob("**/rows.json"))
    if not files: die(f"no rows.json under {rows_dir}")
    rows, fixture = [], False
    for f in files:
        body = json.loads(f.read_text())
        fixture |= bool(body.get("fixture"))
        for r in body["rows"]:
            if r.get("dropped"): continue
            r = dict(r)
            if "model" not in r:
                if r.get("kind") == "clef": r["model"], r["arm"] = "Clef-Flash", "A"
                elif r.get("arm") in ARMS: r["model"], r["arm"] = ARMS[r["arm"]]
                else: die(f"{f}: arm {r.get('arm')!r} (kind {r.get('kind')!r}) is not in ARMS")
            rows.append(r)
    return rows, fixture


def of(rows, model, arm, **kw):
    return [r for r in rows if r["model"] == model and r["arm"] == arm and all(r.get(k) == v for k, v in kw.items())]


def med(xs, what):
    xs = list(xs)
    if not xs: die(f"no counted rows for {what}")
    return statistics.median(xs)


def firsts(R):
    out = {}
    for r in sorted(R, key=lambda r: r["round"]): out.setdefault((r["suite"], r["id"]), r["tops"])
    return out


def unit_for(vmax, most):
    for u in UNITS_MS:
        if vmax / u <= most: return u
    die(f"no square unit puts {vmax} ms in {most} squares")


ms = lambda x: f"{x:,.1f} ms" if round(x, 1) < 1000 else f"{x:,.0f} ms"


# ---- the bodies ----------------------------------------------------------------------------------------------------
def body(bodies, dirn, suite, rid):
    p = Path(bodies) / dirn / f"{suite}-{rid}.json"
    if not p.exists(): return None
    b = json.loads(p.read_text())
    if not isinstance(b, dict) or not isinstance(b.get("answers"), dict): die(f"{p}: not a SystemOne body (no answers)")
    if b.get("fixture"): FIXTURE.add(str(p))
    return b, p


def dirs_of(bodies, model, route=None):
    have = {d.name for d in Path(bodies).iterdir() if d.is_dir()} if Path(bodies).is_dir() else set()
    unknown = sorted(have - set(BODY_DIRS))
    if unknown: die(f"bodies/{unknown} are not in BODY_DIRS (whose bodies they hold)")
    return [d for d, (m, rt) in BODY_DIRS.items() if d in have and m == model and (route is None or rt == route)]


def answer(q, a, where):
    """One question's answer drawn as 100 squares: (pick, top count, runner-up count, confidence of 100 or None, the
    pick as the rows write it)."""
    t = q["type"]
    if a.get("type") != t: die(f"{where}: a {a.get('type')} answer to a {t} question")
    if t == "noul":
        py = a["noul"]
        pick = "yes" if py >= 0.5 else "no"
        top, run, conf, row = max(py, 1 - py), min(py, 1 - py), None, pick
    else:
        P = a["probabilities"]
        keys = list(q["criteria"]) if t == "choice" else [str(i) for i in range(len(q["criteria"]))]
        if list(P) != keys: die(f"{where}: probabilities over {list(P)}, the question's options are {keys}")
        best = keys[0]
        for k in keys[1:]:
            if P[k] > P[best]: best = k
        if t == "choice" and a["choice"] != best: die(f"{where}: choice {a['choice']!r}, the largest probability is {best!r}")
        ps = sorted(P.values(), reverse=True)
        top, run = ps[0], ps[1]
        pick = best if t == "choice" else q["criteria"][int(best)]
        row, conf = best, round(100 * a["confidence"])
    nt = round(100 * top)
    nr = min(round(100 * run), 100 - nt)
    return {"pick": pick, "top": nt, "run": nr, "conf": conf, "row": row, "pct": f"{nt}%"}


# ---- Part B --------------------------------------------------------------------------------------------------------
def suites(src):
    """{suite: {id: (line, request)}} from the suite files' lines (src: {"en": lines, "ko": lines})."""
    out = {}
    for name, lines in src.items():
        out[name] = {}
        for i, l in enumerate(lines):
            if l.strip(): r = json.loads(l); out[name][r["id"]] = (i + 1, r)
    return out


def question_text(req, qid, size):
    """The words a hard question is read by: its instructions, or, when they only point at a line of the state
    ("문제 2의 정답은?"), that line."""
    ins = req["questions"][qid]["instructions"]
    for line in req["state"].split("\n"):
        head = line.split(":", 1)[0].strip()
        if ":" in line and head and ins.startswith(head) and len(ins.split()) <= 4: return wrap(line.strip(), size)
    return wrap(ins, size)


def part_b(rows_dir, bodies_dir, suite_src, hd, copy, inputs, P):
    """Part B's block, strings, sources and shots. hd: make_data.py's hard() (None while the hard rows are empty); P the
    beat period (the long race's finish lands on the first beat after its slowest lane)."""
    rows, fixture = load_rows(rows_dir)
    S = suites(suite_src)
    C, cites, b = dict(FIXED_B), {k: ["label"] for k in FIXED_B}, {"fixture": fixture}
    rsrc = f"rows {Path(rows_dir).name}"
    # the requests: the Qwen3.6 /v1/systemone bodies, their picks held to the jump arm's rows
    rq_dirs = dirs_of(bodies_dir, *REQ_BODY)
    if not rq_dirs: die(f"no bodies dir holds {REQ_BODY} (BODY_DIRS)")
    jt = firsts(of(rows, *REQ_ARM))
    b["req"] = []
    C["rq_body"] = "answer + probabilities"        # the footer beside POST /v1/systemone: what its body holds
    cites["rq_body"] = [f"bodies {rq_dirs[0]}/ (answers: the pick, each option's probability)",
                        "answer.rs:3 (the softmax runs over the options)"]
    nreq = int((inputs.get("b") or {}).get("requests", 2))     # inputs.json b.requests: the first n shown
    b["long_mode"] = (inputs.get("b") or {}).get("long", "off")
    if b["long_mode"] not in LONG_MODES: die(f"b.long {b['long_mode']!r} is not one of {LONG_MODES}")
    if not 1 <= nreq <= len(REQUESTS): die(f"b.requests {nreq} is not 1..{len(REQUESTS)}")
    for i, (suite, rid) in enumerate(REQUESTS[:nreq]):
        if rid == "guard-04": die("guard-04 is never shown")
        if rid not in S[suite]: die(f"no request {suite}/{rid} in the {suite} suite")
        line, req = S[suite][rid]
        got = body(bodies_dir, rq_dirs[0], suite, rid)
        if not got: die(f"no body bodies/{rq_dirs[0]}/{suite}-{rid}.json")
        bd, bp = got
        state = req["state"] if isinstance(req["state"], str) else json.dumps(req["state"], ensure_ascii=False)
        size = REQ_SIZE
        lines = wrap(state, size)
        while len(lines) > REQ_LINES and size > REQ_MIN: size -= 1; lines = wrap(state, size)
        if len(lines) > REQ_LINES: die(f"{suite}/{rid}: {len(lines)} lines at {size} px")
        qs = []
        for qid, q in req["questions"].items():
            if qid not in bd["answers"]: die(f"{bp}: no answer to {qid}")
            a = answer(q, bd["answers"][qid], f"{bp} {qid}")
            top = jt.get((suite, rid), {}).get(qid)
            if top is None: die(f"the {REQ_ARM} rows have no answer to {suite}/{rid} {qid}")
            if top != a["row"]: die(f"{suite}/{rid} {qid}: the body picks {a['row']!r}, the {REQ_ARM[1]} rows {top!r}")
            qs.append({"q": qid, "type": q["type"], **a})
        k = f"b_r{i}"
        C.update({f"{k}_id": f"{suite}/{rid}", f"{k}_txt": lines, f"{k}_q": [x["q"] for x in qs],
                  f"{k}_pk": [x["pick"] for x in qs], f"{k}_pc": [x["pct"] for x in qs]})
        # no confidence line: the body's percentages are shares among the options, not a confidence (Addition 8)
        cites[f"{k}_id"] = cites[f"{k}_txt"] = cites[f"{k}_q"] = [f"{SUITE_FILE[suite]}:{line} ({rid})"]
        cites[f"{k}_pk"] = cites[f"{k}_pc"] = [f"body {Path(bp).parent.name}/{Path(bp).name}", f"{rsrc} ({REQ_ARM[1]} tops agree)"]
        b["req"].append({"key": k, "suite": suite, "id": rid, "size": size, "face": face_of(state),
                         "qs": [{x: y for x, y in q.items() if x not in ("row",)} for q in qs],
                         "body": f"{Path(bp).parent.name}/{Path(bp).name}"})
    # the answers kept: schemajump against plain structured output, a request's first counted round each
    j, st = firsts(of(rows, "Qwen3.6-35B-A3B", "jump")), firsts(of(rows, "Qwen3.6-35B-A3B", "step"))
    if not j or set(j) != set(st): die(f"the jump and step arms answered {len(j)} and {len(st)} requests, not the same set")
    same = [j[k] == st[k] for k in sorted(j)]
    C["b_sa_n"] = f"{sum(same)}/{len(same)}"; cites["b_sa_n"] = [f"{rsrc} (jump tops vs step tops, first counted round)"]
    b["same"] = {"same": sum(same), "of": len(same), "marks": same}
    # the timed requests: short p50 per arm, the two long requests split into prompt reading and the rest
    arms_t = [("clef", "Clef-Flash", "A"), ("q_jump", "Qwen3.6-35B-A3B", "jump"), ("q_step_m", "Qwen3.6-35B-A3B", "step")]
    sh = []
    for key, model, arm in arms_t:
        R = of(rows, model, arm, bucket="short")
        sh.append({"key": key, "p50": med((r["wall_ms"] for r in R), f"{model} {arm} short"), "n": len(R)})
    shorts = {(r["suite"], r["id"]): r["prompt_n"] for r in of(rows, "Clef-Flash", "A", bucket="short")}
    smax = max(shorts.values())
    if smax >= 1000: die(f"a short request has {smax} prompt tokens")
    u = unit_for(max(x["p50"] for x in sh), 15)
    for x in sh: x["sq"] = max(1, round(x["p50"] / u))
    C.update({"b_sh_sub": f"UNDER {smax // 1000 * 1000 + 1000:,} TOKENS",
              "b_sh_v": [ms(x["p50"]) for x in sh], "b_foot": f"p50 · one at a time · {copy['card']}"})
    cites["b_sh_sub"] = cites["b_sh_v"] = cites["b_foot"] = [rsrc]
    b["short"] = {"unit_ms": u, "rows": sh}
    longs = sorted({r["id"] for r in of(rows, "Clef-Flash", "A", bucket="long")},
                   key=lambda i: min(r["prompt_n"] for r in of(rows, "Clef-Flash", "A", id=i)))
    if len(longs) != 2: die(f"{len(longs)} long requests, not 2")
    lg, gap_p, gap_all = [], 0.0, 0.0
    for rid in longs:
        lanes = []
        for key, model, arm in arms_t[:2]:
            R = of(rows, model, arm, id=rid)
            if any(r.get("prompt_ms") is None for r in R): die(f"a long row of {model} {arm} {rid} has no prompt_ms")
            ns = {r["prompt_n"] for r in R}
            if len(ns) != 1: die(f"{model} {arm} {rid}: prompt_n {sorted(ns)}")
            wall = med((r["wall_ms"] for r in R), f"{model} {arm} {rid}")
            pr = med((r["prompt_ms"] for r in R), f"{model} {arm} {rid}")
            lanes.append({"key": key, "wall": wall, "prompt": pr, "rest": med((r["wall_ms"] - r["prompt_ms"] for r in R), rid),
                          "tokens": ns.pop(), "n": len(R)})
        gap_p += lanes[0]["prompt"] - lanes[1]["prompt"]
        gap_all += lanes[0]["wall"] - lanes[1]["wall"]
        lg.append({"id": rid, "lanes": lanes, "ratio": lanes[0]["wall"] / lanes[1]["wall"]})
    share = gap_p / gap_all if gap_all > 0 else 0.0
    if share >= 0.9: why = "almost all of it is prompt reading"
    elif share >= 0.5: why = "most of it is prompt reading"
    else: die(f"the long gap is {share:.0%} prompt reading: the long shot's line does not hold")
    u = unit_for(max(l["wall"] for x in lg for l in x["lanes"]), 24)
    for x in lg:
        for l in x["lanes"]:
            l["sq"] = max(1, round(l["wall"] / u)); l["sq_p"] = min(l["sq"], round(l["prompt"] / u))
    names = {"clef": copy["clef"], "q_jump": copy["q_jump"]}
    for i, x in enumerate(lg):
        C[f"b_lg{i}_n"] = [f"{names[l['key']]} · {l['tokens']:,} tokens" for l in x["lanes"]]
        C[f"b_lg{i}_r"] = f"{x['ratio']:.1f}× faster"
        cites[f"b_lg{i}_n"] = [f"{rsrc} (prompt_n: each model's own tokenizer)"]
        cites[f"b_lg{i}_r"] = [f"{rsrc} (p50 walls of {x['id']})"]
    C["b_lg_why"] = why; cites["b_lg_why"] = [f"{rsrc} (the gap's share in prompt_ms: {share:.1%})"]
    C["b_sh_long"] = "long prompts: the gap is " + ("almost all prompt reading" if share >= 0.9 else "mostly prompt reading")
    cites["b_sh_long"] = cites["b_lg_why"]
    b["long"] = {"unit_ms": u, "reqs": lg, "race_s": max(l["wall"] for x in lg for l in x["lanes"]) / 1000, "share": share}
    # the hard suite: correct/N per head model, the examples as each model's pick and its mark, V4.1-Flash's two arms
    b["hard"] = None
    if hd:
        A = {(a["model"], a["arm"]): a for a in hd["arms"]}
        head = [dict(A[(m, arm)], name_key=k, short_key=sk) for m, k, sk, arm in HARD_HEAD if (m, arm) in A]
        if len(head) >= 2:
            best = max(a["correct"] for a in head)
            shown = sorted(head, key=lambda a: -a["correct"])       # the rulers most correct first
            C["b_hd_c"] = [f"{a['correct']}/{a['n']}" for a in shown]
            C["b_hd_n"] = f"{hd['n']} questions we wrote, our labels"
            src_h = f"hard rows {hd['rows']} scored against {hd['gold']}" + (" (FIXTURE)" if hd["fixture"] else "")
            for k in ("b_hd_c", "b_hd_n"): cites[k] = [src_h]
            hs = suites({"hard": suite_src["hard"]})["hard"]
            gold = {g["id"]: g["gold"] for g in (json.loads(l) for l in suite_src["hard_gold"] if l.strip())}
            qs = [(i, q) for i in gold for q in gold[i]]
            ok = lambda a, i, q: a["tops"].get(i, {}).get(q) == gold[i][q]
            differ = lambda i, q: len({a["tops"].get(i, {}).get(q) for a in head}) > 1
            tiers = [("last only right", lambda i, q: ok(head[-1], i, q) and not any(ok(a, i, q) for a in head[:-1])),
                     ("first right", lambda i, q: ok(head[0], i, q) and not all(ok(a, i, q) for a in head[1:])),
                     ("first misses", lambda i, q: not ok(head[0], i, q) and any(ok(a, i, q) for a in head[1:])),
                     ("differ", differ), ("all right", lambda i, q: all(ok(a, i, q) for a in head))]
            nex = int((inputs.get("b") or {}).get("examples", 3))   # inputs.json b.examples: 0..EX_MAX
            if not 0 <= nex <= EX_MAX: die(f"b.examples {nex} is not 0..{EX_MAX}")
            def cost(x):      # the reading rule on the question's text: 4 words a second, a second a number
                ws = " ".join(question_text(hs[x[0]][1], x[1], CAP_SIZE)).split()
                nn = sum(bool(re.fullmatch(r"[\d.,:%×]*\d[\d.,:%×]*", w.strip("?.,()"))) for w in ws)
                return (len(ws) - nn) / 4 + nn
            roots = [bodies_dir] + [Path(v) if Path(v).is_absolute() else HERE / v
                                    for v in ((inputs.get("hard") or {}).get("bodies") or [])]   # hard.bodies: more sittings'
            def body_of(model, rid):    # a model's first body of the request over the roots (systemone ones first)
                for r in roots:
                    for d in dirs_of(r, model):
                        g = body(r, d, "hard", rid)
                        if g: return g
                die(f"no body of {model} for hard/{rid} under {[str(r) for r in roots]}")
            def bodies_of(rid):     # each head model's body of the request
                return [body_of(a["model"], rid) for a in head]
            def agrees(x):          # an example's bodies pick what the scored rows picked, for every model
                rid, qid = x
                q = hs[rid][1]["questions"][qid]
                return all(answer(q, bd["answers"][qid], f"{bp} {qid}")["row"] == a["tops"][rid][qid]
                           for a, (bd, bp) in zip(head, bodies_of(rid)))
            order = [x for x in sorted(dict.fromkeys(x for x in HX_PREFER + qs if x in qs), key=cost) if agrees(x)]
            ex = []      # (rid, qid, kind)
            for kind, w in tiers[:3]:        # one each way first: the smallest model right and another wrong, then
                x = next((x for x in order if w(*x) and len(ex) < nex), None)       # the other way round
                if x: ex.append((*x, kind))
            for kind, w in tiers:
                for once in (True, False):
                    for x in order:
                        if len(ex) == nex: break
                        if w(*x) and x not in [e[:2] for e in ex] and not (once and x[0] in [e[0] for e in ex]):
                            ex.append((*x, kind))
            b["hard"] = {"head": [{"model": a["model"], "key": a["name_key"], "short": a["short_key"], "correct": a["correct"],
                                   "n": a["n"], "top": a["correct"] == best} for a in shown], "ex": []}
            for e, (rid, qid, kind) in enumerate(ex):
                line, req = hs[rid]
                q = req["questions"][qid]
                cols = []
                for a in head:
                    bd, bp = body_of(a["model"], rid)
                    x = answer(q, bd["answers"][qid], f"{bp} {qid}")
                    if x["row"] != a["tops"][rid][qid]: die(f"{bp} {qid}: the body picks {x['row']!r}, the scored rows {a['tops'][rid][qid]!r}")
                    cols.append({"pick": x["pick"], "ok": x["row"] == gold[rid][qid],      # the pick and its mark only:
                                 "body": f"{Path(bp).parent.name}/{Path(bp).name}"})   # no shares across models
                k = f"b_hx{e}"
                C.update({f"{k}_id": f"hard/{rid}", f"{k}_q": question_text(req, qid, CAP_SIZE),
                          f"{k}_nm": [copy[a["short_key"]] for a in head], f"{k}_pk": [c["pick"] for c in cols],
                          f"{k}_gold": f"our label: {gold[rid][qid]}"})
                cites[f"{k}_id"] = cites[f"{k}_q"] = [f"{hd['suite']}:{line} ({rid} {qid})"]
                cites[f"{k}_gold"] = [f"{hd['gold']} ({rid} {qid}: our label)"]
                cites[f"{k}_pk"] = [f"bodies {[c['body'] for c in cols]}", src_h]
                cites[f"{k}_nm"] = ["the models' short names (make_data.py CITED)"]
                b["hard"]["ex"].append({"key": k, "id": rid, "q": qid, "kind": kind,
                                        "cols": cols, "face": face_of(" ".join(C[f"{k}_q"]))})
        jv, sv = A.get(("DeepSeek-V4.1-Flash", "jump")), A.get(("DeepSeek-V4.1-Flash", "step"))
        if jv and sv:
            cards = (inputs.get("hard") or {}).get("v41_cards") or ""
            if not cards: die("hard.v41_cards is empty: the V4.1-Flash shot's foot names its cards")
            same41 = sum(jv["tops"][i] == sv["tops"][i] for i in jv["tops"])
            # V4.1-Flash's value here is what it knows, not its speed: no time on screen, its conditions in the footer
            C["b_hd_v41c"] = [f"{copy['v41_s']}: {cards}"] if len(f"{copy['v41_s']}: {cards}") <= 36 else [f"{copy['v41_s']}: {cards.split(' · ')[-1]}", f"on {cards.split(' · ')[0]}"]
            cites["b_hd_v41c"] = ["inputs.json hard.v41_cards", f"hard rows {hd['rows']} (V4.1-Flash tops {same41}/{len(jv['tops'])} the same on both arms)"]
            b["v41"] = {"same": same41}
    b["fixture"] = fixture or bool(FIXTURE)
    b["beats"] = {"grid": GRID_AT, "ans": ANS_AT, "go": GO_BEAT, "v41": HD_V41_AT, "finish": GO_BEAT + math.ceil(b["long"]["race_s"] / P + 1e-9)}
    b["short"]["requests"] = len(shorts)
    return {"b": b, "copy": C, "cites": cites, "shots": shots(b, copy), "anchor_l": anchor_l(b)}


def shots(b, copy):
    """Part B's shots in make_data.py's form: (id, [(group, landing beat, how, [copy keys])], carry)."""
    S = []
    for i, r in enumerate(b["req"]):
        k = r["key"]
        carry = ["q_jump", "rq_post", "rq_body"] if i else []
        S.append((f"req{i}", [("text", 0, "cut", ["q_jump", "rq_post", "rq_body", f"{k}_txt"]),
                              ("grids", ANS_AT, "cut", [f"{k}_q", f"{k}_pk", f"{k}_pc"])],
                  carry))
    S.append(("bsame", [("same", 0, "cut", ["b_sa_head", "b_sa_n", "b_sa_t"])], []))
    if b["hard"]:
        v41 = ["b_hd_v41c"] if b.get("v41") else []
        S.append(("bhard", [("count", 0, "cut", ["b_hd_head"] + [h["key"] for h in b["hard"]["head"]] + ["b_hd_c"] + v41 + ["b_hd_n"])], []))
        for e, x in enumerate(b["hard"]["ex"]):
            k = x["key"]     # the label and the models' names stand where the example before left them
            S.append((f"bhx{e}", [("q", 0, "cut", ["b_hd_ex", f"{k}_q", f"{k}_gold", f"{k}_nm"]), ("picks", ANS_AT, "cut", [f"{k}_pk"])],
                      ["b_hd_ex", f"{k}_nm"] if e else []))
    line = ["b_sh_long"] if b["long_mode"] == "line" else []
    S.append(("bshort", [("bars", 0, "cut", ["b_sh_head", "b_sh_sub", "clef", "q_jump", "q_step_m", "b_sh_v"] + line + ["b_foot", "foot_rt"])], []))
    if b["long_mode"] == "shot":
        S.append(("blong", [("setup", 0, "cut", ["b_lg_head", "b_lg0_n", "b_lg1_n", "b_lg_leg_p", "b_lg_leg_r", "b_foot", "foot_rt"]),
                            ("finish", b["beats"]["finish"], "cut", ["b_lg0_r", "b_lg1_r", "b_lg_why"])], ["b_foot", "foot_rt"]))
    return S


def anchor_l(b):
    """make_data.py's L anchor: the long race's GO when LONG is a shot, else SHORT's cut; the shots before take the
    beats a whole bar leaves over."""
    before = [f"bhx{e}" for e in range(len((b["hard"] or {}).get("ex", [])))][::-1] + ["bhard"] + \
             [f"req{i}" for i in range(len(b["req"]))][::-1] + ["bsame"]     # SAME ANSWERS last: it stays <= 3 s
    if b["long_mode"] == "shot": return ("L", "blong", GO_BEAT, ["bshort"] + before)
    return ("L", "bshort", 0, before)


# ---- the preview: Part B alone on its own clock --------------------------------------------------------------------
def preview(out, rows_dir, bodies_dir, hard_rows):
    import make_data as md
    md.QTY = QTY            # a percentage is a number (make_data.py's QTY reads "96%" as a word)
    beats = json.loads((HERE / "beats.json").read_text())[md.MUSIC_ID]
    P = beats["period_s"]
    src, _ = md.sources()
    copy, cites = md.cite(src)
    copy.update(md.FIXED)
    for k in md.FIXED: cites[k] = ["label"]
    copy["version"] = md.INPUTS["version"]
    route = md.INPUTS.get("route_measured", "response_format")      # make_data.py main()'s rule
    copy["foot_rt"] = {"response_format": "chat models via response_format", "systemone": "chat models via POST /v1/systemone"}[route]
    hd = None
    if hard_rows:
        clef = HERE / "../../../../bloomery-sjcmp/tools/ref/clef"     # the suite and its gold as committed
        md.INPUTS["hard"] = {"rows": str(hard_rows), "suite": str((clef / "suite-hard.jsonl").resolve()),
                             "gold": str((clef / "suite-hard.gold.jsonl").resolve()), "v41_cards": "RTX A6000 + RTX 3090"}
        hd = md.hard()
    H = md.INPUTS["hard"]
    suite_src = {"en": src_lines(md, "tools/ref/clef/suite.jsonl"), "ko": src["suite"],
                 "hard": Path(H["suite"]).read_text().split("\n") if hd else [],
                 "hard_gold": Path(H["gold"]).read_text().split("\n") if hd else []}
    pb = part_b(rows_dir, bodies_dir, suite_src, hd, copy, md.INPUTS, P)
    copy.update(pb["copy"]); cites.update(pb["cites"])
    spec = pb["shots"] + [("bend", [("lockup", 2, "cut", ["name", "version", "url"])], [])]
    L = md.lengths(spec, copy, P, pb["b"]["long"]["race_s"], 0)
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
    events = [[f"cut {S['id']}", S["t0"], None] for S in segs] + events_b(segs, on)
    data = {"film": "release-036", "timeline": {"T": T, "period": P, "lead": md.LEAD, "segments": segs, "fade_out_s": round(2 * P, 6),
                                                "nbeats": b0, "beats": [round(k * P, 4) for k in range(b0 + 1)],
                                                "events": events, "ticks": sorted(e[1] for e in events if e[0].startswith("tick"))},
            "copy": copy, "sources": cites, "b": pb["b"], "placeholder": False, "fixture": False, "draft_body": False}
    Path(out).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    print(f"{out}: T {T} s, {b0} beats of {P} s")
    print("shot     group    beats words nums  read  holds")
    for S in segs:
        for g in S["groups"]: print(f"{S['id']:8} {g['name']:8} {S['len']:5} {g['words']:5} {g['numbers']:4} {g['read_s']:5.2f} {S['t1'] - g['still']:6.2f}")


def events_b(segs, on):
    """The picture's switches Part B adds to the timeline's events: each grids group's landing (a slam on its beat),
    and the 16ths its grids count up on after the first (ticks, which render.py's sync scan takes as grid)."""
    ev = []
    for S in segs:
        for g in S["groups"]:
            if g["at"]: ev.append([f"slam {S['id']}.{g['name']}", round(on(S["b0"] + g["at"]), 6), None])
        if any(g["name"] == "grids" for g in S["groups"]):
            ev += [[f"tick {S['id']}.count.{j}", round(on(S["b0"] + GRID_AT + j / 4), 6), None] for j in range(1, 4)]
            ev.append([f"slam {S['id']}.count", round(on(S["b0"] + GRID_AT), 6), None])
    return ev


def src_lines(md, path):
    return subprocess.run(["git", "-C", str(md.BLOOMERY), "show", f"{md.README_REV}:{path}"], capture_output=True, text=True,
                          check=True).stdout.split("\n")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] != "--preview" or len(a) < 2: die("usage: make_data_b.py --preview OUT.json [--rows DIR] [--bodies DIR] [--hard-rows DIR]")
    opt = dict(zip(a[2::2], a[3::2]))
    preview(a[1], opt.get("--rows", HERE / "probe/bfx/rows"), opt.get("--bodies", HERE / "probe/bfx/bodies"),
            opt.get("--hard-rows", HERE / "probe/bfx/hard/rows"))
