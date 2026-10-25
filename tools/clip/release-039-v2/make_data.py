"""Build data.json for the 0.3.9 film v2 (film.html): every string it draws (each number checked against the source it
cites, a rounded hero against the measured value it rounds), every figure a bar or a volume is drawn from, and
every time a station flies in and a group lands, from the track's beat grid.

  python3 make_data.py              writes data.json and prints the read table
  MAC=<file>                        the Mac numbers (default sources/mac-numbers.md, a copy of the Mac session's
                                    ~/.cache/bloomery/clip039/mac-numbers.md; copy it again when that file moves)

Sources (all under sources/): spec.md (the draft round's spec: the NVIDIA table, the residency and NVFP4-tile rows, the
byte figures, the contributors' list), spec-v2.md (this round's spec: the hero list and its rounding), mac-numbers.md,
release-notes-0.3.9.md, prs/<n>.md (`gh pr view <n> --repo midagedev/bloomery`) and lead-2026-10-25.md (the lead's
weight-file byte sums and @avlp12's 0.3.9 Ultra rows). A string's numbers must each be found in one of the sources it cites; a hero shown rounded
names the measured value it rounds (`approx`), which must itself be in a cited source and round half-up to the shown
digits; a ratio shown (2×) names its two measured ends. A mismatch stops the build by name (rc 4).

Timing: the storyboard (DESIGN.md) fixes each station's beats and each group's landing beat. A group holds still for
its read time (4 words a second plus 1 s a number, at least 2.5 s) from its settle to the flight out of its station,
which starts one beat before the next station's first beat; a station's groups are read one after another. The track
is cut from instrument-s1004 (0.3.6's) by bars (ARRANGEMENT): the drop on the title (film beat 1), the breakdown's
hit on the Apple Silicon cut (77), the E bar on the END (185).
"""
import gzip, json, math, os, re, sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "sources"
FPS = 60
LEAD = 0.5 / FPS          # every switch is computed half a frame before its beat: the picture leads, never lags
MUSIC_ID = "instrument-s1004"
READ_WPS, READ_NUM_S, READ_MIN_S = 4.0, 1.0, 2.5
EXIT = {"usage": 2, "source": 4, "timing": 5}
T_MAX = 120.0
# the track from its lead-in beat straight through bar 99, then the draft's last two stretches (the Apple Silicon hit,
# track 127, and the E bar, 203, keep their places in the film); splice.py check measures the two joins
ARRANGEMENT = [(30, 99), (119, 183), (151, 211)]
FADE_BEATS = 2
FLIGHT_BEATS = 1.0        # a station's flight out starts this many beats before the next station's first beat


def die(name, msg):
    print(f"make_data.py: refused ({name}): {msg}", file=sys.stderr)
    sys.exit(EXIT[name])


# ---- the sources -----------------------------------------------------------------------------------------------------
def norm(s):
    return s.replace(",", "").replace(" ", " ").replace("−", "-").replace("–", "-")


TEXT = {"spec": (SRC / "spec.md").read_text(), "spec2": (SRC / "spec-v2.md").read_text(),
        "mac": Path(os.environ.get("MAC", SRC / "mac-numbers.md")).read_text(),
        "notes": (SRC / "release-notes-0.3.9.md").read_text(),
        # the lead's corrections (weight-file byte sums; @avlp12's #593 Ultra rows at 0.3.9)
        "lead": (SRC / "lead-2026-10-25.md").read_text()}
for p in (SRC / "prs").glob("*.md"): TEXT[f"pr{p.stem}"] = p.read_text()
TEXT_N = {k: norm(v) for k, v in TEXT.items()}


# ---- reading: words and numbers --------------------------------------------------------------------------------------
# A number: a measured or sized quantity, with an optional sign, a depth mark (@, pp) and a unit glued on (%, ×, -token);
# a range (16-19 %) is two. Names with digits (M3.1, Qwen3.6-35B-A3B, b11827, Q4_K_M, 0.3.9, 816B-A42B) are words.
NUM = re.compile(r"^[+−-]?(pp|@)?\d[\d,]*(\.\d+)?(%|×|-token|-row|-id)?$")
RANGE = re.compile(r"^[+−-]?\d[\d,.]*[–-]\d[\d,.]*%?$")
UNITS = {"ms", "s", "%", "tok/s", "tokens", "ids", "gb", "gib", "w", "id"}
SEP = re.compile(r"[\s·→|]+")
CARDS = {"a6000", "3090"}


def read_units(strings):
    """(words, numbers) over a group's strings, each distinct string counted once."""
    words = nums = 0
    for s in dict.fromkeys(strings):
        toks = [t.strip(".,;:()'\"") for t in SEP.split(s)]
        toks = [t for t in toks if t and t not in ("+", "=", "/", "-", "—", "&", "vs")]
        i = 0
        while i < len(toks):
            w = toks[i]
            if w.lower() == "rtx" and i + 1 < len(toks):      # RTX A6000 is one name
                words += 1; i += 2; continue
            if w.lower() in CARDS:                             # a card named alone (A6000, 3090) is a word
                words += 1; i += 1; continue
            if RANGE.match(w):
                nums += 2; i += 1
            elif NUM.match(w):
                nums += 1; i += 1
            else:
                words += 1; i += 1; continue
            if i < len(toks) and toks[i].lower() in UNITS: i += 1
    return words, nums


def read_s(strings):
    w, n = read_units(strings)
    return max(READ_MIN_S, w / READ_WPS + n * READ_NUM_S), w, n


# ---- the strings -----------------------------------------------------------------------------------------------------
def numbers_in(s):
    """The quantities a string states (not the digits of a name): each token that reads as a number or a range."""
    out = []
    for t in SEP.split(s):
        t = t.strip(".,;:()'\"")
        if RANGE.match(t): out += re.split(r"[–-]", t.lstrip("+−-").rstrip("%"))
        elif NUM.match(t): out.append(re.sub(r"^[+−-]?(pp|@)?", "", t).rstrip("%×").split("-")[0])
    return [norm(x) for x in out if x]


def found(n, src):
    return re.search(r"(?<![\d.])" + re.escape(n) + r"(?!\d|\.\d)", TEXT_N[src]) is not None


def rounds_to(measured, shown):
    """True when the measured value (a source string) rounds half-up to the shown one at the shown precision."""
    q = Decimal(1).scaleb(-len(shown.split(".")[1])) if "." in shown else Decimal(1)
    return Decimal(measured).quantize(q, rounding=ROUND_HALF_UP) == Decimal(shown)


COPY, CITES, HEROES = {}, {}, {}


def put(key, s, *cites, approx=None, ratio=None):
    """A string and its sources. Each number in it must be in one of the cited texts, or be a key of approx whose
    value (the measured number, as the source writes it) is in a cited text and rounds half-up to it; ratio=(shown,
    a, b) holds a shown ratio (2×) to two measured ends a and b, each in a cited text, with round(b / a) == shown."""
    if key in COPY: die("source", f"copy key {key} twice")
    for c in cites:
        if c != "label" and c not in TEXT: die("source", f"{key}: no source {c}")
    srcs = [c for c in cites if c in TEXT]
    approx = approx or {}
    for n in numbers_in(s):
        if ratio and n == ratio[0]:
            shown, a, b = ratio
            for x in (a, b):
                if not any(found(norm(x), c) for c in srcs): die("source", f"{key}: ratio end {x} is in none of {cites}")
            if round(float(b) / float(a)) != int(shown):
                die("source", f"{key}: {b}/{a} = {float(b) / float(a):.3f} does not round to {shown}")
            CITES.setdefault(key, []).append(f"{shown}× = {b} / {a} = {float(b) / float(a):.3f} [derived]")
            continue
        if n in approx:
            m = approx[n]
            if not any(found(norm(m), c) for c in srcs): die("source", f"{key}: measured {m} is in none of {cites}")
            if not rounds_to(norm(m), n): die("source", f"{key}: {m} does not round to {n}")
            CITES.setdefault(key, []).append(f"{n} rounds {m}")
            continue
        if not any(found(n, c) for c in srcs):
            die("source", f"{key}: {n} in {s!r} is in none of {cites}")
    for n in approx:
        if n not in numbers_in(s): die("source", f"{key}: approx names {n}, which {s!r} does not show")
    COPY[key] = s
    CITES[key] = CITES.get(key, []) + list(cites)


def hero(key, s, *cites, value, **kw):
    """A hero number: the string, and the value its count-up lands on (the shown number, for the bar it may draw)."""
    put(key, s, *cites, **kw)
    HEROES[key] = value


def build_copy():
    # chapter marks (screen space, quiet)
    put("h_nv", "NVIDIA", "label"); put("h_k", "CONTRIBUTORS", "label"); put("h_ap", "APPLE SILICON", "label")
    # TITLE
    put("name", "bloomery", "label")
    put("version", "0.3.9", "notes")
    put("t_nv", "NVIDIA", "label"); put("t_nv1", "two giant models", "spec")
    put("t_ap", "APPLE SILICON", "label"); put("t_ap1", "its own Metal backend", "spec")
    # BYTES (the lead's weight-file sums 225.6 GB and 250.1 GB, replacing the spec's whole-folder 227.75 and 252.45)
    put("b_muse", "Muse Spark Open", "spec")
    hero("b_muse_v", "226 GB", "lead", value=226, approx={"226": "225.6"})
    put("b_mm", "MiniMax-M3.1-Flash", "spec")
    hero("b_mm_v", "250 GB", "lead", value=250, approx={"250": "250.1"})
    # the cards' 72 GB, a label on the glass vessel (the station's two heroes are the models); "neither model fits"
    put("v_cards_v", "72 GB", "spec")
    put("v_cards", "RTX A6000 + RTX 3090", "spec")
    put("v_fit", "Neither model fits.", "spec")
    # the answer, the M3.1 card's headline (spec: "the cards hold the hot part and the host tier runs the rest")
    put("m_run", "bloomery runs both.", "spec")
    # M3.1 on the two cards (spec table: decode @512 21.03, pp512 122.57; spec-v2: 21 and 123)
    put("m_head", "MiniMax-M3.1-Flash", "spec")
    hero("m_d", "21 tok/s", "spec", "spec2", value=21, approx={"21": "21.03"}); put("m_dl", "decode", "spec")
    hero("m_p", "123 tok/s", "spec", "spec2", value=123, approx={"123": "122.57"}); put("m_pl", "prompt", "spec")
    put("m_muse", "Muse Spark Open · 16.7 tok/s decode", "spec", "spec2", approx={"16.7": "16.65"})
    put("m_cond", "RTX A6000 + RTX 3090 · serving defaults", "spec")
    put("m_jk", "card experts run @juliankang4's NVFP4 kernels", "notes", "spec")
    # THANKS (each number in its pull request's body; spec-v2: prefill ×2 (+98 %), four requests 28 → 56)
    put("k_name", "@juliankang4", "spec")
    put("k_sub", "measured on his DGX Spark", "spec")
    hero("k1_v", "2×", "pr668", "spec2", value=2, ratio=("2", "393.3", "779.7"))
    put("k1_l", "4,096-token prefill", "pr668"); put("k1_c", "NVFP4 checkpoint · +98 %", "pr668", approx={"98": "98.2"})
    hero("k2_v", "28 → 56 tok/s", "pr703", "spec2", value=56, approx={"28": "28.29", "56": "55.80"})
    put("k2_l", "Qwen3.8 · four requests at once", "pr703", "spec")
    put("k_w1", "the FP4-Local folder reader", "notes"); put("k_w2", "the new start screen", "notes")
    put("k_bg", "@Burntgogi", "spec"); put("k_bg1", "shared model code · Flint groundwork", "notes")
    # APPLE SILICON
    put("a_head", "Apple Silicon", "label")
    put("a_srv", "bloomery-serve-metal", "mac"); put("a_own", "its own Metal backend", "spec")
    put("a_l1", "Qwen3.6-35B-A3B on Mac GPUs", "mac")
    put("a_l2", "MLX 4-bit checkpoints via prepare", "mac"); put("a_l3", "prefix reuse", "mac")
    # M4 PRO, one sitting (mac-numbers 4b decode, 4a prompt at 4096 ids; spec-v2's rounding)
    put("r_tag", "M4 PRO · DECODE", "mac"); put("r_unit", "tok/s", "label")
    put("r_p1", "same MLX 4-bit weights", "mac"); put("r_p2", "same Q4_K_M file", "mac")
    put("r_bl", "bloomery", "mac"); put("r_mlx", "mlx-lm 0.32.2", "mac"); put("r_lcpp", "llama.cpp b11827", "mac")
    hero("r_d1", "101", "mac", "spec2", value=101, approx={"101": "101.2"})
    hero("r_d2", "93", "mac", "spec2", value=93, approx={"93": "93.0"})
    hero("r_d3", "86", "mac", "spec2", value=86, approx={"86": "85.6"})
    hero("r_d4", "66", "mac", "spec2", value=66, approx={"66": "66.2"})
    put("r_cond", "Qwen3.6-35B-A3B · short prompt · three rounds · development loop", "mac")
    put("q_tag", "M4 PRO · PROMPT · 4,096 IDS", "mac")
    hero("q_1", "1,077", "mac", "spec2", value=1077, approx={"1077": "1076.5"})
    hero("q_2", "1,038", "mac", "spec2", value=1038, approx={"1038": "1038.0"})
    hero("q_3", "1,045", "mac", "spec2", value=1045, approx={"1045": "1044.5"})
    hero("q_4", "825", "mac", "spec2", value=825, approx={"825": "825.1"})
    put("q_cond", "random token ids · one sitting · development loop", "mac")
    # the Ultras (@avlp12 on #593 at 0.3.9, the lead's note): a caption-level moment, the M4 pairs stay the heroes
    put("u_line", "M5 Ultra, measured by @avlp12", "lead")
    # before -> after on one file (Q4_K_M): #777's head (SIMD-group) to 0.3.9 (neural-accelerator GEMMs, #796)
    put("u_q", "Q4_K_M", "lead")
    put("u_m5", "3,831 → 5,972 tok/s prompt @4,096 · 212 tok/s decode", "lead", approx={"3831": "3830.9", "5972": "5971.8"})
    put("u_na", "0.3.9 · neural-accelerator GEMMs", "lead")
    # mlx-lm ran its own MLX 4-bit weights, another file: words only, never a bar on our bar's scale
    put("u_mlx", "mlx-lm on its own MLX 4-bit weights: 10,162 tok/s — still ahead", "lead", approx={"10162": "10162.3"})
    # the 0.3.9 prompt steps (mac-numbers 3), words only
    put("p_tag", "0.3.9 · PROMPTS ON THE MAC", "label")
    put("p_1", "batched prompt passes", "mac"); put("p_2", "experts in 64-row tiles", "mac")
    put("p_3", "less fixed cost per prompt call", "mac")
    put("p_4", "M5 neural accelerators", "spec"); put("p_4s", "picked by the device", "mac", "spec")
    # END
    put("url", "github.com/midagedev/bloomery", "label")


# ---- the figures the volumes and bars are drawn from (each the source's own value) -------------------------------------
def figures():
    return {
        # the weight files' bytes (the lead's measurement), the cards' memory
        "size": {"muse": 225.6, "mm": 250.1, "a6000": 48.0, "r3090": 24.0, "cards": 72.0},
        # #668's 4,096-token prefill, #703's four requests: before, after
        "thanks": {"pre": [393.3, 779.7], "four": [28.29, 55.80]},
        # M4 Pro, one sitting: [bloomery, other] per pair (mac-numbers 4b decode, 4a prompt at 4096 ids)
        "m4": {"dec": [[101.2, 93.0], [85.6, 66.2]], "pp": [[1076.5, 1038.0], [1044.5, 825.1]]},
        # M5 Ultra prompt at 4,096 ids (@avlp12, #593): bloomery Q4_K_M at #777's head and at 0.3.9 (one file, one bar);
        # mlx-lm's 10,162.3 ran other weights and is a caption, so no figure draws it
        "ultra": {"m5": [3830.9, 5971.8]},
    }


def check_figures(fig):
    """Every figure is a number a source states (so no mark is drawn from a number of its own)."""
    flat = []
    def walk(v):
        if isinstance(v, dict): [walk(w) for w in v.values()]
        elif isinstance(v, list): [walk(w) for w in v]
        else: flat.append(v)
    walk(fig)
    for x in flat:
        variants = {norm(f"{x:g}"), norm(f"{x:.2f}"), norm(f"{x:.1f}")}
        if not any(found(v, src) for v in variants for src in ("spec", "mac", "pr668", "pr703", "lead")):
            die("source", f"figure {x} is in neither the spec, mac-numbers.md, the lead's corrections nor the contributors' pull requests")


# ---- the storyboard (DESIGN.md) ------------------------------------------------------------------------------------------
# (station, first beat, [(group, landing beat, settle beats after landing, [copy keys])]). A station runs to the next
# one's first beat; its flight out starts FLIGHT_BEATS before that. Chapter marks are read with their part's first group.
PARTS = {"nvidia": (0, 46, "h_nv"), "thanks": (46, 77, "h_k"), "apple": (77, 185, "h_ap"), "end": (185, 193, None)}
STORY = [
    ("title", 0, [("lockup", 1, 2.5, ["name", "version", "t_nv", "t_nv1", "t_ap", "t_ap1"])]),
    # one move: both monoliths rise and count, the vessel rises at b15, the bands and the headline at b17
    ("bytes", 11, [("fit", 12, 1, ["h_nv", "b_muse_v", "b_muse", "b_mm_v", "b_mm", "v_cards_v", "v_cards", "v_fit"])]),
    # the answer rises on the flight's landing (b26), the numbers count on the next beat (b27, done by b27.4)
    ("m31", 26, [("speed", 26, 1.5, ["m_run", "m_head", "m_d", "m_dl", "m_p", "m_pl", "m_muse"]),
                 ("jk", 33, 0.5, ["m_cond", "m_jk"])]),
    ("thanks", 46, [("name", 46, 1, ["h_k", "k_name", "k_sub"]),
                    ("pre", 50, 1, ["k1_v", "k1_l", "k1_c"]),
                    ("four", 58, 1, ["k2_v", "k2_l"]),
                    ("more", 68, 0.5, ["k_w1", "k_w2", "k_bg", "k_bg1"], ["pre", "four"])]),
    ("apple", 77, [("what", 77, 1.5, ["h_ap", "a_head", "a_srv", "a_own"]),
                   ("how", 82, 0.5, ["a_l1", "a_l2", "a_l3"])]),
    ("m4dec", 92, [("lab", 92, 0.5, ["r_tag", "r_unit", "r_cond"]),
                   ("p1", 93, 1, ["r_p1", "r_bl", "r_mlx", "r_d1", "r_d2"]),
                   ("p2", 97, 1, ["r_p2", "r_lcpp", "r_d3", "r_d4"])]),
    ("m4pp", 115, [("lab", 116, 0.5, ["q_tag", "q_cond"]),
                   ("p1", 117, 1, ["q_1", "q_2"]),
                   ("p2", 121, 1, ["q_3", "q_4"])]),
    ("ultras", 137, [("line", 137, 0.5, ["u_line", "u_q", "u_m5", "u_na"]),
                     ("cap", 149, 0.5, ["u_mlx"])]),
    ("steps", 160, [("s1", 160, 0.5, ["p_tag", "p_1"]),
                    ("s2", 166, 0.5, ["p_2"]),
                    ("s3", 172, 0.5, ["p_3"]),
                    ("s4", 178, 0.5, ["p_4", "p_4s"])]),
    ("end", 185, [("lockup", 185, 0.5, ["name", "version", "url"])]),
]


def main():
    beats_json = json.loads((HERE / "beats.json").read_text())
    music = {"id": MUSIC_ID, **{k: v for k, v in beats_json[MUSIC_ID].items() if k != "loud_db"}}
    P = music["period_s"]
    build_copy()
    fig = figures(); check_figures(fig)
    nb_total = sum(e - a for a, e in ARRANGEMENT)
    T = round(nb_total * P, 4)
    if T > T_MAX: die("timing", f"the film is {T} s ({nb_total} beats), over {T_MAX} s")
    on = lambda b: max(0.0, b * P - LEAD)
    # the hits: the drop (track 31) on the title's lockup, 127 on the Apple Silicon cut, E (203) on the END
    hits = {"drop": (31, 1), "hit127": (127, 77), "E": (203, 185)}
    for name, (tb, want) in hits.items():
        got, ob = None, 0         # the last stretch that plays the hit's beat unspliced from the bar before it
        for a, e in ARRANGEMENT:
            if a < tb < e or (a == tb and name != "drop"): got = ob + tb - a
            ob += e - a
        if got != want: die("timing", f"hit {name} (track beat {tb}) plays at film beat {got}, the storyboard needs {want}")
    seen_keys, segs, events, rows, late = set(), [], [], [], []
    for i, (sid, b0, groups) in enumerate(STORY):
        b1 = STORY[i + 1][1] if i + 1 < len(STORY) else nb_total
        out_b = b1 - FLIGHT_BEATS if i + 1 < len(STORY) else nb_total - FADE_BEATS
        S = {"id": sid, "b0": b0, "b1": b1, "t0": round(on(b0), 6), "t1": round(on(b1), 6), "out": round(on(out_b), 6),
             "groups": []}
        clock = None
        done = {}
        for name, at, settle_b, keys, *rest in groups:
            for r in (rest[0] if rest else []):      # a group that takes an earlier group's place lands after its read
                if on(at) + 1e-9 < done[r]:
                    late.append(f"{sid}.{name} lands at {on(at):.3f} s in {r}'s place, read until {done[r]:.3f} s")
            for k in keys:
                if k not in COPY: die("source", f"{sid}.{name}: no copy {k}")
            if not b0 <= at < b1: die("timing", f"{sid}.{name} lands at beat {at}, outside its station [{b0}, {b1})")
            need, w, n = read_s([COPY[k] for k in keys if not (k in seen_keys and k.startswith("h_"))])
            land, still = on(at), on(at + settle_b)
            clock = still if clock is None else max(clock, still)
            clock += need
            if clock > S["out"] + 1e-9:
                late.append(f"{sid}.{name}: read through {clock:.3f} s, the flight out starts at {S['out']:.3f} s")
            done[name] = clock
            S["groups"].append({"name": name, "keys": keys, "at": at, "land": round(land, 6), "still": round(still, 6),
                                "read_s": round(need, 3), "words": w, "numbers": n, "read_to": round(clock, 6)})
            rows.append((sid, name, w, n, need, S["out"] - still, S["out"] - clock))
            events.append([f"land {sid}.{name}", round(land, 6), None])
            seen_keys.update(keys)
        events.append([f"fly {sid}", S["t0"], None])
        segs.append(S)
    if late:
        print("station  group   words nums   read  hold  spare", file=sys.stderr)
        for r in rows: print(f"{r[0]:8} {r[1]:7} {r[2]:5} {r[3]:4} {r[4]:6.2f} {r[5]:5.2f} {r[6]:6.2f}", file=sys.stderr)
        die("timing", "; ".join(late))
    heroes_per = {}
    for S in segs:
        hs = [k for g in S["groups"] for k in g["keys"] if k in HEROES and not k.startswith(("r_d2", "r_d4", "q_2", "q_4"))]
        heroes_per[S["id"]] = hs
        if len(hs) > 2 and S["id"] not in ("m4dec", "m4pp"):
            die("timing", f"{S['id']} shows {len(hs)} hero numbers, the spec allows two")
    splices, ob = [], 0
    for (a, e), nxt in zip(ARRANGEMENT, ARRANGEMENT[1:] + [None]):
        ob += e - a
        if nxt: splices.append({"film_beat": ob, "t": round(ob * P, 6), "from_track_beat": e, "to_track_beat": nxt[0]})
    music.update({"arrangement": [list(x) for x in ARRANGEMENT], "splices": splices, "xfade_s": 0.015,
                  "open_at_beat": ARRANGEMENT[0][0]})
    tl = {"T": T, "at": round(music["first_beat_s"] + ARRANGEMENT[0][0] * P, 4), "period": P, "first": 0.0, "lead": LEAD,
          "nbeats": nb_total, "beats": [round(k * P, 4) for k in range(nb_total + 1)], "segments": segs,
          "events": sorted(events, key=lambda e: e[1]), "fade_out_s": round(FADE_BEATS * P, 6), "ticks": [],
          "hits": {k: v[1] for k, v in hits.items()}, "flight_beats": FLIGHT_BEATS}
    parts = {}
    for name, (a, b, _h) in PARTS.items():
        parts[name] = {"b0": a, "b1": b, "t0": round(on(a), 6), "t1": round(on(b), 6), "s": round((b - a) * P, 3),
                       "share": round((b - a) / nb_total, 4)}
    data = {"film": "release-039-v2", "music": music, "timeline": tl, "copy": COPY, "sources": CITES,
            "heroes": HEROES, "fig": fig, "parts": parts, "notes": {"draft": False}}
    (HERE / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    print(f"data.json: T {T} s = {nb_total} beats of {P} s ({music['bpm']} BPM), track {MUSIC_ID} from {tl['at']} s; "
          f"arrangement {ARRANGEMENT}")
    print("parts: " + "; ".join(f"{k} {v['s']:.2f} s ({v['share']:.1%})" for k, v in parts.items()))
    print("heroes: " + "; ".join(f"{k} {len(v)}" for k, v in heroes_per.items()))
    print("station  group   words nums   read  hold  spare")
    for r in rows: print(f"{r[0]:8} {r[1]:7} {r[2]:5} {r[3]:4} {r[4]:6.2f} {r[5]:5.2f} {r[6]:6.2f}")


if __name__ == "__main__":
    main()
