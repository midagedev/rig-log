#!/bin/bash
# Stand one model up once, walk every markdown file in the repo past it, hand the cards back.
# The lease, the witness and the teardown are translate-round.sh's; this only replaces the
# single-file client with the batch one.
#
#   MODEL=solar2 repo-batch.sh          # the default, chosen 2026-09-18
#   MODEL=v41    repo-batch.sh
#
# Which model this repo is translated by is a decision, not a default, and the reasoning is in
# log/2026-09-18.md#c-a-local-model-translates-the-log. The short version: read in one sitting
# over all 33 blocks with the labels shuffled, Solar Open 2, V4.1 and Gemma 4 all scored one
# meaning change, so meaning does not separate them; Solar Open 2 is the fastest of the three
# at 2.0 h against V4.1's 3.9 h and holds glossary at 100 %. What it costs is a dependency on a
# patch that is not in upstream llama.cpp, which is the standing risk and is WKS-34's subject.
set -u
LEASE=/home/user/gpu-lease
# The output directory carries the model, so two models can never share a resume ledger. They
# did on 2026-09-18: a V4.1 batch was interrupted, left fifty rows that all said `ok: false`,
# and the first Solar Open 2 run resumed on top of them, skipped every file and reported
# success over an empty directory. The ledger bug is fixed in translate-batch.py; this makes
# the collision impossible rather than survivable.
OUT=${OUT:-/home/user/translate/repo-${MODEL:-solar2}}
PORT=8011
say(){ echo "$(date +%H:%M:%S) $*"; }
mkdir -p "$OUT"

if [ -f "$LEASE" ]; then
  held=$(awk '{print $2}' "$LEASE")
  if [ -n "${held:-}" ] && kill -0 "$held" 2>/dev/null; then say "ABORT: lease held: $(cat $LEASE)"; exit 1; fi
  say "clearing an abandoned lease: $(cat $LEASE)"; rm -f "$LEASE"
fi
echo "translate-repo $$ $(date -Is)" > "$LEASE"
say "lease taken; io $(awk '/^some/{print $2}' /proc/pressure/io)"

# Measured 2026-09-18, and it is the inversion of the incident docs/quiet-machine.md is about:
# this trap sent one SIGTERM, waited, printed `gpus after: 20112 45892` and released the lease
# over 66 GB the server was still holding. A lease released while the cards are occupied is
# worse than a lease left behind -- the next round reads it as free, loads onto what is left,
# and fails in a way that looks like a model problem. So: escalate once, then let the memory
# decide. If the cards do not come back the lease stays and the run reports failure.
cleanup(){
  rc=$?
  if [ -n "${SPID:-}" ] && kill -0 "$SPID" 2>/dev/null; then
    say "stopping the server ($SPID)"; kill -TERM "$SPID" 2>/dev/null || true
    for i in $(seq 120); do kill -0 "$SPID" 2>/dev/null || break; sleep 1; done
    if kill -0 "$SPID" 2>/dev/null; then
      say "still alive ${i}s after SIGTERM; SIGKILL"
      kill -KILL "$SPID" 2>/dev/null || true
      for i in $(seq 30); do kill -0 "$SPID" 2>/dev/null || break; sleep 1; done
    else
      say "server exited ${i}s after SIGTERM"
    fi
  fi
  V=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr '\n' ' ')
  say "gpus after: $V"
  if [ "$(echo $V | tr ' ' '+' | sed 's/+$//' | bc)" -gt 2000 ]; then
    say "HELD: $V MiB still on the cards -- the lease stays, it is not free"
    say "=== repo batch done, rc=1 (cards not returned) ==="; exit 1
  fi
  [ "$(awk '{print $2}' "$LEASE" 2>/dev/null)" = "$$" ] && rm -f "$LEASE" && say "lease released"
  say "=== repo batch done, rc=$rc ==="
}
trap cleanup EXIT

. /home/user/gpu-order.env
export CUDA_VISIBLE_DEVICES=$A6000_UUID,$GF3090_UUID
# The serving line lives in one place per model -- configs/{v41,solar2}-serve.sh, copied to the
# box beside this script. They used to be pasted here as well; two copies of a placement drift,
# and the log's claims are about the placement, not about whichever copy happened to run.
#
# EXTRA_JSON is the other half of the same rule. V4.1 takes `--reasoning off` on the server,
# Solar Open 2 has no such flag and gates its reasoning channel on a template kwarg instead --
# and without it the whole generation goes to that channel and every file comes back empty.
# Measured twice on 2026-09-18. The batch client refuses an empty part now, so the failure is
# loud either way, but the point is not to have it.
#
# Both halves are arrays so that nothing here is re-split by the shell after expansion.
case "${MODEL:-solar2}" in
  v41)
    SERVE=/home/user/v41-serve.sh; SERVE_ENV=(EXTRA="--reasoning off"); CLIENT=() ;;
  solar2)
    SERVE=/home/user/solar2-serve.sh; SERVE_ENV=()
    # An array, not `${VAR:+--flag "$VAR"}`: that form expands and *then* word-splits, so the
    # JSON would arrive as five arguments and the quotes inside would be literal characters.
    CLIENT=(--extra-json '{"chat_template_kwargs": {"reasoning_effort": "minimal"}}') ;;
  *) say "ABORT: MODEL=${MODEL:-} is not one this script serves"; exit 1 ;;
esac
say "model ${MODEL:-solar2} via $SERVE"
env C=${C:-16384} NP=${NP:-} PORT=$PORT "${SERVE_ENV[@]}" \
  bash "$SERVE" > "$OUT/server.log" 2>&1 &
SPID=$!
for _ in 1 2 3 4 5; do comm=$(cat /proc/$SPID/comm 2>/dev/null || echo gone); [ "$comm" = llama-server ] && break; sleep 0.4; done
[ "$comm" = llama-server ] || { say "ABORT: \$! is $SPID comm=$comm"; exit 1; }
say "server $SPID loading"
for i in $(seq 900); do
  curl -sf http://127.0.0.1:$PORT/health >/dev/null 2>&1 && break
  kill -0 $SPID 2>/dev/null || { say "ABORT: server died loading"; exit 1; }
  sleep 1
done
curl -sf http://127.0.0.1:$PORT/health >/dev/null || { say "ABORT: never healthy"; exit 1; }
say "healthy after ${i}s"

cd /home/user/translate/rig-log
# FILES names the subset to translate. Unset it and the batch walks the whole tree, which is
# what the first pass wants; set it and the same runner does a follow-up round without a second
# copy of the serving line. Added 2026-09-18, when five documents were left in English after the
# rest of the tree had already moved -- re-running the whole tree to reach five files would have
# re-translated forty-six that were already done, and --resume only protects against that while
# the ledger and the output directory agree.
if [ -n "${FILES:-}" ]; then
  # shellcheck disable=SC2206
  TARGETS=($FILES)
  for f in "${TARGETS[@]}"; do
    [ -f "$f" ] || { say "ABORT: FILES names $f, which is not in the tree"; exit 1; }
  done
else
  TARGETS=(README.md $(ls docs/*.md) $(ls log/*.md))
fi
say "translating ${#TARGETS[@]} file(s)"
python3 /home/user/translate/translate-batch.py \
  --url http://127.0.0.1:$PORT/v1/chat/completions --model "${MODEL:-solar2}" \
  "${CLIENT[@]}" \
  --out "$OUT" --root . --resume \
  --files "${TARGETS[@]}"
rc=$?

# The gates run here rather than in a separate pass, because a batch that finishes and is never
# checked is a batch whose defects arrive weeks later in a file someone is editing. The
# untranslated-English check is the newest of the three and exists because of this model: it
# wrote `costing했다` on 2026-09-18, and neither the structure gate nor the glossary gate can
# see a shape like that (tools/check-untranslated.py).
say "=== gates ==="
find "$OUT" -name '*.md' -print0 \
  | xargs -0 -r python3 /home/user/translate/check-untranslated.py | tail -40
exit $rc
