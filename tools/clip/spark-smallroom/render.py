"""Render film.html frame by frame (headless Chromium, software raster: --disable-gpu, so the Mac's GPU stays closed).

  probe [t1 t2 ...]  stills at those times (default: the spec's eight) -> probe/sheet.png
  audit              seeks every 0.05 s with window.audit on; every number drawn must be in data.json, every pane
                     string a piece of its own tape's text (rc 1 and the offending strings otherwise)
  full               SUB subframes per frame (default 6), blended with tmix -> out/video.mp4
                     F0/F1 = frame range for one parallel chunk, NO_ENCODE=1 to skip the encode in chunks
  encode             encode sub/ into out/video.mp4 after the chunks finish (MUSIC, MUSIC_AT lay a track under it)
  pops               single-frame pop scan of out/video.mp4 (0 expected)

Serve this folder first: python3 -m http.server 8767 --bind 127.0.0.1 (FILM_URL overrides the page URL).

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
Changes: 1080x1080, 55 s, software raster, SUB from the environment, chunked frame ranges, a separate encode step,
system ffmpeg, the number audit, the residency clip's pop scan.
"""
import asyncio, json, os, re, shutil, subprocess, sys
from pathlib import Path
import numpy as np
from playwright.async_api import async_playwright

HERE = Path(__file__).parent
FF = shutil.which("ffmpeg")
URL = os.environ.get("FILM_URL", "http://127.0.0.1:8767/film.html")
FPS, T, SUB = 60, 55.0, int(os.environ.get("SUB", 6))
PROBE = [2, 8, 15, 22, 30, 38, 40.5, 48, 54]


async def open_page(p):
    b = await p.chromium.launch(args=["--disable-gpu", "--disable-gpu-compositing"])
    pg = await b.new_page(viewport={"width": 1080, "height": 1080}, device_scale_factor=1)
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append("console: " + m.text) if m.type in ("error", "warning") else None)
    await pg.goto(URL)
    try:
        await pg.wait_for_function("window.ready === true", timeout=120000)
    except Exception:
        print("PAGE ERRORS:", errs[:8]); raise
    return b, pg, errs


async def shot(pg, t, path, fmt="png"):
    await pg.evaluate(f"window.seek({t})")
    el = await pg.query_selector("#stage")
    await el.screenshot(path=str(path), type=fmt, **({"quality": 95} if fmt == "jpeg" else {}))


def sheet(folder, pattern, n, out, cols=4, size=480):
    rows = -(-n // cols)
    subprocess.run([FF, "-v", "error", "-y", "-i", str(folder / pattern), "-vf",
                    f"scale={size}:-1,tile={cols}x{rows}:padding=6:color=white", "-frames:v", "1", str(out)], check=True)


async def probe(times, name="sheet.png", cols=4):
    out = HERE / "probe"; shutil.rmtree(out, ignore_errors=True); out.mkdir()
    async with async_playwright() as p:
        b, pg, errs = await open_page(p)
        for i, t in enumerate(times): await shot(pg, t, out / f"p_{i:02d}.png")
        await b.close()
    if errs: print("PAGE ERRORS:", errs[:8])
    sheet(out, "p_%02d.png", len(times), out / name, cols=cols)
    print("probe:", len(times), "->", out / name)


NUM = re.compile(r"\d+(?:\.\d+)?")


def allowed_numbers(d):
    """Every numeric token in data.json's values, except the tapes' raw stamps (never drawn)."""
    keep = set()
    def walk(v, path):
        if path.endswith(".tt"): return
        if isinstance(v, dict):
            for k, x in v.items(): walk(x, path + "." + k)
        elif isinstance(v, list):
            for x in v: walk(x, path)
        elif isinstance(v, bool) or v is None: return
        elif isinstance(v, (int, float)): keep.update(NUM.findall(json.dumps(v)))
        elif isinstance(v, str): keep.update(NUM.findall(v))
    walk(d, "")
    return keep


async def audit():
    d = json.loads((HERE / "data.json").read_text())
    ok_nums = allowed_numbers(d)
    tape_txt = {a["key"]: "".join(a["tx"]) for a in d["race"]["arms"]}
    seen, bad = {}, []
    async with async_playwright() as p:
        b, pg, errs = await open_page(p)
        hc = await pg.evaluate("window.hangulCheck()")
        print("hangul pixels:", hc)
        if hc["pretendard_vs_system"] < 50:
            bad.append((0, "font", "hangul", "Pretendard and the system face draw alike; the check cannot tell them apart"))
        if hc["stack_vs_pretendard"] != 0:
            bad.append((0, "font", "hangul", "the token stack does not draw Hangul with the copied Pretendard"))
        await pg.evaluate("window.audit = true")
        n = int(T / 0.05) + 1
        for i in range(n):
            t = min(T, i * 0.05)
            got = await pg.evaluate(f"(() => {{ window.drawn = []; window.seek({t}); return window.drawn; }})()")
            for s, cat in got:
                seen.setdefault((s, cat), t)
        await b.close()
    for (s, cat), t in sorted(seen.items(), key=lambda kv: kv[1]):
        if cat.startswith("tape:"):
            if s not in tape_txt[cat[5:]]: bad.append((t, cat, s, "not in its tape's text"))
        elif cat == "prompt":
            core = s.strip("“”").rstrip("…")
            if core not in d["race"]["prompt"]: bad.append((t, cat, s, "not in the prompt"))
        else:
            for x in NUM.findall(s):
                if x not in ok_nums: bad.append((t, cat, s, f"number {x} is not in data.json"))
    ui = sorted({s for (s, c) in seen if c == "ui" and NUM.search(s)})
    print(f"audit: {len(seen)} distinct strings drawn, {len(ui)} UI strings carry numbers, {len(bad)} refused")
    for x in bad[:40]: print("  REFUSED t=%.2f %s %r: %s" % x)
    if errs: print("PAGE ERRORS:", errs[:8])
    sys.exit(1 if bad or errs else 0)


async def full():
    sub = HERE / "sub"; sub.mkdir(exist_ok=True)   # chunks share the folder: names are global subframe indices
    n = int(round(T * FPS))
    f0, f1 = int(os.environ.get("F0", 0)), int(os.environ.get("F1", n))
    k = f0 * SUB
    offs = [(j - (SUB - 1) / 2) / (FPS * SUB) for j in range(SUB)]
    async with async_playwright() as p:
        b, pg, errs = await open_page(p)
        for i in range(f0, f1):
            for o in offs:
                t = min(T - 1e-3, max(0.0, i / FPS + o))
                await shot(pg, t, sub / f"s_{k:05d}.jpg", "jpeg"); k += 1
            if i % 60 == 0: print(f"frame {i}/{n}", flush=True)
        await b.close()
    if errs: print("PAGE ERRORS:", errs[:8])
    if os.environ.get("NO_ENCODE"): return
    encode()


def encode():
    sub = HERE / "sub"
    (HERE / "out").mkdir(exist_ok=True)
    subprocess.run([FF, "-v", "error", "-y", "-framerate", str(FPS * SUB), "-i", str(sub / "s_%05d.jpg"),
                    "-vf", f"tmix=frames={SUB},select='eq(mod(n\\,{SUB})\\,{SUB - 1})',setpts=N/{FPS}/TB", "-r", str(FPS),
                    "-c:v", "libx264", "-crf", "14", "-preset", "slow", "-pix_fmt", "yuv420p", str(HERE / "out/video.mp4")], check=True)
    print("video ->", HERE / "out/video.mp4")
    music = os.environ.get("MUSIC")
    if music:   # lay the track under the picture: short fade in, 2 s fade out, -4 dB
        subprocess.run([FF, "-v", "error", "-y", "-i", str(HERE / "out/video.mp4"), "-ss", os.environ.get("MUSIC_AT", "0"), "-t", str(T), "-i", music,
                        "-filter_complex", f"[1:a]afade=t=in:d=0.3,afade=t=out:st={T - 2.0}:d=2.0,volume=-4dB[a]",
                        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                        str(HERE / "out/video-music.mp4")], check=True)
        print("with music ->", HERE / "out/video-music.mp4")


def pops(path=None):
    """A pop is one frame unlike both neighbours while the neighbours match each other.
    The grain re-seeds every 5 frames and holds, so it is a step, not a pop."""
    path = path or HERE / "out/video.mp4"
    raw = subprocess.run([FF, "-v", "quiet", "-i", str(path), "-vf", "scale=180:180,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 180, 180).astype(np.float32)
    dif = lambda a, b: float(np.abs(fr[a] - fr[b]).mean())
    hits = []
    for i in range(1, len(fr) - 1):
        a, b, c = dif(i, i - 1), dif(i, i + 1), dif(i - 1, i + 1)
        if min(a, b) > 2.0 and min(a, b) > 3 * max(c, .3): hits.append((i, round(i / FPS, 3), round(min(a, b), 2), round(c, 2)))
    print("pops:", len(hits), "frames:", len(fr))
    for h in hits: print("  frame", h[0], "t", h[1], "diff", h[2], "neighbours", h[3])
    sys.exit(1 if hits else 0)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "probe": asyncio.run(probe([float(x) for x in sys.argv[2:]] or PROBE))
    elif cmd == "audit": asyncio.run(audit())
    elif cmd == "full": asyncio.run(full())
    elif cmd == "pops": pops(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "encode": encode()
    else: sys.exit(f"unknown command {cmd}")
