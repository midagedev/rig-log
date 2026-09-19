#!/bin/bash
# DeepSeek-V4.1-Flash on two GPUs, system RAM, and NVMe.
#
# The model is 347 GB at Q3_K_M against 72 GB of VRAM, so the question is not
# whether it fits but what goes where. Three tiers:
#
#   GPU   every layer's attention and hyper-connection tensors (60 MB a layer,
#         2.5 GB for all forty), plus as many expert layers as the cards hold.
#   RAM   the remaining expert layers, about 6.5 GB each.
#         An expert layer is about 6.5 GB here (three [5120, 2304, 384] tensors),
#         so the counts below are deliberately low for a first boot: four layers
#         on the 48 GB card, two on the 24 GB, and raise them once a run has
#         reported how much VRAM is actually left.
#   NVMe  the two engram tables, 42.2 GB each. These are conditional memory:
#         384 M rows read through ggml_get_rows, 24 rows per token per layer
#         and only two layers carry one, so a token touches 48 rows -- 5.2 KiB.
#         --lazy-mode leaves them on the file and serves rows on demand.
#
# One -ot, comma-separated. This branch warns that repeating -ot keeps only
# the last value, which would silently send every expert to the CPU and leave
# both cards empty -- a configuration that loads, serves, and reports a number
# that means something else entirely. Order still matters within the list:
# the catch-all exps=CPU has to come last.
#
# -ub 512 now, -ub 2048 before 2026-09-13 evening; -c 16384 rather than 32768.
# Prompt processing is batched and compute-bound, so a larger micro-batch
# amortizes each expert tensor read across more tokens: at a 4288-token prompt,
# -ub 512 gave 214 tok/s and -ub 2048 gave 343, with decode unchanged. The
# compute buffer scales with the micro-batch (4.3 GB on CUDA0 and 2.4 GB on
# CUDA1 at 512, measured), and that VRAM is worth more as expert layers:
# decode with experts on the CPU is bound by system memory bandwidth, and every
# 6.5 GB layer moved onto a card takes 3 % off the bytes a token reads. The
# trade is deliberate: long-prompt prefill is slower, decode is faster.
# Context is the same trade: 32768 forces -ub down and prefill with it.
# Quantizing the KV cache does not buy it back; the buffer, not the cache, is
# what does not fit.
#
# The draft gets one -otd. A draft context without tensor overrides enables
# pipeline parallelism across the two cards, which keeps four copies of its
# compute buffers; the override is a no-op placement that turns that off. A
# single draft device (-devd CUDA0) is not an option: the DSpark draft reads the
# target's hidden states, some of which live on CUDA1, and the scheduler aborts.
#
# Run it on a machine with nothing else holding VRAM.
set -eu

# The build is the V4.1 runtime branch merged with upstream master plus the V4.1 DSpark draft port
# (log/2026-09-13-deepseek-v41-on-ik-llama.md, "The same draft on mainline").
# Since 2026-09-14 12:45 the build carries 75a0eb4f1, the fused lightning indexer for V4.1: the unfused indexer
# materialized a [positions x tokens x 32 heads] fp32 score twice, which capped the context at 16k; with the fused
# op 64k loads at this placement and 256k at four expert layers (WKS-12). Outputs are byte-identical, decode unchanged.
# The build and gpu-order.env live under the serving user's home, not the caller's: a
# measuring round run as root resolved $HOME to /root and missed the binary entirely
# (2026-09-19). One base for both, overridable, so the two lines cannot drift apart again.
IKHOME=${IKHOME:-/home/user}
B=${B:-$IKHOME/llama.cpp-v41-merged/build/bin/llama-server}
# engramQ8-tokembdBF16-attnQ8: the Q3_K_M upload with its engram tensors grafted from the Q8_0 build
# (log/2026-09-13-engram-q8-repack.md), its token embedding kept in bf16, which the DSpark
# draft borrows (41 -> 45 % acceptance at block 5, 55 -> 60 % at block 3, for 1.3 GB of RAM),
# and since 2026-09-14 its attention, shared-expert and indexer projections at Q8_0 (WKS-13,
# log/2026-09-14-v41-gap-closed-prefill-and-queue.md): the upload had 288 of 328 of them at Q2_K.
# Perplexity 2.1190 -> 1.8992 for 4.7 GB more VRAM, which is why the placement below is seven
# expert layers, not eight: at seven the grafted file decodes 25.2 against 23.0 for the old file
# at the same placement, level with the old file's eight-layer 25.6 -- the Q8_0 kernel and two
# points of draft acceptance pay for the layer.
M=${M:-/models/DeepSeek-V4.1-Flash-Q3_K_M-engramQ8-tokembdBF16-attnQ8/DeepSeek-V4.1-Flash-Q3_K_M-00001-of-00009.gguf}
# The DSpark draft: block 3 measured 22.8 tok/s median against 17.7 without it (20 greedy prompts,
# quiet box, warmed), 24.8 after the VRAM re-balance below, 25.6 with blk 7 on the cards too (old file, eight layers), 25.2 on the
# attention-Q8_0 file at the seven layers below; block 5 is the same within noise. The request-level speculative.n_max is
# disabled in this server, so the block size is set here.
D=${D:-/models/DeepSeek-V4.1-Flash-DSpark/DeepSeek-V4.1-Flash-Fp8-128x742M-MXFP4_MOE.tl37.gguf}

. "$IKHOME/gpu-order.env"   # CUDA0 = A6000 by UUID (2026-09-16, slot move flipped PCI order); configs/gpu-order.env

# C and NP are the serving defaults unless a measuring round overrides them, and unset they
# reproduce this file as it ran before 2026-09-18 byte for byte. They exist because the batch
# translation asks a different question of this placement than an interactive session does:
# 140 independent requests in a queue care about aggregate throughput, not about one stream's
# latency, and the only concurrency number this box has on this model is second-hand
# (log/2026-09-14-air-cooler-swap.md: three concurrent decodes at 21 tok/s each against 28 for
# one). -c divides between slots, so -np 3 at -c 16384 gives each request 5461 tokens, which
# most parts of this repo do not fit in; measuring it needs both knobs at once.
C=${C:-16384}
NP=${NP:-}
# PORT and EXTRA exist so that a measuring round does not need a second copy of the serving
# line. There were two copies until 2026-09-18 -- this file and the one pasted into the batch
# runner -- and a copy is a placement that drifts silently from the one the log describes.
PORT=${PORT:-8001}
EXTRA=${EXTRA:-}
# NMAX is the DSpark draft depth and DRAFT=0 removes the draft entirely. Both exist for the
# same reason EXTRA does: a measuring round that sweeps the draft must not carry its own copy
# of this line. WKS-36 sweeps NMAX to find out whether a k-token verification pass costs the
# same as a one-token pass (it should; measured it does not).
NMAX=${NMAX:-3}
DRAFT=${DRAFT:-1}
draft_args=()
if [ "$DRAFT" != 0 ]; then
  draft_args=(-md "$D" --spec-type draft-dspark --spec-draft-n-max "$NMAX" -otd "output_norm=CUDA0")
fi
exec "$B" -m "$M" --alias DeepSeek-V4.1-Flash \
  -c "$C" ${NP:+-np "$NP"} -ngl 99 -t 32 -b 2048 -ub 512 \
  --lazy-mode auto \
  -ot "blk\.[0-3]\.ffn_.*_exps=CUDA0,blk\.6\.ffn_down_exps=CUDA0,blk\.[4-5]\.ffn_.*_exps=CUDA1,blk\.6\.ffn_(gate|up)_exps=CUDA1,exps=CPU" \
  "${draft_args[@]}" \
  --jinja $EXTRA \
  --host 127.0.0.1 --port "$PORT"
