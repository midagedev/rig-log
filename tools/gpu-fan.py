#!/usr/bin/env python3
"""gpu-fan.py — read and set GPU fan speed on this box, headless.

`nvidia-smi` on driver 615.71.09 has no fan option at all, and `nvidia-settings`
needs an X display this machine does not run, so the standing note that nothing here
can curve a fan was half right: the six CHA_FAN headers are empty and the case fans
are on the PSU, but the *GPU* fans are controllable through NVML without X. Measured
2026-09-16: nvmlDeviceSetFanSpeed_v2, nvmlDeviceSetFanControlPolicy and
nvmlDeviceSetDefaultFanSpeed_v2 are all present, the 3090 reports two fan channels
and the A6000 one.

Why it matters rather than being a curiosity: an LTX-2.5 denoise holds the A6000 at
87-88 C with SwThermal active while its blower sits at whatever the card's own curve
chose, and the 3090 idles at 0 % — zero-RPM — so during a single-card render nothing
moves the air above it.

  gpu-fan.py                     # what every fan is doing now
  gpu-fan.py --gpu <uuid> --speed 70
  gpu-fan.py --gpu <uuid> --auto        # hand control back to the card
  gpu-fan.py --all-auto                 # hand every fan back

A manual speed is machine state, like a clock lock: it survives this process. There is
no exit trap here because the point is to leave it set — whoever sets it owns putting
it back, and `--all-auto` is that. A fan left at 100 % is loud but harmless; a fan left
at 20 % under load is not, so prefer raising.
"""

import argparse
import sys
import time

try:
    import pynvml as N
except ImportError:
    sys.exit("no pynvml: run under a venv that has nvidia-ml-py "
             "(uv run --with nvidia-ml-py python tools/gpu-fan.py ...)")


def handles():
    out = []
    for i in range(N.nvmlDeviceGetCount()):
        h = N.nvmlDeviceGetHandleByIndex(i)
        out.append((i, h, N.nvmlDeviceGetName(h), N.nvmlDeviceGetUUID(h)))
    return out


def show():
    for i, h, name, uuid in handles():
        try:
            fans = N.nvmlDeviceGetNumFans(h)
        except N.NVMLError:
            fans = 0
        speeds = []
        for f in range(fans):
            try:
                speeds.append(f"{N.nvmlDeviceGetFanSpeed_v2(h, f)}%")
            except N.NVMLError as e:
                speeds.append(f"?({e})")
        temp = N.nvmlDeviceGetTemperature(h, N.NVML_TEMPERATURE_GPU)
        try:
            policy = N.nvmlDeviceGetFanControlPolicy_v2(h, 0)
            # NVML_FAN_POLICY_TEMPERATURE_CONTINOUS_SW = 0, NVML_FAN_POLICY_MANUAL = 1.
            # Measured 2026-09-16: setting a speed flips the 3090 from 0 to 1, so 0 is the
            # card's own curve and 1 is ours — the reverse of what the names suggest.
            pol = {0: "auto", 1: "manual"}.get(policy, str(policy))
        except N.NVMLError:
            pol = "?"
        print(f"[{i}] {name:24s} {temp:3d} C  fans={fans} [{', '.join(speeds) or '-'}]  policy={pol}")
        print(f"     {uuid}")


def resolve(want):
    for i, h, name, uuid in handles():
        if want in (uuid, name, str(i)):
            return h, name, uuid
    sys.exit(f"no GPU matching {want!r}; run with no arguments to list them")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--gpu", help="UUID, exact product name, or index")
    p.add_argument("--speed", type=int, help="percent, 0-100")
    p.add_argument("--auto", action="store_true", help="return this GPU's fans to the card's curve")
    p.add_argument("--all-auto", action="store_true", help="return every GPU's fans to its curve")
    a = p.parse_args()

    N.nvmlInit()
    if a.all_auto:
        for i, h, name, uuid in handles():
            try:
                fans = N.nvmlDeviceGetNumFans(h)
            except N.NVMLError:
                continue
            for f in range(fans):
                try:
                    N.nvmlDeviceSetDefaultFanSpeed_v2(h, f)
                    print(f"{name} fan {f}: back to the card's curve")
                except N.NVMLError as e:
                    print(f"{name} fan {f}: NOT restored — {e}")
        show()
        return

    if not a.gpu:
        show()
        return

    h, name, uuid = resolve(a.gpu)
    fans = N.nvmlDeviceGetNumFans(h)
    if a.auto:
        for f in range(fans):
            try:
                N.nvmlDeviceSetDefaultFanSpeed_v2(h, f)
                print(f"{name} fan {f}: back to the card's curve")
            except N.NVMLError as e:
                print(f"{name} fan {f}: NOT restored — {e}")
    elif a.speed is not None:
        if not 0 <= a.speed <= 100:
            sys.exit("--speed must be 0-100")
        for f in range(fans):
            try:
                N.nvmlDeviceSetFanSpeed_v2(h, f, a.speed)
                print(f"{name} fan {f}: set to {a.speed}%")
            except N.NVMLError as e:
                print(f"{name} fan {f}: REFUSED — {e}")
        # the reading lags the set: a fan spinning up from zero read 0 % immediately after
        # a successful set to 60, and 53 % six seconds later. Wait before reporting, or the
        # tool appears to have done nothing.
        time.sleep(8)
    show()


if __name__ == "__main__":
    main()
