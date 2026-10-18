"""Build data.json for film.html: every string the 0.3.4 film draws, each checked against its source line, and every
time it cuts on, from the picked track's measured beat grid.

  python3 make_data.py
  MUSIC_ID=<id>        the track, a key of beats.json (default volt-s1004; beats.py measures a new one)
  OPEN_AT_BEAT=<k>     the track's beat the film opens on (default: the track's row in TRACKS, which puts the drop on
                       PROMPT's first beat, or the film's beats before PROMPT ahead of the track's drop)
  END_BEAT=<k>         the track's beat where its sound ends (default: the track's row in TRACKS)
  FADE_OUT_S=<s>       render.py's fade at the end (default 0.1: the track ends on its own cut)
  NOTES=<file>         the 0.3.4 release notes (default the lead's copy of the published body)
  README_REV=<rev>     the bloomery commit whose README.md the strings quote (default 9723698f2)

Sources: the release notes (the same text as https://github.com/midagedev/bloomery/releases/tag/v0.3.4) and
bloomery's README.md at README_REV. A string whose source line does not say what the string says stops the build by
name. The film draws only strings this file writes: film.html refuses any other.

Timing: a shot lasts its beats; a card lands its elements on its beats and then holds still for its read time (4 words
a second plus 1 s a number, at least 2.5 s), counted from its last element's settle; it ends on the first beat after
that. Every length is in beats, so another track is a data change: MUSIC_ID (and OPEN_AT_BEAT, END_BEAT for a track
not in TRACKS) re-times the whole film.
"""
import json, math, os, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).parent
FONTS = {"Anybody": HERE / "fonts/Anybody-VF.ttf", "Mono": HERE / "fonts/MartianMono-VF.ttf"}
FPS = 60
LEAD = 0.5 / FPS          # every switch is computed half a frame before its beat: the picture leads, never lags
NOTES = Path(os.environ.get("NOTES", "/Users/hckim/orca/briefs/reports/release-notes-0.3.4.md"))
BLOOMERY = Path(os.environ.get("BLOOMERY", "/Users/hckim/repo/bloomery"))
README_REV = os.environ.get("README_REV", "9723698f2")
MUSIC_ID = os.environ.get("MUSIC_ID", "volt-s1004")
FADE_OUT_S = float(os.environ.get("FADE_OUT_S", "0.1"))
T_MIN, T_MAX = 38.0, 44.0

# Each generated track's alignment, measured in phase 1 (DESIGN.md, Music): the beat the film opens on and the beat
# where the sound ends (the END card's pulse arrives on it and the lockup holds one beat over the tail).
TRACKS = {"volt-s1004": {"open_at": 23, "end_beat": 135},     # drop on clip beat 67 = PROMPT b0; cut at 47.43 s
          "volt-s1006": {"open_at": 12, "end_beat": 127}}     # no drop; sound ends at 44.65 s

READ_WPS, READ_NUM_S, READ_MIN_S = 4.0, 1.0, 2.5
# How long each kind of landing takes to settle (film.html's arrival curves): a slam, a mark drawing in, a tag rising,
# a slot swap (0.10 s out, 0.16 s in), a zoom-through and a follow pan; a squeeze runs SQUEEZE_BEATS.
SETTLE = {"slam": 0.20, "draw": 0.16, "rise": 0.16, "swap": 0.26, "zoom": 0.30, "pan": 0.30, "squeeze": 0.0}


def die(msg):
    sys.exit(f"make_data.py: {msg}")


# ---- sources -------------------------------------------------------------------------------------------------------
def sources():
    if not NOTES.exists():
        die(f"no release notes at {NOTES} (NOTES=<file>)")
    notes = NOTES.read_text().split("\n")
    try:
        readme = subprocess.run(["git", "-C", str(BLOOMERY), "show", f"{README_REV}:README.md"], capture_output=True,
                                text=True, check=True).stdout.split("\n")
    except subprocess.CalledProcessError as e:
        die(f"git show {README_REV}:README.md in {BLOOMERY}: {e.stderr.strip()}")
    return {"notes": notes, "README": readme}


def said(src, doc, n, quote):
    """Line n of doc (1-based) must hold quote."""
    line = src[doc][n - 1] if 0 < n <= len(src[doc]) else ""
    if quote not in line:
        die(f"{doc}:{n} does not say {quote!r} (it says {line[:120]!r})")
    return f"{doc}:{n}"


def words_of(s):
    return [w for w in re.split(r"[\s·,()|*`:]+", s.lower()) if w]


# The film's strings: key -> (string, [(doc, line, quote)], how it follows from the quotes). "words" means every word of
# the string (lower case, separators dropped) is a word of its quotes; anything else is the reason it is reworded.
STRINGS = {
    "name":        ("bloomery", [("notes", 1, "bloomery 0.3.4 adds")], "words"),
    "version":     ("0.3.4", [("notes", 1, "bloomery 0.3.4 adds")], "words"),
    "release":     ("RELEASE", [], "the film's tag, a label with no claim"),
    "bolt_tag":    ("NEMOTRON 3.5 BOLT", [("notes", 1, "Nemotron 3.5 Bolt 74B-A9B")], "words"),
    "b74":         ("74B", [("notes", 1, "Nemotron 3.5 Bolt 74B-A9B")], "the first half of 74B-A9B"),
    "a9b":         ("-A9B", [("notes", 1, "Nemotron 3.5 Bolt 74B-A9B")], "the second half of 74B-A9B"),
    "card":        ("RTX 3090", [("README", 159, "**One RTX 3090 24 GB**"),
                                 ("notes", 14, "| Decode at depth 4096, RTX 3090 (250 W) | 86.69 |")], "words"),
    "vram":        ("24 GB", [("README", 159, "**One RTX 3090 24 GB**")], "words"),
    "bolt_line":   ("the whole model on the card",
                    [("README", 168, "| Nemotron 3.5 Bolt 74B-A9B `24GB` (0.3.4) | the whole model on the card |")], "words"),
    "decode":      ("DECODE", [("notes", 14, "| Decode at depth 4096, RTX 3090 (250 W) | 86.69 |")], "words"),
    "unit":        ("TOK/S", [("notes", 5, "| | tok/s |")], "the table's unit, in caps"),
    "decode_n":    ("86.69", [("notes", 14, "| Decode at depth 4096, RTX 3090 (250 W) | 86.69 |")], "words"),
    "decode_cond": ("at depth 4096", [("notes", 14, "| Decode at depth 4096, RTX 3090 (250 W) | 86.69 |")], "words"),
    "rig":         ("RTX 3090 · 250 W", [("notes", 14, "| Decode at depth 4096, RTX 3090 (250 W) | 86.69 |"),
                                         ("notes", 12, "| Prompt 4096, RTX 3090 (250 W) | 2047.32 |")], "words"),
    "prompt":      ("PROMPT", [("notes", 12, "| Prompt 4096, RTX 3090 (250 W) | 2047.32 |")], "words"),
    "prompt_n":    ("2,047", [("notes", 12, "| Prompt 4096, RTX 3090 (250 W) | 2047.32 |"),
                              ("README", 168, "| 86.9 | 1,773 / 2,047 |")], "2047.32 to the token, as README prints it"),
    "prompt_cond": ("a 4096-token prompt", [("notes", 12, "| Prompt 4096, RTX 3090 (250 W) | 2047.32 |"),
                                            ("README", 161, "Prompt tok/s (P = 512 / 4096)")],
                    "'Prompt 4096' (a prompt of P = 4096 tokens) in words"),
    "spark_h1":    ("SEVERAL DGX SPARKS", [("README", 41, "Several DGX Sparks serve one model")], "words"),
    "spark_h2":    ("SERVE ONE MODEL", [("README", 41, "Several DGX Sparks serve one model")], "words"),
    "nvme":        ("NVMe", [("README", 41, "pages them from its own NVMe")], "words"),
    "spark_line":  ("each node pages its experts from its own NVMe",
                    [("README", 41, "a tier node on another Spark owns routed experts by id range and pages them from its own NVMe"),
                     ("notes", 71, "charges node 0 for row-table fills from NVMe")],
                    "README:41's tier node, and node 0's own fills from NVMe (notes:71), in one line"),
    "m_qwen":      ("Qwen3.8", [("notes", 73, "Qwen3.8 decodes across two Sparks")], "words"),
    "m_glm":       ("GLM-5.3-Flash", [("notes", 76, "GLM-5.3-Flash and DeepSeek-V4.1-Flash open a node expert tier")], "words"),
    "m_ds":        ("DeepSeek-V4.1-Flash", [("notes", 76, "GLM-5.3-Flash and DeepSeek-V4.1-Flash open a node expert tier")], "words"),
    "models_line": ("over RDMA · by @juliankang4",
                    [("notes", 67, "**Multi-node serving over RDMA (DGX Spark)**, by @juliankang4")], "words"),
    "embed_tag":   ("EmbeddingGemma 2 · EmbeddingGemma v1",
                    [("notes", 1, "over EmbeddingGemma 2 (#323) and EmbeddingGemma v1 (#390)")], "words"),
    "embed":       ("EMBEDDINGS", [("notes", 33, "`/v1/embeddings` beside the chat model")], "the endpoint's noun, in caps"),
    "embed_line":  ("beside the chat model", [("notes", 33, "`/v1/embeddings` beside the chat model")], "words"),
    "lane_text":   ("TEXT", [("notes", 33, "text, sampled video frames, mono 16 kHz f32 PCM audio")], "words"),
    "lane_video":  ("VIDEO", [("notes", 1, "with video frames and audio for EmbeddingGemma 2")], "words"),
    "lane_audio":  ("AUDIO", [("notes", 1, "with video frames and audio for EmbeddingGemma 2")], "words"),
    "endpoint":    ("/v1/embeddings", [("notes", 33, "`/v1/embeddings` beside the chat model")], "words"),
    "thanks":      ("thank you", [("notes", 165, "## Thanks")], "the section's head as a sentence"),
    "h_julian":    ("@juliankang4", [("notes", 167, "- @juliankang4: the multi-node tier link")], "words"),
    "c_julian":    ("multi-node tier · embeddings · audio",
                    [("notes", 167, "the multi-node tier link"),
                     ("notes", 168, "the EmbeddingGemma 2 encoder and the `/v1/embeddings` endpoint"),
                     ("notes", 169, "the gemma4a audio groundwork and audio tower")],
                    "three of the credits in a word each: the tier link, the embeddings endpoint, the audio tower"),
    "h_burnt":     ("@Burntgogi", [("notes", 172, "- @Burntgogi: the tokenizer codepoint refusal")], "words"),
    "c_burnt":     ("tokenizer · placement · gate fixes",
                    [("notes", 172, "the tokenizer codepoint refusal (#270)"),
                     ("notes", 173, "refusals (#359, #372), the gate strictness fixes")],
                    "three of the credits in a word each: the tokenizer, the placement overflow and the gate fixes"),
    "repo":        ("github.com/midagedev/bloomery", [("README", None, "github.com/midagedev/bloomery")], "the repository"),
}
# The measured rates the token grid runs at (one cell a token): the notes' own values.
RATES = {"decode": ("notes", 14, r"\| Decode at depth 4096, RTX 3090 \(250 W\) \| ([\d.]+) \|"),
         "prompt": ("notes", 12, r"\| Prompt 4096, RTX 3090 \(250 W\) \| ([\d.]+) \|")}


def check_strings(src):
    copy, cites = {}, {}
    for key, (s, quotes, how) in STRINGS.items():
        at = []
        for doc, n, q in quotes:
            if n is None:
                if not any(q in line for line in src[doc]):
                    die(f"{doc} never says {q!r} (string {key})")
                at.append(doc)
            else:
                at.append(said(src, doc, n, q))
        if how == "words":
            have = set(w for _, _, q in quotes for w in words_of(q))
            miss = [w for w in words_of(s) if w not in have]
            if miss:
                die(f"string {key} {s!r}: {miss} not in its quotes {at}")
        cites[key] = {"s": s, "src": at, "how": how}
        copy[key] = s
    n = float(re.search(RATES["prompt"][2], src["notes"][11]).group(1))
    if f"{round(n):,}" != copy["prompt_n"]:
        die(f"prompt_n {copy['prompt_n']!r} is not notes:12's {n} to the token")
    rates = {}
    for k, (doc, line, rx) in RATES.items():
        m = re.search(rx, src[doc][line - 1])
        if not m:
            die(f"{doc}:{line} has no {k} rate")
        rates[k] = float(m.group(1))
    if f"{rates['decode']:.2f}" != copy["decode_n"]:
        die(f"decode_n {copy['decode_n']!r} is not notes:14's {rates['decode']}")
    return copy, cites, rates


# ---- read time -----------------------------------------------------------------------------------------------------
QTY = re.compile(r"\d[\d,]*(\.\d+)?(-token)?|\d+B-A\d+B")   # 86.69, 2,047, 4096-token, 74B-A9B; not 0.3.4, v1, Qwen3.8
UNITS = {"GB", "W"}                                       # a unit after a quantity is part of it
NAME_NUM = {"RTX"}                                        # RTX 3090 is one name
NAME_VER = {"NEMOTRON", "EmbeddingGemma"}                 # a version after a name is a word: 3.5, 2
SEP = {"·"}


def read_units(strings):
    """(seconds, words, numbers) to read these strings: each distinct string once."""
    words = nums = 0
    for s in dict.fromkeys(strings):
        toks, i = s.split(), 0
        while i < len(toks):
            tok = toks[i]
            if tok in SEP:
                i += 1
                continue
            if tok in NAME_NUM and i + 1 < len(toks) and QTY.fullmatch(toks[i + 1]):
                words += 1
                i += 2
                continue
            if QTY.fullmatch(tok) and not (i and toks[i - 1] in NAME_VER):
                nums += 1
                i += 2 if i + 1 < len(toks) and toks[i + 1] in UNITS else 1
                continue
            words += 1
            i += 1
    return max(READ_MIN_S, words / READ_WPS + nums * READ_NUM_S), words, nums


# ---- the shot table ------------------------------------------------------------------------------------------------
# (id, kind, beats, landings, cues, read, drawn). Landings are (name, beat from the segment's first beat, how it lands):
# what is read lands; the card's read clock starts when the last one has settled. Cues are the current's beats (a
# strike, a fill, a run): on a beat, in the sync list, never on the read clock. A card's read strings are what its hold
# is read for (carried strings, read on the card before, are not counted again; "=s" is a string drawn in parts);
# drawn is every string the hold draws, which film.html checks. A shot has a fixed length in beats.
SHOTS = [
    ("leader", "shot", 4, [], [("step0", 0), ("step1", 1), ("step2", 2), ("step3", 3)], [], []),
    ("title", "card", None, [("version", 0, "slam"), ("name", 0, "squeeze"), ("release", 1, "rise")],
     [("strike", 0), ("run", 0)], ["version", "name", "release"], ["version", "name", "release"]),
    ("bolt", "card", None, [("b74", 0, "slam"), ("tag", 0, "rise"), ("squeeze", 2, "squeeze"), ("card", 2, "draw"),
                            ("vram", 3, "slam"), ("line", 3, "rise")],
     [("run_in", 0), ("fingers", 3)],
     ["bolt_tag", "card", "=74B-A9B", "vram", "bolt_line"], ["bolt_tag", "card", "b74", "a9b", "vram", "bolt_line"]),
    ("decode", "card", None, [("zoom", 0, "zoom")], [("fill", 1)],
     ["decode", "unit", "decode_n", "decode_cond", "rig"], ["decode", "unit", "decode_n", "decode_cond", "rig"]),
    ("prompt", "card", None, [("swap", 0, "swap")], [("flood", 0)],
     ["prompt", "prompt_n", "prompt_cond"], ["prompt", "unit", "prompt_n", "prompt_cond", "rig"]),
    ("sparks", "card", None, [("pan", 0, "pan"), ("node0", 1, "draw"), ("node1", 2, "draw"), ("line", 2, "rise")],
     [("page0", 3), ("page1", 4)], ["spark_h1", "spark_h2", "nvme", "spark_line"], ["spark_h1", "spark_h2", "nvme", "spark_line"]),
    ("models", "card", None, [("names", 0, "swap"), ("line", 1, "swap")], [("rdma", 1)],
     ["m_qwen", "m_glm", "m_ds", "models_line"], ["m_qwen", "m_glm", "m_ds", "nvme", "models_line"]),
    ("embed", "card", None, [("head", 0, "squeeze"), ("text", 1, "slam"), ("video", 2, "slam"), ("audio", 3, "slam"),
                             ("tag", 4, "rise"), ("endpoint", 5, "rise")], [("run", 4)],
     ["embed", "embed_line", "embed_tag", "lane_text", "lane_video", "lane_audio", "endpoint"],
     ["embed", "embed_line", "embed_tag", "lane_text", "lane_video", "lane_audio", "endpoint"]),
    ("thanks", "card", None, [("head", 0, "slam"), ("credits", 1, "rise")], [("collapse", 0), ("run", 1)],
     ["thanks", "h_julian", "c_julian", "h_burnt", "c_burnt"], ["thanks", "h_julian", "c_julian", "h_burnt", "c_burnt"]),
    ("end", "card", None, [("lockup", 0, "slam"), ("url", 1, "rise")], [("strike", 0), ("run", 3)],
     ["name", "version", "repo"], ["name", "version", "repo"]),
]
SQUEEZE_BEATS = 1         # a squeeze runs one beat from its landing; the card's read starts when it has settled
DROP_AT = "prompt"        # the track's drop lands on this segment's first beat
# Spare beats after the drop (the film ends on the track's cut, so the drop and the end fix the post-drop length),
# given in this order, each up to its cap, so cuts open bars; END holds whatever is left until the cut.
SPARE = [("embed", 1), ("thanks", 1)]


def timeline(music, copy):
    P = music["period_s"]
    row = TRACKS.get(MUSIC_ID, {})
    pre = []
    for sid, *_ in SHOTS:
        if sid == DROP_AT:
            break
        pre.append(sid)

    def beat_at(b):
        return round(b * P, 6)          # film time of film beat b (the film opens on a beat)

    def on(b):
        return max(0.0, round(b * P - LEAD, 6))

    segs, b = [], 0
    for sid, kind, beats, lands, cues, read, drawn in SHOTS:
        if kind == "shot":
            segs.append({"id": sid, "kind": kind, "b0": b, "len": beats, "land": {}, "cue": dict(cues)})
            b += beats
            continue
        last = max(k for _, k, _ in lands)
        settle = 0.0
        for name, k, how in lands:
            end = (k + SQUEEZE_BEATS) * P if how == "squeeze" else k * P + SETTLE[how]
            settle = max(settle, end - last * P)
        rs = [s[1:] if s.startswith("=") else copy[s] for s in read]
        need, w, n = read_units(rs)
        length = math.ceil(last + (settle + need) / P - 1e-9)
        segs.append({"id": sid, "kind": kind, "b0": b, "len": length, "min_len": length,
                     "land": {name: k for name, k, _ in lands}, "how": {name: how for name, _, how in lands},
                     "cue": dict(cues),
                     "last": last, "settle_s": round(settle, 4), "read": round(need, 3), "words": w, "numbers": n,
                     "read_strings": rs, "drawn": [copy[s] for s in drawn]})
        b += length
    by = {s["id"]: s for s in segs}
    pre_beats = by[DROP_AT]["b0"]
    open_at = int(os.environ["OPEN_AT_BEAT"]) if os.environ.get("OPEN_AT_BEAT") else row.get("open_at")
    if open_at is None:
        open_at = music["drop_beat"] - pre_beats
    end_beat = int(os.environ["END_BEAT"]) if os.environ.get("END_BEAT") else row.get("end_beat")
    if end_beat is None:
        die(f"no END_BEAT for {MUSIC_ID}: the beat where its sound ends (beats.json's loud_db falls off there)")
    if open_at + pre_beats != music["drop_beat"] and MUSIC_ID in ("volt-s1004",):
        die(f"PROMPT opens on track beat {open_at + pre_beats}, the drop is on {music['drop_beat']}")
    total = end_beat - open_at + 1           # the cut on END's pulse beat, then one still beat over the tail
    spare = total - sum(s["len"] for s in segs)
    if spare < 0:
        die(f"the film needs {sum(s['len'] for s in segs)} beats, the track gives {total} from beat {open_at}")
    for sid, cap in SPARE:
        add = min(cap, spare)
        by[sid]["len"] += add
        spare -= add
    by["end"]["len"] += spare
    b = 0
    for s in segs:
        s["b0"], s["b1"] = b, b + s["len"]
        s["t0"], s["t1"] = on(s["b0"]), on(s["b1"])
        b = s["b1"]
        if s["kind"] == "card":
            s["still"] = round(on(s["b0"] + s["last"]) + s["settle_s"], 4)
            if s["t1"] - s["still"] < s["read"] - 1e-6:
                die(f"card {s['id']} holds {s['t1'] - s['still']:.2f} s for a {s['read']} s read")
    end = by["end"]
    end["hit"] = end_beat - open_at - end["b0"]           # END's beat that the track's sound ends on
    end["cue"]["hit"] = end["hit"]
    if end["hit"] < end["min_len"] - 1:
        die(f"the track ends on END b{end['hit']}, before END's read")
    T = round(segs[-1]["b1"] * P, 4)
    if not T_MIN <= T <= T_MAX:
        die(f"the film runs {T} s, outside {T_MIN}..{T_MAX}")
    at = round(music["first_beat_s"] + open_at * P, 4)
    if at + T > music["length_s"] + 1e-6:
        die(f"the film runs {T} s from {at} s, past the track's {music['length_s']} s")
    first = round(music["first_beat_s"] + open_at * P - at, 6)
    events = []
    for s in segs:
        if s["b0"] > 0:
            events.append([f"cut {s['id']}", on(s["b0"]), None])
        for kind, d in (("land", s["land"]), ("cue", s["cue"])):
            for name, k in d.items():
                if k > 0:
                    events.append([f"{kind} {s['id']}.{name}", on(s["b0"] + k), None])
    return {"T": T, "at": at, "period": P, "first": first, "lead": LEAD, "open_at_beat": open_at, "end_beat": end_beat,
            "nbeats": segs[-1]["b1"], "drop_film_beat": by[DROP_AT]["b0"],
            "beats": [round(first + k * P, 4) for k in range(segs[-1]["b1"] + 1)],
            "segments": segs, "events": sorted(events, key=lambda e: e[1]), "fade_out_s": FADE_OUT_S}


def glyph_check(copy):
    """Every string is drawn in Anybody or Martian Mono; a character either face lacks is refused by name."""
    from fontTools.ttLib import TTFont
    cm = {k: set(TTFont(p).getBestCmap()) for k, p in FONTS.items()}
    bad = [(k, c) for k, s in copy.items() for c in s if c != " " and not all(ord(c) in m for m in cm.values())]
    if bad:
        die("characters with no glyph in a face: " + ", ".join(f"{k} {c!r} U+{ord(c):04X}" for k, c in bad[:12]))


def main():
    if sys.argv[1:]:
        sys.exit(__doc__)
    beats = json.loads((HERE / "beats.json").read_text())
    if MUSIC_ID not in beats:
        die(f"music {MUSIC_ID} is not in beats.json (python3 beats.py music/{MUSIC_ID}.mp3)")
    music = {"id": MUSIC_ID, **{k: v for k, v in beats[MUSIC_ID].items() if k != "loud_db"}}
    src = sources()
    copy, cites, rates = check_strings(src)
    glyph_check(copy)
    tl = timeline(music, copy)
    data = {"film": "release-034", "music": music, "timeline": tl, "copy": copy, "rates": rates, "sources": cites,
            "notes": {"draft": False, "path": str(NOTES), "readme_rev": README_REV}}
    (HERE / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    P = tl["period"]
    print(f"data.json: T {tl['T']} s = {tl['nbeats']} beats of {P} s ({music['bpm']} BPM), track {MUSIC_ID} from "
          f"{tl['at']} s (beat {tl['open_at_beat']}), drop on film beat {tl['drop_film_beat']}, sound ends on END "
          f"b{tl['segments'][-1]['hit']}; {len(tl['events'])} cuts and landings on beats; fade {FADE_OUT_S} s")
    print("shot     beats      seconds        settle  read  words nums  hold")
    for s in tl["segments"]:
        if s["kind"] == "shot":
            print(f"{s['id']:8s} {s['b0']:3d}-{s['b1']:<3d} {s['t0']:6.2f}-{s['t1']:<6.2f}")
            continue
        print(f"{s['id']:8s} {s['b0']:3d}-{s['b1']:<3d} {s['t0']:6.2f}-{s['t1']:<6.2f}  b{s['last']}+{s['settle_s']:.2f} "
              f"{s['read']:5.2f} {s['words']:5d} {s['numbers']:4d}  {s['t1'] - s['still']:5.2f}"
              + (f"  (+{s['len'] - s['min_len']} spare)" if s["len"] > s["min_len"] else ""))
    for k, c in cites.items():
        if c["how"] != "words":
            print(f"  {k:12s} {c['s']!r:44s} {', '.join(c['src']) or '-'}: {c['how']}")


if __name__ == "__main__":
    main()
