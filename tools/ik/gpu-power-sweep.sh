#!/bin/bash
# gpu-power-sweep.sh <tag-prefix> [caps…] — is this rate the board power cap or the memory path?
#
# Runs ik-vram-take.sh once per board power limit on GPU0, with nothing else
# changed, and restores the default limit on every exit path. Born 2026-09-15,
# when every card of the day carried `throttled: yes` and the honest answer was
# that nobody had taken the budget away to see: 281 W -> 141 tok/s, 199 W -> 133,
# 150 W -> 120, so 47 % less power cost 15 % of the rate and the cap was not the
# ceiling. A boolean throttle flag cannot tell you that; a sweep can.
#
# 2026-09-16: every `nvidia-smi -i 0` here was addressing the 3090 (420 W default limit),
# not the A6000 its own comments named, because -i is bus order and the A6000 moved to
# bus 61 that morning. A sweep of a card that was never capped reads as "not power
# bound", which is the one answer this tool exists to rule out. Addressed by UUID from
# gpu-order.env now, the same fix as every other runner in this repo.
#
#   M=/models/…/x.gguf PROMPT_FILES=/home/user/s1.txt \
#     gpu-power-sweep.sh qwen36-q4 300 200 150
#
# Every other knob is ik-vram-take.sh's (M, CTX, UB, THREADS, SESSIONS, NPRED,
# FOR, PROMPT/PROMPT_FILES, TOKTAPE, EXTRA_FLAGS, NOTE).
set -u
. /home/user/gpu-order.env   # -i 0 is bus order: after the 2026-09-16 slot move that is the 3090
SMI_I="-i $A6000_UUID"
PREFIX=${1:?tag prefix required}; shift
CAPS=${*:-$(nvidia-smi $SMI_I --query-gpu=power.default_limit --format=csv,noheader,nounits | cut -d. -f1)}
TAKE=${TAKE:-/home/user/ik-vram-take.sh}
OUT=${OUT:-/home/user/ik-vram}; mkdir -p "$OUT"
DEF=$(nvidia-smi $SMI_I --query-gpu=power.default_limit --format=csv,noheader,nounits | cut -d. -f1)
[ -r "$TAKE" ] || { echo "refused: no take runner at $TAKE"; exit 1; }
# the cap is machine state, so it is restored on every exit -- including a signal
restore(){ nvidia-smi $SMI_I -pl "$DEF" >/dev/null 2>&1
  echo "$(date +%H:%M:%S) cap restored to $(nvidia-smi $SMI_I --query-gpu=power.limit --format=csv,noheader,nounits) W"; }
trap restore EXIT
for pl in $CAPS; do
  nvidia-smi $SMI_I -pl "$pl" >/dev/null || { echo "could not set cap $pl W (root? within min/max?)"; exit 1; }
  echo "=== cap now $(nvidia-smi $SMI_I --query-gpu=power.limit --format=csv,noheader,nounits) W"
  L=$OUT/$PREFIX-pl$pl.log
  NOTE="${NOTE:-$PREFIX}, A6000 board power cap ${pl} W" bash "$TAKE" "$PREFIX-pl$pl" > "$L" 2>&1
  echo "rc $? log $L"
  grep -E "Decode|GPU0 [0-9]+°C|IK_VRAM|✓ Tape " "$L"
done
