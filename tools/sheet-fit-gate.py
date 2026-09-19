#!/usr/bin/env python3
"""Numeric overflow gate for the placement sheet: does every element sit inside the box?

Three vision rounds were spent on the same class of fault (text re-wrapping and pushing
the legend off the page). This answers it with getBoundingClientRect instead, so the next
edit gets the answer in a second and vision is spent on what only eyes can judge.
"""
import re, subprocess, sys, tempfile, pathlib
# --probe sel,sel,... swaps the placement sheet's selector list for another page's (2026-09-19,
# the share card). The geometry, Chrome flags and the three-state verdict stay the same.
args = [a for a in sys.argv[1:] if not a.startswith("--probe")]
PROBE = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--probe=")), None)
SRC = pathlib.Path(args[0] if args else "assets/placement-sheet.html").resolve()
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
probe = """
<style>.sheet{width:1248px!important;max-width:none!important;height:702px!important;aspect-ratio:auto!important}</style>
<script>
addEventListener('load', () => setTimeout(() => {
  const sheet = document.querySelector('.sheet');
  const b = sheet.getBoundingClientRect();
  const cs = getComputedStyle(sheet);
  const padB = parseFloat(cs.paddingBottom);
  const rows = [];
  for (const sel of SELECTORS) {
    const e = document.querySelector(sel);
    if (!e) { rows.push(sel + '\\tMISSING'); continue; }
    const r = e.getBoundingClientRect();
    rows.push(sel + '\\t' + r.bottom.toFixed(1) + '\\t' + (b.bottom - padB - r.bottom).toFixed(1));
  }
  rows.push('SHEET_BOTTOM\\t' + b.bottom.toFixed(1) + '\\tpadding ' + padB.toFixed(1));
  rows.push('GEOMETRY\\tsheet ' + b.width.toFixed(0) + 'x' + b.height.toFixed(0)
            + '  viewport ' + innerWidth + 'x' + innerHeight + '  dpr ' + devicePixelRatio);
  const su = document.querySelector('.setup'); if (su) rows.push('SETUP_LINES\\t' + Math.round(su.getBoundingClientRect().height));
  document.title = 'FITGATE ' + rows.join(' | ');
}, 2500));
</script>
"""
DEFAULT = ['.maplbl', '.legend', '.legend div:last-child', '.obs div:last-child',
           'table tr:last-child', '.setup', '.map', '.nvme']
sels = PROBE.split(",") if PROBE else DEFAULT
probe = probe.replace("SELECTORS", repr(sels))
html = SRC.read_text()
with tempfile.TemporaryDirectory() as td:
    t = pathlib.Path(td) / "probe.html"
    t.write_text(html + probe)
    out = subprocess.run([CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
                          "--force-device-scale-factor=2", "--window-size=1280,750",
                          "--virtual-time-budget=8000", "--dump-dom", t.as_uri()],
                         capture_output=True, text=True).stdout
m = re.search(r"<title>FITGATE ([^<]*)</title>", out)
if not m:
    sys.exit("gate could not read the page (no FITGATE title); Chrome output %d bytes" % len(out))
parts = m.group(1).split(" | ")
for part in parts:                      # pre-pass: the padding is needed before any row
    f = part.split("\t")
    if f[0] == "SHEET_BOTTOM": PAD_PRE = float(f[2].split()[1])
print(f"{'element':26} {'bottom':>8} {'clearance to padding':>22}")
bad = []; tight = []; PAD = PAD_PRE
for part in parts:
    f = part.split("\t")
    if f[0] == "SHEET_BOTTOM":
        print(f"{'-'*26} {f[1]:>8} {f[2]:>22}"); continue
    if f[0] == "GEOMETRY":
        print(f"{'geometry':26} {f[1]}")
        if not f[1].startswith("sheet 1248x702"):
            bad.append("gate measured the wrong geometry (%s); the committed shot is 1248x702 at dpr 2" % f[1])
        continue
    if f[0] == "SETUP_LINES":
        print(f"{'.setup height':26} {f[1]+' px':>8}"); continue
    if len(f) < 3 or f[1] == "MISSING":
        bad.append(f"{f[0]} did not render at all"); print(f"{f[0]:26} {'MISSING':>8}"); continue
    clear = float(f[2])
    # Three distinguishable answers, not two. A box edge inside the padding is fine; a box
    # edge in the padding band is tight but nothing is clipped (line-height leaves leading
    # below the glyphs, so the ink is further in than the box); past the BORDER is the
    # failure that actually shows, and it is what rev 1 and 2 did.
    if clear < -PAD:
        state = "CLIPPED"; bad.append(f"{f[0]} is past the border by {abs(clear)-PAD:.1f} px")
    elif clear < 0:
        state = f"tight ({abs(clear):.1f} px into the {PAD:.0f} px padding)"; tight.append(f[0])
    else:
        state = "ok"
    print(f"{f[0]:26} {f[1]:>8} {f[2]:>22}   {state}")
print()
if bad:
    print("FAIL"); [print("  " + b) for b in bad]; sys.exit(1)
if tight:
    print("PASS, tight - nothing is clipped, but these sit inside the padding band:")
    [print("  " + t) for t in tight]
    print("  one more wrapped line anywhere above them clips the sheet")
else:
    print("PASS - every probed element is inside the sheet's padding box")
