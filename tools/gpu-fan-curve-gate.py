#!/usr/bin/env python3
"""gpu-fan-curve-gate.py — what the fan daemon will command, asked without a GPU.

The defect this exists for (2026-09-17): `gpu-fan-curve.py` documented that a
zero-RPM card like the 3090 should be run with `--floor 0` so it stays stopped at
idle, and the code did the opposite. `target()` is flat below the curve's first
point, so the default curve returned 35 % at a 33 °C idle and `max(want, floor)`
with floor 0 left it at 35. The doc was a claim about behaviour the code did not
have, and nothing measured it — a fan percent is only visible on the card.

So the decision moved into `command()` and this asks it directly. It needs no
NVML: pynvml is stubbed, because the point is the arithmetic, not the driver.

    python3 tools/gpu-fan-curve-gate.py      # prints each case, exits 1 on any miss

FAIL-first: on the source before the fix, case 1 returns 35 and this exits 1.
"""
import sys
import types
from pathlib import Path

sys.modules.setdefault("pynvml", types.ModuleType("pynvml"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import importlib.util

spec = importlib.util.spec_from_file_location(
    "gpu_fan_curve", Path(__file__).resolve().parent / "gpu-fan-curve.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

A6000_DEFAULT = m.parse_curve("45:35,60:50,70:70,78:90,84:100")   # the tool's built-in default
A6000 = A6000_DEFAULT                                             # kept under the old name below
# The curves the unit ships (configs/gpu-fan.service), one per card, each topping out at the
# temperature that card was measured to settle at under a full-power load.
A6000_SHIPPED = m.parse_curve("50:30,62:45,70:65,75:85,80:100")
# The curve the unit ships (configs/gpu-fan-3090.service): one mode, floor 30 because that is
# where this card pins a manual fan anyway, and 100 % at the 75 °C the die was measured to
# settle at under a 420 W burn.
GF3090 = m.parse_curve("50:30,58:45,65:65,70:85,75:100")

CASES = [
    # curve,  floor, temp, want, why
    (A6000, 0, 33, 0, "a floor of 0 below the first point — the arithmetic defect this gate exists for"),
    (GF3090, 30, 33, 30, "the shipped 3090 curve idles at its floor, which is the card's manual minimum"),
    (GF3090, 30, 75, 100, "100 % at the measured 75 °C ceiling, against the 56 % the card chose there"),
    (GF3090, 30, 82, 100, "and it stays at 100 above it"),
    (A6000, 0, 33, 0, "--floor 0 means 0 below the first point, whatever the curve's first percent"),
    (A6000, 35, 33, 35, "default floor (= the curve's own first percent): the A6000 is unchanged"),
    (A6000, 35, 65, 60, "interpolation between 60:50 and 70:70 is untouched"),
    (A6000, 35, 90, 100, "above the last point the curve is still flat at 100"),
    (A6000, 70, 65, 70, "a floor above the curve still wins"),
    (GF3090, 30, 63, 59, "at the burn's 63 °C: 59 % against the 31 % its own curve chose"),
    (GF3090, 30, 70, 85, "at 70 °C, where the card's own curve was still at 44 %"),
    (A6000_SHIPPED, 30, 85, 100, "A6000 at the 85 °C its own curve answered with 57 %"),
    (A6000_SHIPPED, 30, 88, 100, "A6000 at the 88 °C peak of the dual burn, where it chose 75 %"),
    (A6000_SHIPPED, 30, 70, 65, "A6000 at 70 °C: 65 % against the ~40 % its own curve chose"),
    (A6000_SHIPPED, 30, 33, 30, "A6000 idles at the same 30 % manual floor as the 3090"),
]

bad = 0
for curve, floor, temp, want, why in CASES:
    got = m.command(curve, floor, temp)
    ok = got == want
    bad += not ok
    print(f"{'ok  ' if ok else 'MISS'}  floor={floor:<3} {temp:>3} C -> {got:>3}% (want {want:>3}%)  {why}")
print(f"\n{len(CASES) - bad}/{len(CASES)} cases")
sys.exit(1 if bad else 0)
