"""Render the style frames of style.html to PNG.

  .venv/bin/python styles/shoot.py [frame ...]      (default: every frame in FRAMES below)

Serve release-034 first: python3 -m http.server 8795 --bind 127.0.0.1 (write its pid; stop only that pid).
Writes styles/<frame>.png (1080x1080), styles/<frame>-540.png (the phone view) and styles/sheet.png (every frame at
540 px, two rows).
"""
import asyncio, subprocess, sys
from pathlib import Path
from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8795/styles/style.html?f={}"
FRAMES = ["title", "b74pre", "b74", "tokens", "sparks", "embed"]   # "decode" (the trace version) renders by name


async def main(names):
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1080, "height": 1080}, device_scale_factor=1)
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        for f in names:
            await pg.goto(URL.format(f))
            await pg.wait_for_function("window.ready === true", timeout=60000)
            film, fault = await pg.evaluate("[window.FILM, window.fault || '']")
            if film != "release-034-styles":
                sys.exit(f"port 8795 serves {film!r}, not release-034's style frames")
            if fault or errs:
                sys.exit(f"{f}: {fault or errs}")
            await pg.locator("#stage").screenshot(path=str(HERE / f"{f}.png"))
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(HERE / f"{f}.png"), "-vf", "scale=540:540:flags=area",
                            str(HERE / f"{f}-540.png")], check=True)
        await b.close()
    ins = sum([["-i", str(HERE / f"{f}-540.png")] for f in FRAMES], [])
    cols = 3
    lay = "|".join(f"{(i % cols) * 540}_{(i // cols) * 540}" for i in range(len(FRAMES)))
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex",
                    f"xstack=inputs={len(FRAMES)}:layout={lay}", str(HERE / "sheet.png")], check=True)


asyncio.run(main(sys.argv[1:] or FRAMES))
