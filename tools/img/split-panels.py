#!/usr/bin/env python3
"""split-panels.py — cut a storyboard sheet into its panels, for use as conditioning frames.

Why a sheet at all: a multi-shot clip needs the same characters in every shot, and asking an
image model for each shot separately means matching them by seed and wording and still
watching them drift. One 2×2 sheet is **one diffusion pass**, so the cast is consistent by
construction. This is the user's method and it is the right one.

    split-panels.py <sheet.png> -o <dir> [--grid 2 2] [--resize 1536 1024]

The gutters are found rather than assumed. A model asked for "thin clean white gutters" does
not put them at exactly one half and one half, so cutting at exact fractions clips a limb or
leaves a white band — and a white band at the edge of a conditioning frame is a thing the
video model will happily keep. Columns and rows that are near-white across most of their
length are scored, the widest run nearest each expected boundary is taken as that gutter, and
the fraction split is the fallback when no gutter is found (reported, not silent).

Panels are resized to the video geometry they will condition, because LTX's `--image` takes
whatever it is given and a mismatch is one more thing that is not written down anywhere. Note
that the still is re-encoded through H.264 at CRF 33 before the model sees it
(`DEFAULT_IMAGE_CRF` for LTX-2.5), so a panel being a quarter of a sheet costs less sharpness
than it appears to.
"""

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

WHITE = 232          # a gutter pixel is at least this bright in all channels
COVER = 0.80         # and a gutter line is that bright across at least this much of its span


def runs(mask):
    """[(start, end_exclusive)] for each maximal True run in a 1-D boolean array."""
    out, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def gutters(a, axis, parts):
    """Interior cut points along `axis`, one per interior boundary of `parts` panels.

    Returns (cuts, found_flags) where a cut is (lo, hi) bounding the gutter to discard.
    """
    bright = (a >= WHITE).all(axis=2)
    # fraction of the perpendicular span that is bright, per line along this axis
    frac = bright.mean(axis=1 - axis)
    cand = [r for r in runs(frac >= COVER) if r[0] > 0 and r[1] < len(frac)]
    n = a.shape[axis]
    cuts, found = [], []
    for k in range(1, parts):
        want = n * k / parts
        near = [r for r in cand if abs((r[0] + r[1]) / 2 - want) <= n * 0.06]
        if near:
            # the widest run near the expected boundary is the gutter; ties go to the nearest
            r = max(near, key=lambda r: (r[1] - r[0], -abs((r[0] + r[1]) / 2 - want)))
            cuts.append(r)
            found.append(True)
        else:
            cuts.append((round(want), round(want)))
            found.append(False)
    return cuts, found


def spans(n, cuts):
    """Panel [start, end) ranges from the image length and the gutters between them."""
    out, prev = [], 0
    for lo, hi in cuts:
        out.append((prev, lo))
        prev = hi
    out.append((prev, n))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("sheet")
    p.add_argument("-o", "--out", required=True, help="directory for the panels")
    p.add_argument("--grid", nargs=2, type=int, default=[2, 2], metavar=("COLS", "ROWS"))
    p.add_argument("--resize", nargs=2, type=int, default=[1536, 1024], metavar=("W", "H"),
                   help="the video geometry these will condition; 0 0 to keep panel size")
    p.add_argument("--prefix", default="shot")
    a = p.parse_args()

    im = Image.open(a.sheet).convert("RGB")
    arr = np.asarray(im)
    cols, rows = a.grid
    vcuts, vfound = gutters(arr, 1, cols)     # vertical gutters split columns
    hcuts, hfound = gutters(arr, 0, rows)     # horizontal gutters split rows
    if not all(vfound) or not all(hfound):
        print(f"  note: gutters found v={vfound} h={hfound}; "
              f"a False fell back to an even fraction split")

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    xs, ys = spans(im.width, vcuts), spans(im.height, hcuts)
    i = 0
    for (y0, y1) in ys:
        for (x0, x1) in xs:
            i += 1
            panel = im.crop((x0, y0, x1, y1))
            if a.resize != [0, 0]:
                panel = panel.resize(tuple(a.resize), Image.LANCZOS)
            f = out / f"{a.prefix}{i}.png"
            panel.save(f)
            print(f"  {f}  from ({x0},{y0})-({x1},{y1})  -> {panel.width}x{panel.height}")
    print(f"{i} panel(s) from {a.sheet}")


if __name__ == "__main__":
    main()
