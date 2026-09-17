#!/bin/bash
# stream-sweep.sh — one take per stream count per engine, serially, one lease at a time.
#
# WKS-32 left the four-stream gap unexplained: mistral.rs 0.9.3 goes 105 → 283 tok/s from one stream
# to four on Qwen3.6-35B-A3B Q6_K, and ik_llama.cpp goes 130 → 149 on the same card, model and
# prompts. Two things measured on 2026-09-17 narrow it before this sweep runs:
#
#   * The model is a hybrid. mistral.rs's loader prints "Qwen3Next: 10 full attention layers,
#     30 linear attention (GDN) layers", so three quarters of the stack is a recurrent state update
#     rather than a KV read, and both engines have their own linear-attention path (ik:
#     src/llama-delta-net.h, ggml/src/ggml-cuda/delta-net.cu).
#   * It is not CUDA graphs on the mistral.rs side. Its own counter says every decode step is
#     `mistralrs_cuda_graph_dispatch_total{mode="skipped",reason="model_unsupported"}` — 199 of 200
#     steps at one stream and 201 at four — with a zero-byte graph pool. Whatever the gain is, it is
#     not a captured graph being replayed.
#
# So the sweep measures the shape: if the per-stream rate holds and the aggregate climbs on one
# engine while the other flattens, the cost that concurrency amortises is per-step, and the sweep
# says how much of it there is. Eight distinct prompts, because a repeated prompt changes the
# prefix-cache row and buys a hit neither engine would get in a real four-user minute.
#
# Two choices in here are about not measuring the wrong thing:
#
#   * **Thinking stays on, with `-n 512`.** The aggregate rate is TotalPredictedN over
#     (last token − first content), so a take whose streams stop at EOS at different lengths spends
#     the tail of its window with a shrinking population and reports a lower aggregate for a reason
#     that has nothing to do with the engine — measured 2026-09-17, the same four-stream mistral.rs
#     config read 283 tok/s with thinking on and 237 with it off, EOS between 234 and 345 tokens.
#     With thinking on every stream runs to the 512 cap, so every row's window is full.
#   * **The server is built for eight slots in every row.** Only the client's stream count moves.
#     Otherwise a one-stream row runs against a one-slot server and an eight-stream row against an
#     eight-slot one, which is two variables per row; mistral.rs's scheduler also derives
#     `max_num_seqs` from `--max-batch-size` non-linearly (measured: 4 → 4, but 8 → 32).
#
# Each row is one take by the existing runners, so the lease, the quiet-machine witness, the tape and
# the no-think gate are the ones already in use — this file only orders them and waits for the lease
# to come back between takes.
#
#   stream-sweep.sh mrs 1,2,4,8        # mistral.rs arm
#   stream-sweep.sh ik  1,2,4,8        # ik_llama.cpp arm
#   PREFIX=sweep2 stream-sweep.sh ik 4 # one row again under a different tag
set -u
ENGINE=${1:?engine required: mrs | ik}
COUNTS=${2:-1,2,4,8}
PREFIX=${PREFIX:-sweep}
M=${M:-/models/Qwen3.6-35B-A3B/Qwen3.6-35B-A3B-UD-Q6_K.gguf}
CTX=${CTX:-32768}; NPRED=${NPRED:-512}; FOR=${FOR:-180s}; SLOTS=${SLOTS:-8}
OUT=${OUT:-/home/user/sweep}; mkdir -p $OUT
PROMPT_DIR=${PROMPT_DIR:-/home/user/hero5}
LEASE=/home/user/gpu-lease
say(){ echo "$(date +%H:%M:%S) sweep: $*"; }

case $ENGINE in
  mrs) RUNNER=/home/user/mrs-take.sh;      SENT=MRS_TAKE ;;
  ik)  RUNNER=/home/user/ik-vram-take.sh;  SENT=IK_VRAM ;;
  *)   say "refused: engine must be mrs or ik"; exit 1 ;;
esac
[ -x "$RUNNER" ] || { say "refused: no runner at $RUNNER"; exit 1; }

# wait_lease — the previous take releases the lease in its own finish(); until it does, the next
# runner would refuse. Waits on the lease file, never on a pid pattern (a pgrep for the runner's
# own name matches this shell's command line — that loop is a known way to hang forever).
wait_lease(){
  local i
  for i in $(seq 180); do [ -f $LEASE ] || return 0; sleep 5; done
  say "lease still held after 15 min: $(cat $LEASE 2>/dev/null)"; return 1
}

OIFS=$IFS; IFS=','
for n in $COUNTS; do
  IFS=$OIFS
  wait_lease || exit 1
  PF=""
  for i in $(seq $n); do PF="${PF:+$PF,}$PROMPT_DIR/hl$i.txt"; done
  [ $n -le 8 ] || { say "refused: only eight prompts exist, asked for $n streams"; exit 1; }
  TAG="$PREFIX-$ENGINE-${n}s"; LOG=$OUT/$TAG.log
  say "--- $TAG: $n stream(s) against a $SLOTS-slot server, $n distinct prompts, ctx $CTX, n $NPRED"
  # the whole runner output goes to a file, never through a pipe: a pipeline's exit status is the
  # pager's, and a failed take that reads green is a row in the table that should not be there
  case $ENGINE in
    mrs) env M="$M" CTX=$CTX MAXSEQS=$SLOTS SESSIONS=$n NPRED=$NPRED FOR=$FOR \
             PROMPT_FILES="$PF" \
             NOTE="stream sweep, $n streams, $SLOTS slots, distinct prompts, thinking on" \
             $RUNNER "$TAG" > $LOG 2>&1 ;;
    ik)  env M="$M" CTX=$CTX EXTRA_FLAGS="-np $SLOTS ${IK_EXTRA:-}" SESSIONS=$n NPRED=$NPRED FOR=$FOR \
             PROMPT_FILES="$PF" \
             NOTE="stream sweep, $n streams, $SLOTS slots, distinct prompts, thinking on" \
             $RUNNER "$TAG" > $LOG 2>&1 ;;
  esac
  if grep -q "${SENT}_DONE" $LOG; then
    say "$TAG ok: $(grep -oE "[0-9.]+ tok/s aggregate" $LOG | head -1) — $LOG"
    grep -oE "Tape +~?[^ ]*\.tape" $LOG | head -1 | sed 's/^/           /'
  else
    say "$TAG FAILED — this row does not go in the table. Last lines:"
    tail -12 $LOG | sed 's/^/           /'
  fi
  IFS=','
done
IFS=$OIFS
say "sweep done for $ENGINE ($COUNTS); tapes are in /home/user/toktape-runs"
echo SWEEP_DONE
