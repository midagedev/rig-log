#!/usr/bin/env python3
"""gpu-power-fast.py — per-card power as fast as NVML will answer.

Every power number this investigation has rests on is a 1 Hz sample or worse, and the
hypothesis that survives the two DMA rungs is about what happens BETWEEN samples: NCCL
makes both cards wait for each other and then draw together, which is a transient
structure that a one-second mean cannot show. dmon's floor is 1 s; NVML has no such
floor, so this polls it directly and records whatever rate it actually delivers.

--probe measures the instrument before trusting it: poll flat out for a few seconds and
report how often the reading actually CHANGES, which is the sensor's real update rate
rather than the loop's.
"""
import argparse, os, sys, time
import pynvml as N

ap = argparse.ArgumentParser()
ap.add_argument("--uuid", action="append", required=True, help="repeatable; one column per card")
ap.add_argument("--hz", type=float, default=200.0)
ap.add_argument("--seconds", type=float, default=60.0)
ap.add_argument("--probe", action="store_true", help="measure the sensor's update rate and exit")
a = ap.parse_args()

N.nvmlInit()
hs = [(u, N.nvmlDeviceGetHandleByUUID(u.encode())) for u in a.uuid]

if a.probe:
    for u, h in hs:
        name = N.nvmlDeviceGetName(h)
        t0 = time.time(); n = 0; changes = 0; prev = None
        while time.time() - t0 < 3.0:
            v = N.nvmlDeviceGetPowerUsage(h); n += 1
            if v != prev:
                changes += 1; prev = v
        el = time.time() - t0
        print(f"{name}: {n/el:8.0f} polls/s, {changes/el:6.1f} distinct readings/s "
              f"-> sensor updates about every {el/max(changes,1)*1000:.0f} ms")
    sys.exit(0)

period = 1.0 / a.hz
print("epoch," + ",".join(f"w_{u[-6:]}" for u, _ in hs), flush=True)
end = time.time() + a.seconds
nxt = time.time()
while time.time() < end:
    row = [f"{time.time():.6f}"]
    for _u, h in hs:
        try:
            row.append(str(N.nvmlDeviceGetPowerUsage(h)))
        except N.NVMLError:
            row.append("")
    print(",".join(row))
    nxt += period
    d = nxt - time.time()
    if d > 0:
        time.sleep(d)
    else:
        nxt = time.time()
