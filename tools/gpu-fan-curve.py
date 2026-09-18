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
  from the curve on purpose — a card with zero-RPM idle, like the 3090 here at 33 °C,
  is made *worse* by a floor of 35 %: noise for no heat. On such a card use
  `--floor 0` and accept that a SIGKILL leaves it stopped until something sets it
  again, or leave the card out with `--gpu`.
  **A floor of 0 is not silence by itself.** Measured 2026-09-17 on the 3090: NVML
  accepts `SetFanSpeed_v2(h, f, 0)` and reports it set, and the card sits at 30 % for
  as long as it is in manual mode — zero RPM is reachable only through
  `SetDefaultFanSpeed_v2`, i.e. by giving the fan back. So a curve that wants a silent
  idle needs `--auto-below` (30 on that card), and the arithmetic below is necessary
  but not sufficient.
  **Below the curve's first point the command is the floor, not the first point's
  percent.** That is the other fix of 2026-09-17: the paragraph above had said `--floor 0`
  keeps a zero-RPM card stopped, and it did not — `target()` is flat below the first
  point, so the default curve commanded its 35 % at a 33 °C idle and `max(want, 0)`
  left it there. For a floor that defaults to the curve's own first percent this
  changes nothing, which is why the A6000's numbers are still comparable.
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
import os
import signal
import socket
import sys
import time
from datetime import datetime


def sd_notify(state):
    """Tell systemd we are alive. Measured 2026-09-18, the reason this exists:

    while this daemon is not processing its loop the fans are still in policy=manual at
    whatever percent it last commanded, and **the card's own curve cannot intervene while
    manual is held**. A peer session polling through a stop caught the shape: the fan sat at
    32 % for ninety seconds while the die went 60 -> 79 C under a 296 W load, and only moved
    once systemd gave up and ExecStopPost handed the fan back. A dead controller holding a
    manual fan is worse than no controller.

    Restart=always does not cover it, because a HUNG daemon never exits. A watchdog does:
    stop pinging and systemd kills and restarts us, and ExecStopPost hands the fans back on
    the way through. No dependency -- this is a datagram to $NOTIFY_SOCKET -- and it is a
    no-op when run by hand outside systemd.
    """
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr[0] == "@":
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(addr)
            sock.sendall(state.encode())
    except OSError:
        pass

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


def command(curve, floor, temp):
    """The percent to command: one owner, so the gate can ask it without a GPU.

    Below the curve's first point the floor is the command rather than the first
    point's percent — that is what makes `--floor 0` keep a zero-RPM card stopped.
    When floor is left to default (= curve[0][1]) the two are the same number, so
    the A6000's behaviour is unchanged by this rule.
    """
    if temp <= curve[0][0]:
        return floor
    return max(target(curve, temp), floor)


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
            out.append((h, name, uuid, fans, i))
    if want and not out:
        sys.exit(f"no GPU with fans matching {want!r}")
    return out


def say(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--curve", action="append", metavar="[SELECTOR=]SPEC",
                   help="temp:percent pairs, comma separated. Repeatable, and a 'SELECTOR=' "
                        "prefix (UUID, exact product name, or index) gives one card its own "
                        "curve: two cards in one box do not share a target, so one daemon that "
                        "manages both has to carry both curves. A spec with no selector is the "
                        f"default for cards that have none (built-in default {DEFAULT_CURVE})")
    p.add_argument("--gpu", help="UUID, exact product name, or index; default every card with fans")
    p.add_argument("--interval", type=float, default=5.0, help="seconds between samples")
    p.add_argument("--deadband", type=int, default=4,
                   help="minimum change in percent worth commanding (default 4)")
    p.add_argument("--auto-below", type=int, default=1, metavar="N",
                   help="at or below N %, hand the fan back to the card instead of commanding a "
                        "number. Measured 2026-09-17 on the 3090: a manual set is accepted at any "
                        "percent but the card holds 30 %% while it is in manual mode, and only "
                        "policy=auto reaches zero RPM — so a curve that wants silence has to give "
                        "the fan back, not ask for 0. Use 30 on that card; the default of 1 only "
                        "covers an exact 0")
    p.add_argument("--floor", type=int, default=None,
                   help="never command below this percent (default: the curve's lowest point). "
                        "0 lets a zero-RPM card stay stopped when idle")
    p.add_argument("--once", action="store_true", help="evaluate one step and exit without setting")
    a = p.parse_args()

    # A spec is temp:percent pairs and never contains '=', so the first '=' is the selector.
    default_curve, per_card = None, {}
    for item in (a.curve or [DEFAULT_CURVE]):
        sel, eq, spec = item.partition("=")
        if eq:
            per_card[sel] = parse_curve(spec)
        else:
            default_curve = parse_curve(sel)
    N.nvmlInit()
    devs = []
    for h, name, uuid, fans, idx in cards(a.gpu):
        curve = per_card.get(uuid) or per_card.get(name) or per_card.get(str(idx)) or default_curve
        if curve is None:
            sys.exit(f"no curve for {name} ({uuid}): give it one with --curve {uuid}=... "
                     f"or add a curve with no selector as the default")
        floor = curve[0][1] if a.floor is None else a.floor
        if not 0 <= floor <= 100:
            sys.exit(f"--floor {floor} out of range")
        devs.append((h, name, uuid, fans, curve, floor))

    if a.once:
        for h, name, uuid, fans, curve, floor in devs:
            t = N.nvmlDeviceGetTemperature(h, N.NVML_TEMPERATURE_GPU)
            want = command(curve, floor, t)
            below = " (below the curve's first point: the floor is the command)" if t <= curve[0][0] else ""
            say(f"{name}: {t} C -> would set {want}% ({fans} fan(s)){below}; nothing changed")
        return

    touched = []

    def restore(*_):
        for h, name, _u, fans, _c, _f in touched:
            for f in range(fans):
                try:
                    N.nvmlDeviceSetDefaultFanSpeed_v2(h, f)
                except N.NVMLError as e:
                    say(f"{name} fan {f}: NOT restored — {e}")
        say(f"restored {len(touched)} card(s) to their own curve")
        sd_notify("STOPPING=1")
        sys.exit(0)

    signal.signal(signal.SIGTERM, restore)
    signal.signal(signal.SIGINT, restore)

    say(f"deadband {a.deadband}, every {a.interval}s")
    for _h, name, uuid, fans, curve, floor in devs:
        say(f"  managing {name} ({fans} fan(s)) {uuid}")
        say(f"    curve {curve}, floor {floor}%")
    say("NOTE: thermal numbers taken from here on are not comparable to earlier ones")
    sd_notify("READY=1")

    last = {}
    try:
        while True:
            for h, name, uuid, fans, curve, floor in devs:
                try:
                    t = N.nvmlDeviceGetTemperature(h, N.NVML_TEMPERATURE_GPU)
                except N.NVMLError as e:
                    say(f"{name}: temperature unreadable ({e}); leaving the fan alone")
                    continue
                want = command(curve, floor, t)
                prev = last.get(uuid)
                give_back = want <= a.auto_below
                # A hand-back is a change of owner, not a change of percent, so the deadband must
                # not swallow it: prev and want can be the same number while the fan is in the
                # wrong mode. Only percent-to-percent moves are damped.
                if prev is not None and not give_back and prev > a.auto_below \
                        and abs(want - prev) < a.deadband:
                    continue
                if give_back and prev is not None and prev <= a.auto_below:
                    continue
                ok = True
                for f in range(fans):
                    try:
                        if give_back:
                            N.nvmlDeviceSetDefaultFanSpeed_v2(h, f)
                        else:
                            N.nvmlDeviceSetFanSpeed_v2(h, f, want)
                    except N.NVMLError as e:
                        say(f"{name} fan {f}: REFUSED — {e}")
                        ok = False
                if ok:
                    shown = f"{want}% -> the card's own curve" if give_back else f"{want}%"
                    say(f"{name}: {t} C  {prev if prev is not None else '-'}% -> {shown}")
                    last[uuid] = want
                    if (h, name, uuid, fans, curve, floor) not in touched:
                        touched.append((h, name, uuid, fans, curve, floor))
            sd_notify("WATCHDOG=1")
            time.sleep(a.interval)
    except KeyboardInterrupt:
        restore()


if __name__ == "__main__":
    main()
