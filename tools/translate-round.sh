#!/bin/bash
# translate-round.sh — one document, one model, one measured row.
#
#   translate-round.sh <model-tag> <source.md> <who>
#   MASK=1 OUT=<dir> translate-round.sh …
#
# Takes the lease, stands a server up on a port nothing else uses, translates the file
# whole in one request, tears the server down and hands the cards back. The witness --
# io pressure and the live llama processes -- is recorded at the start and at the end of
# the run, because a rate taken on a busy box is not a rate (docs/quiet-machine.md).
#
# Every model is a case below rather than a call into configs/: those scripts hardcode
# port 8001 and `exec`, and the point here is that a ladder of models answers the same
# request under the same conditions. The flags in each branch are copied from the config
# that measured that model, and the branch says which.
#
# The server is backgrounded as a *simple command* with the environment exported on its
# own line beforehand. An env-var prefix, a `cd &&`, or a `setsid` in front of it makes
# bash fork a subshell and `$!` then names the wrapper, which has cost this machine four
# separate incidents. The assertion straight after the launch is what proves it did not
# happen this time.
set -eu

# Run from a private copy of this file, always. bash reads a script incrementally, so a
# deploy over it kills the run at the next line it had not reached yet -- which is exactly
# what happened at 10:08 on 2026-09-18: the V4.1 round had loaded in 3 m 28 s and was
# listening when a new copy of this script landed on top of it and bash died with
# "unexpected EOF while looking for matching quote". docs/quiet-machine.md documents that
# incident, and this round was translating docs/quiet-machine.md at the time. The cure is
# the one that entry names, and it belongs in the runner rather than in a habit.
if [ -z "${TR_PRIVATE:-}" ]; then
  TR_PRIVATE=$(mktemp "${TMPDIR:-/tmp}/translate-round.XXXXXX.sh")
  cat "$0" > "$TR_PRIVATE"
  export TR_PRIVATE
  exec bash "$TR_PRIVATE" "$@"
fi

TAG=${1:?model tag}
SRC=${2:?source markdown}
WHO=${3:?who approved this}
PORT=${PORT:-8011}
LEASE=/home/user/gpu-lease
OUT=${OUT:-/home/user/translate/$TAG-$(basename "$SRC" .md)}
MASK=${MASK:-}          # MASK=1 holds the fenced blocks back instead of asking for them
RAW=${RAW:-}            # RAW=1 posts a ChatML prompt to /completions, past the server's parser
IO_MAX=${IO_MAX:-5}
# MTP is on by default and MTP=0 takes it off. It is a knob rather than a constant because of
# what the saved stream showed on 2026-09-18: GLM's Korean came back with 18 U+FFFD in 6429
# characters, each one a whole syllable inside a *single* delta (` \ufffd\ufffd\uc790` for ` \uc22b\uc790`), and the
# server sent those escapes itself. A delta carrying several tokens is what MTP produces, so
# the suspect is a multi-token step detokenized one token at a time, which breaks a byte-fallback
# sequence. Turning it off is the A/B that says whether that is the cause or a coincidence.
MTP=${MTP-1}
STREAM=${STREAM-1}
# `${VAR:+flag}` asks whether VAR is non-empty, and "0" is non-empty, so MTP=0 and STREAM=0 both
# left their flag in place. Measured 2026-09-18: a whole A/B round ran with MTP still on and its
# 15-versus-18 difference was read as evidence. A switch that silently means its opposite is
# worse than no switch, so the values are normalised here, once, and the branches below only
# ever see empty or set.
case "${MTP,,}" in 0|no|off|false|"") MTP= ;; *) MTP=1 ;; esac
case "${STREAM,,}" in 0|no|off|false|"") STREAM= ;; *) STREAM=1 ;; esac

BIN=/home/user/llama.cpp-v41-merged/build/bin/llama-server
. /home/user/gpu-order.env
KIND=llama          # llama | tabby
CLIENT=()           # extra flags for translate-md.py
ARGS=()
case "$TAG" in
  # Qwen3.6-35B-A3B, both quants. Flags from configs/qwen36-3090-serve.sh; the Q6_K file
  # is 29.3 GB and wants the 48 GB card, the Q4_K_XL is 20.8 GB and fits the 24 GB one.
  qwen36-q6)
    DEV=$A6000_UUID
    ARGS=(-m /models/Qwen3.6-35B-A3B/Qwen3.6-35B-A3B-UD-Q6_K.gguf
          -c 32768 -ngl 99 -fa on -t 16 -b 2048 -ub 512 -ctk q8_0 -ctv q8_0
          --jinja --chat-template-kwargs '{"enable_thinking": false}') ;;
  qwen36-q4)
    DEV=$GF3090_UUID
    ARGS=(-m /models/Qwen3.6-35B-A3B/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf
          -c 32768 -ngl 99 -fa on -t 16 -b 2048 -ub 512 -ctk q8_0 -ctv q8_0
          --jinja --chat-template-kwargs '{"enable_thinking": false}') ;;
  # Qwen3-Coder-Next IQ4_XS, one 42.7 GB file. Both cards visible rather than the A6000
  # alone: 42.7 GB of weights plus a KV cache plus compute buffers on a 48 GB card is one
  # OOM away, and llama.cpp splits across the two by free VRAM on its own.
  coder-next)
    DEV=$A6000_UUID,$GF3090_UUID
    # --reasoning-format none because with the parser in the path this server answered
    # HTTP 500, "the model produced output that does not match the expected peg-native
    # format" (measured 2026-09-18): the answer existed, and llama-server threw it away
    # parsing it against this model's tool-call grammar.
    ARGS=(-m /models/Qwen3-Coder-Next/Qwen3-Coder-Next-IQ4_XS.gguf
          -c 16384 -ngl 99 -fa on -t 16 -b 2048 -ub 512 -ctk q8_0 -ctv q8_0
          --jinja --reasoning-format none --reasoning off) ;;
  # The same file with llama.cpp's plain ChatML template instead of the one in the GGUF.
  # The model's own template makes the server parse every answer against this model's
  # tool-call grammar, and prose does not match it.
  coder-next-chatml)
    DEV=$A6000_UUID,$GF3090_UUID
    ARGS=(-m /models/Qwen3-Coder-Next/Qwen3-Coder-Next-IQ4_XS.gguf
          -c 16384 -ngl 99 -fa on -t 16 -b 2048 -ub 512 -ctk q8_0 -ctv q8_0
          --chat-template chatml --reasoning-format none) ;;
  # DeepSeek-V4.1-Flash, the model this machine actually serves. Placement, draft and
  # --lazy-mode copied verbatim from configs/v41-serve.sh; see that file for why each
  # number is what it is. No thinking kwarg here -- this template is not Qwen's, so the
  # reply is checked rather than the request (tools/translate-md.py refuses a <think>).
  v41)
    DEV=$A6000_UUID,$GF3090_UUID
    ARGS=(-m /models/DeepSeek-V4.1-Flash-Q3_K_M-engramQ8-tokembdBF16-attnQ8/DeepSeek-V4.1-Flash-Q3_K_M-00001-of-00009.gguf
          -c 16384 -ngl 99 -t 32 -b 2048 -ub 512 --lazy-mode auto
          -ot 'blk\.[0-3]\.ffn_.*_exps=CUDA0,blk\.6\.ffn_down_exps=CUDA0,blk\.[4-5]\.ffn_.*_exps=CUDA1,blk\.6\.ffn_(gate|up)_exps=CUDA1,exps=CPU'
          -md /models/DeepSeek-V4.1-Flash-DSpark/DeepSeek-V4.1-Flash-Fp8-128x742M-MXFP4_MOE.tl37.gguf
          --spec-type draft-dspark --spec-draft-n-max 3 -otd 'output_norm=CUDA0'
          --jinja --reasoning off) ;;
  # Gemma 4 31B-it at UD-Q6_K_XL, 27.5 GB, whole on the 48 GB card, with the MTP head as a
  # draft. Built 2026-04 and fetched 2026-09-18; served by the mainline tree (b10989) rather
  # than the V4.1 merge, because that is where the newer architectures are.
  gemma4-q6)
    BIN=/home/user/llama.cpp/build/bin/llama-server
    DEV=$A6000_UUID
    ARGS=(-m /models/gemma-4-31B-it/gemma-4-31B-it-UD-Q6_K_XL.gguf
          -c 32768 -ngl 99 -fa on -t 16 -b 2048 -ub 512 -ctk q8_0 -ctv q8_0
          -md /models/gemma-4-31B-it/mtp-gemma-4-31B-it.gguf --spec-type draft-mtp --spec-draft-n-max 3
          --jinja --reasoning off) ;;
  # Solar Open 100B IQ4_XS, 55.5 GB: Upstage's open-weight model, 102.6B total and 12B active
  # across 129 experts (top 8 of 128 routed, plus one shared). It is in the ladder because it is
  # the second Korean-first model here after K-EXAONE, and because the Korean-first hypothesis
  # has not yet been confirmed by anything measured on this box -- K-EXAONE came ninth.
  #
  # It needs no patch. The GGUF declares `general.architecture = glm4moe`, read from the first
  # 2 MB of the file with a range request before any of it was downloaded, and this build's
  # src/models/glm4-moe.cpp carries `case 48: LLM_TYPE_102B_A12B; // Solar Open`. This is the
  # same binary the other llama.cpp rows used, so the comparison is between models and not
  # between builds. The 250B **Solar Open 2** is the newer and much stronger model -- Upstage
  # publishes Korean average 66.95 against 85.43 -- and is the one that cannot run here:
  # `solar_open2` is not in upstream llama.cpp (ggml-org/llama.cpp#26115, open, no PR).
  #
  # 55.5 GB against 72 GB of VRAM leaves room for the cache and the compute buffers, so this is
  # the first large row in the ladder with no expert layer on the host. -c is 16384 rather than
  # the 32768 the other cards use: the document is about 3 100 tokens in and 3 600 out, and the
  # context is where the VRAM headroom would go first. No draft model exists for it.
  #
  # `reasoning_effort: minimal` is not decoration. Measured 2026-09-18, the first take: Solar
  # deliberated in English -- "We need to translate the markdown document into Korean... Let's
  # go through the document" -- never started translating, and degenerated into `The verb "있다"
  # ends with "다"?` repeated to the 16 384-token cap. 13 396 tokens, out-in ratio 4.48,
  # `finish_reason: length`, no Korean document at all. The model's own chat template explains
  # it: `reasoning_effort` defaults to **"high"**, and the only thing that switches thinking off
  # is
  #     {%- if reasoning_effort in ["low", "minimal"] -%}
  #         {{- "<|begin|>assistant<|think|><|end|>" }}
  #     {%- endif -%}
  # -- an empty think block, pre-filled, so there is nothing for the model to open. That arrives
  # as `chat_template_kwargs`, which **llama-server silently ignores unless it was started with
  # `--jinja`** (measured 2026-09-17, two hero takes published as "thinking off" with all four
  # streams opening `<think>`). `--jinja` is on the line above for that reason. A request
  # parameter is not an answer: read the reply before believing it.
  solar100)
    BIN=/home/user/llama.cpp/build/bin/llama-server
    DEV=$A6000_UUID,$GF3090_UUID
    CLIENT=(--extra-json '{"chat_template_kwargs": {"reasoning_effort": "minimal"}}')
    ARGS=(-m /models/Solar-Open-100B/Solar-Open-100B.IQ4_XS.gguf
          -c 16384 -ngl 99 -fa on -t 32 -b 2048 -ub 512
          --jinja) ;;
  # Solar Open 2 250B-A15B IQ4_XS, 127 GiB in four shards, through **a community patch**, which
  # is the only reason this row exists at all: `solar_open2` is not in upstream llama.cpp
  # (ggml-org/llama.cpp#26115, open, no PR). The patch is prometheusAIR's, published beside the
  # GGUF it converts, fetched by URL and checked against the sha256 that
  # WHYKEYSAY/serve-solar-open2-250b records -- that second repo wraps the patch in serving
  # scripts and is not its author. 46.5 KB, 11 files, 801 added lines; the model itself is 387
  # of them, and its first line says where they came from:
  #     // Derived from src/models/kimi-linear.cpp: the linear-attention block is KDA
  # It inherits `llm_build_delta_net_base` and calls the existing `build_delta_net`, so almost
  # none of this is new arithmetic -- which is why 387 lines is enough for a 250B model.
  # Built from upstream 6ea215d17 at sm_86 (the patch author's script says 120a, for a 5090).
  #
  # Placement is by explicit `-ot`, and the reason is *not* that `-ncmoe` is broken -- an
  # earlier version of this comment said it was, and of the report built on it, and both were
  # wrong. ~~`-ncmoe` does not take effect for this architecture~~ (struck 2026-09-18). The
  # layer sizes say plainly what happened: read out of the GGUF headers, every layer carries
  # 2.490 GiB of experts (layer 0 has 3.223) and the non-expert weights are 6.61 GiB in total.
  # `-ncmoe N` keeps the *first* N expert layers on the host, so it leaves the *last* ones on
  # the cards, and `-ts 2,1` puts the last layers on the 24 GB card:
  #
  #     -ncmoe 32  ->  layers 32-47 on CUDA1:  16 x 2.490 GiB = 40 796 MiB   (died at 40 617)
  #     -ncmoe 36  ->  layers 36-47 on CUDA1:  12 x 2.490 + 3.3 = 33 900 MiB (died at 32 967)
  #
  # Both failures are the flag doing exactly what it documents. What `-ncmoe` cannot express is
  # the thing this model needs: *which* card each expert layer goes to. `-ot` can, and the rule
  # it follows here is that an expert layer is placed on the same card `-ts` gave the rest of
  # that layer -- CUDA0 takes them from the front, CUDA1 from the back -- so the hidden state
  # does not cross the bus twice inside one block.
  #
  # G0 and G1 are layer *counts*, not indices, and the regex below is generated from them so a
  # placement is changed by editing two numbers rather than an alternation. The first load is
  # deliberately low: 127 GiB does not fit in 72 GB of card, the run reports what VRAM was
  # actually left, and the number is raised from that rather than from arithmetic.
  #
  # `-ts 2,1` is the capacity split: the cards are 48 GB and 24 GB, and the default put 40 GiB
  # on the smaller one. 48 layers, of which only 12 are GQA; the other 36 are KDA and carry a
  # recurrent state rather than a KV cache, so what -c costs here is not what it costs on the
  # other rows.
  solar2)
    # CMOE=1 sends every expert to the host, which is the placement that cannot fail to fit and
    # so is the one that says whether anything else is wrong -- it is the baseline row, 21.3
    # tok/s. Otherwise G0 expert layers go to CUDA0 counting up from 0 and G1 go to CUDA1
    # counting down from 47, and everything between them stays on the host.
    case "${CMOE:-}" in
      1|yes|true) MOE_PLACE=(-cmoe) ;;
      *) G0=${G0:-16}; G1=${G1:-8}
         # Built by listing the layer numbers rather than writing an alternation by hand: a
         # range typo in `1[0-2]` is silent, and its cost is a 25-second load and a wrong row.
         n0=; for l in $(seq 0 $((G0-1))); do n0="${n0:+$n0|}$l"; done
         n1=; for l in $(seq $((48-G1)) 47); do n1="${n1:+$n1|}$l"; done
         MOE_PLACE=(-ot "blk\\.($n0)\\.ffn_.*_exps=CUDA0,blk\\.($n1)\\.ffn_.*_exps=CUDA1,exps=CPU") ;;
    esac
    # Same switch as solar100, different token names. Measured 2026-09-18, the first take:
    # 13 450 tokens, out-in 4.58, `finish_reason: length`, and a **1-byte** translation -- the
    # whole generation went to the reasoning channel and the answer was empty. The template
    # defaults `reasoning_effort` to "high" and closes the think block immediately for anything
    # outside ["medium","high","xhigh"]:
    #     {%- else -%} "<|im:start|>assistant<|im:content|><|think:start|><|think:end|>"
    # The empty-answer check below this file's client call is what caught it; the row would
    # otherwise have reported 21.1 tok/s over 671 s and written nothing.
    CLIENT=(--extra-json '{"chat_template_kwargs": {"reasoning_effort": "minimal"}}')
    # The loader asks for this one itself, every load, in its own words: "tensor overrides to
    # CPU are used with mmap enabled - consider using --no-mmap for better performance". It is
    # a switch here rather than a constant because the advice is not obviously right on this
    # box -- 251 GB of RAM holds the whole 127 GiB file in page cache, so mmap is already
    # reading out of memory, and --no-mmap buys a second copy of ~60 GiB and a much longer
    # load. Measured 2026-09-18 at the placement below, one variable: prefill 154.5 -> 177.3
    # tok/s (+15 %), decode 29.4 -> 29.7 (inside the run-to-run spread, so: no decode claim),
    # load 7 s -> 43 s. It is on by default because a translation round pays the load once and
    # the prefill on every document; NOMMAP=0 takes it off for an interactive server.
    case "${NOMMAP-1}" in 0|no|off|false|"") MMAP=() ;; *) MMAP=(--no-mmap) ;; esac
    # `-t 16` on a 32-core part, and it is not a typo. Swept 2026-09-18 at the placement below
    # with everything else held: 8 -> 24.4, 12 -> 29.6, 16 -> 30.7 and 30.9, 20 -> 30.0,
    # 24 -> 30.2, 32 -> 29.7 tok/s. The repeat at 16 is what makes the rest readable -- 0.2
    # tok/s apart, so a 0.5 difference is a difference. Prefill does not move at all across the
    # sweep (175.9 to 177.3), which says the same thing from the other side: the host threads
    # are decoding experts, that work is bound by memory bandwidth rather than by cores, and
    # past sixteen of them the extra threads are contending for the same bus. Every other row
    # in this file says `-t 32` because that is right for a model whose experts are on the
    # cards; it is wrong here, and it was wrong by 4 %.
    BIN=/home/user/llama.cpp-solar2/build/bin/llama-server
    DEV=$A6000_UUID,$GF3090_UUID
    ARGS=(-m /models/Solar-Open2-250B-IQ4_XS/Solar-Open2-250B-IQ4_XS-00001-of-00004.gguf
          -c 16384 -ngl 99 "${MOE_PLACE[@]}" "${MMAP[@]}" -ts ${TS:-2,1} -fa on
          -t ${THREADS:-16} -b 2048 -ub 512
          --jinja) ;;
  # K-EXAONE-236B-A23B IQ4_XS, 128 GB, LG's Korean-first MoE: 128 experts with 8 routed, 48
  # layers plus an MTP layer. Placement is deliberately low for a first load -- twelve expert
  # layers on the 48 GB card and six on the 24 GB -- and the run reports what was actually
  # left, which is how every large placement in this repo was arrived at.
  kexaone)
    BIN=/home/user/llama.cpp/build/bin/llama-server
    DEV=$A6000_UUID,$GF3090_UUID
    ARGS=(-m /models/K-EXAONE-236B-A23B/K-EXAONE-236B-A23B-IQ4_XS.gguf
          -c 16384 -ngl 99 -fa on -t 32 -b 2048 -ub 512 -ctk q8_0 -ctv q8_0
          -ot 'blk\.([0-9]|1[01])\.ffn_.*_exps=CUDA0,blk\.1[2-7]\.ffn_.*_exps=CUDA1,exps=CPU'
          --jinja --reasoning off) ;;
  # The same model and placement, with the instruction moved into the user turn. Measured
  # 2026-09-18: given the instruction as a system message, K-EXAONE did not translate the
  # document at all -- it answered "let me distill, clarify, and extend your method" and
  # rewrote it with its own headings. Five other models took the identical prompt and did
  # as they were told, so this asks whether the turn it arrives in is what makes the
  # difference, before the row is reported as the model refusing the task.
  kexaone-user)
    BIN=/home/user/llama.cpp/build/bin/llama-server
    DEV=$A6000_UUID,$GF3090_UUID
    CLIENT=(--prompt-in-user)
    ARGS=(-m /models/K-EXAONE-236B-A23B/K-EXAONE-236B-A23B-IQ4_XS.gguf
          -c 16384 -ngl 99 -fa on -t 32 -b 2048 -ub 512 -ctk q8_0 -ctv q8_0
          -ot 'blk\.([0-9]|1[01])\.ffn_.*_exps=CUDA0,blk\.1[2-7]\.ffn_.*_exps=CUDA1,exps=CPU'
          --jinja --reasoning off) ;;
  # gpt-oss, OpenAI's open weights, in the native MXFP4 the release ships -- no requantization,
  # so this is the model as published. 120b is 63.4 GB and does not fit the 48 GB card alone;
  # 20b is 12.1 GB and fits the 24 GB one with room for the cache. Both come with an eagle3
  # draft head in the same repo, used here for speculative decoding.
  #
  # These are reasoning models and thinking cannot be switched off, only turned down, so both
  # rows carry `--reasoning-effort low` and their token counts include whatever analysis the
  # model still does. That is a real difference from the other rungs and the entry says so.
  gptoss-120b)
    BIN=/home/user/llama.cpp/build/bin/llama-server
    DEV=$A6000_UUID,$GF3090_UUID
    ARGS=(-m /models/gpt-oss-120b/gpt-oss-120b-MXFP4.gguf
          -c 32768 -ngl 99 -fa on -t 32 -b 2048 -ub 512
          -md /models/gpt-oss-120b/eagle3-gpt-oss-120b-Q8_0.gguf --spec-draft-n-max 3
          --jinja --reasoning-effort low) ;;
  gptoss-20b)
    BIN=/home/user/llama.cpp/build/bin/llama-server
    DEV=$GF3090_UUID
    ARGS=(-m /models/gpt-oss-20b/gpt-oss-20b-MXFP4.gguf
          -c 32768 -ngl 99 -fa on -t 16 -b 2048 -ub 512
          -md /models/gpt-oss-20b/eagle3-gpt-oss-20b-Q8_0.gguf --spec-draft-n-max 3
          --jinja --reasoning-effort low) ;;
  # GLM-5.3-Flash at exl3 4.05 bpw, 154 GB, through TabbyAPI rather than llama.cpp: a different
  # engine and a different family, which is the point of including it.
  #
  # The gpu_split is rebuilt here rather than taken from ~/tabbyAPI-config.yml. That file dates
  # from 2026-09-15 and reads its split under CUDA_DEVICE_ORDER=PCI_BUS_ID, which put the A6000
  # first -- it was on bus 01. The slot move of 2026-09-16 put it on bus 61, so the same file
  # today asks the 24 GB card to hold 44 GB. configs/gpu-order.env exists for exactly this, and
  # the order here comes from it: CUDA takes the list order, so the 48 GB card is device 0.
  # GLM-5.3-Flash at exl3 4.05 bpw through **exl3-serve**, which is what actually served this
  # model here. The first three attempts went through TabbyAPI because ~/tabbyAPI-config.yml
  # names GLM and was the obvious thing to reach for -- and none of them produced a translation.
  # The tapes in assets/ say what really ran: `summary.server.kind` is `exllamav3` and the args
  # are the line below, recorded 2026-09-15. The TabbyAPI config was written for the #454
  # FAIL-first check, not for serving takes, which its own first comment says.
  #
  # -gs 44,21 means 44 GB on the first device. That was the A6000 when this line was recorded,
  # because the A6000 was on bus 01; the slot move of 2026-09-16 put it on bus 61 and would now
  # hand 44 GB to the 24 GB card. CUDA_VISIBLE_DEVICES is set from configs/gpu-order.env below,
  # which puts the 48 GB card first by UUID and keeps the split meaning what it meant.
  #
  # -cs is 16384 and not the tape's 8192. The recorded line came from a streaming demo whose
  # prompts were short; a whole document is 3 129 tokens in and about 3 100 out, and at 8192 the
  # answer stopped at 4 096 generated with the last table still in English and the final sentence
  # cut (measured 2026-09-18). A context copied from a workload that is not yours is a defect,
  # even when every other flag on the line is right.
  glm53)
    KIND=exl3
    PORT=${PORT_EXL3:-8089}
    DEV=$A6000_UUID,$GF3090_UUID
    # STREAM=0 drops --stream. It is the A/B for the broken characters: measured 2026-09-18,
    # GLM's Korean came back with 18 U+FFFD in 6429 characters and the saved stream showed the
    # server writing `\ufffd` into the JSON itself, so the client is not where they are made.
    # Turning MTP off left 15 of them, which rules out the multi-token step. What is left to
    # separate is the incremental detokenizer from the model, and only the non-streamed path
    # does that: one request, one decode of the whole sequence, nothing to carry across steps.
    CLIENT=(${STREAM:+--stream}) ;;
  glm53-tabby)
    KIND=tabby
    PORT=${PORT_TABBY:-5055}
    DEV=$A6000_UUID,$GF3090_UUID
    CLIENT=(--stream --extra-json '{"template_vars": {"enable_thinking": false}}') ;;
  *) echo "unknown model tag $TAG" >&2; exit 2 ;;
esac

mkdir -p "$OUT"
say(){ echo "$(date +%H:%M:%S.%1N) $*" | tee -a "$OUT/run.log"; }

witness(){  # the row's own evidence of quietness, at both ends
  local when=$1
  { echo "when=$when"
    echo "load1=$(cut -d' ' -f1 /proc/loadavg)"
    grep '^some' /proc/pressure/io
    echo "llama=$(pgrep -c '[l]lama-server' || true)"
  } | tee -a "$OUT/witness.txt" | sed "s/^/  /" >> "$OUT/run.log"
}

say "=== translate round: $TAG on $(basename "$SRC"), approved by $WHO ==="

# A lease whose pid does not answer is no lease (2026-09-17: a stale one cost a peer a night).
if [ -f "$LEASE" ]; then
  held=$(awk '{print $2}' "$LEASE")
  if [ -n "${held:-}" ] && kill -0 "$held" 2>/dev/null; then
    say "ABORT: lease held by live pid $held -- $(cat $LEASE)"; exit 1
  fi
  say "clearing an abandoned lease: $(cat $LEASE)"; rm -f "$LEASE"
fi
io=$(awk '/^some/{split($2,a,"="); print a[2]}' /proc/pressure/io)
awk -v io="$io" -v m="$IO_MAX" 'BEGIN{exit !(io+0 > m+0)}' && { say "ABORT: io pressure some avg10=$io > $IO_MAX"; exit 1; }
echo "translate $$ $(date -Is)" > "$LEASE"
say "lease taken: $(cat $LEASE)"
witness start

cleanup(){
  rc=$?
  if [ -n "${SPID:-}" ] && kill -0 "$SPID" 2>/dev/null; then
    # exllamav3 unloads through the server's own API; killing it with the model resident is how
    # a previous session left both cards held (docs/quiet-machine.md).
    [ "${KIND:-llama}" = tabby ] && curl -s -m 60 -X POST "http://127.0.0.1:$PORT/v1/model/unload" -o /dev/null && sleep 3 || true
    say "stopping the server (pid $SPID)"
    kill -TERM "$SPID" 2>/dev/null || true
    for _ in $(seq 120); do kill -0 "$SPID" 2>/dev/null || break; sleep 1; done
    # exllamav3's CPU expert worker is a spawned child and can outlive the leader holding VRAM.
    members(){ ps -eo pid=,sid= | awk -v s="$SPID" '$2==s && $1!=s{printf "%s ", $1}'; }
    for _ in $(seq 15); do [ -z "$(members)" ] && break; sleep 1; done
    [ -n "$(members)" ] && { say "session members left: $(members) -> SIGTERM"; kill -TERM $(members) 2>/dev/null || true; sleep 10; }
  fi
  for _ in $(seq 60); do
    [ "$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -1)" -lt 2000 ] && break
    sleep 2
  done
  say "gpus after: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr '\n' ' ')"
  witness end
  [ "$(awk '{print $2}' "$LEASE" 2>/dev/null)" = "$$" ] && rm -f "$LEASE" && say "lease released"
  rm -f "${TR_PRIVATE:-}"
  say "=== done, rc=$rc ==="
}
trap cleanup EXIT

export CUDA_VISIBLE_DEVICES=$DEV
if [ "$KIND" = exl3 ]; then
  # `--max-tokens-cap` and `--parallel 1` were added 2026-09-18 after the first GLM row came
  # back cut. The client asks for 16384; exl3-serve's `--max-tokens-cap` defaults to **4096**
  # and silently clamps the request to it, then reports `finish_reason: "stop"` -- so the row
  # read as a model that chose to end its answer in the middle of a table. The evidence is
  # that run's own timings.json: `predicted_tokens: 4096`, exactly the default, `"stop"`.
  # The cause was not the cache size, which an earlier note in this file blamed.
  # `--parallel 1` goes with it: the cache is divided between slots, so at `--parallel 2` a
  # 16384 cap has 8192 - 3129 = 5063 tokens of room and would clamp again a little further on.
  # Only one request is ever in flight here.
  #
  # The cap is 12288 and not 16384, which is the whole cache: measured 2026-09-18, a cap equal
  # to the cache makes exl3-serve accept the request, send one empty delta and close the stream
  # with no error anywhere -- prompt 3129 + 16384 reserved does not fit in 16384 and the server
  # does not say so. 12288 leaves 3129 + 12288 = 15417 inside the cache, and the answer needs
  # about 4500. That failure is only visible at all because --save-stream keeps the wire.
  /home/user/.venv-exl3/bin/python3 /home/user/.venv-exl3/bin/exl3-serve \
    -m /models/GLM-5.3-Flash-exl3-4.05 -gs 44,21 -mcs 185 -mct 32 -cs ${CS:-16384} ${MTP:+-mtp} \
    --max-tokens-cap 12288 --parallel 1 --port "$PORT" > "$OUT/server.log" 2>&1 &
  SPID=$!
  WANT=python3
elif [ "$KIND" = tabby ]; then
  TREE=/home/user/tabbyAPI
  # The config is used exactly as ~/tabbyAPI-config.yml has it, and that is the fix rather than
  # the shortcut. Measured 2026-09-18, twice: with `reasoning: false` GLM-5.3 thought anyway and
  # the whole trace landed in `content`; with `reasoning: true` but `start_in_reasoning: never`
  # it thought in plain prose with no opening tag, so there was nothing for TabbyAPI to separate
  # and the answer still came back inside 500 lines of deliberation. The template's own
  # `start_in_reasoning: auto` is what puts a delimiter there. Thinking therefore counts against
  # this row's time and tokens, the same caveat the gpt-oss rows carry.
  cat /home/user/tabbyAPI-config.yml > "$OUT/config.yml"
  cp "$OUT/config.yml" "$TREE/config.yml"
  cd "$TREE"
  /home/user/.venv-tabby/bin/python main.py > "$OUT/server.log" 2>&1 &
  SPID=$!
  WANT=python
else
  "$BIN" "${ARGS[@]}" --alias "$TAG" --host 127.0.0.1 --port "$PORT" > "$OUT/server.log" 2>&1 &
  SPID=$!
  WANT=llama-server
fi
# A simple command should be llama-server from the first read, but the check is cheap and
# the failure it guards against is silent, so it gets a few tries rather than one.
for _ in 1 2 3 4 5; do
  comm=$(cat "/proc/$SPID/comm" 2>/dev/null || echo gone)
  [ "$comm" = "$WANT" ] && break
  sleep 0.4
done
[ "$comm" = "$WANT" ] || { say "ABORT: \$! is $SPID comm=$comm, not $WANT"; exit 1; }
say "server pid $SPID comm=$comm"
say "flags: ${ARGS[*]}"

HEALTH=health
[ "$KIND" = tabby ] && HEALTH=v1/models
# exl3-serve answers /health and /props; it has no /v1/models, which is TabbyAPI's.
[ "$KIND" = exl3 ] && HEALTH=health
for i in $(seq 1800); do
  curl -sf "http://127.0.0.1:$PORT/$HEALTH" >/dev/null 2>&1 && break
  kill -0 "$SPID" 2>/dev/null || { say "ABORT: server died while loading -- $(grep -m2 -iE 'error|failed' "$OUT/server.log" | cut -c1-200)"; exit 1; }
  sleep 1
done
curl -sf "http://127.0.0.1:$PORT/$HEALTH" >/dev/null || { say "ABORT: server never became healthy"; exit 1; }
# The card is named, not just numbered. `nvidia-smi` answers in *index* order, which on this
# board is 0=3090 and 1=A6000, while CUDA_VISIBLE_DEVICES puts the A6000 first -- so CUDA0 is
# the second number printed. Two placements were planned off that inversion held in someone's
# head before it was written down here (2026-09-18).
say "server healthy after ${i}s; vram $(nvidia-smi --query-gpu=index,name,memory.used --format=csv,noheader,nounits | sed 's/NVIDIA //; s/GeForce //' | paste -sd' | ' -)"

say "translating $SRC whole, one request${MASK:+, fenced blocks held back}"
# `| tee` makes the pipeline's status the status of tee, so without this the round
# reported rc=0 over an HTTP 500 and wrote an empty translation next to a clean log
# (measured 2026-09-18 on coder-next, the first model whose server refused to answer).
set -o pipefail
python3 /home/user/translate/translate-md.py \
  --in "$SRC" --out "$OUT/$(basename "$SRC" .md).ko.md" \
  --url "http://127.0.0.1:$PORT/v1/chat/completions" --model "$TAG" \
  --timings "$OUT/timings.json" ${MASK:+--mask-fences} ${RAW:+--raw-chatml} \
  --save-stream "$OUT/stream.sse" \
  ${CLIENT[@]+"${CLIENT[@]}"} 2>&1 | tee -a "$OUT/run.log"

[ -s "$OUT/timings.json" ] || { say "ABORT: no timings written -- the request did not succeed"; exit 1; }
# timings.json being written is not the same as an answer arriving. Measured 2026-09-18: exl3-serve
# accepted a request it could not fit, sent one empty delta, closed the stream, and this round
# reported rc=0 over a one-byte translation and a row of nulls.
KO="$OUT/$(basename "$SRC" .md).ko.md"
[ "$(wc -c < "$KO")" -gt 200 ] || { say "ABORT: the translation is $(wc -c < "$KO") bytes -- the server answered nothing"; exit 1; }
say "translation written to $OUT/$(basename "$SRC" .md).ko.md"
