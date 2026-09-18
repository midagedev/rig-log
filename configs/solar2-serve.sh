#!/bin/bash
# Solar Open 2 250B-A15B IQ4_XS, the placement this box actually runs it at.
#
# One copy of the serving line, the way configs/v41-serve.sh is one copy: a placement pasted
# into two files drifts, and this repo's claims are about the placement rather than about
# whichever copy happened to run. tools/translate-round.sh's `solar2)` branch and
# tools/repo-batch.sh both reach this file.
#
# The model is 127 GiB in four shards and needs a patch that is not in upstream llama.cpp
# (ggml-org/llama.cpp#26115 is open with no PR; the patch is prometheusAIR's, sha256
# d2906be2c009…afa538, applied to 6ea215d17 and built at sm_86 by /home/user/build-solar2.sh).
# That is the standing risk of serving this model and it is written here so nobody has to
# rediscover it: a llama.cpp upgrade that does not re-apply the patch takes this config down.
#
# Every number below was measured on 2026-09-18 and the entry is
# log/2026-09-18-c-a-local-model-translates-the-log.md.
#
#   placement  -ot, 16 expert layers to CUDA0 from the front and 8 to CUDA1 from the back.
#              Read out of the GGUF headers: every layer carries 2.490 GiB of experts (layer 0
#              has 3.223) and the non-expert weights are 6.61 GiB in all. An expert layer goes
#              on the card `-ts` gave the rest of that layer, so the hidden state does not
#              cross the bus twice inside one block. Raised from what each load reported, not
#              from arithmetic: 3090 23 654 MiB and A6000 47 640 MiB, 922 and 1 500 free.
#              -cmoe (everything on the host) is 21.3 tok/s; this is 30.9.
#   --no-mmap  the loader asks for it on every load when there are CPU overrides. Measured at
#              this placement, one variable: prefill 154.5 -> 177.3 tok/s, decode unchanged
#              inside the run-to-run spread, load 7 s -> 43 s. Worth it for a batch.
#   -t 16      on a 32-core part, and not a typo. Swept: 8 -> 24.4, 12 -> 29.6, 16 -> 30.7 and
#              30.9, 20 -> 30.0, 24 -> 30.2, 32 -> 29.7 tok/s, with prefill flat at ~176
#              throughout. The host threads decode experts, that work is bound by memory
#              bandwidth rather than cores, and past sixteen they contend for the same bus.
#   --jinja    llama-server ignores chat_template_kwargs without it, and this template gates
#              its reasoning channel on one. Without `reasoning_effort: minimal` the whole
#              generation goes to that channel and the answer is empty -- 13 450 tokens for a
#              1-byte file, twice, on 2026-09-18. The client sends the kwarg; this makes the
#              server read it.
set -eu
B=${B:-/home/user/llama.cpp-solar2/build/bin/llama-server}
M=${M:-/models/Solar-Open2-250B-IQ4_XS/Solar-Open2-250B-IQ4_XS-00001-of-00004.gguf}
C=${C:-16384}
PORT=${PORT:-8011}
G0=${G0:-16}
G1=${G1:-8}
EXTRA=${EXTRA:-}

n0=; for l in $(seq 0 $((G0-1))); do n0="${n0:+$n0|}$l"; done
n1=; for l in $(seq $((48-G1)) 47); do n1="${n1:+$n1|}$l"; done

exec "$B" -m "$M" --alias Solar-Open2-250B \
  -c "$C" -ngl 99 -ts ${TS:-2,1} -fa on -t ${THREADS:-16} -b 2048 -ub 512 --no-mmap \
  -ot "blk\.($n0)\.ffn_.*_exps=CUDA0,blk\.($n1)\.ffn_.*_exps=CUDA1,exps=CPU" \
  --jinja $EXTRA \
  --host 127.0.0.1 --port "$PORT"
