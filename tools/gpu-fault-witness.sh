#!/bin/bash
# dma-witness.sh — four independent loggers, each stamping its own rows.
#
# This is the 2026-09-18 witness with the three defects its own run exposed, fixed:
#
#  1. It queried by INDEX. After the fault nvidia-smi renumbers the survivor to
#     position 0, so the column labelled with the dead card carried the live one's
#     readings. Everything here is pinned by UUID.
#  2. Its presence test was "did the nvidia-smi query return anything", which kept
#     saying yes because the surviving card kept answering. `nvidia-smi -L` counting
#     cards is the honest test, and it runs in 30-40 ms.
#  3. Its BMC channel cost 5.2 s a sample because every ipmitool call re-walked the
#     sensor repository. Dumping the SDR once and passing it back with -S, and naming
#     the sensor exactly ("PCIE01 Temp.", not "PCIE01"), takes the same reading in
#     0.11 s. That matters more than it sounds: the central claim of the last run was
#     an ORDERING between this channel and the driver's, and the channel could not
#     resolve anything finer than five seconds.
#
# A fourth thing is new rather than fixed: `nvidia-smi dmon -s put` reports rxpci and
# txpci in MB/s, which is the variable this whole experiment is about, and no previous
# run recorded it.
#
# The loggers do NOT share a timestamp and are not meant to. Each writes its own
# precise clock and they run as separate processes, so no logger can delay another --
# which is the artefact the last witness only just avoided.
#
#   bash dma-witness.sh <outdir> [seconds]
set -u
OUT=${1:?outdir}; SECS=${2:-1200}
GF3090=GPU-307fa0f6-daae-24e5-6fd3-cd50620de6b1
A6000=GPU-8c129fa6-7382-35a5-2464-9ff01d99fcd4
mkdir -p "$OUT"
HERE=$(cd "$(dirname "$0")" && pwd)

say(){ echo "$(date +%T) $*" | tee -a "$OUT/witness.log"; }

# Record a pid the only way that is safe here: from $! at spawn, then assert what it
# actually is. Measured three times on this machine that $! named a wrapper -- a
# compound command, a sudo, and a backgrounded shell function -- and the runner then
# signalled the wrapper while the program kept going.
note_pid(){ # note_pid <pid> <name> <expected comm>
  echo "$1" > "$OUT/$2.pid"
  local c; c=$(cat /proc/$1/comm 2>/dev/null || echo GONE)
  say "  $2 pid $1 comm=$c (expected $3)"
  [ "$c" = "$3" ] || say "  !! $2: recorded pid is a $c, not a $3 -- stopping it may not stop the program"
}

say "=== rung-1 witness, ${SECS}s, out $OUT ==="
ipmitool sdr dump "$OUT/sdr.cache" >/dev/null 2>&1 && say "SDR cached" || say "!! SDR dump failed; BMC rows will be slow"

# --- per-card telemetry at 1 Hz, pinned by UUID -----------------------------------
nvidia-smi dmon -s put -d 1 -o T -i "$GF3090" > "$OUT/dmon-3090.log" 2>&1 &
note_pid $! dmon-3090 nvidia-smi
nvidia-smi dmon -s put -d 1 -o T -i "$A6000" > "$OUT/dmon-a6000.log" 2>&1 &
note_pid $! dmon-a6000 nvidia-smi

# --- the BMC's side-band channel, as fast as it will go ---------------------------
# Its whole value is that it reaches the card without PCIe and without the NVIDIA
# driver. It is the only clock in this run that is independent of the thing under test.
bash "$HERE/gpu-fault-witness-bmc.sh" "$OUT" "$SECS" > "$OUT/bmc.csv" 2>"$OUT/bmc.err" &
note_pid $! bmc bash

# --- the driver's own answer to "how many cards are there" ------------------------
bash "$HERE/gpu-fault-witness-presence.sh" "$OUT" "$SECS" > "$OUT/presence.csv" 2>"$OUT/presence.err" &
note_pid $! presence bash

say "all four loggers up; stop them with: bash $HERE/gpu-witness-stop.sh $OUT"
