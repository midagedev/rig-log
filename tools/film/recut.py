"""Round 2's re-cut of the a-1401 track: whole 8-beat phrases dropped or repeated, at seams measured first.

Usage: recut.py ORIG.wav BEATS_ORIG.json OUT.wav BEATS_OUT.json SEGMENTS
       recut.py ORIG.wav BEATS_ORIG.json --measure A>B [A>B ...]
  SEGMENTS lists the track's grid-beat spans in play order, "0:16,24:56,48:" (the last span runs to the end). Each
  seam jumps from the end of one span to the start of the next; the jump is a whole number of 8-beat phrases (forward
  drops a phrase, back repeats it), so the bar and the phrase phase hold and the grid runs on through it. As
  splicecut.py: both points 8 ms before their grid beat (the quiet before the transient), an equal-power crossfade of
  6 ms, the jump round(n * period * sr) samples. --measure prints, for each seam A>B (track beats), the rms of the two
  6 ms windows and of their difference, the number that picks a seam.
"""
import json, sys
import numpy as np, soundfile as sf

orig, bj = sys.argv[1:3]
B = json.load(open(bj))
P, PH = B['grid']['period'], B['grid']['phase']
y, sr = sf.read(orig, always_2d=True, dtype='float64')
LEAD, XF = 0.008, 0.006
h = int(round(XF * sr / 2))
pos = lambda b: int(round((PH + b * P - LEAD) * sr))
rms = lambda x: float(np.sqrt(np.mean(x ** 2)))
db = lambda x: 20 * np.log10(rms(x) + 1e-12)


def seam(a, b):
    s0 = pos(a)
    s1 = s0 + int(round((b - a) * P * sr))
    wa, wb = y[s0 - h:s0 + h].mean(axis=1), y[s1 - h:s1 + h].mean(axis=1)
    # the 50 ms after each point too: what the ear hears just past the join
    la, lb = y[s0:s0 + int(0.05 * sr)].mean(axis=1), y[s1:s1 + int(0.05 * sr)].mean(axis=1)
    return s0, s1, wa, wb, la, lb


if sys.argv[3] == '--measure':
    for spec in sys.argv[4:]:
        a, b = map(int, spec.split('>'))
        if (b - a) % 8:
            sys.exit(f'recut.py: {a}>{b} is not a whole number of phrases')
        s0, s1, wa, wb, la, lb = seam(a, b)
        print(f'seam {a:>2}>{b:<2} ({s0 / sr:7.4f} s -> {s1 / sr:7.4f} s): windows {db(wa):6.1f} / {db(wb):6.1f} dBFS, '
              f'difference {db(wa - wb):6.1f} dBFS; next 50 ms {db(la):6.1f} / {db(lb):6.1f}, difference {db(la - lb):6.1f}')
    sys.exit(0)

out, bo, segs = sys.argv[3], sys.argv[4], sys.argv[5]
spans = []
for s in segs.split(','):
    a, b = s.split(':')
    spans.append((int(a), int(b) if b else None))
nbeats = len(B['beat_times'])
parts, cur, log, beat_src = [], 0, [], []
for i, (a, b) in enumerate(spans):
    if i == 0 and a != 0:
        sys.exit('recut.py: the first span starts at beat 0')
    if i > 0:
        pa = spans[i - 1][1]
        if (a - pa) % 8:
            sys.exit(f'recut.py: the seam {pa}>{a} is not a whole number of phrases')
        s0, s1, wa, wb, la, lb = seam(pa, a)
        u = np.linspace(0, np.pi / 2, 2 * h)[:, None]
        parts.append(y[s0 - h:s0 + h] * np.cos(u) + y[s1 - h:s1 + h] * np.sin(u))
        cur = s1 + h
        log.append(f'seam {pa}>{a}: track {s0 / sr:.4f} s -> {s1 / sr:.4f} s, jump {s1 - s0:+d} samples '
                   f'({(s1 - s0) / sr:+.5f} s = {a - pa:+d} x {P} s, error {((s1 - s0) / sr - (a - pa) * P) * 1e6:+.1f} us); '
                   f'windows {db(wa):.1f} / {db(wb):.1f} dBFS, difference {db(wa - wb):.1f} dBFS')
    end = pos(b) - h if b is not None else len(y)
    parts.append(y[cur:end])
    beat_src += list(range(a, b if b is not None else nbeats))
    cur = end
z = np.concatenate(parts)
sf.write(out, z.astype(np.float32), sr, subtype=sf.info(orig).subtype)
for l in log:
    print('recut: ' + l)
print(f'out: {len(z) / sr:.3f} s')
O = dict(B)
O['name'] = f"{B['name']} (re-cut: track beats {segs})"
O['beat_times'] = [round(k * P, 5) for k in range(len(beat_src))]
for key in ('low_db', 'rms_db'):
    if key in B:
        O[key] = [B[key][i] for i in beat_src if i < len(B[key])]
O.pop('splice', None)
O['recut'] = {'source': orig.split('/')[-1], 'spans': segs, 'seams': log, 'lead_ms': LEAD * 1000, 'xfade_ms': XF * 1000,
              'out_s': round(len(z) / sr, 4), 'beat_map': 'film beat k is track beat track_beat[k]', 'track_beat': beat_src}
json.dump(O, open(bo, 'w'), indent=1)
print(f'beats: {bo} ({len(O["beat_times"])} beats)')
