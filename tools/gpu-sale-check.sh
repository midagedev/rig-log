#!/bin/bash
# gpu-sale-check.sh <tag> — the evidence a buyer can read: one card, by UUID, under the lease.
#
# What it produces, all under /home/user/gpu-check/<tag>/:
#   identity.txt     nvidia-smi -q: name, VBIOS, serial, PCIe link, ECC/retired-page fields, current state
#   aer-before.txt / aer-after.txt   lspci error-status registers of the card and its root port
#   memtest.log      cuda_memtest over the whole VRAM (pattern tests, several passes)
#   burn.log         gpu_burn with result verification for BURN_MIN minutes (default 30)
#   dmon.csv         1 Hz witness during the burn: power, SM clock, mem clock, temp, fan, throttle reasons, VRAM
#   pcie-bw.txt      host<->device copy bandwidth (torch, pinned), 1 GiB each way, 5 reps
#   dmesg-delta.txt  kernel lines added during the run (Xid, NVRM, AER — a clean card adds none)
#   REPORT.md        the summary, with the numbers a buyer asks for and a pass/fail per section
#
# Contract: same as every take here. One lease file, the target card verified idle first, released
# on every exit path; refuses after 23:30 KST; the witness is the card's own counters at 1 Hz.
# The card is chosen by UUID (GPU=<uuid>, default the 3090 in gpu-order.env); every child process
# sees only that card through CUDA_VISIBLE_DEVICES, so nothing here can land on the other GPU.
#
#   GPU=$GF3090_UUID BURN_MIN=30 bash gpu-sale-check.sh sale-3090-1
#
# Sentinel GPUCHECK_DONE / GPUCHECK_FAILED. Signals only pids recorded at spawn.
set -u
TAG=${1:?a unique tag}
. /home/user/gpu-order.env
GPU=${GPU:-$GF3090_UUID}
BURN_MIN=${BURN_MIN:-30}
MEMTEST_PASSES=${MEMTEST_PASSES:-3}
OUT=/home/user/gpu-check/$TAG; LEASE=/home/user/gpu-lease; LEASE_TAG="gpucheck-$TAG"
TOOLS=/home/user/gpu-check-tools
mkdir -p $OUT $TOOLS
say(){ echo "$(date +%T) $*" | tee -a $OUT/run.log; }
smi(){ nvidia-smi -i $GPU "$@"; }
BUS=$(smi --query-gpu=pci.bus_id --format=csv,noheader | sed 's/^0000//' | tr 'A-F' 'a-f')   # 00000000:41:00.0 -> 0000:41:00.0
DEV=${BUS#0000}; DEV=0000${DEV}
PARENT=$(basename "$(readlink -f /sys/bus/pci/devices/$DEV/..)")

cleanup(){ rc=${1:-1}
  for p in $WPID $BPID; do [ -n "${p:-}" ] && kill -0 $p 2>/dev/null && kill -TERM $p; done
  [ -f $LEASE ] && grep -q "^$LEASE_TAG " $LEASE && rm -f $LEASE && say "lease released"
  [ $rc -eq 0 ] && echo GPUCHECK_DONE || echo GPUCHECK_FAILED; exit $rc; }
WPID=""; BPID=""
trap 'say INTERRUPTED; cleanup 1' INT TERM

# --- gates ---
[ "$(date +%H%M)" -lt 2330 ] || { say "refused: after 23:30 KST"; echo GPUCHECK_FAILED; exit 1; }
[ -f $LEASE ] && { say "refused: lease held: $(cat $LEASE)"; echo GPUCHECK_FAILED; exit 1; }
USED=$(smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null) || { say "refused: card $GPU not answering nvidia-smi"; echo GPUCHECK_FAILED; exit 1; }
[ "$USED" -lt 500 ] || { say "refused: card busy ($USED MiB)"; echo GPUCHECK_FAILED; exit 1; }
echo "$LEASE_TAG $$ $(date -Is)" > $LEASE
export CUDA_VISIBLE_DEVICES=$GPU
say "=== GPU sale check: $GPU at $DEV (root port $PARENT), burn $BURN_MIN min, memtest $MEMTEST_PASSES passes ==="

# --- identity ---
smi -q > $OUT/identity.txt
smi --query-gpu=name,vbios_version,serial,driver_version,pcie.link.gen.max,pcie.link.width.max,memory.total,power.limit,power.default_limit --format=csv | tee -a $OUT/run.log
aer(){ for d in $DEV $PARENT; do echo "## $d"; lspci -vvv -s ${d#0000:} 2>/dev/null | grep -E "LnkSta:|UESta:|CESta:"; done; }
aer > $OUT/aer-before.txt
dmesg -T > $OUT/dmesg-before.txt

# --- tools (built once, kept) ---
if [ ! -x $TOOLS/gpu_burn ]; then
  say "building gpu_burn"
  ( cd $TOOLS && [ -d gpu-burn ] || git clone -q https://github.com/wilicc/gpu-burn.git ) && \
  ( cd $TOOLS/gpu-burn && make -j8 CUDAPATH=/usr/local/cuda > $OUT/build-gpu-burn.log 2>&1 && cp gpu_burn compare.ptx $TOOLS/ ) || { say "gpu_burn build failed (see build-gpu-burn.log)"; cleanup 1; }
fi
if [ ! -x $TOOLS/cuda_memtest ]; then
  say "building cuda_memtest"
  ( cd $TOOLS && [ -d cuda_memtest ] || git clone -q https://github.com/ComputationalRadiationPhysics/cuda_memtest.git ) && \
  ( cd $TOOLS/cuda_memtest && mkdir -p build && cd build && cmake .. -DCMAKE_BUILD_TYPE=Release > $OUT/build-memtest.log 2>&1 && make -j8 >> $OUT/build-memtest.log 2>&1 && cp cuda_memtest $TOOLS/ ) || { say "cuda_memtest build failed (see build-memtest.log)"; cleanup 1; }
fi

# --- witness ---
smi --query-gpu=timestamp,power.draw,clocks.sm,clocks.mem,temperature.gpu,fan.speed,memory.used,utilization.gpu,clocks_throttle_reasons.active --format=csv -l 1 > $OUT/dmon.csv 2>/dev/null &
WPID=$!; echo $WPID > $OUT/witness.pid

# --- 1. VRAM test ---
say "memtest: $MEMTEST_PASSES passes over all VRAM"
t0=$(date +%s)
$TOOLS/cuda_memtest --num_passes $MEMTEST_PASSES --stress > $OUT/memtest.log 2>&1; MRC=$?
say "memtest rc=$MRC after $(( $(date +%s)-t0 )) s; errors reported: $(grep -ciE "error|fail" $OUT/memtest.log)"

# --- 2. burn with verification ---
say "gpu_burn: $BURN_MIN min, results compared against a reference"
t0=$(date +%s)
( cd $TOOLS && ./gpu_burn -c compare.ptx $((BURN_MIN*60)) ) > $OUT/burn.log 2>&1 &
BPID=$!; echo $BPID > $OUT/burn.pid; wait $BPID; BRC=$?; BPID=""
say "gpu_burn rc=$BRC after $(( $(date +%s)-t0 )) s; verdict line: $(grep -E "OK|FAULTY" $OUT/burn.log | tail -1)"

# --- 3. PCIe bandwidth (torch, pinned host memory) ---
say "pcie bandwidth"
/home/user/LTX-2/.venv/bin/python - > $OUT/pcie-bw.txt 2>&1 <<'PY'
import torch, time
n = 1 << 30
h = torch.empty(n, dtype=torch.uint8, pin_memory=True); d = torch.empty(n, dtype=torch.uint8, device="cuda")
def bw(fn):
    torch.cuda.synchronize(); best = 0
    for _ in range(5):
        t = time.perf_counter(); fn(); torch.cuda.synchronize(); best = max(best, n / (time.perf_counter() - t) / 1e9)
    return best
print(f"device: {torch.cuda.get_device_name(0)}")
print(f"H2D pinned 1 GiB: {bw(lambda: d.copy_(h, non_blocking=True)):.1f} GB/s")
print(f"D2H pinned 1 GiB: {bw(lambda: h.copy_(d, non_blocking=True)):.1f} GB/s")
x = torch.randn(8192, 8192, device="cuda", dtype=torch.float16)
torch.cuda.synchronize(); t = time.perf_counter()
for _ in range(20): y = x @ x
torch.cuda.synchronize(); dt = time.perf_counter() - t
print(f"fp16 matmul 8192^3 x20: {20 * 2 * 8192**3 / dt / 1e12:.1f} TFLOPS")
PY
cat $OUT/pcie-bw.txt | tee -a $OUT/run.log

# --- wrap up ---
kill -TERM $WPID 2>/dev/null; WPID=""
aer > $OUT/aer-after.txt
dmesg -T > $OUT/dmesg-after.txt
diff $OUT/dmesg-before.txt $OUT/dmesg-after.txt | grep "^>" | grep -iE "Xid|NVRM|AER|pcieport" > $OUT/dmesg-delta.txt
XID=$(wc -l < $OUT/dmesg-delta.txt)
python3 - "$OUT" "$GPU" "$BURN_MIN" "$MRC" "$BRC" "$XID" <<'PY'
import csv, sys, statistics as st
out, gpu, burn_min, mrc, brc, xid = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
rows = [r for r in csv.reader(open(f"{out}/dmon.csv")) if len(r) >= 9 and r[0].strip() != "timestamp"]
def col(i):
    v = []
    for r in rows:
        try: v.append(float(r[i].split()[0]))
        except: pass
    return v
pw, sm, mem, tmp, fan = col(1), col(2), col(3), col(4), col(5)
reasons = sorted({r[8].strip() for r in rows})
ident = open(f"{out}/identity.txt").read()
def field(k):
    for line in ident.splitlines():
        if line.strip().startswith(k): return line.split(":",1)[1].strip()
    return "?"
burn_verdict = [l for l in open(f"{out}/burn.log").read().splitlines() if "OK" in l or "FAULTY" in l]
memtest_err = sum(1 for l in open(f"{out}/memtest.log") if "ERROR" in l.upper() or "FAIL" in l.upper())
bw = open(f"{out}/pcie-bw.txt").read().strip()
aer_b = open(f"{out}/aer-before.txt").read(); aer_a = open(f"{out}/aer-after.txt").read()
lines = []
lines.append(f"# GPU sale check — {field('Product Name')} ({gpu})\n")
lines.append(f"- VBIOS {field('VBIOS Version')} · serial {field('Serial Number')} · driver {field('Driver Version')}")
lines.append(f"- PCIe max gen {field('Max')} · samples {len(rows)} at 1 Hz\n")
lines.append("| test | result | verdict |\n|---|---|---|")
lines.append(f"| cuda_memtest, all VRAM | rc {mrc}, {memtest_err} error lines | {'PASS' if mrc==0 and memtest_err==0 else 'FAIL'} |")
lines.append(f"| gpu_burn {burn_min} min, verified | rc {brc}, {burn_verdict[-1].strip() if burn_verdict else 'no verdict line'} | {'PASS' if brc==0 and burn_verdict and 'FAULTY' not in burn_verdict[-1] else 'FAIL'} |")
if pw:
    lines.append(f"| power under burn | max {max(pw):.0f} W, mean {st.mean(pw):.0f} W | — |")
    lines.append(f"| SM clock under burn | min {min(sm):.0f}, mean {st.mean(sm):.0f} MHz | — |")
    lines.append(f"| memory clock | {min(mem):.0f}–{max(mem):.0f} MHz | — |")
    lines.append(f"| temperature | max {max(tmp):.0f} °C | {'PASS' if max(tmp) < 90 else 'HOT'} |")
    lines.append(f"| fan | max {max(fan):.0f} % | — |")
    lines.append(f"| throttle reasons seen | {', '.join(reasons)} | — |")
lines.append(f"| kernel log delta (Xid/NVRM/AER) | {xid} lines | {'PASS' if xid==0 else 'FAIL'} |")
lines.append(f"| PCIe AER registers unchanged | {'yes' if aer_b==aer_a else 'CHANGED'} | {'PASS' if aer_b==aer_a else 'CHECK'} |")
lines.append("\n## PCIe bandwidth and compute\n```\n" + bw + "\n```\n")
lines.append("## AER registers after\n```\n" + aer_a + "```\n")
lines.append("Files: identity.txt, memtest.log, burn.log, dmon.csv, pcie-bw.txt, dmesg-delta.txt, aer-before/after.txt.")
open(f"{out}/REPORT.md","w").write("\n".join(lines)+"\n"); print("\n".join(lines))
PY
RC=0; [ $MRC -eq 0 ] && [ $BRC -eq 0 ] && [ $XID -eq 0 ] || RC=1
say "=== done, rc $RC; report $OUT/REPORT.md ==="
cleanup $RC
