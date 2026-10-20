"""A listening screen of the 0.3.4 film's candidates that passed screen.py, by gemini-3.8-flash-high through agy.

  python3 musicgen/listen.py CALIBRATION.mp3 CLIP.mp3 ...      (absolute or relative paths; results beside each clip)
  python3 musicgen/listen.py --screen CLIP.mp3 ...              (after a calibration that did not pass: no verdict,
                                                                 each row and .listen.json is marked a screen)

Each file is judged by two independent agy calls with the same rubric; a field counts only where both calls agree.
The calibration file (0.3.1's generated big-band take, shout-s1001, from our own render's music) must come back as
not electronic, with brass and with no synth bass, in both calls, or the run stops: an ear that calls a big band
electronic cannot pick among electronic takes.
The prompt names no file's origin, no model and no other candidate. Each call also says where the music first gets
bigger (drop_s counts when both calls name a second within 1 s), to check beats.py's drop by ear. Writes
<clip>.listen.json and prints one row each.
"""
import json, re, subprocess, sys
from pathlib import Path

# The prompt asks for what is heard in the listener's own words, so it names nothing the file should contain; the
# fields are read from those words here.
PROMPT = """Open the audio file {path} with your audio/file reading tool and listen to all of it. Do not use shell
commands. Then answer with one JSON object and nothing else:
{{"heard": "one sentence on what you hear", "instruments": ["each instrument you clearly hear"],
 "genre": "the genre in a few words", "voice": true or false (any singing or speech),
 "glitches": "none", "minor" or "major", "energy": 1 to 5, "ending": "how the last two seconds end",
 "drop": the second at which the music first becomes clearly bigger and fuller, as a number, or null if it never does}}"""
CLASSES = {"electronic": r"electronic|edm|drum and bass|drum & bass|dnb|breakbeat|electro|techno|house|dubstep|"
                         r"bass music|synth|trap|glitch",
           "synth_bass": r"synth bass|bass synth|reese|sub bass|sub-bass|808|synthesizer bass|wobble",
           "brass": r"trumpet|trombone|brass|horn|sax", "drums": r"drum|breakbeat|kick|snare|hi-hat|hihat"}
FIELDS = ["electronic", "synth_bass", "brass", "drums", "voice", "glitches", "energy"]


def classify(a):
    words = " ".join([a.get("genre", ""), " ".join(a.get("instruments", []))]).lower()
    out = {k: bool(re.search(rx, words if k != "electronic" else a.get("genre", "").lower())) for k, rx in CLASSES.items()}
    if a.get("glitches") not in ("none", "minor", "major") or a.get("energy") not in (1, 2, 3, 4, 5) \
            or not isinstance(a.get("voice"), bool):
        sys.exit(f"listen.py: an answer outside its fields: {a}")
    return out | {"voice": a["voice"], "glitches": a["glitches"], "energy": a["energy"]}


def ask(path):
    cmd = ["agy", "-p", PROMPT.format(path=path), "--model", "gemini-3.8-flash-high", "--dangerously-skip-permissions",
           "--print-timeout", "4m", "--output-format", "json"]
    r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
    try:
        ev = json.loads(r.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        sys.exit(f"listen.py: agy gave no JSON for {path} (rc {r.returncode}): {r.stderr[-300:]}")
    if str(ev.get("status")).upper() != "SUCCESS":     # agy exits 0 on a failed turn; its result event says
        sys.exit(f"listen.py: agy's result for {path} is {ev.get('status')!r}: {str(ev)[:300]}")
    m = re.search(r"\{.*\}", ev.get("response") or "", re.S)      # the answer's JSON object, inside any prose or fence
    if not m:
        sys.exit(f"listen.py: agy's answer for {path} holds no JSON object: {(ev.get('response') or '')[:300]!r}")
    return json.loads(m.group(0))


def judge(path, screen=False):
    a, b = ask(path), ask(path)
    ca, cb = classify(a), classify(b)
    agreed = {k: ca[k] for k in FIELDS if ca[k] == cb[k]}
    da, db = a.get("drop"), b.get("drop")      # heard where it gets bigger; agreed when both name one within 1 s
    if isinstance(da, (int, float)) and isinstance(db, (int, float)) and abs(da - db) <= 1.0:
        agreed["drop_s"] = round((da + db) / 2, 2)
    out = {"file": str(path), "calls": [a, b], "agreed": agreed, "screen_only": screen}
    Path(f"{path}.listen.json").write_text(json.dumps(out, indent=1) + "\n")
    return agreed


def main():
    screen = sys.argv[1:2] == ["--screen"]      # after a calibration that did not pass: rows are a screen, not a verdict
    args = sys.argv[2:] if screen else sys.argv[1:]
    if len(args) < (1 if screen else 2):
        sys.exit(__doc__)
    if screen:
        clips = [Path(p).resolve() for p in args]
        print("listen.py --screen: no calibration in this run; every row is a screen, not a verdict")
    else:
        cal, clips = Path(args[0]).resolve(), [Path(p).resolve() for p in args[1:]]
        c = judge(cal)
        if not (c.get("electronic") is False and c.get("synth_bass") is False and c.get("brass") is True):
            sys.exit(f"listen.py: the calibration came back {c}; not judging the candidates (--screen judges them as a "
                     f"screen only)")
        print(f"calibration {cal.name}: {c}")
    for p in clips:
        g = judge(p, screen)
        print(f"{p.name}: " + ", ".join(f"{k}={g.get(k, '?')}" for k in FIELDS + ["drop_s"]), flush=True)


if __name__ == "__main__":
    main()
