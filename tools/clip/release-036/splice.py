"""The film's track, cut from the one mp3 by data.json's arrangement (make_data.py): whole bars of the same track
joined at downbeats, each join an equal-power crossfade of xfade_s that ends on the downbeat, so the incoming bar's
first kick is untouched. Nothing is generated.

  python3 splice.py                 writes music/<id>-film.wav (output 0 s is the film's 0 s) and prints the joins
  python3 splice.py check [wav]     the joins measured: beats.py's grid of the wav (in a scratch copy, beats.json is
                                    not touched), and per join the RMS of the beat before and after it against the
                                    track's own beat-to-beat steps
render.py encode lays the wav under the picture when data.json has an arrangement.
"""
import json, os, shutil, subprocess, sys, tempfile, wave
from pathlib import Path
import numpy as np

HERE = Path(__file__).parent
FF = shutil.which("ffmpeg")
SR = 44100


def decode(path):
    raw = subprocess.run([FF, "-v", "error", "-i", str(path), "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64)


def build(data, src=None, out=None):
    mu, T = data["music"], data["timeline"]["T"]
    P, fb, nx = mu["period_s"], mu["first_beat_s"], round(mu["xfade_s"] * SR)
    src = Path(src or HERE / f"music/{mu['id']}.mp3")
    out = Path(out or HERE / f"music/{mu['id']}-film.wav")
    x = decode(src)
    y = np.zeros((round(T * SR), 2))
    th = np.linspace(0, np.pi / 2, nx, endpoint=False) + np.pi / 4 / nx
    w_in, w_out = np.sin(th)[:, None], np.cos(th)[:, None]
    ob, joins = 0, []
    for k, (a, e) in enumerate(mu["arrangement"]):
        o0, o1 = round(ob * P * SR), min(len(y), round((ob + e - a) * P * SR))
        s0 = round((fb + a * P) * SR)
        if s0 + (o1 - o0) > len(x): sys.exit(f"splice.py: bar {a}..{e} runs past the track's end")
        if k:   # the join: the outgoing bar's last nx samples under the incoming bar's nx samples before its downbeat
            y[o0 - nx:o0] = y[o0 - nx:o0] * w_out + x[s0 - nx:s0] * w_in
            joins.append((ob, o0 / SR, a))
        y[o0:o1] = x[s0:s0 + (o1 - o0)]
        ob += e - a
    pcm = (np.clip(y, -1, 1) * 32767).round().astype("<i2")
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
    return out, joins


def beat_db(y, P, nb, t0=0.0):
    m = y.mean(axis=1) if y.ndim == 2 else y
    out = []
    for k in range(nb):
        s = m[round((t0 + k * P) * SR):round((t0 + (k + 1) * P) * SR)]
        out.append(20 * np.log10(np.sqrt(np.mean(s ** 2)) + 1e-9) if len(s) else -120.0)
    return np.array(out)


def check(data, wav):
    mu, P = data["music"], data["music"]["period_s"]
    y = decode(wav)
    nb = data["timeline"]["nbeats"]
    db = beat_db(y, P, nb)
    # the track's own beat-to-beat steps inside its loud bars (the yardstick for a join's step)
    x = decode(HERE / f"music/{mu['id']}.mp3")
    sdb = beat_db(x, P, mu["beats"] - 1, mu["first_beat_s"])
    steps = np.abs(np.diff(sdb))[sdb[1:] > -25]
    print(f"track: beat-to-beat RMS step in its loud beats: median {np.median(steps):.1f} dB, p90 {np.percentile(steps, 90):.1f} dB")
    worst = 0.0
    for j in mu["splices"]:
        b = j["film_beat"]
        st = db[b] - db[b - 1]
        # the same step where the track itself plays into that bar (the bar before it in the track)
        tb = j["to_track_beat"]
        own = sdb[tb] - sdb[tb - 1] if tb >= 1 else float("nan")
        worst = max(worst, abs(st - own))
        print(f"  join at film beat {b:3} ({b * P:7.3f} s), track beat {j['from_track_beat']} -> {j['to_track_beat']}: "
              f"beat before {db[b - 1]:6.1f} dB, after {db[b]:6.1f} dB, step {st:+5.1f} dB (the track's own step into bar {tb}: {own:+5.1f} dB)")
    # the grid: beats.py on the wav, in a scratch dir so beats.json is not touched
    d = Path(tempfile.mkdtemp())
    shutil.copy(HERE / "beats.py", d / "beats.py")
    (d / "beats.json").write_text("{}")
    shutil.copy(wav, d / "film.wav")
    # the prior and range around the track's own tempo (a fixed 172 measured a 128 BPM track at 164.56)
    bpm = mu["bpm"]
    env = dict(os.environ, BEATS_PRIOR=f"{bpm:g}", BEATS_RANGE=f"{bpm * 0.88:.0f}-{bpm * 1.12:.0f}", BEATS_DROP_WIN="8",
               BEATS_DROP_FROM="1")
    r = subprocess.run([sys.executable, str(d / "beats.py"), str(d / "film.wav")], cwd=d, env=env, capture_output=True, text=True)
    print(r.stdout.strip()[-600:], r.stderr.strip()[-300:])
    g = json.loads((d / "beats.json").read_text()).get("film", {})
    if g:
        ph = (g["first_beat_s"] % P) * 1000
        ph = ph - P * 1000 if ph > P * 500 else ph
        print(f"grid of the film's track: {g['bpm']} BPM (the track {mu['bpm']}), period {g['period_s']} s, first beat "
              f"{g['first_beat_s']} s = {ph:+.1f} ms from the film's grid; kicks on the grid {g['kick_on_grid']} "
              f"(median {g['kick_median_ms']} ms)")
    print(f"worst join step against the track's own: {worst:.1f} dB")
    return g, worst


if __name__ == "__main__":
    data = json.loads((HERE / "data.json").read_text())
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        wav = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / f"music/{data['music']['id']}-film.wav"
        check(data, wav)
    else:
        out, joins = build(data)
        print(f"{out}: {data['timeline']['T']} s, {len(joins)} joins at film beats {[j[0] for j in joins]}")
