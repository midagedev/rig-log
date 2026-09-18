#!/usr/bin/env python3
"""Rung 1 of the fault ladder: sustained pinned host <-> device DMA, and no NCCL.

2026-09-18. Two NCCL DDP runs took the 3090 off the bus, at 133 s and at 110 s.
Three controls did not: a 30-minute solo gpu_burn on the same card at 421 W, a
10-minute dual-card burn, and the reseat battery. Peak power is not the variable
-- the fault happened at 384 W and the clean burn reached 420 W. What every clean
row has in common is that it is compute-bound: the SMs are busy and the PCIe link
is nearly idle. NCCL with P2P disabled stages every gradient through pinned host
memory, so the host interface is the thing it exercises and no control ever did.

This file varies that one variable and nothing else. No NCCL, no torch.distributed,
no model, no second CUDA context: one process per card, pinned host buffers, and
copies in both directions deep enough to keep the DMA engines busy.

  - If a card falls off the bus under this, bus traffic is the variable, NCCL is a
    red herring, and the reproducer is this file.
  - If both cards survive this while NCCL kills one, then bus pressure alone is not
    sufficient and the fault needs the driver or firmware path -- which is exactly
    the tension the entry left open.

The card is chosen by UUID through CUDA_VISIBLE_DEVICES in the launcher and never
by index. After a fault nvidia-smi renumbers the survivor to position 0, which is
how a column in the last run's witness came to mean the other card.
"""

import argparse
import os
import signal
import sys
import time

import torch

ap = argparse.ArgumentParser()
ap.add_argument("--mb", type=int, default=25,
                help="MiB per transfer (default 25: PyTorch DDP's default gradient bucket cap, "
                     "so the transfer size matches what the faulting run actually moved)")
ap.add_argument("--depth", type=int, default=8, help="transfers in flight per direction")
ap.add_argument("--seconds", type=float, default=900.0)
ap.add_argument("--compute", type=int, default=0, metavar="N",
                help="also run an N x N fp32 matmul loop on its own stream, beside the DMA. "
                     "Rung 1 moved 37 GB/s across the link at 160 W and nothing happened, so the "
                     "next thing to vary is whether the fault needs the SMs loaded at the same "
                     "time: the faulting run was at 384 W. 0 disables it (that is rung 1).")
ap.add_argument("--compute-iters", type=int, default=4,
                help="matmuls enqueued per DMA iteration; raise to buy power, at the cost of "
                     "some of the transfer rate")
ap.add_argument("--label", default="card")
ap.add_argument("--pidfile", default=None,
                help="write our own pid here. The launcher cannot record it: an env-var prefix "
                     "plus setsid makes bash fork, so $! names the wrapper and not this process. "
                     "That has now cost this machine four incidents; the program says who it is.")
a = ap.parse_args()

seen = torch.cuda.device_count()
if seen != 1:
    sys.exit(f"expected exactly one visible card, saw {seen}: point CUDA_VISIBLE_DEVICES "
             f"at one GPU UUID (it is {os.environ.get('CUDA_VISIBLE_DEVICES')!r})")

dev = torch.device("cuda:0")
name = torch.cuda.get_device_name(0)


def say(*x):
    print(time.strftime("%H:%M:%S"), f"[{a.label}]", *x, flush=True)


say(f"{name}  via CUDA_VISIBLE_DEVICES={os.environ.get('CUDA_VISIBLE_DEVICES')}")
say(f"torch {torch.__version__}  cuda {torch.version.cuda}  pid {os.getpid()}")
if a.pidfile:
    with open(a.pidfile, "w") as fh:
        fh.write(f"{os.getpid()}\n")

n = (a.mb * 1024 * 1024) // 4
h_up = [torch.empty(n, dtype=torch.float32, pin_memory=True) for _ in range(a.depth)]
h_dn = [torch.empty(n, dtype=torch.float32, pin_memory=True) for _ in range(a.depth)]
d_up = [torch.empty(n, dtype=torch.float32, device=dev) for _ in range(a.depth)]
d_dn = [torch.empty(n, dtype=torch.float32, device=dev) for _ in range(a.depth)]
for b in h_up:
    b.fill_(1.5)
for b in d_dn:
    b.fill_(2.5)

per_iter = 2 * a.depth * n * 4
say(f"{a.mb} MiB x {a.depth} deep, both directions: {per_iter / 1e6:.0f} MB per iteration; "
    f"host {2 * a.depth * n * 4 / 1e9:.2f} GB pinned, device {2 * a.depth * n * 4 / 1e9:.2f} GB")

# Separate streams so the two directions are in flight at once. That is the shape
# the staging path has -- a gradient going out while the reduced one comes back --
# and a one-direction-at-a-time loop would not put the root port in the same state.
s_up = torch.cuda.Stream(device=dev)
s_dn = torch.cuda.Stream(device=dev)

s_cmp = None
if a.compute:
    m = a.compute
    mA = torch.randn(m, m, device=dev)
    mB = torch.randn(m, m, device=dev)
    mC = torch.empty(m, m, device=dev)
    s_cmp = torch.cuda.Stream(device=dev)
    say(f"compute: {m}x{m} fp32 matmul x{a.compute_iters} per iteration, on its own stream")

stop = False


def on_signal(signum, _frame):
    global stop
    stop = True
    say(f"signal {signum}: finishing the current iteration and stopping")


signal.signal(signal.SIGTERM, on_signal)
signal.signal(signal.SIGINT, on_signal)

t0 = time.time()
moved = 0
iters = 0
last_report = t0
torch.cuda.synchronize()
say("DMA loop starts")

while not stop and (time.time() - t0) < a.seconds:
    with torch.cuda.stream(s_up):
        for i in range(a.depth):
            d_up[i].copy_(h_up[i], non_blocking=True)
    with torch.cuda.stream(s_dn):
        for i in range(a.depth):
            h_dn[i].copy_(d_dn[i], non_blocking=True)
    if s_cmp is not None:
        with torch.cuda.stream(s_cmp):
            for _ in range(a.compute_iters):
                torch.mm(mA, mB, out=mC)
    s_up.synchronize()
    s_dn.synchronize()
    if s_cmp is not None:
        s_cmp.synchronize()
    moved += per_iter
    iters += 1
    now = time.time()
    if now - last_report >= 5.0:
        el = now - t0
        say(f"{el:6.0f}s  iter {iters:6d}  {moved / el / 1e9:5.1f} GB/s aggregate "
            f"({moved / el / 2e9:5.1f} each way)")
        last_report = now

el = time.time() - t0
say(f"done: {iters} iterations, {moved / 1e9:.0f} GB in {el:.0f}s, "
    f"{moved / el / 1e9:.1f} GB/s aggregate")
