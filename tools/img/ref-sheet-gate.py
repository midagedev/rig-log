#!/usr/bin/env python3
"""Reference-sheet gate: how many 2x2 panels read as bounded film frames?

Measured 2026-09-16 (opus vision judge on three Krea-2 sheets and their IC-LoRA clips):
a sheet whose panels are subjects cut out on pure black (edge ring ~0) produced one
composed scene; sheets whose panels were all full frames (edge ring 13-154) were copied
by the video model as a quad split screen, gutters matching to the pixel. This counts
panels whose inner edge ring is brighter than the gutter. Exit 1 when more than MAX
(default 2) read as frames. Cheap numeric proxy for the vision verdict, not a replacement.
"""
import sys, numpy as np
from PIL import Image
path = sys.argv[1]; MAX = int(sys.argv[2]) if len(sys.argv) > 2 else 2
a = np.asarray(Image.open(path).convert("RGB")).max(axis=2)
H, W = a.shape
def ring(y0, y1, x0, x1, inset=0.06, band=6):
    h, w = y1 - y0, x1 - x0
    iy0, iy1 = y0 + int(h*inset), y1 - int(h*inset); ix0, ix1 = x0 + int(w*inset), x1 - int(w*inset)
    edges = np.concatenate([a[iy0:iy0+band, ix0:ix1].ravel(), a[iy1-band:iy1, ix0:ix1].ravel(),
                            a[iy0:iy1, ix0:ix0+band].ravel(), a[iy0:iy1, ix1-band:ix1].ravel()])
    return float(np.median(edges))
names = ["TL", "TR", "BL", "BR"]
rings = [ring(0, H//2, 0, W//2), ring(0, H//2, W//2, W), ring(H//2, H, 0, W//2), ring(H//2, H, W//2, W)]
black = float((a <= 2).mean())
frames = sum(r > 8 for r in rings)
print(f"{path}: black {black:.1%}  edge rings " + " ".join(f"{n}={r:.0f}" for n, r in zip(names, rings)) + f"  -> {frames} panel(s) read as bounded frames (max {MAX})")
sys.exit(0 if frames <= MAX else 1)
