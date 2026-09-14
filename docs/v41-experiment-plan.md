# What to run, in what order, and what would prove it wrong

**2026-09-12.** A plan, written before the first run rather than after it, so
that the numbers it produces can disagree with it.

[The lever survey](raising-tokens-per-second.md) projects **16–18 tok/s** for
DeepSeek-V4.1-Flash on this machine and ranks six ways to raise it. Every one
of those figures rests on a single borrowed constant — 64.8 GB/s of effective
memory bandwidth, back-calculated from a *different* model measured on
2026-09-11. The first purpose of these experiments is to replace that constant.
The second is to find out whether the premise the whole configuration is built
on — that 84.6 GB of engram tables can stay on the drive — is true.

## The protocol every run follows

**The machine must be quiet.** `llm.service` holds both GPUs and 113 GB of
resident model; it stops first. The 510 GB original-weights download writes to
the same NVMe that holds the model, which both evicts expert pages from the
page cache and competes for exactly the IOPS these runs are trying to
attribute to engram — it pauses too. It is resumable by design, so pausing
costs nothing but time.

**Measure with [`configs/bench-serve.sh`](../configs/bench-serve.sh).** It
records, per run: decode and prefill throughput, `VmRSS` split into `RssAnon`
and `RssFile`, major faults, and the model drive's read count and bytes — the
last four as deltas across the run. Throughput on its own cannot distinguish a
run slowed by expert pages missing from the page cache from one slowed by
engram rows coming off the drive; those counters can.

**One variable per run.** The `-ot` split, `-c`, and the quantization each
move VRAM around, and moving two at once produces a number that cannot be
attributed. Where a change is expected to be free, say so in advance and let
the run contradict it.

## E0 — Does it load, and does the premise hold

The only experiment whose result is not a number.

Start the server as [`configs/v41-serve.sh`](../configs/v41-serve.sh) is
written — deliberately conservative, four expert layers on the A6000 and two
on the 3090 — and read the resident set once loading settles.

| outcome | meaning | next |
|---|---|---|
| not-resident ≈ 84.6 GB | engram stayed on the file, as designed | E1 |
| not-resident ≈ 0 | `--lazy-mode auto` did not mark the 42 GB tensors | retry with `--lazy-mode on` |
| load fails or OOMs | the split is wrong, or the branch cannot serve this file | narrow the split, then read the error properly |

`auto` marks tensors above 4 GiB; the engram tensors are 42.2 GB each, so it
should catch them. "Should" is why this is an experiment.

The load itself is worth timing. 347 GB off a drive whose measured sustained
read is around 6 GB/s is a floor of about a minute, and a load much slower
than that says something about how the file is being read.

## E1 — The number that replaces the assumption

A fixed prompt, `temperature 0`, 128 tokens, one stream.

The projection is 17.4 tok/s. What matters is not whether it lands there but
what the run implies about effective bandwidth, which is recoverable from it:

```
effective GB/s = (bytes per token from RAM) / (ms per token)
```

with bytes-per-token known from the measured budget and the `-ot` split. If it
comes back near 64.8 GB/s, the V4 calibration transfers and the whole lever
table stands. If it comes back near 115.8, the gather is not the problem and
most of the table is wrong. If it comes back far below 64.8, something
specific to this model — engram, hyper-connection, the host-side hash — is
eating time that the budget does not account for, and E2 finds it.

## E2 — What engram actually costs

The arithmetic says a token touches about 48 engram rows of 110 bytes each,
which is nothing in bytes and possibly a lot in latency: 48 serial page faults
at this drive's measured 0.056 ms QD1 random read would be **2.7 ms per
token**, against a 3.6 ms budget for the entire rest of the per-token GPU work.

This needs no new run — E1's counters answer it:

- **major faults per token** near 48 means the rows are coming off the drive
  one fault at a time, and the cost is fault latency, not bandwidth.
- **near zero** means the rows are being served from the page cache, which
  would be good for speed and bad for the premise: it means engram is
  competing with expert weights for the 251 GB of RAM after all.
- **drive bytes per token** much above 5 KB means read-ahead is amplifying
  110-byte rows into pages, despite the `POSIX_MADV_RANDOM` the branch sets.

The middle case is the one to watch for, because it is the failure mode that
looks like success.

## E3 — Widen the split until it stops paying

The starting split is six expert layers on the GPUs. The measured budget says
about **9.6** fit once 4.0 GB of dense tensors and the KV cache are placed —
but the KV size for this architecture at 32k is not yet measured, so the
ceiling is a guess and E3 is how it gets found.

Raise the count one layer at a time and record tok/s and free VRAM. Each layer
moves `4.04/40 = 0.101 GB` per token off DDR4, which at 64.8 GB/s is 1.56 ms —
about **+0.5 tok/s per layer** at this speed. That predicted slope is the
point of the sweep: if the measured slope matches, the model of what is
happening is right, and the remaining levers can be trusted. If tok/s is flat
while layers move to VRAM, the bottleneck is not where this document says it
is, and everything downstream needs rethinking.

Stop when a layer fails to allocate, and keep the last configuration that
loaded with headroom to spare. The previous model's entry records the cost of
getting this wrong silently: a draft model that could not allocate its KV
scheduler logged an error on every decode step and ran *slower* than no
speculation, with nothing pointing at VRAM.

## E4 — Concurrency, which may be the largest number here

`-np 4`, four concurrent completions, aggregate throughput.

The V4 run measured 47 tok/s aggregate against 29 single-stream — a 1.6×
that costs nothing but a flag, because a layer's experts are read once and
used by every token in the batch. If the goal is a served endpoint rather than
one fast stream, this outranks every other lever on the list.

It also interacts with engram in a way nothing else does: four streams at
different positions need four different sets of engram rows, so major faults
per token should stay roughly constant while tok/s rises. If they scale
super-linearly instead, engram is a concurrency bottleneck and that is a new
finding.

## E5 — Prefill, separately

Prompt processing is compute-bound and batched, and the previous run found it
moves in the opposite direction from decode: speculation lowered it, and so
did a smaller batch. `-b 4096 -ub 4096` is the documented recommendation for
heavy CPU offload; the current script uses `-b 2048 -ub 512`.

Worth one sweep, reported separately from decode, because a configuration that
is right for one can be wrong for the other and this repo has already published
a table where that happened.

## The queue as of 2026-09-14 morning

Measured since the sections above were written: the ik-against-mainline gap
is a first-pass page-fault gap (warm, ik 18.8 against mainline 19.8 at the
same split; [docs](ik-vs-mainline-v41-gap.md)), and long-prompt prefill on
the served `-ub 512` profile is 214 tok/s against 343 at `-ub 2048` (4288
tokens, earlier build). Three windows, in this order; each stops the
production server, runs on port 8099, and restores it.

| # | window | what it settles | gate |
|---|---|---|---|
| Q1 | ik engram row prefetch (port of 86d01ece1 into `llama_set_engram_rows`), same six prompts, faults counted | whether the 41–62 faults a token and the 28 % first-pass loss are the engram rows | ik pass 1 from 13.6 toward 18.8; faults toward mainline's 13–21 |
| Q2 | prefill: deterministic code prompt at ~4k and ~15k tokens, `-ub` 512 / 1024 / 2048 / 4096, PCIe link gen and width sampled during prefill, then `cache_prompt` on a growing prefix | E5 with numbers; whether prefill is PCIe-bound (the CUDA backend pulls CPU expert weights for batches ≥ 32, `ggml_backend_cuda_device_offload_op`), and how much a coding client's next turn actually prefills | tok/s per `-ub`; `prompt_n` on the second request of the pair |
| Q3 | precision on the GPU-resident tensors (below) | whether attention and shared experts at Q8_0 change perplexity, at a VRAM cost and no decode cost | 4-chunk perplexity on the served file against the grafted one; decode within the load-to-load band |
| Q4 | ~~re-distil the draft against the served target: fine-tune the tl37 draft head on the target's greedy continuations~~ corrected 2026-09-14 afternoon: the DSpark draft is not a head, it is three full V4.1 MoE blocks, 14.23 B parameters, 8 GB at MXFP4, and it reads the target's hidden states at layers 38–40 (`dflash.target_layers`). Training it needs (a) a PyTorch implementation of the dflash architecture, which does not exist yet (the transformers port ignores the draft weights; DeepSeek ships no training code), (b) a llama.cpp change to dump those three hidden states per token, and (c) memory for a 14 B model, which a 12 GB card does not have even at 4 bits with activations. WKS-16 stays open as a question, not a scheduled window | whether acceptance is bounded by draft/target mismatch at all: the engram Q3→Q8 change moved acceptance 58.0 → 58.9 % while target perplexity moved 6 %; a published MXFP4 target shows 51 % on prose and 79 % on code, in the same band as ours, so the mismatch may be costing nothing. The "60 → 70 %" figure is a projection with no measurement behind it | first, a reference acceptance on a higher-precision target (nothing on this machine reaches it; the fp8 figure is not published); only if that shows a real gap does the training pipeline earn its build |
| Q5 | draft precision (WKS-17): convert the DSpark draft from the fp8 originals at Q8_0 (`convert_hf_to_gguf.py --dspark`), fix `target_layers` as tl37 was fixed, run the twenty-prompt drafted pair against the MXFP4 draft on the same target | whether the 58–60 % acceptance is the draft's own ceiling or its 4-bit quantization; the no-training half of the WKS-16 question | accepted/drafted and tok/s, same target file and placement; a flat result closes WKS-16 |
| Q6 | routed experts at MXFP4 by graft (WKS-18): the uploader's "Q8_0" set keeps the experts at MXFP4 — the native 4-bit — in shards 1–7 (289 GB, 6.72 GiB a layer against the served mix's 6.47 GB); first the on-card layers (blk 0–7, shards 1–2), then all forty | how much of the perplexity is in the lossy Q3_K/Q4_K requantization of experts that were released at 4 bits; on-card layers cost VRAM only, the rest costs +11.6 % bytes a token | 4-chunk perplexity against 1.8992; decode on the twenty prompts for the all-layer file; MXFP4 CPU kernel speed per byte checked | **Stage 1 measured 2026-09-14: 1.8964 ± 0.0491 against 1.8992 — −0.15 %, within noise; the seven-layer placement no longer loads (+5.1 GB on the cards). Stage 2 parked.** |
| Q7 | RAM experts lower by graft (WKS-19): the uploader's Q2_K set (experts Q2_K gate/up, Q3_K down, ~2.9 bpw) into the CPU-resident layers only, attention kept at Q8_0 | the tok/s side of the precision curve, about −25 % bytes a token on 32 layers | perplexity cost and drafted decode gain as a pair |
| Q8 | engram lazy-mode row cost (WKS-20): served placement, experts warmed on other prompts, the twenty prompts three passes with the coolant gate between them, major faults per pass as the witness | what the 30–48 random 4 KB NVMe reads a token cost against rows already cached; shi3z's runtime gathers engram rows from host RAM at ~1 ms a token, the reference | pass-1 vs pass-2/3 median; first run 2026-09-14 12:10 gave pass 1 23.26 at 28.5 faults a token and lost pass 2 to the thermal guard | **Measured 13:04: 23.36 → 25.07 / 25.08, 22.1 → 0 faults a token — the rows cost 6.8 % of decode on fresh text; RAM pinning is the follow-up.** |
| Q9 | fused lightning indexer on V4.1 (WKS-12 window 4): the port's indexer materialized [positions × tokens × 32 heads] fp32 twice, 135 GB at 256k and `-ub 2048`; commit 75a0eb4f1 takes `ggml_lightning_indexer` under `fused_lid` as the V4 path does | whether 256k loads at all, byte identity of twenty greedy outputs against the unfused binary, decode unchanged, then the prompt-cache prefix pair | c16k identity 20/20 and tok/s within the band; c64k, c256k KV q8_0 (code, `-ub 2048`), c256k (decode) load; `prompt_n` on the growing-prefix pair | **Measured 13:13: identity 20/20, warm 25.16; c64k and c256k (code, four layers) load, c256k decode (seven layers) does not; the cache pair pays a 2048-token SWA-checkpoint tax per hit — window 5 tries `--swa-full` and `-b 512`.** |
| Q10 | host RAM bandwidth (WKS-22): **measured 2026-09-14** — read cap 132 GB/s (8 threads reach 92 %; clock, binding, interleave < 1 %); one CCD 40.2 GB/s, two 79.7, four 131.2, so the four-CCD 5975WX cannot draw eight channels and the full-load cap is memory-side (public 5975WX figure 147: ~10 % recoverable in BIOS memory clock/timings, not in flags); decode vs `-t`: 16 → 19.8, 24 → 23.2, 32 → 25.1, 48 → 24.1, 64 → 18.9 warm, physical cores win | ~~whether the 43 % of peak the bus is not delivering is threads, clock, TLB, or configuration~~ it is the CCD count and the memory side; next step is BIOS (memory 3400/3600 with FCLK 1:1, memtest + identity check), user's hands | done; BIOS step parked on WKS-22 |
| Q11 | PCIe corrected errors on the A6000 link (WKS-21): 115 BadTLP since the 09-12 boot, none in the three boots before, clustered in load windows | which load type produces them (decode, prefill, NVMe graft), the link state under load, whether the rate climbs — a marginal link is a reseat or a slot move before it is anything else | dmesg timestamps against runner logs; CESta before and after a window; LnkSta at 16GT/s ×16 under load |
| Q12 | expert routing histogram (WKS-23): log the router's top-k per layer over the twenty prompts and a coding transcript; byte-hit rate of an N-experts-per-layer GPU cache vs the whole-layer placement at equal VRAM | whether expert use is skewed enough that per-expert placement beats per-layer — shi3z's single-A100 run got 40–56 % hits on 80 cached experts | the histogram; hit rate at 45 GB of cache; go/no-go on a fork-level per-expert placement |


Measured since (2026-09-14 evening): chat-turn TTFT on the 256k profile is
26–31 s and it is the checkpoint placement (WKS-12 comment, log section
"The thirty seconds per turn are the checkpoint"); the short-prompt prefill
floor is the per-ubatch PCIe copy of the CPU expert set and `--no-op-offload`
beats it below ~700 tokens (WKS-27). Threshold sweep done: `GGML_OP_OFFLOAD_MIN_BATCH=768` closes the
short-prompt floor (257 tok 10.2 → 4.5 s, long prefill unchanged, 1024
and 2048 lose; log section "The offload threshold"). Queue now:
end-of-prompt checkpoint patch A/B + CUDA-path KV q8_0 check → then Q11 PCIe AER, Q7, Q12, WKS-24/25/26.

### Priority as of 2026-09-14 afternoon

Running now, in chain: Q9 (fused indexer, then the prompt-cache pair) →
Q8 (engram cost, second run). Then, in order of expected decode gain per
hour of machine time: **Q10** (bandwidth — the wall everything else sits
behind; a threads-and-clock sweep is one window and needs no download),
**Q11** (AER correlation — reads only, piggybacks on any window), **Q7**
(RAM experts Q2_K — bytes a token down 25 % on 32 layers, one download),
**Q12** (routing histogram — instrumentation, no download), WKS-11(2)
(intermediate engram precision), Q5 (draft precision — blocked on a V4.1
DSpark export). Q6 stage 2 is parked on the stage-1 result. Q4 is struck.


The likely outcome of Q2 is two serving profiles — decode (the current one)
and coding (larger `-ub`, longer context, possibly no draft) — rather than
one compromise.

### Q3 — raise precision where the bandwidth is not the bottleneck

The user's question was whether the experts that sit in RAM could be
quantized less, for quality, without losing tok/s. The served file, read by
tensor group (2026-09-14, the `engramQ8-tokembdBF16` shards):

| group | quant | size |
|---|---|---:|
| engram tables | Q8_0 | 209.2 GB |
| routed experts | Q3_K 155.7 · Q4_K 96.8 · Q5_K 6.2 | 258.7 GB |
| attention | Q3_K | 2.2 GB |
| shared experts | Q3_K / Q4_K / Q5_K | 0.7 GB |
| dense ffn, norms | BF16 / F32 | 0.2 GB |
| token embedding / output | BF16 / Q6_K | 1.8 GB |

The routed experts cannot go up. Decode with experts on the CPU is bound by
the bytes a token reads (3.44 GB at this quant against 115.8 GB/s), so every
bit per weight added to the experts is subtracted from tok/s in proportion;
Q3_K to Q4_K_M is roughly +35 % bytes. And 259 GB of experts plus 209 GB of
engram already sit on 251 GB of RAM as memory-mapped files, which is where
the first-pass faults come from; larger experts fault more.

What can go up is everything the GPU reads: attention (2.2 GB at Q3_K, the
tensor group most sensitive to quantization), the shared experts (0.7 GB,
read every token), and, at a VRAM price per layer, the eight routed-expert
layers that live on the cards. Attention and shared experts at Q8_0 are
about 5 GB more VRAM in total and zero bytes more per token on the CPU side.
Five gigabytes is one expert layer's worth of card memory (about 3 % of
decode), or comes out of the compute-buffer headroom if `-ub` stays at 512.

How to build the file: the same graft the engram repack used
([log](../log/2026-09-13-engram-q8-repack.md), `tools/engram-repack/repack.py`)
with the attention and `_shexp` tensors taken from the uploader's Q8_0 build
instead of the engram tensors. ~~Those tensors are spread across the Q8_0
shards 1–7, which are not on disk (only 8–10, the engram shards, are); at
about 6 GB of wanted tensors against 300 GB of shards, fetch them by HTTP
range from the tensor offsets rather than downloading the shards.~~
Corrected 2026-09-14 afternoon, from the shard headers: shards 1–7 hold
only routed-expert tensors (12–18 a shard), and every attention, shared
expert and indexer tensor of all forty layers — 924 tensors, Q8_0 where
quantized — sits in shard 10, the 10 GB shard that is already on disk. No
download is needed; the graft reads the source locally. (An HTTP-range
extractor was written and run on a second machine before the headers were
read; it fetched zero tensors, which is how the premise was found wrong.) The fp8
originals are on disk (476 GB) as the fallback source. Perplexity: four
chunks, 39 s a chunk on this placement, measured once on the current file
first so the comparison has a baseline.

Not in Q3: `--tensor-type` overrides in `llama-quantize` from the fp8
originals. That produces the same file at the cost of a full requantization
pass; the graft is the cheaper route while the tooling exists.

## Blocked, and on what

These are the large levers, and none of them can run yet.

| experiment | what it would settle | blocked on |
|---|---|---|
| `-ser` sweep, 6 → 5 → 4 → 3 experts | the cheapest 1.4× available, and what it costs in perplexity | ik_llama cannot load `deepseek41` |
| `-thp` | whether huge pages recover part of the missing 44% of memory bandwidth | same |
| `-rtr` | whether repacking beats keeping engram off RAM — they are mutually exclusive | same |
| MTP restored in conversion | speculation, projected 1.18× | a conversion change; original weights downloading |
| experts at ~2.4 bpw | the largest single lever, projected 29 tok/s | ik support, plus requantizing 510 GB |

The ik architecture port unblocks the first three at once, which is the
argument for doing it before the conversion work rather than after.

## What this plan is not measuring

Quality. Every lever in the middle of the table — fewer active experts, pruned
experts, lower-bit quantization — buys speed with accuracy, and none of the
runs above would notice. A perplexity baseline on this file, taken once while
the machine is quiet, is what makes those trades comparable later. It is not
on the critical path to a first number, and it should not be skipped on that
basis.
