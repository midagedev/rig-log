"""Render film.html frame by frame.

  check             seek every frame and subframe (no pictures: window.NORASTER) and fail on any page error: text under
                    the floor or past the edge, a mark under its size floor, settled text overlapping, the pulse's head
                    near text, a card's hold not still, a string that is not in data.json, a character its face lacks;
                    F0/F1 check one frame range (the glyph check then covers that range's strings)
  probe t1 t2 ...   stills at those times -> probe/<PROBE_TAG or "main">/p_NN.png (1080), m_NN.png (the 540 px phone
                    view), and one sheet.png: each still at half size beside its phone view
  full              SUB subframes per frame (default 6), blended with tmix -> out/video.mp4; in the camera moves
                    each subframe is the mean of FAST_K draws (default 4; needs Pillow)
                    F0/F1 = frame range for one parallel chunk, NO_ENCODE=1 to skip the encode in chunks
  encode            encode sub/ into out/video.mp4 after the chunks finish, then lay the track under it ->
                    out/video-music.mp4. The track (music/<id>.mp3) and its start (MUSIC_AT) come from data.json;
                    MUSIC (a path) and MUSIC_AT override them, and a MUSIC whose file name is not data.json's track id
                    is refused: another track needs make_data.py (MUSIC_ID=<id>) first, which re-times the picture
  pops [file]       single-frame pop scan of out/video.mp4 (or file)
  flash [file]      WCAG 2.3.1 general-flash scan of out/video.mp4 (or file): at most 3 flashes in any 1 s
  sync [file]       the rhythm, measured on the output (out/video-music.mp4, or file): every cut or slam onset in the
                    picture against the beat grid, and the kick phase of its audio against the same grid

Serve this folder first: python3 -m http.server 8797 --bind 127.0.0.1 (FILM_URL overrides the page URL; FILM the id, default release-034-v3). The page
must say it is this film (window.FILM), so a server left over from another clip cannot pass for it.
The film's length T has one owner, data.json (make_data.py derives it from the beat grid); this file reads it there.

Adapted from render_template.py in https://github.com/howseen-ai/claude-motion-design:
  MIT License. Copyright (c) 2026 Howseen AI (Raphael Aubry).
  Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
  documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
  rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
  persons to whom the Software is furnished to do so, subject to the following conditions: The above copyright notice
  and this permission notice shall be included in all copies or substantial portions of the Software.
  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
  WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
  COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
  OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
Changes: 1080x1080, T and the track read from data.json, SUB from the environment, chunked frame ranges, separate
encode step, system ffmpeg, a pop scan, a page fault (bad data.json) stops the run by name, page errors fail the run,
a whole-film check pass with a glyph check, 540 px phone stills on one sheet, the film's identity, the sync scan.
"""
import asyncio, json, os, shutil, subprocess, sys
from pathlib import Path
import numpy as np
from playwright.async_api import async_playwright

HERE = Path(__file__).parent
FF = shutil.which("ffmpeg")
URL = os.environ.get("FILM_URL", "http://127.0.0.1:8797/film.html")
FILM = os.environ.get("FILM", "release-034-v3")
FPS, SUB = 60, int(os.environ.get("SUB", 6))
DATA = json.loads((HERE / "data.json").read_text())
T = DATA["timeline"]["T"]
PHONE = 540
FONTS = {"Anybody": HERE / "fonts/Anybody-VF.ttf", "AnybodyItalic": HERE / "fonts/Anybody-Italic-VF.ttf",
         "Mono": HERE / "fonts/MartianMono-VF.ttf"}


async def open_page(p):
    b = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required", *os.environ.get("CHROME_ARGS", "").split()])
    pg = await b.new_page(viewport={"width": 1080, "height": 1080}, device_scale_factor=1)
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append("console: " + m.text) if m.type in ("error", "warning") else None)
    await pg.goto(URL)
    await pg.wait_for_function("window.ready === true", timeout=120000)
    film, fault, t = await pg.evaluate("[window.FILM, window.fault || '', window.T]")
    if film != FILM:
        await b.close()
        sys.exit(f"{URL} serves {film!r}, not {FILM}: another clip's server is on this port")
    if fault:
        await b.close()
        sys.exit(f"film.html refused its data: {fault}")
    if abs(t - T) > 1e-9:
        await b.close()
        sys.exit(f"the page reads T {t}, data.json says {T}: the server serves another data.json")
    return b, pg, errs


async def shot(pg, t, path, fmt="png"):
    await pg.evaluate(f"window.seek({t})")
    el = await pg.query_selector("#stage")
    await el.screenshot(path=str(path), type=fmt, **({"quality": 95} if fmt == "jpeg" else {}))


def report(errs):
    """Page errors are defects (the film's floors and its data guard report through console.error): print, fail."""
    if not errs:
        print("PAGE ERRORS: 0")
        return
    uniq = list(dict.fromkeys(errs))
    print(f"PAGE ERRORS ({len(errs)}, {len(uniq)} distinct):")
    for e in uniq[:20]: print("  ", e)
    sys.exit(1)


def glyphs(drawn):
    from fontTools.ttLib import TTFont
    cmaps = {k: set(TTFont(p).getBestCmap()) for k, p in FONTS.items()}
    bad = {}
    for row in drawn:
        face, s = row.split("\t", 1)
        for c in s:
            if c not in "\n " and ord(c) not in cmaps[face]:
                bad.setdefault((face, c), s[:60])
    print(f"GLYPHS: {len(drawn)} strings drawn, {len(bad)} characters missing from their face")
    for (face, c), s in list(bad.items())[:20]: print(f"   {face} {c!r} U+{ord(c):04X} in {s!r}")
    return not bad


async def check():
    """Every time `full` draws: each frame's SUB subframe times, so a slam's overshoot between frames is held to the
    floors too, not only the frame centres."""
    n = int(round(T * FPS))
    f0, f1 = int(os.environ.get("F0", 0)), int(os.environ.get("F1", n + 1))
    offs = [(j - (SUB - 1) / 2) / (FPS * SUB) for j in range(SUB)]
    times = sorted({min(T - 1e-3, max(0.0, i / FPS + o)) for i in range(f0, f1) for o in offs + [0.0]})
    async with async_playwright() as p:
        b, pg, errs = await open_page(p)
        await pg.evaluate("window.LOG = new Set(); window.NORASTER = true")
        for t in times:
            await pg.evaluate(f"window.seek({t})")
        drawn = await pg.evaluate("Array.from(window.LOG)")
        await b.close()
    print(f"check: frames {f0}..{f1 - 1} of {n + 1} over {T} s, {len(times)} drawn times (each frame and its {SUB} subframes)")
    ok = glyphs(drawn)
    report(errs)
    if not ok: sys.exit(1)


async def probe(times):
    out = HERE / "probe" / os.environ.get("PROBE_TAG", "main"); shutil.rmtree(out, ignore_errors=True); out.mkdir(parents=True)
    async with async_playwright() as p:
        b, pg, errs = await open_page(p)
        for i, t in enumerate(times): await shot(pg, t, out / f"p_{i:02d}.png")
        await b.close()
    for i in range(len(times)):   # the phone view: each still at half size, area-averaged as a phone scales it
        subprocess.run([FF, "-v", "error", "-y", "-i", str(out / f"p_{i:02d}.png"), "-vf", f"scale={PHONE}:{PHONE}:flags=area",
                        str(out / f"m_{i:02d}.png")], check=True)
    # one sheet: per still, the 1080 frame at half size (lanczos, sharp) beside its phone view; two pairs a row
    n, cols = len(times), 2
    rows = -(-n // cols)
    inputs, filt = [], []
    for i in range(n):
        inputs += ["-i", str(out / f"p_{i:02d}.png"), "-i", str(out / f"m_{i:02d}.png")]
        filt.append(f"[{2 * i}:v]scale={PHONE}:{PHONE}:flags=lanczos[a{i}];[a{i}][{2 * i + 1}:v]hstack=2,"
                    f"pad=iw+12:ih+12:0:0:color=white[t{i}]")
    for i in range(n, rows * cols):
        filt.append(f"color=white:s={2 * PHONE + 12}x{PHONE + 12}:d=1[t{i}]")
    filt.append("".join(f"[t{i}]" for i in range(rows * cols)) + f"xstack=inputs={rows * cols}:layout=" +
                "|".join(f"{(i % cols) * (2 * PHONE + 12)}_{(i // cols) * (PHONE + 12)}" for i in range(rows * cols)) + "[s]")
    subprocess.run([FF, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(filt), "-map", "[s]", "-frames:v", "1",
                    str(out / "sheet.png")], check=True)
    print("probe:", n, "->", out / "sheet.png", f"(each 1080 still at half size beside its {PHONE} px phone view; "
          "reading order", " ".join(f"{x:g}" for x in times) + ")")
    report(errs)


# The camera moves and the collapse (segments that land "zoom" or "pan", or cue "collapse", on their first beat, for
# 0.32 s) change scale or place by up to half again a frame; there each of the SUB subframes is itself the mean of
# FAST_K draws, so the blend has SUB x FAST_K samples and no stepped copies. Lossless draws, averaged in float.
FAST_K = int(os.environ.get("FAST_K", 4))
FAST = [(s["t0"], s["t0"] + 0.32) for s in DATA["timeline"]["segments"]
        if {"zoom", "pan"} & set(s["land"]) or s["cue"].get("collapse") == 0]


def fast(i):
    return FAST_K > 1 and any(a - 1 / FPS < i / FPS < b + 1 / FPS for a, b in FAST)


async def full():
    sub = HERE / "sub"; sub.mkdir(exist_ok=True)   # chunks share the folder: names are global subframe indices
    n = int(round(T * FPS))
    f0, f1 = int(os.environ.get("F0", 0)), int(os.environ.get("F1", n))
    k = f0 * SUB
    offs = [(j - (SUB - 1) / 2) / (FPS * SUB) for j in range(SUB)]
    async with async_playwright() as p:
        b, pg, errs = await open_page(p)
        el = await pg.query_selector("#stage")
        for i in range(f0, f1):
            if fast(i):
                import io
                from PIL import Image
                m = SUB * FAST_K
                for j0 in range(0, m, FAST_K):
                    acc = None
                    for j in range(j0, j0 + FAST_K):
                        t = min(T - 1e-3, max(0.0, i / FPS + (j - (m - 1) / 2) / (FPS * m)))
                        await pg.evaluate(f"window.seek({t})")
                        a = np.asarray(Image.open(io.BytesIO(await el.screenshot(type="png"))).convert("RGB"), np.float32)
                        acc = a if acc is None else acc + a
                    Image.fromarray(np.clip(acc / FAST_K + 0.5, 0, 255).astype(np.uint8)).save(sub / f"s_{k:05d}.jpg", quality=95)
                    k += 1
            else:
                for o in offs:
                    t = min(T - 1e-3, max(0.0, i / FPS + o))
                    await shot(pg, t, sub / f"s_{k:05d}.jpg", "jpeg"); k += 1
            if i % 60 == 0: print(f"frame {i}/{n}", flush=True)
        await b.close()
    report(errs)
    if os.environ.get("NO_ENCODE"): return
    encode()


def encode():
    sub = HERE / "sub"
    (HERE / "out").mkdir(exist_ok=True)
    if DATA["notes"]["draft"]:
        print("DRAFT NOTES: this render must not ship (re-run make_data.py on the published notes)")
    subprocess.run([FF, "-v", "error", "-y", "-framerate", str(FPS * SUB), "-i", str(sub / "s_%05d.jpg"),
                    "-vf", f"tmix=frames={SUB},select='eq(mod(n\\,{SUB})\\,{SUB - 1})',setpts=N/{FPS}/TB", "-r", str(FPS),
                    "-c:v", "libx264", "-crf", os.environ.get("CRF", "14"), "-preset", "slow", "-pix_fmt", "yuv420p", str(HERE / "out/video.mp4")], check=True)
    print("video ->", HERE / "out/video.mp4")
    music = os.environ.get("MUSIC", str(HERE / f"music/{DATA['music']['id']}.mp3"))
    at = os.environ.get("MUSIC_AT", str(DATA["timeline"]["at"]))
    if Path(music).stem != DATA["music"]["id"]:
        sys.exit(f"MUSIC {music} is not track {DATA['music']['id']}, which data.json timed the picture to: "
                 f"run MUSIC_ID={Path(music).stem} make_data.py … and render again")
    if not Path(music).exists():
        sys.exit(f"no track at {music}: curl -sSL -o {music} {DATA['music']['url']}")
    # lay the track under the picture: short fade in, a fade out of the timeline's fade_out_s (2 s unless the track
    # ends on its own hard stop), -4 dB
    fo = float(DATA["timeline"].get("fade_out_s", 2.0))
    subprocess.run([FF, "-v", "error", "-y", "-i", str(HERE / "out/video.mp4"), "-ss", at, "-t", str(T), "-i", music,
                    "-filter_complex", f"[1:a]afade=t=in:d=0.05,afade=t=out:st={T - fo}:d={fo},volume=-4dB[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                    "-movflags", "+faststart", str(HERE / "out/video-music.mp4")], check=True)
    print(f"with music {DATA['music']['id']} from {at} s ->", HERE / "out/video-music.mp4")


def frames(path, size=180):
    # area-averaged, so the film grain (a fresh plate every second frame) averages out and only shapes move the scans
    raw = subprocess.run([FF, "-v", "quiet", "-i", str(path), "-vf", f"scale={size}:{size}:flags=area,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, size, size).astype(np.float32)


def pops(path=None):
    """A pop is one frame unlike both neighbours while the neighbours match each other."""
    fr = frames(path or HERE / "out/video.mp4")
    dif = lambda a, b: float(np.abs(fr[a] - fr[b]).mean())
    hits = []
    for i in range(1, len(fr) - 1):
        a, b, c = dif(i, i - 1), dif(i, i + 1), dif(i - 1, i + 1)
        if min(a, b) > 2.0 and min(a, b) > 3 * max(c, .3): hits.append((i, round(i / FPS, 3), round(min(a, b), 2), round(c, 2)))
    print("frames:", len(fr), "pops:", len(hits))
    for h in hits: print("  frame", h[0], "t", h[1], "diff", h[2], "neighbours", h[3])
    if hits: sys.exit(1)


def flash(path=None):
    """WCAG 2.3.1, general flash: a flash is a pair of opposing changes in relative luminance of 0.10 or more (10 % of
    the maximum), where the darker state is under 0.80, over at least a quarter of the frame (the 10-degree field at a phone's
    viewing distance is smaller; the quarter is the stricter reading). At most three flashes in any one second."""
    raw = subprocess.run([FF, "-v", "quiet", "-i", str(path or HERE / "out/video.mp4"), "-vf", "scale=120:120,format=rgb24",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 120, 120, 3).astype(np.float64) / 255
    lin = np.where(fr <= 0.04045, fr / 12.92, ((fr + 0.055) / 1.055) ** 2.4)
    Y = lin @ np.array([0.2126, 0.7152, 0.0722])
    # per pixel, the sign of each frame-to-frame change that is a flash transition; a frame transitions when a quarter
    # of its pixels do, in one direction
    hi, lo = np.maximum(Y[1:], Y[:-1]), np.minimum(Y[1:], Y[:-1])
    big = ((hi - lo) >= 0.1) & (lo < 0.8)
    up = (big & (Y[1:] > Y[:-1])).mean(axis=(1, 2)) >= 0.25
    dn = (big & (Y[1:] < Y[:-1])).mean(axis=(1, 2)) >= 0.25
    trans = [(i + 1, 1) for i in np.nonzero(up)[0]] + [(i + 1, -1) for i in np.nonzero(dn)[0]]
    trans.sort()
    # a flash is an opposing pair; count pairs in each 1 s window
    pairs, last = [], None
    for f, s in trans:
        if last is not None and s != last[1]: pairs.append(f); last = None
        else: last = (f, s)
    worst = max([sum(1 for q in pairs if p <= q < p + FPS) for p in pairs] or [0])
    print(f"flash: {len(trans)} large-area transitions, {len(pairs)} flashes, at most {worst} in any 1 s (limit 3)")
    for f in pairs[:20]: print(f"   flash ending frame {f} ({f / FPS:.3f} s)")
    if worst > 3: sys.exit(1)


def sync(path=None):
    """Rhythm on the output. Picture: a change onset is a frame that differs from the one before (above the grain's
    floor, below) by half a grey level or more and by at least three times the change into the frame before: a cut or a slam starting (also out of a
    scene still in motion), not typing or a blinking cursor, which move about a tenth of a level a frame. An onset
    within a quarter second of the one before belongs to the same motion (a slam's settle and shake) and is not counted. Each onset must sit within one frame of a
    beat, and each distinct cut or slam time in data.json is counted against them. Sound: the kick
    onsets of the muxed audio (30-150 Hz flux, as beats.py) folded at the grid's period; the fold's peak is the
    audio's offset from the picture's beats, and must be under one frame."""
    tl = DATA["timeline"]
    beats = np.array(tl["beats"]); P = tl["period"]
    path = path or HERE / "out/video-music.mp4"
    fr = frames(path, 120)
    d = np.array([0] + [float(np.abs(fr[i] - fr[i - 1]).mean()) for i in range(1, len(fr))])
    # The grain takes a fresh plate on every even frame, which moves those frames by a steady g levels and the odd
    # ones (same plate as the frame before) by none: g is the median of an even frame's change over the odd frame's
    # after it, and comes off every even frame, so a cut or a slam stands on the same floor at either parity.
    n2 = (len(d) - 2) // 2
    g = float(np.median(d[2:2 + 2 * n2:2] - d[3:3 + 2 * n2:2]))
    d[2::2] = np.maximum(0, d[2::2] - g)
    print(f"grain: {g:.2f} levels on even frames, taken off")
    hard = []
    for i in range(1, len(d)):
        if d[i] >= .5 and d[i] >= 3 * d[i - 1]:
            if not hard or i - hard[-1] > FPS // 4: hard.append(i)
    off = [(i, min(abs(i / FPS - beats)) * FPS) for i in hard]
    bad = [(i, o) for i, o in off if o > 1.0 + 1e-6]
    times = sorted({round(e[1] * FPS) for e in tl["events"] if not e[0].startswith(("type", "enter"))})
    seen = [f for f in times if any(abs(f - i) <= 1 for i in hard)]
    print(f"picture: {len(hard)} change onsets, {len(hard) - len(bad)} within one frame of a beat; "
          f"{len(seen)} of the {len(times)} cut and slam times have an onset")
    for i, o in bad: print(f"   frame {i} ({i / FPS:.3f} s) is {o:.2f} frames from the nearest beat")
    sys.path.insert(0, str(HERE)); import beats as B
    raw = subprocess.run([FF, "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(B.SR),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.float32).astype(np.float64)
    t, _, low, _ = B.envelopes(x)
    sel = t < T - float(tl.get("fade_out_s", 2.0)) - .5   # before the fade
    ph = np.arange(-P / 2, P / 2, 5e-4)
    c = B.comb(t[sel], low[sel], P, (tl["first"] + ph) % P)
    lag = float(ph[int(np.argmax(c))])
    print(f"sound: kick phase {lag * 1e3:+.1f} ms from the picture's beats ({lag * FPS:+.2f} frames)")
    if bad or abs(lag) * FPS > 1.0: sys.exit(1)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "check": asyncio.run(check())
    elif cmd == "probe": asyncio.run(probe([float(x) for x in sys.argv[2:]]))
    elif cmd == "full": asyncio.run(full())
    elif cmd == "pops": pops(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "flash": flash(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "sync": sync(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "encode": encode()
    else: sys.exit(__doc__)
