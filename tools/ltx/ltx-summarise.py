#!/usr/bin/env python3
"""ltx-summarise.py <run-dir>... — recompute one take's numbers from its raw witness.

Exists because the first ltx-take.sh printed its own summary with an awk that compared
CSV fields as strings: it reported a peak of 8022 MiB for a run whose real peak was
48016, because "8022" sorts above "42812". The raw dmon.csv survived the bug, so every
take from before the fix is still readable — which is the argument for writing the
witness to a file instead of only summarising it into a log line.

The denoise windows are the numbers that matter. A whole-run mean is diluted by model
building and VAE decode, which on this box are a third of the wall time, so power,
clock and temperature are averaged over each denoising loop alone, bounded by the
stamps in run.log.
"""

import re
import sys
from pathlib import Path

STAGE = re.compile(r"(\d\d):(\d\d):(\d\d)\s+(?:INFO:[a-z_.]*:)?(.*)")
DENOISE = re.compile(r"Running denoising loop \((\d+) steps, (\S+) (\d+) frames")
BOUNDARY = re.compile(r"Building (?:video encoder|video decoder|transformer)|Video saved")


def stamps(run_log):
    """(seconds, text) for every stamped line we treat as a stage boundary."""
    out = []
    for line in run_log.read_text(errors="replace").splitlines():
        m = STAGE.match(line)
        if not m:
            continue
        text = m.group(4)
        if DENOISE.search(text) or BOUNDARY.search(text):
            out.append((int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)), text))
    return out


def witness(dmon_csv, uuid):
    """second -> (watts, sm_mhz, celsius, util, mib, mem_mhz) for one card, numerically.

    mem_mhz is absent from takes recorded before 2026-09-16 12:50, when the memory
    clock joined the query; those rows report it as 0 rather than failing to parse.
    """
    rows = {}
    for line in dmon_csv.read_text(errors="replace").splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) < 8 or f[1] != uuid:
            continue
        hms = f[0].split()[-1].split(".")[0].split(":")
        try:
            rows[int(hms[0]) * 3600 + int(hms[1]) * 60 + int(hms[2])] = (
                float(f[2]), float(f[3]), float(f[4]), float(f[6]), float(f[5]),
                float(f[8]) if len(f) > 8 and f[8].isdigit() else 0.0)
        except ValueError:
            continue  # nvidia-smi prints "[N/A]" for a field it cannot read
    return rows


def peaks(dmon_csv):
    m = {}
    for line in dmon_csv.read_text(errors="replace").splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) < 8:
            continue
        try:
            used = int(f[5])
        except ValueError:
            continue
        m[f[1]] = max(m.get(f[1], 0), used)
    return m


def throttles(dmon_csv, uuid):
    BITS = {0x1: "GpuIdle", 0x4: "SwPowerCap", 0x8: "HwSlowdown", 0x20: "SwThermal",
            0x40: "HwThermal", 0x80: "HwPowerBrake", 0x400: "DisplayClock"}
    seen = set()
    for line in dmon_csv.read_text(errors="replace").splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) < 8 or f[1] != uuid:
            continue
        try:
            v = int(f[7], 16)
        except ValueError:
            continue
        seen |= {name for bit, name in BITS.items() if v & bit}
    return seen


def main():
    uuid = None
    for line in Path("/home/user/gpu-order.env").read_text().splitlines():
        if line.startswith("export A6000_UUID="):
            uuid = line.split("=", 1)[1].strip()
    if not uuid:
        sys.exit("no A6000_UUID in /home/user/gpu-order.env")

    for d in (Path(x) for x in sys.argv[1:]):
        if not (d / "dmon.csv").exists():
            print(f"=== {d}: no dmon.csv")
            continue
        print(f"=== {d.name}")
        for u, mib in sorted(peaks(d / "dmon.csv").items(), key=lambda kv: -kv[1]):
            tag = "A6000" if u == uuid else "3090 "
            print(f"  peak VRAM  {tag}  {mib:6d} MiB")
        if not (d / "run.log").exists():
            continue
        w = witness(d / "dmon.csv", uuid)
        st = stamps(d / "run.log")
        for i, (t0, text) in enumerate(st):
            t1 = st[i + 1][0] if i + 1 < len(st) else max(w, default=t0)
            win = [v for s, v in w.items() if t0 <= s < t1]
            if not win or t1 <= t0:
                continue
            n = len(win)
            m = DENOISE.search(text)
            if m:
                name = f"denoise {m.group(2)} {int(m.group(3))}f"
                per = f"{(t1 - t0) / int(m.group(1)):6.2f} s/step"
            else:
                name = text.replace("Building ", "").strip()[:26]
                per = f"{t1 - t0:6.0f} s     "
            print(f"  {name:<26} {per}  {max(x[4] for x in win):6.0f} MiB  "
                  f"{sum(x[0] for x in win) / n:4.0f} W  "
                  f"{sum(x[1] for x in win) / n:4.0f} MHz sm  "
                  f"{sum(x[5] for x in win) / n:4.0f} MHz mem  "
                  f"{max(x[2] for x in win):3.0f} C  "
                  f"{sum(x[3] for x in win) / n:3.0f}% util")
        rss = re.search(r"Maximum resident set size \(kbytes\):\s*(\d+)",
                        (d / "run.log").read_text(errors="replace"))
        if rss:
            print(f"  peak host RSS {int(rss.group(1)) / 1048576:.1f} GiB")
        print(f"  throttle reasons on the A6000: {' '.join(sorted(throttles(d / 'dmon.csv', uuid))) or 'none'}")


if __name__ == "__main__":
    main()
