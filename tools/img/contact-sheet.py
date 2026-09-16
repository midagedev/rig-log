#!/usr/bin/env python3
"""contact-sheet.py — tile a take's images into one labelled sheet, for picking by eye.

Image generation is a pick-from-four loop, which is why every UI built for it (Midjourney's
grid, ComfyUI, Forge, Fooocus) puts four candidates in front of a person. None of those fit
here: the GPU is on a shared headless box behind a lease, and the person whose eye decides
reads a terminal, where a PNG is a path and not a picture. So the loop needs one thing from
those UIs and not the rest — **the grid** — and a link to it.

    contact-sheet.py <dir>... -o sheet.jpg [--cols 2] [--width 2048] [--label-from-dir]

Each tile is captioned with its filename and, when several directories are given, its
directory, so "the third one" is unambiguous when someone replies with a choice. Output is
JPEG on purpose: a 2×2 of 1536×1024 frames is 12 MB as PNG and about 1 MB as quality-88 JPEG,
and this is a thing to look at, never a thing to condition on — the originals stay where the
take wrote them.

Measured 2026-09-16, which is why this exists: two rounds of eight candidates were judged by
a vision agent instead, at roughly five minutes and a 8.5 MB transcript each, to answer a
question a person answers in two seconds. The sheet is not a replacement for a measurement —
it is a replacement for asking a model to have taste.
"""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# DejaVu ships with Pillow's own test data on most Linux images and is present on this box;
# the fallback is Pillow's bitmap default, which is ugly but never missing.
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def load_font(size):
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("dirs", nargs="+", help="directories of PNGs, or individual image files")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--cols", type=int, default=0, help="default: 2 for <=4 tiles, else 3")
    p.add_argument("--width", type=int, default=2048, help="sheet width in pixels")
    p.add_argument("--quality", type=int, default=88)
    p.add_argument("--label-from-dir", action="store_true",
                   help="prefix each caption with its directory name (default when >1 dir)")
    a = p.parse_args()

    files = []
    for d in a.dirs:
        q = Path(d)
        if q.is_dir():
            files += sorted(x for x in q.iterdir()
                            if x.suffix.lower() in (".png", ".jpg", ".jpeg"))
        elif q.is_file():
            files.append(q)
        else:
            raise SystemExit(f"no such path: {d}")
    if not files:
        raise SystemExit("no images found")

    show_dir = a.label_from_dir or len({f.parent for f in files}) > 1
    cols = a.cols or (2 if len(files) <= 4 else 3)
    rows = (len(files) + cols - 1) // cols

    tile_w = a.width // cols
    # every tile gets the same box, sized from the first image's aspect; a mixed-aspect set
    # is letterboxed rather than stretched, because a distorted candidate is a wrong candidate
    first = Image.open(files[0])
    tile_h = round(tile_w * first.height / first.width)
    cap_h = max(22, tile_w // 34)
    font = load_font(max(13, cap_h - 8))

    sheet = Image.new("RGB", (tile_w * cols, (tile_h + cap_h) * rows), (24, 24, 26))
    d = ImageDraw.Draw(sheet)
    for i, f in enumerate(files):
        im = Image.open(f).convert("RGB")
        im.thumbnail((tile_w, tile_h), Image.LANCZOS)
        x = (i % cols) * tile_w + (tile_w - im.width) // 2
        y = (i // cols) * (tile_h + cap_h) + (tile_h - im.height) // 2
        sheet.paste(im, (x, y))
        cap = f"{i + 1}. " + (f"{f.parent.name}/{f.name}" if show_dir else f.name)
        d.text(((i % cols) * tile_w + 8, (i // cols) * (tile_h + cap_h) + tile_h + 3),
               cap, font=font, fill=(226, 226, 230))

    out = Path(a.out)
    if out.suffix.lower() in (".jpg", ".jpeg"):
        sheet.save(out, quality=a.quality, optimize=True)
    else:
        sheet.save(out)
    print(f"{out}  {len(files)} tiles, {cols}x{rows}, {sheet.width}x{sheet.height}, "
          f"{out.stat().st_size} bytes")
    for i, f in enumerate(files):
        print(f"  {i + 1}. {f}")


if __name__ == "__main__":
    main()
