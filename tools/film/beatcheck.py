"""Independent check of the finished film's sound against its cuts.

Usage: beatcheck.py FILM_AUDIO.wav TRACK.wav OFFSET CUTS_JSON [PERIOD]
  FILM_AUDIO  the audio decoded from the finished mp4
  TRACK       the picked track the film's music was cut from
  OFFSET      the track time (s) of film time 0 (music/beats.json "offset")
  CUTS_JSON   a JSON list of the film's cut times (s), scene starts after the first

It re-detects the beat grid from the film's own audio (onset strength at a 1 ms hop, the impulse train of the best
period and phase), measures the lag of the film audio against the track by cross-correlation, and prints each cut's
distance to the nearest re-detected beat. Exit 2 when a cut is more than one frame (16.7 ms) off: half a frame of
frame rounding (a cut shows on the frame nearest its beat) plus the fit's own error; or when the lag is more than one
millisecond.
"""
import json, sys
import numpy as np, librosa, soundfile as sf
from scipy.signal import correlate

film_wav, track_wav, off, cuts = sys.argv[1], sys.argv[2], float(sys.argv[3]), json.load(open(sys.argv[4]))
# PERIOD (optional 5th argument): the picked grid's period; the search runs +-0.3 % around it (default 0.50014 s, the
# 0.3.13 track, whose fixed 0.4990-0.5012 s window this replaces)
P0 = float(sys.argv[5]) if len(sys.argv) > 5 else 0.50014
y, sr = sf.read(film_wav, always_2d=True); m = y.mean(axis=1).astype(np.float32)
env = librosa.onset.onset_strength(y=m, sr=sr, hop_length=sr // 1000, n_fft=1024)
fr = 1000.0
n = int(len(m) / sr / P0) - 1
best = None
for P in np.arange(P0 * 0.997, P0 * 1.003, 0.00002):
    for ph in np.arange(0.0, P, 0.001):
        idx = np.round((ph + P * np.arange(n)) * fr).astype(int); idx = idx[idx < len(env) - 7]
        s = sum(env[max(0, i - 6):i + 7].max() for i in idx)
        if best is None or s > best[0]: best = (s, P, ph)
_, P, ph = best
print('film audio grid: period %.5f s (%.3f BPM), phase %+.1f ms' % (P, 60 / P, 1000 * (ph if ph < P / 2 else ph - P)))
# lag of the film audio against the track segment it was cut from (first 10 s, both at the film's rate)
t, tsr = sf.read(track_wav, always_2d=True); t = t.mean(axis=1)
if tsr != sr: t = librosa.resample(t, orig_sr=tsr, target_sr=sr)
a = m[: 10 * sr]; b = t[int(round(off * sr)): int(round(off * sr)) + 10 * sr]
c = correlate(a, b, mode='full', method='fft'); lag = int(np.argmax(c)) - (len(b) - 1)
print('lag film vs track[offset:]: %+d samples (%+.2f ms)' % (lag, 1000 * lag / sr))
worst = 0.0
for x in cuts:
    k = round((x - ph) / P); d = x - (ph + k * P); worst = max(worst, abs(d))
    print('cut %7.3f s  beat %3d  %+6.1f ms' % (x, k, 1000 * d))
print('worst cut %.1f ms (limit 16.7)' % (1000 * worst))
sys.exit(2 if worst > 1 / 60 or abs(lag) > sr / 1000 else 0)
