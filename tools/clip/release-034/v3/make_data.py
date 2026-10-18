"""Build data.json for the v3 film (film.html): the two RTX 3090 tapes it plays, every string it draws (each read from a
tape or checked against its source line) and every time it switches on, from volt-s1006's measured beat grid.

  python3 make_data.py
  TAPES=<dir>       the boltclip tapes (default: bloomery's specs/toktape/boltclip/tapes)
  NOTES=<file>      the 0.3.4 release notes (default: the lead's copy of the published body)
  README_REV=<rev>  the bloomery commit whose README.md the strings quote (default 9723698f2)

The tapes. Each lane is the P4 tape of one arm (its summary.tag names it): bloomery 0.3.4's bloomery-serve and
llama.cpp's llama-server, one RTX 3090 each in turn, the same GGUF and the same rendered prompt. Every label the race
draws comes from the two tapes: the model's name from its file name (MODEL_NAMES; an unknown file is refused), the
card and its memory from host.gpus through placement.devices, each engine and its build from summary.server, the
prompt size from timings.prompt_n, each decode rate from timings.predicted_per_second (the toktape card's decode row),
the tokens and their times from requests[0].tokens. A tape that is not one greedy stream of one request on one card,
or a pair that differs in file, prompt or sampling, is refused by name with its own exit code.

Real time. Token times are the tape's own (ns from the request's send); the film starts both at one instant (GO) and
draws each token when its time comes. Nothing is trimmed, nothing sped up: the race runs until the slower lane's last
token, then holds.

Timing: a shot lasts its beats. Each group of strings lands on its beats and then holds still for its read time (4 words
a second plus 1 s a number, at least 2.5 s) from its last element's settle, before the cut. The race's labels are read
across the race: each group holds from its own settle (the finish group lands at the slower lane's last token), and
all its groups together fit between the first settle and the cut.
"""
import gzip, json, os, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).parent
FPS = 60
LEAD = 0.5 / FPS          # every switch is computed half a frame before its beat: the picture leads, never lags
TAPES = Path(os.environ.get("TAPES", "/Users/hckim/repo/bloomery/specs/toktape/boltclip/tapes"))
NOTES = Path(os.environ.get("NOTES", "/Users/hckim/orca/briefs/reports/release-notes-0.3.4.md"))
BLOOMERY = Path(os.environ.get("BLOOMERY", "/Users/hckim/repo/bloomery"))
README_REV = os.environ.get("README_REV", "9723698f2")
MUSIC_ID = "volt-s1006"
OPEN_AT, END_BEAT = 56, 127   # the track's beat the film opens on (a bar start) and the beat its sound ends on
FADE_OUT_S = 0.1              # the track ends on its own last hit: a short fade only
READ_WPS, READ_NUM_S, READ_MIN_S = 4.0, 1.0, 2.5
SETTLE = {"slam": 0.20, "rise": 0.16, "draw": 0.16, "wipe": 0.20, "stamp": 0.30}

# file name -> (name on screen, size) ; the film names only models listed here
MODEL_NAMES = [(re.compile(r"^NVIDIA-Nemotron-3\.5-Bolt-(\d+B-A\d+B)-24GB\.gguf$"), "NEMOTRON 3.5 BOLT")]
LANES = [("ours", "arm=boltclip-ours-3090-p4", "bloomery"), ("lcpp", "arm=boltclip-lcpp-3090-p4", "llama-server")]
EXIT = {"usage": 2, "unknown-model": 3, "not-single-stream": 4, "not-one-card": 5, "dirty-build": 6, "unequal": 7,
        "not-greedy": 8, "uncounted": 9, "text": 10, "engine": 11, "source": 12, "timing": 13}


def die(name, msg):
    print(f"make_data.py: refused ({name}): {msg}", file=sys.stderr)
    sys.exit(EXIT[name])


# ---- the tapes -----------------------------------------------------------------------------------------------------
def load(path):
    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b": raw = gzip.decompress(raw)
    return json.loads(raw)


def find(tag):
    hits = []
    for p in sorted(TAPES.glob("*/*.toktape")):
        tape = load(p)
        if tape["summary"].get("tag") == tag: hits.append((p, tape))
    if len(hits) != 1:
        die("usage", f"{len(hits)} tapes under {TAPES} carry tag {tag!r}, not one")
    return hits[0]


def card_name(gpu_name):
    return re.sub(r"^NVIDIA\s+", "", gpu_name).replace("GeForce ", "").strip()


def lane(lid, tag, kind):
    path, tape = find(tag)
    s, reqs = tape["summary"], tape["requests"]
    fname = s["model"]["file_name"]
    hit = next(((name, m.group(1)) for rx, name in MODEL_NAMES for m in [rx.match(fname)] if m), None)
    if hit is None: die("unknown-model", f"{path.name}: {fname!r} is not in MODEL_NAMES")
    if s.get("concurrency") != 1 or len(reqs) != 1: die("not-single-stream", f"{path.name}: concurrency {s.get('concurrency')}, {len(reqs)} requests")
    if s["sampling"].get("temperature") != 0 or s["sampling"].get("thinking") != "off":
        die("not-greedy", f"{path.name}: sampling {s['sampling']}")
    t = s["timings"]
    if t.get("predicted_n_source") == "chunks" or not t.get("predicted_per_second"): die("uncounted", f"{path.name}: the decode count is chunks")
    gpus = {g["index"]: g for g in s["host"]["gpus"]}
    cards = [gpus[int(d["device"][3:])] for d in s["placement"]["devices"] if re.fullmatch(r"GPU\d+", d["device"])]
    if len(cards) != 1: die("not-one-card", f"{path.name}: placed on {len(cards)} cards")
    srv = s["server"]
    if srv["kind"] != kind: die("engine", f"{path.name}: server {srv['kind']!r}, expected {kind!r}")
    if "-dirty" in srv.get("build", ""): die("dirty-build", f"{path.name}: build {srv['build']!r}")
    engine = f"bloomery {srv['build'].split()[0]}" if kind == "bloomery" else f"llama.cpp {srv['build'].split()[0]}"
    r = reqs[0]
    toks = r["tokens"]
    text = "".join(x["text"] for x in toks)
    if text != r["prompt"]["completion"]: die("text", f"{path.name}: the tokens' text is not the completion")
    if [x["i"] for x in toks] != list(range(len(toks))): die("text", f"{path.name}: token indices are not 0..n-1")
    ts = [x["t"] / 1e9 for x in toks]
    if any(b < a for a, b in zip(ts, ts[1:])): die("text", f"{path.name}: token times go backwards")
    return {
        "id": lid, "tape": path.name, "tape_id": s["id"], "tag": tag,
        "engine": engine, "model": hit[0], "size": hit[1], "file": fname, "file_bytes": s["model"]["file_bytes"],
        "card": card_name(cards[0]["name"]), "card_index": cards[0]["index"], "vram_gib": cards[0]["vram_bytes"] / 2**30,
        "power_limit_w": next((g.get("power_limit_w") for g in s.get("gpus_at_end", []) if g["index"] == cards[0]["index"]), None),
        "prompt_n": t["prompt_n"], "prompt_sha": s["template"]["rendered_prompt_sha256"],
        "instruction": r["prompt"]["messages"][0]["content"].split("\n")[0],
        "tps": f"{t['predicted_per_second']:.1f}", "tps_raw": t["predicted_per_second"], "predicted_n": t["predicted_n"],
        "ttft_s": round(ts[0], 6), "done_s": round(ts[-1], 6),
        "toks": [[round(a, 6), x["text"]] for a, x in zip(ts, toks)], "text": text,
    }


def pair():
    a, b = (lane(*x) for x in LANES)
    for k in ("model", "size", "file", "file_bytes", "card", "vram_gib", "prompt_n", "prompt_sha", "instruction"):
        if a[k] != b[k]: die("unequal", f"{k}: {a[k]!r} vs {b[k]!r}")
    return a, b


# ---- the cited strings ---------------------------------------------------------------------------------------------
def sources():
    if not NOTES.exists(): die("source", f"no release notes at {NOTES} (NOTES=<file>)")
    try:
        readme = subprocess.run(["git", "-C", str(BLOOMERY), "show", f"{README_REV}:README.md"], capture_output=True,
                                text=True, check=True).stdout.split("\n")
    except subprocess.CalledProcessError as e:
        die("source", f"git show {README_REV}:README.md in {BLOOMERY}: {e.stderr.strip()}")
    pr = (HERE / "sources/sparks-420.md").read_text().split("\n")
    return {"notes": NOTES.read_text().split("\n"), "README": readme, "pr420": pr}


# key -> (string, [(doc, line, quote)]): line n of doc must hold quote, and every word of the string (lower case,
# separators dropped) must be a word of its quotes, except where a reason is given.
CITED = {
    "name":     ("bloomery", [("notes", 1, "bloomery 0.3.4 adds")], None),
    "version":  ("0.3.4", [("notes", 1, "bloomery 0.3.4 adds")], None),
    "sp_head":  ("TWO DGX SPARKS", [("pr420", 10, "uses two DGX Sparks with NVIDIA GB10")], None),
    "sp_ds":    ("DeepSeek-V4.1-Flash", [("README", 41, "for GLM-5.3-Flash and DeepSeek-V4.1-Flash")], None),
    "sp_ds_gb": ("347 GB", [("README", 18, "DeepSeek-V4.1-Flash `Q3_K_M` (347 GB)")], None),
    "sp_glm":   ("GLM-5.3-Flash", [("README", 41, "for GLM-5.3-Flash and DeepSeek-V4.1-Flash")], None),
    "sp_mem":   ("128 GB", [("pr420", 10, "128 GB unified memory per system")], None),
    "sp_link":  ("over RDMA", [("README", 48, "Two Sparks over RDMA serve one model")], None),
    "sp_by":    ("@juliankang4", [("notes", 67, "**Multi-node serving over RDMA (DGX Spark)**, by @juliankang4")], None),
    "url":      ("github.com/midagedev/bloomery", [("README", 41, "https://github.com/midagedev/bloomery/pull/420")], None),
}


def words_of(s):
    return [w for w in re.split(r"[\s·,()|*`:/]+", s.lower()) if w]


def cite(src):
    copy, cites = {}, {}
    for key, (s, quotes, why) in CITED.items():
        qw = set()
        for doc, n, q in quotes:
            line = src[doc][n - 1] if 0 < n <= len(src[doc]) else ""
            if q not in line: die("source", f"{doc}:{n} does not say {q!r} (it says {line[:120]!r})")
            qw |= set(words_of(q))
        if why is None and not set(words_of(s)) <= qw | {w for doc, n, q in quotes for w in words_of(src[doc][n - 1])}:
            die("source", f"{key} {s!r} has words its source lines do not")
        copy[key] = s
        cites[key] = [f"{doc}:{n}" for doc, n, _ in quotes]
    return copy, cites


# ---- reading: words and numbers ------------------------------------------------------------------------------------
QTY = re.compile(r"^(\d[\d,]*(\.\d+)?(-token)?|\d+B-A\d+B|b\d+)$")   # 86.3, 5,680-token, 74B-A9B, b11668; not 0.3.4
UNITS = {"gb", "s", "w"}                                            # a unit after a quantity is part of it
NAME_PARTS = {"rtx": 1, "nemotron": 1}                              # RTX 3090, NEMOTRON 3.5: the number is a name


def read_units(strings):
    """(words, numbers) over a group of strings, each distinct string counted once."""
    words = nums = 0
    for s in dict.fromkeys(strings):
        toks = [w for w in re.split(r"[\s·]+", s) if w]
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


# ---- the timeline --------------------------------------------------------------------------------------------------
# (id, beats, groups): a group is (name, landing beat, how it lands, [copy keys]); a race group may land at a tape time
# instead ("done" = the slower lane's last token).
SHOTS = [
    ("title",  8,  [("lockup", 0, "slam", ["name", "version"])]),
    ("race",   36, [("setup", 1, "rise", ["model", "size", "card_line", "vram", "eng_ours", "eng_lcpp", "foot"]),
                    ("finish", "done", "stamp", ["tps_ours", "tps_lcpp", "tok_s", "clock_end"])]),
    ("sparks", 16, [("sparks", 3, "slam", ["sp_head", "sp_ds", "sp_ds_gb", "sp_glm", "sp_mem", "sp_link", "sp_by"])]),
    ("end",    11, [("lockup", 2, "rise", ["name", "version", "url"])]),
]
GO_BEAT = 2          # the race's beat its two requests are sent on (the lamps go out)


def timeline(music, lanes):
    P, first = music["period_s"], music["first_beat_s"]
    on = lambda b: max(0.0, b * P - LEAD)
    nb = sum(x[1] for x in SHOTS)
    if OPEN_AT + nb != END_BEAT: die("timing", f"the film's {nb} beats from track beat {OPEN_AT} end on {OPEN_AT + nb}, not {END_BEAT}")
    segs, events, b = [], [], 0
    for sid, beats, groups in SHOTS:
        S = {"id": sid, "kind": "tape" if sid == "race" else "card", "b0": b, "len": beats, "b1": b + beats,
             "t0": round(on(b), 6), "t1": round(on(b + beats), 6), "land": {}, "cue": {}, "groups": []}
        events.append([f"cut {sid}", S["t0"], None])
        for name, at, how, keys in groups:
            if at == "done":
                go = on(b + GO_BEAT)
                t_land = go + max(l["done_s"] for l in lanes)
                S["go"] = round(go, 6)
                events.append([f"enter {sid}.{name}", round(t_land, 6), None])
            else:
                t_land = on(b + at)
                S["land"][name] = at
                if at: events.append([f"slam {sid}.{name}", round(t_land, 6), None])
            still = t_land + SETTLE[how]
            S["groups"].append({"name": name, "keys": keys, "land": round(t_land, 6), "still": round(still, 6), "how": how})
        segs.append(S)
        b += beats
    return segs, events, nb, on


def main():
    beats = json.loads((HERE / "beats.json").read_text())
    music = {"id": MUSIC_ID, **{k: v for k, v in beats[MUSIC_ID].items() if k != "loud_db"}}
    ours, lcpp = pair()
    src = sources()
    copy, cites = cite(src)
    clock_end = max(ours["done_s"], lcpp["done_s"])
    copy.update({
        "model": ours["model"], "size": ours["size"],
        "card_line": f"ONE {ours['card'].upper()}", "vram": f"{round(ours['vram_gib'])} GB",
        "eng_ours": ours["engine"], "eng_lcpp": lcpp["engine"],
        "foot": f"{ours['prompt_n']:,}-token prompt · greedy · real time",
        "tps_ours": ours["tps"], "tps_lcpp": lcpp["tps"], "tok_s": "tok/s",
        "clock_end": f"{clock_end:.2f} s",
        "instruction": "› " + ours["instruction"],
    })
    for k in ("model", "size", "card_line", "vram", "eng_ours", "eng_lcpp", "foot", "tps_ours", "tps_lcpp", "clock_end", "instruction"):
        cites[k] = ["tape"]
    cites["tok_s"] = ["unit"]
    segs, events, nb, on = timeline(music, [ours, lcpp])
    P = music["period_s"]
    T = round(nb * P, 4)
    # every group's read against the time it holds still before the cut; the race's groups together as well
    rows = []
    for S in segs:
        tot = 0.0
        for g in S["groups"]:
            strings = [copy[k] for k in g["keys"]]
            need, w, n = read_s(strings)
            g.update({"read_s": round(need, 3), "words": w, "numbers": n, "strings": strings})
            have = S["t1"] - g["still"]
            if have + 1e-9 < need: die("timing", f"{S['id']}.{g['name']} holds {have:.3f} s, its read needs {need:.3f} s")
            tot += need
            rows.append((S["id"], g["name"], w, n, need, have))
        if len(S["groups"]) > 1 and S["t1"] - S["groups"][0]["still"] + 1e-9 < tot:
            die("timing", f"{S['id']}: its groups need {tot:.3f} s together, the shot holds {S['t1'] - S['groups'][0]['still']:.3f} s")
    race = next(S for S in segs if S["id"] == "race")
    for L in (ours, lcpp):
        events.append([f"enter race.first.{L['id']}", round(race["go"] + L["ttft_s"], 6), None])
        events.append([f"enter race.done.{L['id']}", round(race["go"] + L["done_s"], 6), None])
    at = round(music["first_beat_s"] + OPEN_AT * P, 4)
    tl = {"T": T, "at": at, "period": P, "first": round(music["first_beat_s"] + OPEN_AT * P - at, 6), "lead": LEAD,
          "open_at_beat": OPEN_AT, "end_beat": END_BEAT, "nbeats": nb,
          "beats": [round(k * P, 4) for k in range(nb + 1)], "segments": segs,
          "events": sorted(events, key=lambda e: e[1]), "fade_out_s": FADE_OUT_S, "go_beat": GO_BEAT}
    music["url"] = ""
    data = {"film": "release-034-v3", "music": music, "timeline": tl, "copy": copy, "sources": cites,
            "lanes": [{k: v for k, v in L.items() if k not in ("prompt_sha",)} for L in (ours, lcpp)],
            "clock_end_s": clock_end, "notes": {"draft": False, "path": str(NOTES), "readme_rev": README_REV}}
    (HERE / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    print(f"data.json: T {T} s = {nb} beats of {P} s ({music['bpm']} BPM), track {MUSIC_ID} from {at} s (beat {OPEN_AT}) "
          f"to beat {END_BEAT}; fade {FADE_OUT_S} s")
    for L in (ours, lcpp):
        print(f"  lane {L['id']}: {L['tape']} {L['engine']} on {L['card']}: first token {L['ttft_s']:.3f} s, last {L['done_s']:.3f} s, "
              f"{len(L['toks'])} tokens, {L['tps']} tok/s")
    print(f"  race: GO {race['go']:.3f} s, the slower lane done at {race['go'] + clock_end:.3f} s, cut {race['t1']:.3f} s")
    print("shot    group    words nums  read  holds")
    for sid, g, w, n, need, have in rows: print(f"{sid:7} {g:8} {w:5} {n:4} {need:5.2f} {have:6.2f}")


if __name__ == "__main__":
    main()
