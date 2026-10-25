"""Render film.html frame by frame (v2: the page composites on the GPU and accumulates its own motion blur).

  check             walk every frame without pictures (window.checkAll): read text under 44 px, past the 72 px
                    margins, two settled read boxes overlapping, a read group moving over 20 px/s or scaling over 3 %/s,
                    a string that is not in data.json, a character its face lacks, any page error; F0/F1 one range
  probe t1 t2 ...   stills at those times (each with its motion blur) -> probe/<PROBE_TAG or "main">/p_NN.png (1080),
                    m_NN.png (the 540 px phone view), and one sheet.png: each still at half size beside its phone view
  full              every frame from window.frame(i) (the mean of its sub-frame draws over a 180-degree shutter, as a
                    JPEG) piped straight into ffmpeg -> out/video.mp4, then the track under it -> out/video-music.mp4;
                    nothing is written per frame. F0/F1 render one range to out/part_F0.mp4 (join with `join`)
  join              concatenate out/part_*.mp4 in frame order into out/video.mp4, then the track
  mux               lay the track under out/video.mp4 -> out/video-music.mp4 (splice.py cuts it to the film by bars)
  delivery          out/video-music.mp4 re-encoded at CRF 20 for posting (the audio copied, +faststart)
                    -> out/video-music-crf20.mp4; the CRF 15 master stays the file the scans read
  pops [file]       single-frame pop scan of out/video.mp4 (or file)
  flash [file]      WCAG 2.3.1 general-flash scan of out/video.mp4 (or file): at most 3 flashes in any 1 s
  sync [file]       the rhythm, measured on the output (out/video-music.mp4, or file): every change onset in the
                    picture against the beat grid, and the kick phase of its audio against the same grid

Serve this folder first: python3 -m http.server 8800 --bind 127.0.0.1 (FILM_URL overrides the page URL; FILM the id,
default release-039-v2). The page must say it is this film (window.FILM), so a server left over from another clip
cannot pass for it. The film's length T has one owner, data.json (make_data.py derives it from the beat grid).

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
Changes: 1080x1080, T and the track read from data.json, the frame drawn and blurred in the page and piped to
ffmpeg, a page fault (bad data.json) stops the run by name, page errors fail the run, a whole-film check pass with a
glyph check, 540 px phone stills on one sheet, the film's identity, the pop, flash and sync scans.
"""
import asyncio, base64, json, os, shutil, subprocess, sys, time
from pathlib import Path
import numpy as np
from playwright.async_api import async_playwright

HERE = Path(__file__).parent
FF = shutil.which("ffmpeg")
URL = os.environ.get("FILM_URL", "http://127.0.0.1:8800/film.html")
FILM = os.environ.get("FILM", "release-039-v2")
FPS = 60
DATA = json.loads((HERE / "data.json").read_text())
T = DATA["timeline"]["T"]
N = int(round(T * FPS))
PHONE = 540
FONTS = {"Geist": HERE / "fonts/Geist-Variable.ttf", "GeistMono": HERE / "fonts/GeistMono-Variable.ttf"}
# Chrome's own performance notes on a canvas read back every frame are not the film's errors
BENIGN = ("GPU stall due to ReadPixels", "Automatic fallback to software WebGL")


async def open_page(p):
    # the Mac's GPU through ANGLE on Metal (the default headless GL is SwiftShader, about 12x slower here)
    b = await p.chromium.launch(args=["--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist",
                                      *os.environ.get("CHROME_ARGS", "").split()])
    pg = await b.new_page(viewport={"width": 1080, "height": 1080}, device_scale_factor=1)
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append("console: " + m.text)
          if m.type in ("error", "warning") and not any(x in m.text for x in BENIGN) else None)
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


def report(errs):
    """Page errors are defects (the film's data guard reports through console.error): print, fail."""
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
    f0, f1 = int(os.environ.get("F0", 0)), int(os.environ.get("F1", N + 1))
    errors = []
    async with async_playwright() as p:
        b, pg, errs = await open_page(p)
        await pg.evaluate("window.LOG = new Set()")
        for a in range(f0, f1, 600):
            r = await pg.evaluate(f"window.checkAll({a}, {min(f1, a + 600)})")
            errors += r["errors"]
        drawn = await pg.evaluate("Array.from(window.LOG)")
        await b.close()
    print(f"check: frames {f0}..{f1 - 1} of {N + 1} over {T} s")
    uniq = list(dict.fromkeys(errors))
    print(f"FLOOR/MARGIN/OVERLAP/HOLD FAULTS: {len(uniq)}")
    for e in uniq[:60]: print("  ", e)
    ok = glyphs(drawn)
    report(errs)
    if uniq or not ok: sys.exit(1)


async def shot(pg, t, path):
    await pg.evaluate(f"window.seek({t})")
    el = await pg.query_selector("#stage")
    await el.screenshot(path=str(path), type="png")


async def probe(times):
    out = HERE / "probe" / os.environ.get("PROBE_TAG", "main"); shutil.rmtree(out, ignore_errors=True); out.mkdir(parents=True)
    async with async_playwright() as p:
        b, pg, errs = await open_page(p)
        for i, t in enumerate(times): await shot(pg, t, out / f"p_{i:02d}.png")
        await b.close()
    for i in range(len(times)):   # the phone view: each still at half size, area-averaged as a phone scales it
        subprocess.run([FF, "-v", "error", "-y", "-i", str(out / f"p_{i:02d}.png"), "-vf", f"scale={PHONE}:{PHONE}:flags=area",
                        str(out / f"m_{i:02d}.png")], check=True)
    n, cols = len(times), 2
    rows = -(-n // cols)
    inputs, filt = [], []
    for i in range(n):
        inputs += ["-i", str(out / f"p_{i:02d}.png"), "-i", str(out / f"m_{i:02d}.png")]
        filt.append(f"[{2 * i}:v]scale={PHONE}:{PHONE}:flags=lanczos[a{i}];[a{i}][{2 * i + 1}:v]hstack=2,"
                    f"pad=iw+12:ih+12:0:0:color=white[t{i}]")
    for i in range(n, rows * cols):
        filt.append(f"color=white:s={2 * PHONE + 12}x{PHONE + 12}:d=1[t{i}]")
    if rows * cols > 1:
        filt.append("".join(f"[t{i}]" for i in range(rows * cols)) + f"xstack=inputs={rows * cols}:layout=" +
                    "|".join(f"{(i % cols) * (2 * PHONE + 12)}_{(i // cols) * (PHONE + 12)}" for i in range(rows * cols)) + "[s]")
    else:
        filt.append("[t0]null[s]")
    subprocess.run([FF, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(filt), "-map", "[s]", "-frames:v", "1",
                    str(out / "sheet.png")], check=True)
    print("probe:", n, "->", out / "sheet.png", "(reading order", " ".join(f"{x:g}" for x in times) + ")")
    report(errs)


async def full():
    f0, f1 = int(os.environ.get("F0", 0)), int(os.environ.get("F1", N))
    (HERE / "out").mkdir(exist_ok=True)
    whole = f0 == 0 and f1 == N
    dst = HERE / ("out/video.mp4" if whole else f"out/part_{f0:05d}.mp4")
    enc = subprocess.Popen([FF, "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-",
                            "-c:v", "libx264", "-crf", os.environ.get("CRF", "15"), "-preset", "slow", "-pix_fmt", "yuv420p",
                            "-r", str(FPS), str(dst)], stdin=subprocess.PIPE)
    ks, t0 = [], time.time()
    async with async_playwright() as p:
        b, pg, errs = await open_page(p)
        for i in range(f0, f1):
            k, url = await pg.evaluate(f"window.frame({i})")
            enc.stdin.write(base64.b64decode(url.split(",", 1)[1])); ks.append(k)
            if i % 300 == 0:
                el = time.time() - t0
                print(f"frame {i}/{N}  {el:.0f} s  mean K {np.mean(ks):.2f}  max K {max(ks)}", flush=True)
        await b.close()
    enc.stdin.close()
    if enc.wait(): sys.exit(f"ffmpeg ended {enc.returncode}")
    print(f"frames {f0}..{f1 - 1} -> {dst} in {time.time() - t0:.0f} s; sub-frames {sum(ks)} (mean {np.mean(ks):.2f} a frame)")
    report(errs)
    if whole: mux()


def join():
    parts = sorted((HERE / "out").glob("part_*.mp4"))
    lst = HERE / "out/parts.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
    subprocess.run([FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(HERE / "out/video.mp4")], check=True)
    print(f"joined {len(parts)} parts -> {HERE / 'out/video.mp4'}")
    mux()


def mux():
    if DATA["notes"]["draft"]:
        print("DRAFT NOTES: this render must not ship (re-run make_data.py on the published notes)")
    sys.path.insert(0, str(HERE)); import splice
    wav, joins = splice.build(DATA, str(HERE / f"music/{DATA['music']['id']}.mp3"))
    print(f"track spliced: {len(joins)} joins at film beats {[j[0] for j in joins]} -> {wav}")
    fo = float(DATA["timeline"].get("fade_out_s", 2.0))
    subprocess.run([FF, "-v", "error", "-y", "-i", str(HERE / "out/video.mp4"), "-t", str(T), "-i", str(wav),
                    "-filter_complex", f"[1:a]afade=t=in:d=0.05,afade=t=out:st={T - fo}:d={fo},volume=-4dB[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                    "-movflags", "+faststart", str(HERE / "out/video-music.mp4")], check=True)
    print(f"with music {DATA['music']['id']} ->", HERE / "out/video-music.mp4")


def delivery():
    src, dst = HERE / "out/video-music.mp4", HERE / "out/video-music-crf20.mp4"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(src), "-map", "0", "-c:v", "libx264", "-crf", "20", "-preset", "slow",
                    "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(dst)], check=True)
    print(f"delivery {dst} {dst.stat().st_size} B (master {src.stat().st_size} B)")


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
    grid = np.concatenate([beats, np.array(tl.get("ticks", []))])   # the beats and the declared half-beat ticks
    off = [(i, min(abs(i / FPS - grid)) * FPS) for i in hard]
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
    elif cmd == "join": join()
    elif cmd == "mux": mux()
    elif cmd == "delivery": delivery()
    elif cmd == "pops": pops(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "flash": flash(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "sync": sync(sys.argv[2] if len(sys.argv) > 2 else None)
    else: sys.exit(__doc__)
