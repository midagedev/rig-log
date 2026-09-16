#!/usr/bin/env python3
"""ink-overlay.py — write real characters onto a generated frame, as ink on paper.

Why this exists: LTX-2.5 cannot write Hangul. Measured 2026-09-16 — asked for 주4일제
on a sheet of rice paper, it produced brush-like strokes that are not characters. That
is the expected failure for a diffusion model (composed syllable blocks are harder than
short Latin words), and it turns the question into a better one: the model cannot write
Hangul, but can it *keep* Hangul it was given? Image conditioning answers that, and this
script makes the conditioning frame — the glyphs are rendered from a font, so they are
correct by construction rather than by luck.

It is a compositor, not a generator. The text is drawn with a real Korean face, then
given an ink treatment so it sits on the paper instead of on top of it: a slight blur
and threshold to round the stroke ends, a second faint blur underneath for bleed into
the fibres, and per-glyph jitter so the column does not read as typesetting.

  ink-overlay.py <in.png> <out.png> --text 주4일제 --box X Y W H [--angle DEG]
  ink-overlay.py <in.png> <out.png> --text 주4일제 --quad x1 y1 x2 y2 x3 y3 x4 y4
                 [--font PATH] [--vertical] [--opacity 0..1]

The box or quad is where the paper is in that frame, in pixels. Nothing here looks at
the image to find it: the caller supplies it, because a wrong box is obvious to a viewer
and a guess made by this script would be invisible in the log.

`--quad` exists because the first frame this was written for has the paper as a
foreshortened diamond rotated about 45 degrees to the camera, with its bottom apex off
frame. A vision round measured that and named the cost of ignoring it: uniform glyph
sizes in an axis-aligned box do not narrow toward the top the way the paper does, so the
column reads as pasted onto the image rather than inked onto a receding surface. That
matters beyond looks here — a first frame that reads as an overlay invites the model to
dissolve it, which would confound the experiment it is the input to. The quad is the
four corners (top-left, top-right, bottom-right, bottom-left) the rendered column should
land on, and the glyphs are perspective-mapped into it.
"""

import argparse
from pathlib import Path
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

DEFAULT_FONT = "/System/Library/Fonts/Supplemental/AppleMyungjo.ttf"


def perspective_coeffs(dst, src):
    """Coefficients for Image.transform(PERSPECTIVE), which maps output back to input.

    dst is the four corners in the output image, src the four corners of the rendered
    rectangle, both as (x, y) in the order top-left, top-right, bottom-right, bottom-left.
    """
    import numpy as np
    A, B = [], []
    for (dx, dy), (sx, sy) in zip(dst, src):
        A.append([dx, dy, 1, 0, 0, 0, -sx * dx, -sx * dy])
        A.append([0, 0, 0, dx, dy, 1, -sy * dx, -sy * dy])
        B += [sx, sy]
    return np.linalg.solve(np.asarray(A, float), np.asarray(B, float)).tolist()


def render_text(text, box_w, box_h, font_path, vertical, seed=0):
    """A transparent RGBA layer of box size with the text drawn as solid black ink."""
    rnd = random.Random(seed)
    scale = 4  # draw big, then downsample: the stroke edges come out smooth
    W, H = box_w * scale, box_h * scale
    layer = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(layer)

    chars = list(text)
    if vertical:
        cell = H // max(len(chars), 1)
        size = int(min(cell * 0.86, W * 0.86))
    else:
        cell = W // max(len(chars), 1)
        size = int(min(cell * 0.86, H * 0.86))
    font = ImageFont.truetype(font_path, size)

    for i, ch in enumerate(chars):
        l, t, r, b = d.textbbox((0, 0), ch, font=font)
        cw, ch_h = r - l, b - t
        if vertical:
            cx = (W - cw) / 2 - l
            cy = i * cell + (cell - ch_h) / 2 - t
        else:
            cx = i * cell + (cell - cw) / 2 - l
            cy = (H - ch_h) / 2 - t
        # a hand does not centre every glyph identically; a column that does reads as type
        cx += rnd.uniform(-0.035, 0.035) * cell
        cy += rnd.uniform(-0.025, 0.025) * cell
        d.text((cx, cy), ch, font=font, fill=255)

    # round the stroke ends and let the edge soften the way a loaded brush does
    layer = layer.filter(ImageFilter.GaussianBlur(scale * 0.9))
    layer = layer.point(lambda v: 255 if v > 110 else 0)
    return layer.resize((box_w, box_h), Image.LANCZOS)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("src"), p.add_argument("dst")
    p.add_argument("--text", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--box", nargs=4, type=int, metavar=("X", "Y", "W", "H"))
    g.add_argument("--quad", nargs=8, type=float,
                   metavar=("X1", "Y1", "X2", "Y2", "X3", "Y3", "X4", "Y4"),
                   help="four corners in the image: top-left, top-right, bottom-right, bottom-left")
    p.add_argument("--angle", type=float, default=0.0, help="rotate the text layer, degrees CCW")
    p.add_argument("--font", default=DEFAULT_FONT)
    p.add_argument("--vertical", action="store_true", help="stack the characters down a column")
    p.add_argument("--opacity", type=float, default=0.92)
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args()

    if not Path(a.font).exists():
        raise SystemExit(f"no font at {a.font}")
    base = Image.open(a.src).convert("RGB")

    if a.quad:
        q = [(a.quad[i], a.quad[i + 1]) for i in range(0, 8, 2)]
        # render at the quad's own scale so the downsample into perspective stays sharp
        w = int(max(abs(q[1][0] - q[0][0]), abs(q[2][0] - q[3][0])) or 1)
        h = int(max(abs(q[3][1] - q[0][1]), abs(q[2][1] - q[1][1])) or 1)
        w, h = max(w, 24), max(h, 24)
        rect = render_text(a.text, w, h, a.font, a.vertical, a.seed)
        src = [(0, 0), (w, 0), (w, h), (0, h)]
        full = rect.transform(base.size, Image.PERSPECTIVE,
                              perspective_coeffs(q, src), resample=Image.BICUBIC)
        span = min(w, h)
    else:
        x, y, w, h = a.box
        mask = render_text(a.text, w, h, a.font, a.vertical, a.seed)
        if a.angle:
            mask = mask.rotate(a.angle, resample=Image.BICUBIC, expand=True)
            x -= (mask.width - w) // 2
            y -= (mask.height - h) // 2
        full = Image.new("L", base.size, 0)
        full.paste(mask, (x, y))
        span = min(w, h)

    # bleed first, under the stroke, so the ink looks absorbed rather than printed
    full_bleed = full.filter(ImageFilter.GaussianBlur(max(2, span // 90)))
    base = Image.composite(Image.new("RGB", base.size, (38, 32, 30)), base,
                           full_bleed.point(lambda v: int(v * 0.40 * a.opacity)))

    base = Image.composite(Image.new("RGB", base.size, (12, 10, 12)), base,
                           full.point(lambda v: int(v * a.opacity)))

    base.save(a.dst)
    where = f"quad={[round(v) for v in a.quad]}" if a.quad else f"box={a.box} angle={a.angle}"
    print(f"{a.dst}  text={a.text}  {where}  font={Path(a.font).name}")


if __name__ == "__main__":
    main()
