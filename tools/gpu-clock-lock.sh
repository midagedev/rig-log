#!/bin/bash
# gpu-clock-lock.sh <gr-MHz|-> <mem-MHz|-> -- <command…>
#
# One owner for clock locks on the A6000, the way configs/gpu-order.env is the one
# owner for device order. Locks, runs the command, and resets on every exit path
# including a signal: a card left at 5001 MHz memory would silently poison every
# measurement taken on this box afterwards, by this session and by the other two.
#
# Why locks and not the power cap: at the default 300 W the card is already both
# power-capped and thermally capped (SwPowerCap + SwThermal, measured 2026-09-16 on
# an LTX-2.5 denoise), so lowering the cap moves two things at once. Locking a clock
# moves one. And the two locks are orthogonal instruments: sweep the graphics clock
# with memory at its top state to price compute, sweep the memory clock with a
# graphics lock the power cap can actually sustain to price bandwidth.
#
# A lock is a request, never a reading. The command's own witness must show the
# achieved clock during the window that matters, and a row whose achieved clock is
# not within a few percent of the lock is struck rather than plotted. `-` skips a
# lock for that axis.
#
#   gpu-clock-lock.sh 1500 8001 -- env OFFLOAD=none bash /home/user/ltx-take.sh s-gr1500
#
# A6000 memory clock states: 405, 810, 5001, 7601, 8001 MHz. Graphics: 127 states to 2100.
set -u
GR=${1:?graphics clock MHz or -}; MEM=${2:?memory clock MHz or -}; shift 2
[ "${1:-}" = "--" ] || { echo "refused: expected -- before the command"; exit 64; }
shift
[ $# -gt 0 ] || { echo "refused: no command"; exit 64; }
. /home/user/gpu-order.env
I="-i $A6000_UUID"
say(){ echo "$(date +%T) clock-lock: $*"; }
reset(){
  local rc=0
  nvidia-smi $I -rgc >/dev/null 2>&1 || rc=1
  nvidia-smi $I -rmc >/dev/null 2>&1 || rc=1
  local now; now=$(nvidia-smi $I --query-gpu=clocks.max.gr,clocks.max.mem --format=csv,noheader)
  if [ $rc -eq 0 ]; then say "reset; max now $now"
  else say "RESET FAILED — card may still be locked: max now $now"; fi
  return $rc; }
trap 'reset; exit 130' INT TERM
if [ "$GR" != "-" ]; then
  nvidia-smi $I -lgc "$GR","$GR" >/dev/null || { say "cannot lock graphics to $GR"; reset; exit 1; }
fi
if [ "$MEM" != "-" ]; then
  nvidia-smi $I -lmc "$MEM","$MEM" >/dev/null || { say "cannot lock memory to $MEM"; reset; exit 1; }
fi
# The lock is this script's doing, so recording what the card actually did is this
# script's job too: a wrapped runner that keeps no witness of its own still produces a
# self-validating row. Sampled only while the card is busy (util > 50 %), because the
# idle memory clock is 405 MHz and would drag every mean toward it.
W=${CLOCK_WITNESS:-/home/user/clock-lock/gr${GR}-mem${MEM}-$(date +%H%M%S).csv}
mkdir -p "$(dirname "$W")"
nvidia-smi $I --query-gpu=timestamp,clocks.sm,clocks.mem,utilization.gpu,power.draw,temperature.gpu \
  --format=csv,noheader,nounits -l 1 > "$W" 2>&1 &
SM=$!
say "gr=${GR} mem=${MEM} requested; witness $W"
"$@"; rc=$?
kill $SM 2>/dev/null
achieved=$(awk -F, '{ gsub(/ /,"",$4) } $4+0 > 50 { sm+=$2; mem+=$3; p+=$5; if ($6+0>t) t=$6+0; n++ }
  END { if (n) printf "sm %.0f MHz, mem %.0f MHz, %.0f W, %d C, over %d busy samples", sm/n, mem/n, p/n, t, n
        else print "NO BUSY SAMPLES — the row has no achieved clock and cannot be plotted" }' "$W")
say "achieved: $achieved"
# Both axes are checked, not just the graphics one: nvidia-smi accepts -lmc and
# returns success while the card is idle, and nothing reports the lock back — the only
# proof is the achieved clock under load. An unchecked memory axis would read 7601 in
# every row and plot as "bandwidth does not matter", which is the answer being tested.
check(){ local want=$1 field=$2 name=$3
  [ "$want" = "-" ] && return 0
  local a; a=$(awk -F, -v f="$field" '{ gsub(/ /,"",$4) } $4+0 > 50 { v+=$f; n++ } END { if (n) printf "%.0f", v/n }' "$W")
  [ -n "$a" ] || { say "$name: no busy samples — strike this row"; return 1; }
  local d=$(( a > want ? a - want : want - a ))
  if [ $(( d * 100 / want )) -le 3 ]; then say "$name lock held (${a} vs ${want})"
  else say "$name LOCK NOT HELD (${a} vs ${want}) — strike this row"; fi; }
check "$GR" 2 graphics
check "$MEM" 3 memory
reset || rc=1
exit $rc
