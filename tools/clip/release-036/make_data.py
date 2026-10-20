"""Build data.json for the 0.3.6 film (film.html): every number it shows (read from the sitting's rows), every string
it draws (each checked against its source line, or computed from the rows) and every time it switches on, from the
track's measured beat grid.

  python3 make_data.py
  SJ_ROWS=<dir>     the sitting's rows: <dir>/window1/rows.json (Clef-Flash + the jump arm) and window2/rows.json
                    (Clef-Flash + the step arm), as tools/ref/sj-vs-clef.sh writes them (default inputs.json's rows)
  MUSIC_ID=<id>     another track: a row of beats.json and of TRACKS, which sets the arrangement (default
                    instrument-s1004, music/<id>.mp3)
  BLOOMERY=<tree>   the bloomery tree whose README.md and suite the strings quote (README_REV, default inputs.json's)
  SJ_RUNNER=<file>  tools/ref/sj-vs-clef.sh (default: the bloomery tree's, else the rel036 or sjcmp worktree's)

inputs.json holds what the rows do not: the sitting's label, the release version, calls_sum (which of a row's
`calls`, the server's timings.constrained integers, sum to its engine calls: engine_calls), the token pieces file
(tokens.py), an optional saved body of the route (answer_body, held to the decide seat's keys and order; body_hide
names keys never drawn; left empty the answer shot shows the decided JSON and the film stamps it DRAFT), the route
the timed requests went through (route_measured: response_format, the footers say so and the request shot says the
same program serves /v1/systemone, sourced by route_cite or stamped PLACEHOLDER; or systemone), the commit of
sjcmp.py and sj-vs-clef.sh the strings quote (sjcmp_rev), the hard suite (hard: its rows dir, suite and gold files
and DeepSeek-V4.1-Flash's cards; its two shots are left out while rows is empty), the Solar-Open2 slot (left out
while decode is empty), the one "and ..." line (left out while empty) and an optional verdict override.

The numbers. Short = the 13 requests under 1,000 prompt tokens, long = the two long requests (the rows' `bucket`).
Every wall is the client's (POST to the last byte), a dropped first post is not counted, p50 is the median of the
counted rows: Clef-Flash's over both windows (it is the anchor of both), the jump arm's from window 1, the step arm's
from window 2. The long lanes split at the p50 of prompt_ms and the p50 of the wall less prompt_ms. The step delta is
tools/ref/sj-vs-clef.sh's ab row. "SAME" is the jump arm's tops against the step arm's, a request's first counted
round each; "match" is the jump arm's decisions against the official BF16 rows (sources/reference-tops.json). The
verdict is "faster" when the jump arm's short p50 is under Clef-Flash's, else "close". The engine calls per request
are the rows' own (`calls`, summed over call_keys) when every counted Qwen row carries them; else sjcmp.py's
prediction from tokens-qwen36.json, and data.json says placeholder (film.html stamps every frame PLACEHOLDER). The
hard suite: per model and arm, a request's first counted round against the gold, correct of every gold question
(hard()); DeepSeek-V4.1-Flash's schemajump against its plain structured output by wall p50. Every claim line of the
two hard shots comes from those counts (the top model, faster or slower, same answers or how many), and rows whose
file says "fixture" stamp every frame FIXTURE (probe/hard-fixture.py writes such rows).

Timing: a shot lasts its beats. Each group of strings lands on its beats and holds still for its read time (4 words a
second plus 1 s a number, at least 2.5 s) from its last element's settle, before the cut; a shot's groups together fit
between its first settle and the cut. A string a shot carries over unmoved from the shot before is not read again.
The track is arranged to the shots (TRACKS): the jump's first call lands on the hit after the track's first rest,
the long race's GO on the hit after the second, the END cut on the hit after the third; between two hits the track
plays its own bars plus whole bars spliced in at downbeats, as many as the shots there need (splice.py cuts the wav).
"""
import json, math, os, re, statistics, subprocess, sys
from pathlib import Path

HERE = Path(__file__).parent
FPS = 60
LEAD = 0.5 / FPS          # every switch is computed half a frame before its beat: the picture leads, never lags
INPUTS = json.loads(Path(os.environ.get("INPUTS", HERE / "inputs.json")).read_text())
BLOOMERY = Path(os.environ.get("BLOOMERY", HERE / "../../../../bloomery")).resolve()
README_REV = os.environ.get("README_REV", INPUTS["readme_rev"])
REQ_SUITE, REQ_ID = INPUTS["request"].split("/")       # Part A's request, "<suite>/<id>" (en: suite.jsonl, ko: suite-ko.jsonl)
SUITE_DOC = {"en": "suite_en", "ko": "suite"}
SJ_ROWS = Path(os.environ.get("SJ_ROWS", HERE / INPUTS["rows"]))
MUSIC_ID = os.environ.get("MUSIC_ID", "instrument-s1004")
# track -> its arrangement, in track beats (bar_offset opens a bar). The film plays the track from `open` up to its
# first rest, through each rest to the hit after it, and on to `end`; between two rests it plays the groove the
# track has there plus whole bars spliced in (`pool`: bar starts, read cyclically and taken so the spliced group ends
# on the pool's last bar, the bar that leads into a rest in the track), so each hit lands where its shot needs it.
# The hits (ANCHORS): P the prompt's flood (the REST shot plays the rest before it), L the long race's GO, E the END
# cut; a rest is (its first beat, the hit), and a hit with no rest before it is (hit, hit).
# instrument-s1004 (beats.json; RMS a beat over the whole mp3, 2026-10-20): no silent bar; intro to 30 (-22..-29 dB),
# the drop on 31, the groove to 96 (-16..-20), a breakdown 97-126 (-19..-27), its strongest hit on 127 (-13), the
# groove to 207 with a hit on 191 (-14), the tail 208-212 (-24 to -59). P is the breakdown's last bar and the hit on
# 127, L the hit on 191, E the bar on 203 (the END needs 8 beats; the tail decays by itself). The pool is the steady
# groove from 147 (131-146 build up from the hit at -22..-25 dB, so a wrap from 203 into 131 stepped down 2.6 dB where
# the track steps up 2.2) without the bars of the L hit (187, 191), so a spliced-in bar never plays that hit again.
TRACKS = {
    "instrument-s1004": {"rests": {"P": (123, 127), "L": (187, 191), "E": (203, 203)}, "end": 213, "fade_out_beats": 2,
                         "pool": [b for b in range(147, 203, 4) if b not in (187, 191)]},
    "volt-s1007": {"rests": {"P": (55, 63), "L": (71, 79), "E": (103, 111)}, "end": 122, "fade_out_beats": 2,
                   "pool": list(range(15, 55, 4)) + list(range(79, 103, 4))},
}
XFADE_S = 0.015           # the equal-power crossfade at a splice, ending on the downbeat
READ_WPS, READ_NUM_S, READ_MIN_S = 4.0, 1.0, 2.5
SETTLE = {"slam": 0.20, "rise": 0.16, "left": 0.20, "stamp": 0.30, "bulk": 0.20, "pick": 0.30, "piece": 0.12,
          "cut": 0.0, "call": 0.0, "flood": 0.20}
EXIT = {"usage": 2, "rows": 3, "source": 4, "timing": 5, "inputs": 6}


def die(name, msg):
    print(f"make_data.py: refused ({name}): {msg}", file=sys.stderr)
    sys.exit(EXIT[name])


# ---- the rows ------------------------------------------------------------------------------------------------------
def rows_of(window, want_arms):
    p = SJ_ROWS / window / "rows.json"
    if not p.exists(): die("rows", f"no {p} (SJ_ROWS=<dir>)")
    body = json.loads(p.read_text())
    arms = body.get("arms")
    if sorted(arms) != sorted(want_arms): die("rows", f"{p}: arms {arms}, expected {want_arms}")
    rows = [r for r in body["rows"] if not r.get("dropped")]
    for r in rows:
        if r["bucket"] not in ("short", "long"): die("rows", f"{p}: bucket {r['bucket']!r}")
    return rows


def p50(rows, arm, bucket):
    w = [r["wall_ms"] for r in rows if r["arm"] == arm and r["bucket"] == bucket]
    if not w: die("rows", f"no counted {bucket} rows of arm {arm}")
    return statistics.median(w), len(w)


def firsts(rows, arm):
    out = {}
    for r in sorted((r for r in rows if r["arm"] == arm), key=lambda r: r["round"]):
        out.setdefault((r["suite"], r["id"]), r["tops"])
    return out


def measure():
    w1, w2 = rows_of("window1", ["A", "jump"]), rows_of("window2", ["A", "step"])
    clef = [r for r in w1 + w2 if r["arm"] == "A"]
    if {r["kind"] for r in clef} != {"clef"}: die("rows", "arm A is not the Clef arm in both windows")
    m = {}
    m["clef_short"], m["clef_short_n"] = p50(clef, "A", "short")
    m["clef_long"], m["clef_long_n"] = p50(clef, "A", "long")
    m["jump_short"], m["jump_short_n"] = p50(w1, "jump", "short")
    m["jump_long"], m["jump_long_n"] = p50(w1, "jump", "long")
    m["step_short"], m["step_short_n"] = p50(w2, "step", "short")
    # the ab row of sj-vs-clef.sh: per round, the short p50 of each arm; the mean of (jump - step) / step
    rounds = sorted({r["round"] for r in w1 if r["arm"] == "jump"} & {r["round"] for r in w2 if r["arm"] == "step"})
    diffs = []
    for k in rounds:
        a = [r["wall_ms"] for r in w1 if r["arm"] == "jump" and r["round"] == k and r["bucket"] == "short"]
        b = [r["wall_ms"] for r in w2 if r["arm"] == "step" and r["round"] == k and r["bucket"] == "short"]
        if a and b: diffs.append(100 * (statistics.median(a) - statistics.median(b)) / statistics.median(b))
    m["step_delta_pct"], m["rounds"] = statistics.mean(diffs), len(diffs)
    shorts = sorted({(r["id"], r["prompt_n"]) for r in clef if r["bucket"] == "short"})
    longs = sorted({(r["id"], r["prompt_n"]) for r in clef if r["bucket"] == "long"}, key=lambda x: x[1])
    m["short_requests"] = len({i for i, _ in shorts})
    m["short_max_prompt"] = max(n for _, n in shorts)
    m["long_prompts"] = [n for _, n in longs]
    if m["short_max_prompt"] >= 1000 or len(longs) != 2: die("rows", f"buckets: short up to {m['short_max_prompt']}, long {longs}")
    jump, step = firsts(w1, "jump"), firsts(w2, "step")
    if set(jump) != set(step): die("rows", "the jump and step arms answered different requests")
    m["same"], m["same_of"] = sum(jump[k] == step[k] for k in jump), len(jump)
    refs = json.loads((HERE / "sources/reference-tops.json").read_text())
    n = ok = 0
    for (suite, rid), tops in jump.items():
        if suite == "hard": continue        # the hard suite is scored on its gold (hard()), not the official rows
        ref = refs.get(f"{suite}/{rid}")
        if ref is None: die("rows", f"no official row for {suite}/{rid}")
        for q, t in tops.items(): n += 1; ok += t == ref[q]
    m["match"], m["match_of"] = ok, n
    m["jump_tops"] = jump
    # the long split: per arm, the p50 of the prompt pass (the server's prompt_ms) and of the rest of the wall
    for arm, rows, key in (("A", clef, "clef"), ("jump", w1, "jump")):
        L = [r for r in rows if r["arm"] == arm and r["bucket"] == "long"]
        if any(r.get("prompt_ms") is None for r in L): die("rows", f"a long row of arm {arm} has no prompt_ms")
        m[f"{key}_long_prompt"] = statistics.median(r["prompt_ms"] for r in L)
        m[f"{key}_long_rest"] = statistics.median(r["wall_ms"] - r["prompt_ms"] for r in L)
    m["calls"] = calls(w1, w2)
    # the request the first half draws: its prompt (one call) as both Qwen arms took it, and the jump arm's p50 of it
    rid = REQ_ID
    pj = [r for r in w1 if r["arm"] == "jump" and r["id"] == rid]
    ps = [r for r in w2 if r["arm"] == "step" and r["id"] == rid]
    if not pj or not ps: die("rows", f"no counted rows of {rid} in both Qwen arms")
    ns = {r["prompt_n"] for r in pj + ps}
    if len(ns) != 1: die("rows", f"{rid}: prompt_n {sorted(ns)} across the Qwen arms")
    if any(r.get("prompt_ms") is None for r in pj): die("rows", f"a jump row of {rid} has no prompt_ms")
    m["req_prompt_n"] = ns.pop()
    m["req_prompt_ms"], m["req_prompt_ms_n"] = statistics.median(r["prompt_ms"] for r in pj), len(pj)
    return m


CALLS_KEYS = ("next_calls", "prefill_calls", "next_after_calls", "lead", "spans", "tail")   # timings.constrained


def engine_calls(row):
    """A row's engine calls after the prompt: the sum of the keys of its `calls` (the server's timings.constrained
    integers) that inputs.json's calls_sum names, default next_calls + prefill_calls (the rule the lead confirms).
    None when the row carries no counts; a key it lacks, or one the server does not write, is a named error."""
    keys = INPUTS.get("calls_sum") or ["next_calls", "prefill_calls"]
    bad = [k for k in keys if k not in CALLS_KEYS]
    if bad: die("inputs", f"calls_sum names {bad}, not timings.constrained keys {list(CALLS_KEYS)}")
    c = row.get("calls")
    if not c: return None
    miss = [k for k in keys if not isinstance(c.get(k), int)]
    if miss: die("rows", f"{row.get('suite')}/{row.get('id')} {row.get('arm')}: calls has no integer {miss}")
    return sum(c[k] for k in keys)


def calls(w1, w2):
    """The engine calls after the prompt per request: the server's own counts (engine_calls of each row) when every
    counted row of both Qwen arms carries them; else the counts sjcmp.py's program predicts
    (sources/tokens-qwen36.json), and the film says PLACEHOLDER on every frame."""
    keys = INPUTS.get("calls_sum") or ["next_calls", "prefill_calls"]
    tok = json.loads((HERE / INPUTS["tokens"]).read_text())
    per, src = {}, "rows"
    for arm, rows in (("step", w2), ("jump", w1)):
        for r in sorted((r for r in rows if r["arm"] == arm and r["suite"] != "hard"), key=lambda r: r["round"]):
            n = engine_calls(r)
            if n is None: src = "placeholder"; continue
            got = per.setdefault(f"{r['suite']}/{r['id']}", {}).setdefault(arm, n)
            per[f"{r['suite']}/{r['id']}"].setdefault(f"{arm}_calls", r["calls"])
            if got != n: die("rows", f"{r['suite']}/{r['id']} {arm}: {got} calls in one round, {n} in another")
    if src == "placeholder":
        per = {k: {"step": sum(v["step"][x] for x in keys if x in v["step"]), "jump": sum(v["jump"][x] for x in keys if x in v["jump"])}
               for k, v in tok["requests"].items()}
    if len(per) != 15 or any(not {"step", "jump"} <= set(v) for v in per.values()): die("rows", f"call counts for {len(per)} requests")
    order = list(tok["requests"])          # the suites' order
    return {"source": src, "keys": keys, "per": [{"key": k, **per[k]} for k in order],
            "sum_step": sum(per[k]["step"] for k in order), "sum_jump": sum(per[k]["jump"] for k in order),
            "tokens": INPUTS["tokens"], "tokenizer_sha256": tok["tokenizer"]["sha256"]}


# ---- the hard suite ------------------------------------------------------------------------------------------------
# Its models, smallest first (the order the scene draws them), the copy key of each name, and the arms each answers
# through: Clef-Flash its decide seat (arm A), the chat models the schema program (jump); DeepSeek-V4.1-Flash also
# token by token (step: response_format with the jump off), the plain structured output schemajump is set against.
HARD_MODELS = [("Clef-Flash", "clef", "clef", ["A"]), ("Qwen3.6-35B-A3B", "q_model", "q_s", ["jump", "step"]),
               ("DeepSeek-V4.1-Flash", "v41", "v41_s", ["jump", "step"])]
# The sitting runner's arm names (sjcmp), to (model, arm) above.
HARD_ARMS = {"jump": ("Qwen3.6-35B-A3B", "jump"), "step": ("Qwen3.6-35B-A3B", "step"),    # sitting 3's names
             "qwen-jump": ("Qwen3.6-35B-A3B", "jump"), "qwen-step": ("Qwen3.6-35B-A3B", "step"),
             "ds41-jump": ("DeepSeek-V4.1-Flash", "jump"), "ds41-step": ("DeepSeek-V4.1-Flash", "step")}


def lines_of(p):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def hard():
    """The hard suite scored against its gold (inputs.json hard: rows, suite, gold; paths absolute or under this
    directory): per model and arm, the first counted round of each request, correct = its questions whose pick is the
    gold option, n = every gold question; the wall p50 over the arm's counted rows. A row is a sitting row
    (arm, id, round, tops, wall_ms, dropped) plus `model`, one of HARD_MODELS' names. None while hard.rows is empty."""
    H = INPUTS.get("hard") or {}
    if not H.get("rows"): return None
    at = lambda k: Path(H[k]) if Path(H[k]).is_absolute() else HERE / H[k]
    for k in ("suite", "gold"):
        if not H.get(k): die("inputs", f"hard.rows is set and hard.{k} is empty")
        if not at(k).exists(): die("inputs", f"hard.{k}: no {at(k)}")
    suite = {r["id"]: r for r in lines_of(at("suite"))}
    gold = {g["id"]: g["gold"] for g in lines_of(at("gold"))}
    if set(suite) != set(gold): die("source", f"the hard suite's ids and its gold's differ: {sorted(set(suite) ^ set(gold))}")
    for rid, g in gold.items():
        qs = suite[rid]["questions"]
        if set(g) != set(qs): die("source", f"{rid}: gold names {sorted(g)}, the request asks {sorted(qs)}")
        for q, v in g.items():
            opts = list(qs[q]["criteria"]) if qs[q]["type"] == "choice" else ["yes", "no"]
            if v not in opts: die("source", f"{rid}/{q}: gold {v!r} is not one of {opts}")
    n = sum(len(g) for g in gold.values())
    files = sorted(at("rows").glob("**/rows.json"))
    if not files: die("rows", f"no rows.json under {at('rows')}")
    rows, fixture = [], False
    for f in files:
        body = json.loads(f.read_text())
        fixture |= bool(body.get("fixture"))
        rows += [r for r in body["rows"] if not r.get("dropped") and r.get("suite", "hard") == "hard"]   # a sitting's other suites too
    # The sitting's rows carry no model: their arm names it (hard.arm_map overrides the runner's names; a clef-kind
    # row is Clef-Flash's decide seat). A row that already names its model (the fixture) keeps it.
    amap = H.get("arm_map") or HARD_ARMS
    for r in rows:
        if "model" in r: continue
        if r.get("kind") == "clef": r["model"], r["arm"] = "Clef-Flash", "A"
        elif r.get("arm") in amap: r["model"], r["arm"] = amap[r["arm"]]
        else: die("rows", f"hard row arm {r.get('arm')!r} (kind {r.get('kind')!r}) is in neither hard.arm_map nor HARD_ARMS")
    known ={(m, a) for m, _, _, arms in HARD_MODELS for a in arms}
    stray = sorted({(r.get("model"), r.get("arm")) for r in rows} - known, key=str)
    if stray: die("rows", f"hard rows of {stray}, not a model and arm of HARD_MODELS")
    arms = []
    for name, key, short_key, want in HARD_MODELS:
        for arm in want:
            R = [r for r in rows if r["model"] == name and r["arm"] == arm]
            if not R: continue
            first = {}
            for r in sorted(R, key=lambda r: r["round"]): first.setdefault(r["id"], r["tops"])
            if set(first) != set(gold): die("rows", f"hard rows of {name} {arm} answer {len(first)} of the {len(gold)} requests")
            ok = sum(first[i].get(q) == v for i, g in gold.items() for q, v in g.items())
            arms.append({"model": name, "key": key, "short": short_key, "arm": arm, "correct": ok, "n": n,
                         "p50_ms": statistics.median(r["wall_ms"] for r in R), "rows": len(R), "tops": first})
    return {"suite": short(at("suite")), "gold": short(at("gold")), "rows": short(at("rows")), "n": n,
            "requests": len(gold), "fixture": fixture, "arms": arms, "cards": H.get("v41_cards", "")}


# ---- the cited strings ---------------------------------------------------------------------------------------------
def sources():
    try:
        readme = subprocess.run(["git", "-C", str(BLOOMERY), "show", f"{README_REV}:README.md"], capture_output=True,
                                text=True, check=True).stdout.split("\n")
        suite = subprocess.run(["git", "-C", str(BLOOMERY), "show", f"{README_REV}:tools/ref/clef/suite-ko.jsonl"],
                               capture_output=True, text=True, check=True).stdout.split("\n")
        suite_en = subprocess.run(["git", "-C", str(BLOOMERY), "show", f"{README_REV}:tools/ref/clef/suite.jsonl"],
                                  capture_output=True, text=True, check=True).stdout.split("\n")
    except subprocess.CalledProcessError as e:
        die("source", f"git show {README_REV} in {BLOOMERY}: {e.stderr.strip()}")
    runner = next((r for r in [Path(os.environ.get("SJ_RUNNER", BLOOMERY / "tools/ref/sj-vs-clef.sh"))] +
                   [(HERE / f"../../../../{t}/tools/ref/sj-vs-clef.sh").resolve() for t in ("bloomery-rel036", "bloomery-sjcmp")]
                   if r.exists()), None)
    if runner is None: die("source", f"no tools/ref/sj-vs-clef.sh (SJ_RUNNER=<file>)")
    try:
        e2e = subprocess.run(["git", "-C", str(BLOOMERY), "show", f"{README_REV}:tools/ref/clef/e2e.py"], capture_output=True,
                             text=True, check=True).stdout.split("\n")
    except subprocess.CalledProcessError as e:
        die("source", f"git show {README_REV}:tools/ref/clef/e2e.py: {e.stderr.strip()}")
    rev = INPUTS["sjcmp_rev"]          # sjcmp.py at the commit the sitting ran (its tree may be edited since)
    try:
        sjl = subprocess.run(["git", "-C", str(runner.parent), "show", f"{rev}:tools/ref/clef/sjcmp.py"], capture_output=True,
                             text=True, check=True).stdout.split("\n")
    except subprocess.CalledProcessError as e:
        die("source", f"git show {rev}:tools/ref/clef/sjcmp.py in {runner.parent}: {e.stderr.strip()}")
    try:      # the runner at the same commit (its tree is a live worktree)
        rl = subprocess.run(["git", "-C", str(runner.parent), "show", f"{rev}:tools/ref/sj-vs-clef.sh"], capture_output=True,
                            text=True, check=True).stdout.split("\n")
    except subprocess.CalledProcessError as e:
        die("source", f"git show {rev}:tools/ref/sj-vs-clef.sh in {runner.parent}: {e.stderr.strip()}")
    # the model's shape and the prompt call at the README's commit; the step, the jump and the decision row at the
    # commit the sitting ran (genloop.rs is the sjcmp tree's)
    code = {}
    for name, tree, at, path in (("q36", BLOOMERY, README_REV, "crates/gpu-gates/src/q36_fixture.rs"),
                                 ("moe", BLOOMERY, README_REV, "crates/gpu-gates/src/bin/gate_qwen35moe_moe.rs"),
                                 ("seat", BLOOMERY, README_REV, "crates/gpu-gates/src/bin/shared/serve_seats/qwen3.rs"),
                                 ("genloop", runner.parent, rev, "crates/serve/src/genloop.rs")):
        try:
            code[name] = subprocess.run(["git", "-C", str(tree), "show", f"{at}:{path}"], capture_output=True, text=True,
                                        check=True).stdout.split("\n")
        except subprocess.CalledProcessError as e:
            die("source", f"git show {at}:{path} in {tree}: {e.stderr.strip()}")
    return {"README": readme, "suite": suite, "suite_en": suite_en, "runner": rl, "e2e": e2e,
            "sjcmp": sjl, **code}, str(runner)


# key -> (string, [(doc, line, quote)], why): line n of doc must hold quote, and every word of the string (lower case,
# separators dropped) must be a word of its lines, unless why says why not.
CITED = {
    "name":      ("bloomery", [("README", 8, '<h1 align="center">bloomery</h1>')], None),
    "q_model":   ("Qwen3.6-35B-A3B", [("README", 116, "[Qwen3.6-35B-A3B]")], None),
    "card":      ("RTX A6000", [("README", 45, "RTX A6000")], None),
    "clef":      ("Clef-Flash", [("README", 118, "[Clef-Flash]"), ("runner", 2, "Clef-Flash (the decide seat)")], None),
    "claim1":    ("your chat model", [("README", 116, "[Qwen3.6-35B-A3B]"),
                  ("runner", 8, "any model answering a schema the way Clef-Flash does")],
                  "the film's words for a general chat model such as Qwen3.6-35B-A3B (README's qwen3 row)"),
    "claim2":    ("answers decision requests", [("README", 118, "(decision models)"), ("e2e", 239, "/v1/systemone")],
                  "the requests the README's decision models answer, posted to /v1/systemone (e2e.py)"),
    "rq_post":   ("POST /v1/systemone", [("e2e", 239, "/v1/systemone")], "the method and route e2e.py posts a decision request to"),
    "rq_label":  ("a decision model's request", [("README", 118, "(decision models)")], "a request of the decide seat's kind"),
    "st_head":   ("PLAIN STRUCTURED OUTPUT", [("runner", 16, "BLOOMERY_SCHEMAJUMP=off"), ("runner", 21, "`response_format`")],
                  "the step arm (response_format with the jump off, one engine call a token), named so the film says what "
                  "it is compared with; upper case as the film's heads"),
    "jp_head":   ("SCHEMAJUMP", [("runner", 2, "(the schemajump")], "the jump arm's name, upper case as the film's heads"),
    "calls_label": ("engine calls", [("sjcmp", 24, "engine calls are deterministic")], None),
    "rf":        ("response_format: json_schema", [("runner", 21, "`response_format`")],
                  "the request field and its type, as sjcmp.py's chat_body sends it"),
    "req_label": ("a decision request", [("README", 118, "(decision models)")], "a request to a decision model"),
    "q_jump":    ("Qwen3.6 + schemajump", [("runner", 2, "a Qwen3.6 seat (the schemajump")], None),
    "q_step":    ("plain structured output", [("runner", 16, "BLOOMERY_SCHEMAJUMP=off"), ("runner", 21, "`response_format`")],
                  "the step arm: response_format with BLOOMERY_SCHEMAJUMP=off, one engine call a token"),
    "q_step_m":  ("Qwen3.6 + plain structured output", [("runner", 16, "BLOOMERY_SCHEMAJUMP=off"), ("runner", 21, "`response_format`")],
                  "the step arm of the Qwen3.6 seat, beside q_jump"),
    "v41":       ("DeepSeek-V4.1-Flash", [("README", 113, "[DeepSeek-V4.1-Flash]")], None),
    "v41_s":     ("V4.1-Flash", [("README", 113, "[DeepSeek-V4.1-Flash]")], "DeepSeek-V4.1-Flash, short in a claim line"),
    "q_s":       ("Qwen3.6", [("README", 116, "[Qwen3.6-35B-A3B]")], "Qwen3.6-35B-A3B, short in a claim line"),
    "lg_jump":   ("schemajump", [("runner", 2, "(the schemajump")], None),
    "url":       ("github.com/midagedev/bloomery", [("README", 41, "https://github.com/midagedev/bloomery/pull/320")], None),
    "md_head":   ("40 LAYERS × 256 EXPERTS", [("q36", 439, "(40 layers at interval 4)"), ("moe", 2, "softmax over 256 experts")],
                  "the real file's 40 layers and the router's 256 experts, upper case as the film's heads"),
    "md_cap":    ("a token reads 8 + 1 in every layer", [("moe", 2, "the top 8"), ("moe", 3, "as a ninth slot")],
                  "the router's top 8 and the shared expert as the ninth slot, in each of the 40 layers"),
    "dc_head":   ("DECODE · PLAIN STRUCTURED OUTPUT", [("genloop", 41, "[`Engine::next`] a token"),
                  ("runner", 16, "BLOOMERY_SCHEMAJUMP=off")],
                  "the step arm (the jump off) takes one Engine::next a token: decode"),
    "pr_cap1":   ("every expert read once,", [("seat", 76, "The prompt call runs the ubatch walk")],
                  "derived, a picture: under uniform top-8 routing a call of 298 ids reaches all 256 experts of a layer, "
                  "~9 ids an expert (no routing was measured)"),
    "pr_cap2":   ("each for many tokens", [("seat", 76, "The prompt call runs the ubatch walk")],
                  "the caption's second line (pr_cap1)"),
    "dn_cap":    ("the row is read at the options' ids", [("genloop", 43, "largest logit among the ids the program allows there"),
                  ("genloop", 44, "The row is read")], "a decision is the largest logit among the options' ids"),
}
FIXED = {   # strings that claim nothing on their own: units, labels of the picture, the stamps
    "leg_fixed": "one call", "leg_dec": "the model picks",
    "sh_head": "SHORT REQUESTS", "lg_head": "LONG REQUESTS", "sa_head": "SAME ANSWERS",
    "sa_same_t": "schemajump and plain structured output", "sa_match_t": "decisions match Clef-Flash's official answers",
    "so_dec": "decode", "so_pre": "prefill", "so_now": "now runs", "tok_s": "tok/s",
    "rq_served": "served by", "rq_yes": "yes", "rq_no": "no", "spot": "the schema already says this",
    "bo_head": "SAME TEXT", "an_head": "THE ANSWER", "an_cap": "shaped like a decision model's answer",
    "ca_head": "ENGINE CALLS", "lg_leg_p": "reading the prompt", "lg_leg_r": "the rest",
    "ph_stamp": "PLACEHOLDER: derived call counts, not measured", "dr_stamp": "DRAFT: not the server's body yet",
    "rt_stamp": "PLACEHOLDER: route line not sourced yet", "fx_stamp": "FIXTURE: made-up rows and bodies, not measured",
    "hd_head": "HARD QUESTIONS", "hd_p50": "p50 · one at a time",
    "pr_head": "THE PROMPT", "dn_head": "A DECISION",
    "dn_stamp": "PLACEHOLDER: the percentage is not the server's",
    "ax_l0": "L0", "ax_l39": "L39", "ax_e0": "EXPERT 0", "ax_e255": "255", "ax_sh": "+1",
}


def words_of(s):
    return [w for w in re.split(r"[\s·,()|*`:/\[\]\"<>=+]+", s.lower()) if w]


def cite(src):
    copy, cites = {}, {}
    for key, (s, quotes, why) in CITED.items():
        qw = set()
        for doc, n, q in quotes:
            line = src[doc][n - 1] if 0 < n <= len(src[doc]) else ""
            if q not in line: die("source", f"{doc}:{n} does not say {q!r} (it says {line[:120]!r})")
            qw |= set(words_of(line))
        if why is None and not set(words_of(s)) <= qw:
            die("source", f"{key} {s!r} has words its source lines do not: {sorted(set(words_of(s)) - qw)}")
        copy[key] = s
        cites[key] = [f"{doc}:{n}" for doc, n, _ in quotes] + ([f"why: {why}"] if why else [])
    return copy, cites


# ---- the request on screen and its answer --------------------------------------------------------------------------
def request(src, tops):
    """Part A's request (inputs.json request, "<suite>/<id>"): its suite line, its state wrapped to state_em, its picks
    (the jump arm's tops) and the answer as the schema program writes it (sjcmp.py program_parts: compact, one space
    after ':' and ','), laid a question a line. A pick is {qid, kind, options (the JSON values the program allows),
    labels (what the request card shows: the choice's keys, the score's levels, yes/no), pick (the JSON value)}."""
    suite, rid = REQ_SUITE, REQ_ID
    doc = {"en": "suite.jsonl", "ko": "suite-ko.jsonl"}.get(suite) or die("inputs", f"request suite {suite!r} is neither en nor ko")
    hit = [(i + 1, json.loads(l)) for i, l in enumerate(src[SUITE_DOC[suite]]) if l.strip() and json.loads(l)["id"] == rid]
    if len(hit) != 1: die("source", f"{doc} holds {len(hit)} rows with id {rid}")
    line, req = hit[0]
    top = tops.get((suite, rid))
    if top is None: die("rows", f"the jump arm has no answer for {suite}/{rid}")
    # the state, wrapped at spaces to STATE_EM em (a Hangul syllable is 1 em, anything else about 0.55)
    em = lambda s: sum(1.0 if "가" <= c <= "힣" else 0.3 if c in " ,.?" else 0.58 for c in s)
    lines, cur = [], ""
    for w in req["state"].split(" "):     # a line ends where the next word would pass the width, or after a sentence
        nxt = (cur + " " + w).strip()
        if cur and em(nxt) > INPUTS["state_em"]: lines.append(cur); cur = w
        else: cur = nxt
        if cur[-1:] in "?." and em(cur) > INPUTS["state_em"] / 2: lines.append(cur); cur = ""
    if cur: lines.append(cur)
    qs = list(req["questions"].items())
    if not 1 <= len(qs) <= 3: die("source", f"{rid}: {len(qs)} questions; the picture lays out one to three")
    picks = []
    for qid, q in qs:
        if q["type"] == "choice": opts = sorted(q["criteria"]); labels = list(q["criteria"]); val = top[qid]
        elif q["type"] == "noul": opts = ["true", "false"]; labels = ["yes", "no"]; val = {"yes": "true", "no": "false"}[top[qid]]
        elif q["type"] == "score": opts = [str(i) for i in range(len(q["criteria"]))]; labels = list(q["criteria"]); val = top[qid]
        else: die("source", f"{rid}: question type {q['type']}")
        if val not in opts: die("rows", f"{rid}: answer {val!r} is not an option of {qid}")
        picks.append({"qid": qid, "kind": q["type"], "options": opts, "labels": labels, "pick": val})
    # the line runs: [kind, text, face]; F0, F1, ... the fixed runs (each lands whole), D1, D2, ... the decisions; a
    # line's fixed text after its decision belongs to the next fixed run, as does the next line's indent
    face = lambda s: "kr" if HANGUL.search(s) else "mono"
    ans = []
    for k, p in enumerate(picks):
        qt = '"' if p["kind"] == "choice" else ""
        end = "," if k < len(picks) - 1 else "}"
        ans.append([[f"F{k}", '{"' if k == 0 else '"', "mono"], [f"F{k}", p["qid"], face(p["qid"])], [f"F{k}", '": ' + qt, "mono"],
                    [f"D{k + 1}", p["pick"], face(p["pick"]) if qt else "mono"], [f"F{k + 1}", qt + end, "mono"]])
    return {"id": rid, "line": line, "state": lines, "answer": ans, "picks": picks}


# ---- reading: words and numbers ------------------------------------------------------------------------------------
QTY = re.compile(r"^([−-]?\d[\d,]*(\.\d+)?(×|%)?|\d+/\d+)$")   # a percentage is a number
UNITS = {"ms", "s", "%", "tok/s", "tokens"}
NAME_PARTS = {"rtx": 1}


def read_units(strings):
    """(words, numbers) over a group of strings, each distinct string counted once."""
    words = nums = 0
    for s in dict.fromkeys(strings):
        toks = [w for w in re.split(r"[\s·]+", s) if w and w not in ("+", ",", "{", "}", "=", "→")]
        i = 0
        while i < len(toks):
            w = toks[i]
            if w.lower() in NAME_PARTS and i + 1 < len(toks):
                words += 1; i += 2; continue
            if QTY.match(w):
                nums += 1; i += 1
                if i < len(toks) and toks[i].lower() in UNITS: i += 1
                continue
            words += 1; i += 1
    return words, nums


def read_s(strings):
    w, n = read_units(strings)
    return max(READ_MIN_S, w / READ_WPS + n * READ_NUM_S), w, n




# ---- the pieces, the body, the shots -------------------------------------------------------------------------------
# (id, groups, carry): a group is (name, landing beat in the shot, how it lands, [copy keys]); the long race's finish
# lands at a race time ("done" = Clef-Flash's p50 after GO). carry: keys that stand unmoved from the shot before.
GO_BEAT = 3          # the long race's beat its two requests are sent on (the lamps go out), from its cut
# The hits the film needs, in order: (name, shot, beat in the shot, the shots the beats left before it go to)
# (P is make_data_a.py's anchor: schemajump's first call after the rewind. Part A holds its own beats: the beats left
# before L go to Part B's shots, which take an extra beat as a longer hold; none goes to ajump before its beat 4.)
ANCHORS = [("P", "ajump", 4, None), ("L", "blong", GO_BEAT, None),       # P and L: make_data_a.py's and make_data_b.py's
           ("E", "bend", 0, ["blong", "bshort", "bsolar"])]
END_MAX_S = 4.0      # the END plays at most this long: the arrangement stops there (its fade on the last beats)
PUNCT = re.compile(r"^[\W_]*$")
HANGUL = re.compile(r"[가-힣]")


def short(path):
    """A path as data.json records it: under this directory relative to it, else from its tree's name (the bloomery
    tree that held the runner), so the file names no home directory."""
    path = Path(path).resolve()
    if path.is_relative_to(HERE.resolve()): return str(path.relative_to(HERE.resolve()))
    return str(path.relative_to(path.parents[3])) if len(path.parents) > 3 else str(path)


def pieces_of(answer, tok):
    """The request's answer as Qwen3.6's tokenizer cuts it (sources/tokens-qwen36.json): [text, face, run kind, line]
    a piece, laid on the answer's lines; a piece that crosses a run, a line or a face is a named error."""
    lines = ["".join(r[1] for r in answer[0])] + [" " + "".join(r[1] for r in ln) for ln in answer[1:]]
    kinds = []
    for li, line in enumerate(answer):
        if li: kinds.append(line[0][0])            # the second line's indent belongs to its first run
        for kind, text, _ in line: kinds += [kind] * len(text)
    full = "".join(lines)
    got = "".join(p[1] for p in tok["pieces"])
    if got != full: die("source", f"the tokenizer's pieces spell {got!r}, the answer is {full!r}")
    ends = [sum(len(x) for x in lines[:k + 1]) for k in range(len(lines))]
    out, at = [], 0
    for _, text, _ in tok["pieces"]:
        li = next(k for k, e in enumerate(ends) if at < e)
        if at + len(text) > ends[li]: die("source", f"piece {text!r} crosses the answer's line break")
        ks = set(kinds[at:at + len(text)])
        if len(ks) != 1: die("source", f"piece {text!r} crosses runs {sorted(ks)}")
        hz = [bool(HANGUL.match(c)) for c in text if not c.isspace()]
        if any(hz) and not all(hz): die("source", f"piece {text!r} mixes Hangul and ASCII")
        out.append([text, "kr" if any(hz) else "mono", ks.pop(), li])
        at += len(text)
    return out


# The decide seat's SystemOne body (bloomery crates/decision/src/answer.rs): its keys in order, and each answer's
# fields in order by type. A general model's body is held to the same shape.
BODY_KEYS = ["model", "answers", "usage"]
ANSWER_KEYS = {"choice": ["type", "choice", "confidence", "probabilities"], "noul": ["type", "noul"],
               "score": ["type", "score", "confidence", "legend", "probabilities"]}


def body_of(path, answer, hide):
    """The answer shot's body: the saved response of the route (inputs.json answer_body), held to the decide seat's
    keys, types and order (BODY_KEYS, ANSWER_KEYS; the server's timings left out), laid one answer field a line: a
    float to two places, a map of numbers (probabilities, usage) shown as {…}. A key in body_hide is never drawn
    (a top-level key or an answer field). With none saved, the decided JSON (the film stamps DRAFT)."""
    if not path: return [[[k, t, f] for k, t, f in line] for line in answer], True
    body = json.loads((HERE / path).read_text())
    if not isinstance(body, dict): die("inputs", f"{path}: not an object")
    keys = [k for k in body if k != "timings"]
    if keys != BODY_KEYS: die("inputs", f"{path}: keys {keys}, the decide seat's body has {BODY_KEYS} in that order")
    if not isinstance(body["model"], str) or not isinstance(body["answers"], dict) or not isinstance(body["usage"], dict):
        die("inputs", f"{path}: model is not a string, or answers or usage not an object")
    for q, f in body["answers"].items():
        want = ANSWER_KEYS.get(f.get("type") if isinstance(f, dict) else None)
        if want is None or list(f) != want: die("inputs", f"{path}: answer {q!r} has {list(f) if isinstance(f, dict) else f!r}, a {f.get('type') if isinstance(f, dict) else '?'} answer has {want}")
        for k in ("confidence", "noul", "score"):
            if k in f and (isinstance(f[k], bool) or not isinstance(f[k], (int, float))): die("inputs", f"{path}: {q}.{k} is not a number")
    known = set(BODY_KEYS) | {k for v in ANSWER_KEYS.values() for k in v}
    if set(hide) - known: die("inputs", f"body_hide names {sorted(set(hide) - known)}, keys the body does not have")
    face = lambda s: "kr" if HANGUL.search(s) else "mono"
    js = lambda v: json.dumps(v, ensure_ascii=False)
    def val(v):
        if isinstance(v, bool) or not isinstance(v, (int, float, dict)): return js(v)
        if isinstance(v, float): return f"{v:.2f}"
        if isinstance(v, dict) and v and all(isinstance(x, (int, float, str)) for x in v.values()): return "{…}"
        if isinstance(v, dict): die("inputs", f"{path}: a field holds a nested object the film does not lay out")
        return str(v)
    top = [k for k in BODY_KEYS if k not in hide]
    if "answers" not in top: die("inputs", "body_hide hides answers: the answer shot has nothing to show")
    lines = []
    for ti, k in enumerate(top):
        open_ = '{' if ti == 0 else ' '
        end = "," if ti < len(top) - 1 else "}"
        if k != "answers":
            lines.append([["B", open_ + js(k) + ": ", "mono"], ["B", val(body[k]), face(val(body[k]))], ["B", end, "mono"]])
            continue
        lines.append([["B", open_ + js(k) + ": {", "mono"]])
        qs = [(q, [(f, v) for f, v in fields.items() if f not in hide]) for q, fields in body["answers"].items()]
        for i, (q, items) in enumerate(qs):
            if not items: die("inputs", f"body_hide leaves answer {q!r} empty")
            for j, (f, v) in enumerate(items):
                tail = "," if j < len(items) - 1 else "}" + ("," if i < len(qs) - 1 else "}" + end)
                run = [["B", js(f) + ": ", "mono"], ["B", val(v), face(val(v))], ["B", tail, "mono"]]
                lines.append(([["B", "  ", "mono"], ["B", js(q), face(q)], ["B", ": {", "mono"]] if j == 0 else [["B", "      ", "mono"]]) + run)
    return lines, False


# The shots: Part A's from make_data_a.py (the request, one token's trip, plain structured output, schemajump, the same
# text, a decision), Part B's from make_data_b.py.
def shots(has_solar, has_and, part_a, part_b):
    """Part A's shots (make_data_a.py), Part B's (make_data_b.py: the requests to the long race), Solar while filled,
    the END."""
    S = part_a + part_b + [("bend", [("lockup", 2, "cut", ["name", "version", "url"] + (["and_line"] if has_and else []))], [])]
    if has_solar: S.insert(-1, ("bsolar", [("solar", 0, "cut", ["so_now", "so_name", "so_dec", "so_dec_v", "so_pre", "so_pre_v", "so_cond"])], []))
    return S


def flat(v):
    if isinstance(v, str): return [v]
    if isinstance(v, list) and v and isinstance(v[0], str) and len(v) in (3, 4) and v[2 if len(v) == 3 else 1] in ("mono", "kr"):
        return [v[1] if len(v) == 3 else v[0]]
    return [s for x in v for s in flat(x)]


def last_of(sid, name, P, n_step):
    """A group's last element lands this long after the group's landing beat."""
    if (sid, name) == ("decode", "calls"): return (n_step - 1) / 4 * P
    return 0.0


def lengths(spec, copy, P, race_s, n_pieces):
    """Each shot's minimum beats from the reading rule; a group's clock starts at its last element's settle. The
    pieces are read as the answer they spell (a piece is not a word)."""
    out = []
    for sid, groups, carry in spec:
        G, t_end, tot = [], 0.0, 0.0
        for name, at, how, keys in groups:
            rk = ["answer" if k == "pieces" else k for k in keys]
            strings = [s for k in rk if k not in carry for s in flat(copy[k]) if not PUNCT.match(s)]
            need, w, n = read_s(strings)
            t_land = GO_BEAT * P + race_s if at == "done" else at * P
            last = last_of(sid, name, P, n_pieces)
            still = t_land + last + SETTLE[how]
            G.append({"name": name, "keys": keys, "at": None if at == "done" else at, "how": how, "still_rel": still,
                      "read_s": need, "words": w, "numbers": n, "last": last})
            tot += need
            t_end = max(t_end, still + need)
        if len(G) > 1: t_end = max(t_end, G[0]["still_rel"] + tot)
        out.append({"id": sid, "groups": G, "carry": carry, "min": math.ceil(t_end / P - 1e-9)})   # the rest: 0, set by the plan
    return out


def fill(pool, n):
    """n whole bars of the pool, read cyclically and ending on its last bar."""
    return [(pool[(len(pool) - n + i) % len(pool)], pool[(len(pool) - n + i) % len(pool)] + 4) for i in range(n)]


def merge(segs):
    out = []
    for a, b in segs:
        if b <= a: continue
        if out and out[-1][1] == a: out[-1] = (out[-1][0], b)
        else: out.append((a, b))
    return out


def plan(spec_l, music):
    """Place the shots on the track and arrange it: (open beat, {shot: beats}, track row, arrangement). Each anchor's
    hit lands on its shot's beat (ANCHORS): the REST shot plays the rest before P's hit; before P the track opens
    where its hit lands right; between two hits the track plays its own groove plus whole bars spliced in (fill), or
    whole bars cut out, as many as the shots between need, and the at most three beats a whole bar leaves over go to
    the shots there; after E's hit the END plays to the track's end."""
    tr = TRACKS.get(MUSIC_ID)
    if tr is None: die("timing", f"track {MUSIC_ID} has no TRACKS row (its arrangement)")
    order = [s["id"] for s in spec_l]
    mins = {s["id"]: s["min"] for s in spec_l}
    L = dict(mins)
    pos = lambda sid, off: sum(L[x] for x in order[:order.index(sid)]) + off

    def spread(slack, to):
        to = [x for x in to if x in L]
        j = 0
        while slack > 0: L[to[j % len(to)]] += 1; slack -= 1; j += 1

    rests, pool, bars = tr["rests"], tr["pool"], music["bar_offset"] % 4
    (_, sid0, off0, _), later = ANCHORS[0], ANCHORS[1:]
    r0, h0 = rests[ANCHORS[0][0]]
    F0 = pos(sid0, off0)
    n1 = max(0, math.ceil((F0 - h0) / 4))
    open_at = h0 + 4 * n1 - F0
    k = (open_at - bars) % 4                                     # open on a bar when the title can take the beats
    if k <= open_at: L["title"] += k; open_at -= k
    if open_at > r0: die("timing", f"the shots before the rest take {pos('rest', 0)} beats, under the track's first stretch")
    arr = [(open_at, r0)] + fill(pool, n1)
    prev_r, prev_h, prev = r0, h0, (sid0, off0)
    for name, sid, off, to in later:
        r, h = rests[name]
        need = pos(sid, off) - pos(*prev)
        n = math.ceil((need - (h - prev_h)) / 4)
        if n < -((r - prev_h) // 4): die("timing", f"the shots before hit {name} take {need} beats, too few for the track")
        spread((h - prev_h) + 4 * n - need, to)
        arr += [(prev_r, r + min(0, 4 * n))] + fill(pool, max(0, n))
        prev_r, prev_h, prev = r, h, (sid, off)
    end = ANCHORS[-1][1]
    L[end] = min(tr["end"] - prev_h, max(mins[end], math.floor(END_MAX_S / music["period_s"] + 1e-9)))
    if L[end] < mins[end]: die("timing", f"the END needs {mins[end]} beats, the track's end leaves {L[end]}")
    arr = merge(arr + [(prev_r, prev_h + L[end])])
    if os.environ.get("PLAN_DEBUG"):
        for x in spec_l: print("  min", x["id"], x["min"], [(g["name"], g["words"], g["numbers"], round(g["read_s"], 2), round(g["still_rel"], 2)) for g in x["groups"]])
        print("  arrangement", arr)
    return open_at, L, tr, arr


def hits_on(arr, rest0, hit):
    """The film beat where the arrangement plays the track's hit after the rest that starts at rest0 (the stretch
    that plays the rest through to the hit unspliced)."""
    b = 0
    for a, e in arr:
        if a <= rest0 and hit < e: return b + hit - a
        b += e - a
    return None


def main():
    beats = json.loads((HERE / "beats.json").read_text())
    if MUSIC_ID not in beats: die("usage", f"beats.json has no row {MUSIC_ID} (run beats.py on its mp3)")
    music = {"id": MUSIC_ID, **{k: v for k, v in beats[MUSIC_ID].items() if k != "loud_db"}}
    P = music["period_s"]
    m = measure()
    src, runner_path = sources()
    copy, cites = cite(src)
    copy.update(FIXED)
    for k in FIXED: cites[k] = ["label"]
    req = request(src, m["jump_tops"])
    tokdoc = json.loads((HERE / INPUTS["tokens"]).read_text())
    tok = tokdoc["requests"].get(INPUTS["request"])
    if tok is None: die("source", f"{INPUTS['tokens']} has no {INPUTS['request']}")
    pieces = pieces_of(req["answer"], tok)
    body, draft_body = body_of(INPUTS.get("answer_body", ""), req["answer"], INPUTS.get("body_hide") or [])
    C = m["calls"]
    cr = next(x for x in C["per"] if x["key"] == INPUTS["request"])
    placeholder = C["source"] != "rows"
    verdict = INPUTS.get("verdict") or ("faster" if m["jump_short"] < m["clef_short"] else "close")
    if verdict not in ("faster", "close"): die("inputs", f"verdict {verdict!r} is neither faster nor close")
    ms = lambda x: f"{x:,.1f} ms" if round(x, 1) < 1000 else f"{x:,.0f} ms"
    lp = m["long_prompts"]
    sol = INPUTS["solar"]
    has_solar = bool(sol.get("decode")) and bool(sol.get("prefill"))
    has_and = bool(INPUTS.get("and_line"))
    # the long gap: how much of Clef-Flash's lead over the jump arm is its prompt pass (p50 of each part)
    gap_p = m["clef_long_prompt"] - m["jump_long_prompt"]
    gap_all = (m["clef_long_prompt"] + m["clef_long_rest"]) - (m["jump_long_prompt"] + m["jump_long_rest"])
    share = gap_p / gap_all if gap_all > 0 else 0.0
    if share >= 0.9: why = "almost all of it is prompt reading"
    elif share >= 0.5: why = "most of it is prompt reading"
    else: die("rows", f"the long gap is {share:.0%} prompt reading: the long shot's line does not hold")
    copy.update({"version": INPUTS["version"], "body": body})
    # the first half (make_data_a.py): plain structured output's calls (one an id of the answer), schemajump's calls
    # (the program's plan over the same ids), the decision's percentage (the saved body's, else a placeholder)
    n_step, n_jump, plan_j = cr["step"], cr["jump"], [tuple(x) for x in tok["jump_plan"]]
    if sum(n for _, n in plan_j) != len(pieces): die("source", f"{req['id']}: the plan feeds {sum(n for _, n in plan_j)} ids, the answer has {len(pieces)}")
    q1 = req["picks"][0]
    pct, pct_src = "··%", "PLACEHOLDER: no saved body (inputs.json answer_body)"
    if not draft_body:
        pb = json.loads((HERE / INPUTS["answer_body"]).read_text())["answers"].get(q1["qid"], {}).get("probabilities", {})
        if q1["pick"] not in pb: die("inputs", f"{INPUTS['answer_body']}: no probability for {q1['qid']} = {q1['pick']}")
        pct, pct_src = f"{100 * pb[q1['pick']]:.0f}%", f"inputs.json answer_body {INPUTS['answer_body']}"
    if verdict == "close" and m["jump_short"] < m["clef_short"]: print("note: verdict 'close' set although the jump arm is faster")
    if verdict == "faster" and m["jump_short"] >= m["clef_short"]: die("inputs", "verdict 'faster' while the jump arm's short p50 is not under Clef-Flash's")
    csrc = f"rows {short(SJ_ROWS)} (calls: {'+'.join(C['keys'])})" if not placeholder else f"PLACEHOLDER: {INPUTS['tokens']} (sjcmp.py's predicted calls)"
    cites["body"] = [f"inputs.json answer_body {INPUTS['answer_body']}"] if not draft_body else ["DRAFT: the decided JSON (no saved body)"]
    if has_solar:
        copy.update({"so_name": sol["name"], "so_dec_v": f"{sol['decode']} tok/s", "so_pre_v": f"{sol['prefill']} tok/s",
                     "so_cond": sol["cond"]})
        for k in ("so_name", "so_dec_v", "so_pre_v", "so_cond"): cites[k] = ["inputs.json solar (the lead's sitting)"]
    if has_and: copy["and_line"] = INPUTS["and_line"]; cites["and_line"] = ["inputs.json and_line (the release notes)"]
    # the route the timed requests went through: the chat models' footers name it; while it is response_format the
    # request shot says the same program serves /v1/systemone, sourced by the lead's route line (inputs.json
    # route_cite: a file at a commit of the bloomery tree, its line and a quote it holds), a placeholder until then
    route = INPUTS.get("route_measured", "response_format")
    if route not in ("response_format", "systemone"): die("inputs", f"route_measured {route!r} is neither response_format nor systemone")
    copy["foot_rt"] = {"response_format": "chat models via response_format", "systemone": "chat models via POST /v1/systemone"}[route]
    cites["foot_rt"] = [f"inputs.json route_measured {route}", "runner:21" if route == "response_format" else "inputs.json route_cite"]
    rc = INPUTS.get("route_cite") or {}
    route_ph = False
    if route == "response_format":
        copy["rq_route"] = "the same program serves /v1/systemone"
        if rc.get("file"):
            try:
                rl = subprocess.run(["git", "-C", str(BLOOMERY), "show", f"{rc['rev']}:{rc['file']}"], capture_output=True,
                                    text=True, check=True).stdout.split("\n")
            except subprocess.CalledProcessError as e:
                die("source", f"route_cite: git show {rc.get('rev')}:{rc['file']}: {e.stderr.strip()}")
            n = int(rc.get("line") or 0)
            if not (0 < n <= len(rl)) or not rc.get("quote") or rc["quote"] not in rl[n - 1]:
                die("source", f"route_cite: {rc['file']}:{n} does not say {rc.get('quote')!r}")
            cites["rq_route"] = [f"{rc['file']}@{rc['rev']}:{n}", "why: the lead's route statement"]
        else:
            route_ph = True
            cites["rq_route"] = ["PLACEHOLDER: the lead's route statement, no source line yet (inputs.json route_cite)"]
    hd = hard()   # the hard suite's arms (make_data_b.py draws them; hidden while empty)
    import make_data_b
    B = INPUTS.get("b") or {}
    for k in ("rows", "bodies"):
        if not B.get(k): die("inputs", f"b.{k} is empty: Part B reads the sitting's rows and saved bodies")
    at_b = lambda v: Path(v) if Path(v).is_absolute() else HERE / v
    Hs = INPUTS.get("hard") or {}
    at_h = lambda k: Path(Hs[k]) if Path(Hs[k]).is_absolute() else HERE / Hs[k]
    suite_src = {"en": make_data_b.src_lines(sys.modules[__name__], "tools/ref/clef/suite.jsonl"), "ko": src["suite"],
                 "hard": at_h("suite").read_text().split("\n") if hd else [],
                 "hard_gold": at_h("gold").read_text().split("\n") if hd else []}
    pb = make_data_b.part_b(at_b(B["rows"]), at_b(B["bodies"]), suite_src, hd, copy, INPUTS, P)
    copy.update(pb["copy"]); cites.update(pb["cites"])
    # Part A (make_data_a.py): the request, one token's trip, plain structured output, schemajump, the text, a decision
    import make_data_a
    ra = make_data_a.build(sys.modules[__name__], src, req, pieces, plan_j, cr, csrc, pct, pct_src, copy, P)
    copy.update(ra["copy"]); cites.update(ra["cites"])
    ANCHORS[0] = (*ra["anchor"], None)
    ANCHORS[1] = pb["anchor_l"]
    ANCHORS[2] = ("E", "bend", 0, ["blong" if pb["anchor_l"][1] == "blong" else "bshort", "bsolar"])   # the shots after L
    spec = shots(has_solar, has_and, ra["shots"], pb["shots"])
    L = lengths(spec, copy, P, 0.0, 0)
    open_at, beats_by, tr, arr = plan(L, music)
    on = lambda b: max(0.0, b * P - LEAD)
    segs, events, b, rows = [], [], 0, []
    for S0 in L:
        nb = beats_by[S0["id"]]
        S = {"id": S0["id"], "kind": "card", "b0": b, "len": nb, "b1": b + nb, "t0": round(on(b), 6), "t1": round(on(b + nb), 6),
             "groups": [], "carry": S0["carry"], "land": {}, "cue": {}}
        events.append([f"cut {S['id']}", S["t0"], None])
        tot = 0.0
        for g in S0["groups"]:
            t_land = on(b + g["at"])
            if g["at"] and not S["id"].startswith(("req", "bhx")):
                events.append([f"slam {S['id']}.{g['name']}", round(t_land, 6), None])
            still = t_land + g["last"] + SETTLE[g["how"]]
            have = S["t1"] - still
            if have + 1e-9 < g["read_s"]: die("timing", f"{S['id']}.{g['name']} holds {have:.3f} s, its read needs {g['read_s']:.3f} s")
            tot += g["read_s"]
            S["groups"].append({"name": g["name"], "keys": g["keys"], "at": g["at"], "land": round(t_land, 6),
                                "still": round(still, 6), "how": g["how"], "read_s": round(g["read_s"], 3),
                                "words": g["words"], "numbers": g["numbers"]})
            rows.append((S["id"], g["name"], g["words"], g["numbers"], g["read_s"], have))
        if len(S["groups"]) > 1 and S["t1"] - S["groups"][0]["still"] + 1e-9 < tot:
            die("timing", f"{S['id']}: its groups need {tot:.3f} s together, the shot holds {S['t1'] - S['groups'][0]['still']:.3f} s")
        segs.append(S); b += nb
    nb_total = b
    events += make_data_b.events_b([S for S in segs if S["id"].startswith(("req", "bhx"))], on)
    # Part A's 16th-note clock: the trip's layers, plain's tokens and the rewind move on 16ths (parta.js's q16)
    for S in segs:
        if S["id"] in ("atrip", "aplain", "ajump"):
            events += [[f"tick {S['id']}.16th.{k}", round(on(S["b0"] + k / 4), 6), None] for k in range(1, 4 * S["len"]) if k % 4]
    seg = {S["id"]: S for S in segs}
    # the anchors: each hit of the arrangement where its shot needs it (the REST shot ends on P's hit)
    want = {name: seg[sid]["b0"] + off for name, sid, off, _ in ANCHORS}
    for name, sid, off, _ in ANCHORS:
        r0, sb = tr["rests"][name]
        got = hits_on(arr, r0, sb)
        if got != want[name]: die("timing", f"hit {name} (track beat {sb}) plays at film beat {got}, its shot needs {want[name]}")
    if sum(e - a for a, e in arr) != nb_total: die("timing", f"the arrangement plays {sum(e - a for a, e in arr)} beats, the film has {nb_total}")
    splices, ob = [], 0
    for (a, e), nxt in zip(arr, arr[1:] + [None]):
        ob += e - a
        if nxt: splices.append({"film_beat": ob, "t": round(ob * P, 6), "from_track_beat": e, "to_track_beat": nxt[0]})
    music.update({"arrangement": [list(x) for x in arr], "splices": splices, "xfade_s": XFADE_S, "open_at_beat": open_at})
    end_beat = arr[-1][1]      # the track beat the arrangement stops on (the END cap may stop it early)
    T = round(nb_total * P, 4)
    at = round(music["first_beat_s"] + open_at * P, 4)
    tl = {"T": T, "at": at, "period": P, "first": 0.0, "lead": LEAD, "open_at_beat": open_at, "end_beat": end_beat,
          "nbeats": nb_total, "beats": [round(k * P, 4) for k in range(nb_total + 1)], "segments": segs,
          "events": sorted(events, key=lambda e: e[1]), "fade_out_s": round(tr["fade_out_beats"] * P, 6),
          "ticks": sorted(e[1] for e in events if e[0].startswith("tick")), "anchors": want}
    data = {"film": "release-036", "music": music, "timeline": tl, "copy": copy, "sources": cites,
            "measured": {k: v for k, v in m.items() if k not in ("jump_tops",)},
            "request": {"id": req["id"], "picks": req["picks"]},
            "placeholder": placeholder, "draft_body": draft_body, "route_placeholder": False,   # no shot draws rq_route now
            "fixture": bool(pb["b"]["fixture"] or (hd and hd["fixture"])), "b": pb["b"], "a": ra["a"],
            "hard": ({k: v for k, v in hd.items() if k != "arms"} | {"arms": [{k: v for k, v in a.items() if k != "tops"} for a in hd["arms"]]}) if hd else None,
            "notes": {"draft": bool(INPUTS.get("draft", True)), "sitting": INPUTS["sitting"], "readme_rev": README_REV,
                      "runner": short(runner_path), "rows": short(SJ_ROWS), "verdict": verdict, "calls": csrc, "route": route,
                      "long_gap_prompt_share": round(share, 4)}}
    (HERE / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    print(f"data.json: T {T} s = {nb_total} beats of {P} s ({music['bpm']} BPM), track {MUSIC_ID} from {at} s (beat {open_at}) "
          f"to beat {end_beat}; fade {tl['fade_out_s']} s; {INPUTS['sitting']}; hits {want}")
    print(f"  short p50: Clef-Flash {m['clef_short']:.2f} ms (n {m['clef_short_n']}), jump {m['jump_short']:.2f} (n {m['jump_short_n']}), "
          f"step {m['step_short']:.2f} (n {m['step_short_n']}); jump vs step {m['step_delta_pct']:+.2f} % over {m['rounds']} rounds")
    print(f"  long p50: Clef-Flash {m['clef_long']:.2f} ms (n {m['clef_long_n']}), jump {m['jump_long']:.2f} (n {m['jump_long_n']}); "
          f"prompt {m['clef_long_prompt']:.1f} vs {m['jump_long_prompt']:.1f}, the rest {m['clef_long_rest']:.1f} vs {m['jump_long_rest']:.1f} "
          f"(gap {share:.1%} prompt); prompts {m['long_prompts']}; same {m['same']}/{m['same_of']}; match {m['match']}/{m['match_of']}; verdict {verdict}")
    print(f"  calls from {csrc}: {req['id']} step {cr['step']} jump {cr['jump']}; suite step {C['sum_step']} jump {C['sum_jump']}")
    print(f"  engine calls = {' + '.join(C['keys'])} (engine_calls; inputs.json calls_sum)")
    print("    request              step  jump")
    for x in C["per"]: print(f"    {x['key']:20} {x['step']:5} {x['jump']:5}")
    print(f"  route {route}" + ("; the route line (rq_route) is a PLACEHOLDER (no route_cite) and no shot draws it" if route_ph else ""))
    ids = {sp[0] for sp in spec}
    if hd:
        print(f"  hard: {hd['n']} questions in {hd['requests']} requests, {hd['rows']}{' (FIXTURE)' if hd['fixture'] else ''}; "
              + "; ".join(f"{a['model']} {a['arm']} {a['correct']}/{a['n']} p50 {a['p50_ms']:.1f} ms" for a in hd["arms"])
              + f"; shots: hard {'on' if 'bhard' in ids else 'off'}, examples {sum(i.startswith('bhx') for i in ids)}")
    else: print("  hard: off (inputs.json hard.rows is empty)")
    print(f"  answer body: {'DRAFT (none saved)' if draft_body else INPUTS['answer_body']}; solar {'on' if has_solar else 'off'}, and-line {'on' if has_and else 'off'}")
    print(f"  arrangement {arr}; splices at film beats {[x['film_beat'] for x in splices]}")
    print("shot     group    beats words nums  read  holds")
    for S in segs:
        for g in S["groups"]:
            r = next(x for x in rows if x[0] == S["id"] and x[1] == g["name"])
            print(f"{S['id']:8} {g['name']:8} {S['len']:5} {r[2]:5} {r[3]:4} {r[4]:5.2f} {r[5]:6.2f}")
    if placeholder: print("PLACEHOLDER: the rows carry no call counts; the film stamps every frame")
    if data["notes"]["draft"]: print("DRAFT: inputs.json says draft (the sitting or the notes are not final)")


if __name__ == "__main__":
    main()
