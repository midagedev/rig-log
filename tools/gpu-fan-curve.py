#!/usr/bin/env python3
"""gpu-fan-curve.py — the fan curve this machine could not have until today.

The A6000's own curve holds 58-64 % at 86-87 °C, because 87 °C is nowhere near its
95 °C slowdown and the card is only clipping clocks to reach its **84 °C target**.
Measured 2026-09-16 on an LTX-2.5 denoise: forcing 100 % is 16 °C for 2.7 % of the
rate, so sixteen degrees were sitting behind an acoustic preference. `nvidia-smi` on
driver 615.71.09 has no fan option and `nvidia-settings` wants an X display this box
does not run, but NVML sets fan speed headless — [`gpu-fan.py`](gpu-fan.py) is the
one-shot, and this is the policy.

    gpu-fan-curve.py --once                 # one step, print what it would do, exit
    gpu-fan-curve.py                        # run until killed
    gpu-fan-curve.py --curve 45:35,65:55,75:80,82:100
    gpu-fan-curve.py --gpu <uuid>           # one card instead of every card

**This changes every thermal number taken afterwards.** A take recorded with the curve
running is not comparable to one from before it, which is the same trap as the clock
locks: say so in the log entry, and prefer stopping it for a matched pair rather than
remembering which side of the change a number came from.

Safety, in the order it matters:

- The card's own protections are untouched — slowdown at 95 °C, shutdown at 98 °C are
  in hardware, so the worst a wrong curve can do is throttle, never damage.
- A **floor** (`--floor`, default the curve's lowest percent): never undercut, so a
  daemon killed with SIGKILL cannot have left a fan slower than that. It is separate
  from the curve on purpose — a card with zero-RPM idle, like the 3090 here at 47 °C,
  is made *worse* by a floor of 35 %: noise for no heat. On such a card use
  `--floor 0` and accept that a SIGKILL leaves it stopped until something sets it
  again, or leave the card out with `--gpu`. On this box the card with the measured
  problem is the A6000, and it is the one worth managing.
- On exit, including SIGTERM and SIGINT, every fan it touched goes back to the card's
  curve. A daemon killed with SIGKILL cannot do that, which is why the floor exists.
- **Hysteresis**, because the naive loop is the bug here: a curve read literally sets a
  new percent every few seconds as the temperature jitters, and a blower that is
  constantly being re-commanded is both audible and pointless. A change has to be worth
  at least `--deadband` points before it is sent.
- The reading lags the set by several seconds (measured: a fan at 0 % still read 0 %
  immediately after a successful set to 60, and 53 % six seconds later), so this never
  reads back to confirm — it commands, and the temperature is the feedback.
"""

import argparse
import signal
import sys
import time
from datetime import datetime

try:
    import pynvml as N
except ImportError:
    sys.exit("no pynvml: run under a venv that has nvidia-ml-py "
             "(uv run --with nvidia-ml-py python tools/gpu-fan-curve.py ...)")

DEFAULT_CURVE = "45:35,60:50,70:70,78:90,84:100"


def parse_curve(text):
    pts = []
    for piece in text.split(","):
        t, p = piece.split(":")
        pts.append((float(t), int(p)))
    pts.sort()
    if not pts:
        sys.exit("empty curve")
    for _, p in pts:
        if not 0 <= p <= 100:
            sys.exit(f"curve percent {p} out of range")
    return pts


def target(curve, temp):
    """Linear interpolation between curve points, flat outside them."""
    if temp <= curve[0][0]:
        return curve[0][1]
    if temp >= curve[-1][0]:
        return curve[-1][1]
    for (t0, p0), (t1, p1) in zip(curve, curve[1:]):
        if t0 <= temp <= t1:
            span = t1 - t0
            return int(round(p0 + (p1 - p0) * ((temp - t0) / span))) if span else p1
    return curve[-1][1]


def cards(want):
    out = []
    for i in range(N.nvmlDeviceGetCount()):
        h = N.nvmlDeviceGetHandleByIndex(i)
        uuid = N.nvmlDeviceGetUUID(h)
        name = N.nvmlDeviceGetName(h)
        if want and want not in (uuid, name, str(i)):
            continue
        try:
            fans = N.nvmlDeviceGetNumFans(h)
        except N.NVMLError:
            fans = 0
        if fans:
            out.append((h, name, uuid, fans))
    if want and not out:
        sys.exit(f"no GPU with fans matching {want!r}")
    return out


def say(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--curve", default=DEFAULT_CURVE,
                   help=f"temp:percent pairs, comma separated (default {DEFAULT_CURVE})")
    p.add_argument("--gpu", help="UUID, exact product name, or index; default every card with fans")
    p.add_argument("--interval", type=float, default=5.0, help="seconds between samples")
    p.add_argument("--deadband", type=int, default=4,
                   help="minimum change in percent worth commanding (default 4)")
    p.add_argument("--floor", type=int, default=None,
                   help="never command below this percent (default: the curve's lowest point). "
                        "0 lets a zero-RPM card stay stopped when idle")
    p.add_argument("--once", action="store_true", help="evaluate one step and exit without setting")
    a = p.parse_args()

    curve = parse_curve(a.curve)
    floor = curve[0][1] if a.floor is None else a.floor
    if not 0 <= floor <= 100:
        sys.exit(f"--floor {floor} out of range")
    N.nvmlInit()
    devs = cards(a.gpu)

    if a.once:
        for h, name, uuid, fans in devs:
            t = N.nvmlDeviceGetTemperature(h, N.NVML_TEMPERATURE_GPU)
            say(f"{name}: {t} C -> would set {target(curve, t)}% ({fans} fan(s)); nothing changed")
        return

    touched = []

    def restore(*_):
        for h, name, _u, fans in touched:
            for f in range(fans):
                try:
                    N.nvmlDeviceSetDefaultFanSpeed_v2(h, f)
                except N.NVMLError as e:
                    say(f"{name} fan {f}: NOT restored — {e}")
        say(f"restored {len(touched)} card(s) to their own curve")
        sys.exit(0)

    signal.signal(signal.SIGTERM, restore)
    signal.signal(signal.SIGINT, restore)

    say(f"curve {curve}, floor {floor}%, deadband {a.deadband}, every {a.interval}s")
    for _h, name, uuid, fans in devs:
        say(f"  managing {name} ({fans} fan(s)) {uuid}")
    say("NOTE: thermal numbers taken from here on are not comparable to earlier ones")

    last = {}
    try:
        while True:
            for h, name, uuid, fans in devs:
                try:
                    t = N.nvmlDeviceGetTemperature(h, N.NVML_TEMPERATURE_GPU)
                except N.NVMLError as e:
                    say(f"{name}: temperature unreadable ({e}); leaving the fan alone")
                    continue
                want = max(target(curve, t), floor)
                prev = last.get(uuid)
                if prev is not None and abs(want - prev) < a.deadband:
                    continue
                ok = True
                for f in range(fans):
                    try:
                        N.nvmlDeviceSetFanSpeed_v2(h, f, want)
                    except N.NVMLError as e:
                        say(f"{name} fan {f}: REFUSED — {e}")
                        ok = False
                if ok:
                    say(f"{name}: {t} C  {prev if prev is not None else '-'}% -> {want}%")
                    last[uuid] = want
                    if (h, name, uuid, fans) not in touched:
                        touched.append((h, name, uuid, fans))
            time.sleep(a.interval)
    except KeyboardInterrupt:
        restore()


if __name__ == "__main__":
    main()
