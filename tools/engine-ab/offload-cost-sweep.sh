#!/bin/bash
# offload-cost-sweep.sh <engine> [levels] — what does moving weight off the card cost each engine?
#
# 2026-09-17 established the offload *surface*: llama.cpp and ik_llama.cpp both have `-ot NAME=buft`,
# `-cmoe` and `-ncmoe N`; mistral.rs has only layer-granular `-n ORD:NUM`, and until #2430 that was
# broken on any GGUF MoE model. None of them has a disk tier. What none of it says is the price, and
# the price is the whole question: ik keeps a layer's attention and KV on the card and sends only its
# experts, mistral.rs sends the layer whole. That predicts ik degrades more gently, and a prediction
# is not a measurement.
#
# So: one level is "the experts of the first L blocks are off the card", and each engine expresses it
# its own way — `-ncmoe L` against `-n 0:$((40-L))`. On this model those are close in bytes (A3B: a
# block is mostly its expert stack) and deliberately not identical in *kind*, which is the finding
# rather than a flaw in the design. The pairing axis reported is therefore measured VRAM, sampled
# while the take runs, not flag arithmetic.
#
# One stream per row. Concurrency is entry -b's subject and it moves both engines for reasons that
# have nothing to do with placement; mixing the two would make neither readable. Thinking stays on
# with `-n 512` for the reason stream-sweep.sh documents: every window stays full.
#
#   offload-cost-sweep.sh mrs 0,1,4,10
#   offload-cost-sweep.sh ik  0,1,4,10
#
# Rows whose runner did not print its DONE sentinel are named and excluded, never tabulated.
set -u
ENGINE=${1:?engine required: mrs | ik}
LEVELS=${2:-0,1,4,10}
PREFIX=${PREFIX:-offload}
M=${M:-/models/Qwen3.6-35B-A3B/Qwen3.6-35B-A3B-UD-Q6_K.gguf}
NBLOCKS=${NBLOCKS:-40}
CTX=${CTX:-8192}; NPRED=${NPRED:-512}; FOR=${FOR:-240s}; SLOTS=${SLOTS:-1}
OUT=${OUT:-/home/user/offload}; mkdir -p $OUT
PROMPT_DIR=${PROMPT_DIR:-/home/user/hero5}
LEASE=/home/user/gpu-lease
say(){ echo "$(date +%H:%M:%S) offload: $*"; }

case $ENGINE in
  mrs) RUNNER=/home/user/mrs-take.sh;     SENT=MRS_TAKE ;;
  ik)  RUNNER=/home/user/ik-vram-take.sh; SENT=IK_VRAM ;;
  *)   say "refused: engine must be mrs or ik"; exit 1 ;;
esac
[ -x "$RUNNER" ] || { say "refused: no runner at $RUNNER"; exit 1; }
[ -f "$M" ] || { say "refused: no model at $M"; exit 1; }

# Waits on the lease file, never on a pid pattern: a pgrep for this script's own name matches this
# shell's command line, which is a loop that never ends.
wait_lease(){
  local i
  for i in $(seq 180); do [ -f $LEASE ] || return 0; sleep 5; done
  say "lease still held after 15 min: $(cat $LEASE 2>/dev/null)"; return 1
}

# The pairing axis. Sampled rather than derived, because both engines report a device *capacity* at
# load and neither reports the bytes it actually placed. Only the pid recorded here is ever signalled.
sample_vram(){ local f=$1
  while :; do nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1 >> $f; sleep 5; done; }

OIFS=$IFS; IFS=','
for L in $LEVELS; do
  IFS=$OIFS
  [ "$L" -ge 0 ] && [ "$L" -lt "$NBLOCKS" ] || { say "refused: level $L outside 0..$((NBLOCKS-1))"; exit 1; }
  wait_lease || exit 1
  TAG="$PREFIX-$ENGINE-L$L"; LOG=$OUT/$TAG.log; VR=$OUT/$TAG.vram
  : > $VR; sample_vram $VR & SAMP=$!
  case $ENGINE in
    mrs) XTRA="-n 0:$((NBLOCKS-L))" ;;
    ik)  [ "$L" -eq 0 ] && XTRA="" || XTRA="-ncmoe $L" ;;
  esac
  say "--- $TAG: experts of $L block(s) off the card, one stream, ctx $CTX, n $NPRED, flags '$XTRA'"
  # the whole runner output goes to a file, never through a pipe: a pipeline's exit status is the
  # pager's, and a failed take that reads green is a row in the table that should not be there
  case $ENGINE in
    mrs) env M="$M" MRS=${MRS:-/home/user/mistral.rs/target/release/mistralrs} \
             CTX=$CTX MAXSEQS=$SLOTS SESSIONS=1 NPRED=$NPRED FOR=$FOR \
             PROMPT_FILES="$PROMPT_DIR/hl1.txt" MRS_EXTRA="$XTRA" \
             NOTE="offload cost, $L of $NBLOCKS blocks to host as whole layers, one stream, thinking on" \
             $RUNNER "$TAG" > $LOG 2>&1 ;;
    ik)  env M="$M" CTX=$CTX EXTRA_FLAGS="-np $SLOTS $XTRA ${IK_EXTRA:-}" SESSIONS=1 NPRED=$NPRED FOR=$FOR \
             PROMPT_FILES="$PROMPT_DIR/hl1.txt" \
             NOTE="offload cost, experts of first $L of $NBLOCKS blocks to host, one stream, thinking on" \
             $RUNNER "$TAG" > $LOG 2>&1 ;;
  esac
  kill $SAMP 2>/dev/null; wait $SAMP 2>/dev/null
  PEAK=$(sort -n $VR | tail -1)
  if grep -q "${SENT}_DONE" $LOG; then
    say "$TAG ok: peak VRAM ${PEAK:-?} MiB, $(grep -oE "[0-9.]+ tok/s aggregate" $LOG | head -1)"
    grep -oE "Tape +~?[^ ]*\.tape" $LOG | head -1 | sed 's/^/           /'
  else
    say "$TAG FAILED (peak VRAM ${PEAK:-?} MiB) — this row does not go in the table. Last lines:"
    tail -12 $LOG | sed 's/^/           /'
  fi
  IFS=','
done
IFS=$OIFS
say "offload sweep done for $ENGINE ($LEVELS); tapes are in /home/user/toktape-runs"
echo OFFLOAD_SWEEP_DONE
