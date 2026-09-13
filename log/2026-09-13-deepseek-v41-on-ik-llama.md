# DeepSeek-V4.1 runs on ik_llama.cpp: ten builds, two wrong graphs, one number that matched

**2026-09-13.** Yesterday's entry ran DeepSeek-V4.1-Flash on mainline
`llama.cpp` because ik_llama.cpp — the fork this machine otherwise serves
from, for `-ser`, `-rtr` and the low-bit quants — had no `deepseek41`. The
port is described in [the porting note](../docs/porting-v41-to-ik-llama.md);
this entry is the record of making it produce a correct number, measured on
the machine in [the README](../README.md), CPU-only, on this date.

Everything here was measured with mainline still serving on its port and a
209 GB download running on the model drive. That is fine for a correctness
gate — perplexity does not care who else is on the CPU — and it is why ~~no
throughput figure in this entry should be read as a throughput figure~~ no
throughput figure in the first sections should be read as one; the quiet-box
table at the end of the throughput section, added later the same day, is the
exception.

## What happened, in order

The loader was finished first: 1046 tensors, the eight engram tensors and
forty vision routing biases included. Then the graph, in three pieces: the
generalized compressed-KV runtime (two plan slots that take their ratio and
overlap from the file instead of the hardcoded 4-overlapping and 128), the
V4.1 sparse attention with rows pooled on source layers and aliased into the
readers, and the engram lookup with its host-side hash.

Build 6 was the first to reach a graph. It segfaulted in `ggml_mul_mat`
inside `build_deepseek4()` with no assert, and the Release binary had no
line numbers. A `gdb` breakpoint on `ggml_mul_mat` conditioned on a null
operand would have named the tensor; reading the mainline model file first
was faster. Its header comment lists three differences from V4, and one of
them was not in the tensor delta the porting note had measured: **the
hyper-connection coefficients lag by one sublayer**, and because of that
there is no learned output head. The null operand was `output_hc_fn`. The
fix is a mix tensor carried across the layer loop — attention collapses the
four stream copies with the previous FFN's mix, the FFN with attention's,
layer 0 with a one-hot, and the last FFN's mix does the output collapse.

Build 7 decoded. Forty-eight tokens at temperature 0 from a raw prompt:

```
대한민국의 수도는 서울특별시이다. 대한민국의 인구는 51,000,000명이다. 대한민국의 인구는 …
```

Grammatical, factually fine, and repeating — which is what an instruct
model does with a raw prompt and greedy sampling, so it says the graph is
not broken and nothing more. It is worth being explicit: this text came out
of the graph that scores 244 in the next section. A decode that reads fine
is not evidence of a correct graph, and that is exactly the case the
correctness gate exists for.

## The gate

wikitext-2, four chunks of 2048, both binaries at `-ngl 0` on the same
Q3_K_M shards, sharing page cache. The gate has a FAIL-first clause: the
port must first produce a wrong number, or the gate is not known to measure
anything.

| build | chunk 1 | chunk 2 | chunk 3 | chunk 4 | final |
| --- | --- | --- | --- | --- | --- |
| mainline `llama.cpp` | 1.7334 | 1.7571 | 1.8354 | 2.2438 | 2.2438 ± 0.0631 |
| ik build 7 graph (hyper-connection fixed; build 8 binary, log fix only) | 246.06 | 267.78 | 271.80 | 244.72 | 244.72 ± 12.03 |
| ik build 9 | 1.7229 | 1.7499 | 1.8242 | 2.2258 | 2.2258 ± 0.0622 |

Build 7 failed by two orders of magnitude, so the gate was measuring. The
defect was a single line the V4 graph inherits: after the query up
projection, V4 RMS-normalizes each head again, and ik's helper does that
even when the layer carries no weight for it. V4.1 normalizes only the
low-rank part. Mainline says so in a one-line comment; ik's graph had no
reason to mention it because for V4 it was correct. Build 9 skips it for
`deepseek41` and lands within the error bar of the oracle at every chunk,
slightly below it, which is the usual sign of two different Q3_K kernels
rather than of anything to celebrate.

Between builds 7 and 9 there is an un-numbered lesson: the per-tensor
dump (`llama-eval-callback`) was set up on both sides to bisect the layer
where they diverged, and never got used, because the mainline dump died
twice on the way in — once on a missing binary, once because opening a CUDA
context on a GPU the server already owns is an out-of-memory error even at
`-ngl 0`. `CUDA_VISIBLE_DEVICES=""` is the fix. The perplexity run with the
suspected fix finished first.

## The decode path, against the oracle

Perplexity runs the graph in batches; a server runs it one token at a
time, through a path (`n_tokens == 1`, the row gather for the shared
top-k) that perplexity never touches. So the last check was the deployed
shape: ik's `llama-server` at `-ngl 0` on a spare port, mainline's on its
usual one, the same raw prompt string to `/completion` on both, greedy.

| prompt | ik | mainline |
| --- | --- | --- |
| BOS + user + assistant + `</think>` | "The capital of South Korea is Seoul. It is a sprawling, vibrant metropolis that blends ancient palaces and temples with cutting-edge technology and modern skyscrapers, while serving as the country's political" | same for the first twelve tokens, then "…cutting-edge skyscrapers and technology, serving as the country's political, economic" |
| no BOS, with `</think>` | "…It is a bustling metropolis that serves as the country's political, economic, and cultural center…" | "…It is a bustling metropolis known for its blend of ancient temples and modern skyscrapers…" |

Agreement on the opening tokens and drift after the first near-tie is what
two different Q3_K kernels look like, and it is the same drift the
perplexity numbers show. The second ubatch-size run (`-b 512 -ub 512`, so
the engram history crosses ubatch boundaries) came in at 2.2320 ± 0.062
against mainline's 2.2537 ± 0.064 under the same setting.

Two things that are not the graph came out of the same session, and both
belong to ik's server rather than to this port. With `--jinja`, ik renders
the V4.1 chat template without `</think>` when `reasoning_effort` is
`none`, so a chat request that mainline answers directly goes through ik
as a thinking request; and a `/completion` whose `n_predict` lands inside
a multibyte Korean character comes back as a 500, "incomplete UTF-8
string". Both are reproducible with the command lines above and are
filed as follow-ups, not fixed here.

## The draft model: extracted, not yet wired

V4.1-Flash ships a speculative-decoding draft under three names, which is
worth untangling once. DeepSeek calls the mechanism **DSpark**
(semi-autoregressive drafting with confidence-scheduled verification; the
checkpoint's inference code has `dspark_block_size`,
`dspark_target_layer_ids`). The tensors carry the V3-era prefix **`mtp.*`**
(three blocks, `mtp.0`–`mtp.2`), but their contents are DSpark — `mtp.2`
has `markov_head.embed/head` and `confidence_head.proj` — so mainline's
`--mtp` export, which expects V3-style next-token heads, cannot read them.
ik_llama.cpp implements this family under its **DFlash** companion
architecture, and the GGUF it wants is `arch = dflash`.

The Q3_K_M upload has none of these tensors (1046 tensors, exactly the 40
body blocks), so the draft had to come from the fp8 original. The V4.1
branch's converter (`vcruz305/llama.cpp`, which is what "mainline" means
throughout this entry, since upstream has no V4.1 outside an open draft)
refuses `--dspark` for anything but `DeepseekV4ForCausalLM`
(`convert_hf_to_gguf.py:269-274`); a working copy widened the gate with a
`DeepseekV41DSparkModel` that inherits the V4.1 dequantizer — the fp8 block
is [32,32] on V4.1 against [128,128] on V4, and getting that wrong produces
garbage without an error. Result: one file, 7.97 GB, 78 tensors, the draft
experts as MXFP4, at
`DeepSeek-V4.1-Flash-Fp8-128x742M-MXFP4_MOE.gguf` in a `DSpark` directory
beside the model. The block-size check was a round trip on
`mtp.0.attn.wq_a.weight`: fp8 dequantized directly from safetensors against
the GGUF's Q8_0, relative RMS error 5.4e-3; the same comparison with the
[128,128] scale layout forced gives 0.144, which is what the silent
failure would have looked like.

~~That is data, not a working draft. Three things stand between the file
and a tok/s number.~~ Later the same day the draft was wired, loaded, and
measured; the paragraph below this list is the result, and the list is kept
as the plan it was. ik's DSpark loader requires `output_hc_{base,fn,scale}`
(`llama-load-tensors.cpp:2814-2817`), which V4.1 does not have — the
output hyper-connection head is exactly what the lag removed. The draft
graph (`build_dflash_dsv4`) is written to V4's rules and needs the same two
changes the body needed, the one-sublayer lag and the low-rank-only q norm;
a draft that gets them wrong drafts the wrong tokens and lowers throughput
instead of raising it. The body's GPU path is validated below, so the ik
baseline for a draft to be measured against now exists. In that order.

### The draft, wired: it loads, it drafts, and it does not pay yet

The loader and graph changes are one commit in the ik tree (`7b79b229`,
four files, 43 lines): a V4.1 draft is recognised by the absence of
`output_hc_base.weight`, the three head tensors become optional, the draft
graph skips the per-head q norm and carries the hyper-connection mix one
sublayer behind exactly as the body does, and the last FFN's mix collapses
the copies at the output. The draft file needed one correction of its own.
DeepSeek's V4 code collects the target hidden state *after* each target
layer runs; the V4.1 code collects it *before* (`inference/model.py`: "the
MTP head reads the attention input of its target layers, not their
output"). The converter inherited V4's `config + 1` and wrote
`target_layers = [38, 39, 40]`, which ik reads as the outputs of layers
37–39; the reference reads the outputs of 36–38. A metadata-only copy with
`[37, 38, 39]` (`tools/dspark/fix-target-layers.py`, tensors byte-identical)
is the corrected file.

Both files were run through the same gate, ik's server with
`--model-draft … --spec-type dspark:n_max=5`, three 200-token greedy
completions, acceptance from the server's own `draft_n` /
`draft_n_accepted`, with the engram repack still writing on the model
drive (so the tok/s are contended, the acceptance rates are not):

| arm | decode tok/s | drafted | accepted |
| --- | --- | --- | --- |
| no draft | 11.7 / 12.8 / 12.8 | — | — |
| draft, corrected ids [37,38,39] | 8.9 / 12.2 / — | 415 / 317 | 115 (28 %) / 133 (42 %) |
| draft, as converted [38,39,40] | 9.2 / 8.7 / 11.4 | 413 / 452 / 343 | 115 (28 %) / 108 (24 %) / 128 (37 %) |

Two things follow and one does not. The draft runs end to end on this
box, which it did not this morning. ~~It is below break-even: at a quarter to
two fifths accepted, a five-token block costs more target work than it
saves, and decode gets slower with the draft than without.~~ (Struck the same
afternoon: twenty prompts and a smaller block put it above break-even; the
table below.) What does not
follow is the off-by-one: the corrected ids did not move acceptance outside
the noise of three prompts, so either the correction is right and something
else in the draft graph is also wrong, or the capture point is not what the
comment says and the file was right all along. ~~The remaining suspect the
code reading turned up is rope: the reference draft attention uses the
body's YaRN-corrected frequency table, and ik's DSV4 draft graph (V4 and
V4.1 alike) ropes the draft with `freq_scale = 1, ext_factor = 0`, plain
rope — invisible on a 20-token prompt, but the tables were trained on the
other thing.~~ The gate also tried token identity between draft and no-draft
outputs and got a divergence after 74–237 characters on every prompt; that
is the batched-verification versus one-token-at-a-time drift a Q3 target
shows between engines too, and it does not distinguish a lossy draft from a
correct one, which is why acceptance is the number this table is about.

The rope suspect was wrong, and it is struck above. `DSparkAttention` in the
reference asserts `compress_ratio == 0`, and a V4.1 attention layer without
compression turns YaRN off and uses the base theta; plain rope is what the
reference does, and ik does the same in both places it ropes, the block
queries and the context K/V built from the target's hidden states. A second,
line-by-line pass against the reference found the other pieces matching too:
the capture is the input of the target layers, which makes `[37,38,39]` the
right file; the block starts one position past the last target token; the
filler token is 128799; the Markov bias chains each position on the previous
drafted token. One thing does not match. The converted draft carries no
`dflash.attention.causal` key, so ik falls back to a causal mask inside the
five-token block, while the reference (`get_dspark_topk_idxs`) lets every
block position see the whole block. A draft trained on one mask and run on
the other computes different hidden states at every block position after the
first. That is the suspect now, and a copy of the draft with the key set to
false is the test.

### Twenty prompts instead of three, and the block size

The three-prompt table above has error bars wide enough to hide the
answer, so the next gate loaded the corrected draft once and ran twenty
prompts through it, changing the block size per request (`speculative.n_max`
is a request-level override in ik's server). The machine was not quiet — a
CPU benchmark was running alongside, load average 18 to 24 — so the tok/s
column is a floor, not the number; acceptance does not depend on load.

| block (`n_max`) | drafted | accepted | per-prompt median (min–max) | decode tok/s, median |
|---|---|---|---|---|
| 5 | 5181 | 2128 (41.1 %) | 45 % (13–87) | 13.4 |
| 3 | 3590 | 1968 (54.8 %) | 61 % (20–88) | 18.9 |

Two things change. First, the verdict: 18.9 tok/s under load 24 is above the
14 tok/s the same binary decodes without a draft on a quiet box, so the
draft pays, and the morning's "below break-even" was the product of three
prompts and a five-token block. Second, the block: positions four and five of
a five-token block are accepted rarely enough that they cost more
verification than they return; a three-token block takes fourteen points
more acceptance and five and a half tok/s. The per-prompt spread is the other
thing the three-prompt table could not show — 13 % on a prose continuation,
87 % on a SQL query — and it is the reason no three-prompt sample of this
draft agrees with another.

The `causal=false` copy of the draft measured identical to the original on
every prompt, to the decimal. That is not the hypothesis failing; it is the
key being ignored — ik reads `attention.causal` only for the `dflash2`
architecture, and this draft is `dflash`. The two arms are a control, and the
control says the switch was not wired. A one-line patch in the ik tree reads
the key for `dflash` drafts too; the run with that binary is the actual test.

The third and last run of that gate also produced a measurement of the
measurer: the gate script was edited while it was running, bash read the
new line, and the run died on an unbound variable between the last arm and
the serving restart. The serving restart was done by hand. The script is in
`tools/dspark/` as it ran, with the fix.

### The mask, read and then measured

The question the copy could not answer was then answered twice, first by
reading and then by running. Reading first, because most of it does not
need a machine. The reference draft's index function
(`get_dspark_topk_idxs`) hands every position of a proposal block the same
row: the ring of the last 128 committed positions plus all five block slots,
and the sparse-attention kernel masks nothing but a `-1` index. There is no
causal mask anywhere in the draft's attention. ik's mask builder in
`llama-dflash.cpp` did two things differently: it let block position *j* see
only block positions up to *j*, and it slid the 128-key window with the query
row, so row *j* saw 127 − *j* window keys where the reference sees 128 for
every row. Both are real deviations, and both are a few lines.

The first attempt at the fix — the `attention.causal` key — was the wrong
lever, and reading found that too. The flag it flips is `hparams.causal_attn`,
and in ik that flag also gates the KV-cache update ("non-causal masks do not
use the KV cache"), the batch-size clamp, defragmentation, and the embedding-
model input path. A run with that binary would have measured the mask and
four side effects together. The patch that went in instead adds a
draft-local flag, set automatically for V4.1 drafts, and touches only the two
mask lines: whole block visible, window anchored at the newest committed
position. Other DFlash drafts keep the causal, sliding mask. It is commit
`515a94a3` in the ik tree.

The same reading pass went through everything else the draft does and
compared it line by line with the reference: rope (plain, base theta, no
YaRN — the reference asserts the uncompressed path), the capture point
(input of layers 37–39, mean over the four hyper-connection streams; ik
captures `l_out` of 36–38 after decrementing the one-based ids, which is the
same tensor), the block geometry (the sampled token at position +1, noise
tokens after it), the Markov head (bias from the previous drafted token,
chained through the argmax), the shared head and its norm, the
hyper-connection lag order, the q and kv projections and their norms, the
inverse rope on the attention output, the sink, the softmax scale. All of it
matches. The mask was the only deviation in the code.

Then the run, same twenty prompts, same binary otherwise:

| block (`n_max`) | causal mask (before) | reference mask (after) | prompts up / down / same |
|---|---|---|---|
| 5 | 41.1 % (2128 / 5181) | 41.6 % (2139 / 5147) | 6 / 7 / 7 |
| 3, first 11 prompts | 59.1 % (974 / 1649) | 62.8 % (998 / 1588) | 5 / 3 / 3 |

The numbers moved, so the patch is live — the earlier control copy had
not moved them at all — and they moved by less than the per-prompt spread.
Half a point at a five-token block, under four at a three-token block on the
eleven prompts the run completed before one request failed with a 500 (the
harness stopped the arm instead of skipping the prompt; fixed in the
script). The mask was a real mismatch and it was not the cause. The patch
stays because it matches the reference, not because it pays.

What remains is not in the code, and the next two runs found some of it.
The draft has no embedding and no head of its own; it borrows the target's,
and in this target those are `token_embd` at Q3_K and `output` at Q6_K where
the draft was trained against bf16 copies. The uploader's Q8_0 set keeps
both in bf16, so two variants of the target were built by grafting those two
tensors into shard 1 (`tools/dspark/graft-gguf-tensors.py`; the other eight
shards are hard links, the whole thing costs 2 GB of disk): one with the bf16
embedding, one with embedding and head. Same twenty prompts, same patched
binary, all twenty completed in both:

| target shard 1 | `n_max` 5 | per-prompt median (min–max) | `n_max` 3 | per-prompt median (min–max) |
|---|---|---|---|---|
| upload (Q3_K embedding, Q6_K head), causal mask | 41.1 % | 45 % (13–87) | 54.8 % | 61 % (20–88) |
| upload, reference mask | 41.6 % | 50 % (11–78) | 62.8 %* | 64 % (25–85) |
| bf16 embedding | **45.5 %** | 53 % (22–81) | **60.1 %** | 63 % (30–86) |
| bf16 embedding and head | 46.2 % | 52 % (20–80) | 59.9 % | 65 % (24–84) |

\* eleven prompts, the run that stopped on a 500; the same eleven measured
59.1 % with the causal mask.

The embedding is the one that moves. Four points at a five-token block over
the same binary with the upload's shard, and the floor of the per-prompt
spread rises from 11 % to 22 % — the prompts the draft did worst on are the
ones the 3-bit embedding was hurting most. The head on top of it changes
nothing: 0.7 points one way at one block size, 0.2 the other way at the
other, and prompt by prompt six up, six down, eight unchanged. At the
three-token block the two changes cannot be cleanly separated, because the
mask-only run did not finish; what the twenty prompts say is 54.8 % with the
upload's shard and 60.1 % with the bf16 embedding, mask included in the
second. The tok/s columns of these runs are again floors, load 19–28.

So the borrowed embedding was a real part of the gap and the borrowed head
was not. For the machine, the recipe is one grafted shard: keep `token_embd`
in bf16 when a DSpark draft will run against the target. The cost is
1.3 GB of RAM at load. For the uploaders, the same sentence is the
recommendation. Two noise sources are left and neither is grafted away: the
target's hidden features come from a Q3_K body, ~~and the draft's own experts
are an MXFP4 re-quantization of fp8. The draft file is 8 GB, so a Q8_0
re-conversion of it is the cheap next test~~ — struck the same evening: the
checkpoint stores the draft's routed experts as packed 4-bit with one E8M0
scale per 32 weights (`mtp.0.ffn.experts.0.w1.weight` is `I8 [2304, 2560]`,
its scale `[2304, 160]`), which is MXFP4 already. The converter repacks
those bytes; it does not quantize them. Everything else in the draft is fp8
dequantized to Q8_0, and the shared embedding is now bf16. There is no
higher-precision draft to convert from, so the only untested source left is
the Q3_K target body, and a higher-precision target is not cheap on this
machine. For scale, the draft's publisher reports a mean
acceptance length of 3.57 tokens per step on its own benchmarks; a five-token
block at 45.5 % is 2.3 drafted tokens accepted per step plus the verified
one, which is in the same neighbourhood on a different workload.

### The levers, pulled, and the final table for ik

Everything above was measured with something else running. The last window of
the day put all of it on a quiet box in one sequence, with the serving process
stopped at the start and restarted at the end, and pulled the two levers the
profile had left: pinned memory and the choice of engine on the CPU side.

The pinned-memory lever looked like the largest candidate on paper. When `-ot`
sends tensors to the CPU, ik's loader (`src/llama-load-tensors.cpp`) drops
mmap so that those weights land in pinned host memory; with 411 GB on the CPU
side that allocation cannot succeed, and the documented escape,
`GGML_CUDA_NO_PINNED=1`, also makes `ggml_cuda_host_malloc` return null for
every staging buffer, so every host-to-device copy in the graph goes through
pageable memory. A four-line patch adds `GGML_CUDA_NO_PINNED_WEIGHTS`: the
weights stay mmapped and unpinned, the staging buffers stay pinned. Measured
on the same three prompts, no draft, bf16-embedding target: **13.63 tok/s
pageable, 13.60 with pinned staging.** Two loads of the identical no-draft
configuration an hour apart gave 13.63 and 14.13, so the load-to-load band is
about 4 %, and the verdict is that pinned staging is inside it on this graph.
On a small hybrid model it is not: DeepSeek-V2-Lite Q3_K_M with its experts on
the CPU (`llama-bench`, tg128, three repeats) decodes 60.1 tok/s with
everything pageable, 66.0 with pinned staging, 65.1 with everything pinned
the way ik does by default — and mainline, same file, same placement, 68.9.
So the escape hatch does cost 10 % where the weights are small enough to pin,
which is what the patch is for; it is committed on the fork as 3ded8071 with
the V4.1 number in its message, and the V4.1 candidate is closed.

The thread count was the other candidate the profile pointed at (43 % of
samples in the OpenMP barrier, 32 threads on 32 cores with the CUDA driver
and the HTTP thread competing). Same no-draft server at `-t 30`: 14.27 /
13.36 / 13.21 tok/s on the three prompts; at `-t 28`: 13.20 / 13.26 / 13.02;
at `-t 32`: 13.63 / 13.10 / 13.64. All inside the band. Closed.

The engine lever on the CPU side is the small-model kernel bench, run by a
delegate on the same box ([report and every command](../docs/kernel-bench-2026-09-13.md)): on a dense Qwen2.5-7B Q3_K_M at 32 threads ik
decodes 32.0 tok/s against mainline's 30.4 and prefills at 217 against 104;
on DeepSeek-V2-Lite Q3_K_M (a deepseek2 MoE) 73.5 against 66.2 and 447
against 201. `-rtr` and `-fmoe 0` are within 5 % of the defaults on both. So
on CPU matmul ik is ahead, not behind, and the V4.1 gap of 20 % decode and
25 % prefill against mainline is not a generic kernel deficit. That bench also
cost a fifth collision: its own gate was the load average again, and its last
round ran through this window's CPU-only V4.1 measurement, so both were
discarded and the CPU-only comparison was rerun alone. The method note is
[`docs/quiet-machine.md`](../docs/quiet-machine.md).

That rerun is the number that locates the loss. V4.1 itself, the same
bf16-embedding file, `-ngl 0` and no GPU visible, `llama-bench` tg64 with
two repeats, nothing else on the box (IO pressure 0.08 at the start, no
other `llama-*` process): **ik decodes 9.80 tok/s, mainline 7.98.** The
prefill numbers (18.9 ± 10.7 and 16.0 ± 4.1) are too noisy at two repeats to
rank. So on this very graph, all on the CPU, ik is 23 % ahead — and on the
production placement, with six layers of experts and all the attention on
the GPUs, it is 20 % behind. The whole gap, and then some, is in the hybrid
path: what ik does between the CPU experts and the GPU — the host-to-device
traffic per token, the split of the graph, the scheduler — and not in the
matmul. The small-model hybrid bench above says the same thing at smaller
scale (66 against 69 on V2-Lite). That is the performance-improvement point
this bench was run to find, and it is a different place to read than the
kernels this entry has been profiling.

The final table is the bf16-embedding target on the production placement,
ik `llama-server`, twenty greedy 200-token prompts per arm, one model load per
arm, nothing else launched on the box: the kernel bench's command log ends at
16:17 and its process sampler, which listed live `llama-*` pids every ten
seconds, shows only this window's server until it was stopped at 16:48; after
that the witness is the window script alone. The load average of 17–31 in
the rows is the server's own 32 threads on 32 cores. No draft, then the three-token and
five-token blocks:

| arm | drafted | accepted | decode tok/s, median (min–max) | prompts faster than no draft |
| --- | --- | --- | --- | --- |
| no draft | — | — | 14.13 (13.19–14.95) | — |
| DSpark, `n_max` 5 | 4808 | 2187 (45.5 %) | 14.33 (8.42–20.89) | 11 / 20 |
| DSpark, `n_max` 3 | 3321 | 1996 (60.1 %) | **19.86** (11.41–28.89) | 17 / 20 |

The acceptance rates reproduce the earlier contended runs to the decimal,
which is what acceptance should do. The outputs do not: at `n_max` 5 only 3
of the 20 greedy texts are identical to the no-draft text, and the other 17
diverge after 32 to 493 characters, so the drafted arms and the no-draft arm
are timed on continuations that share a prefix and then differ. Earlier in
the day two drafted arms were identical to the character, which fits: the
verification batch and single-token decode round differently, and greedy
argmax flips on a near-tie. The tok/s comparison stands (the texts are the
same length within a few percent); a claim that drafting leaves greedy output
unchanged would not. The rates are the new numbers: the
three-token block is **41 % faster than no draft** at the median, per-prompt
1.43× (0.81–1.95), and the five-token block is break-even. Against mainline
without a draft (17–18 tok/s, quiet box, above — same body, but the
engramQ8 shard 1 with the Q3_K embedding rather than the grafted one), the port
with its draft now decodes faster than mainline does without one, which is
the first time today that sentence has been true. The gap itself is still
there underneath: 14.1 against 17–18 without the draft.

### The same draft on mainline

The lever with the right size was never inside ik. Mainline merged DSpark in
August (PRs #25173 and #25784), and the V4.1 runtime branch this entry has
been measuring against carries that code; what it did not carry was the
V4.1 draft. Loading the draft under mainline fails on `output_hc_fn.weight`
not found: mainline's DSV4 draft graph is the V4 draft, with the learned
output head, the mixes consumed in the same sublayer, and the per-head q
normalization. The three differences are the same three the ik port needed
(commit 7b79b229 there), and mainline's own V4.1 body graph
(`src/models/deepseek41.cpp`) already implements them for the target, so the
port is a transcription: a `dflash_dsv41` flag set when the file has no
`output_hc_base.weight`, the three head tensors optional under it, the
draft loop computing each sublayer's mix for the next one from a one-hot
start and collapsing with the last FFN mix, and the per-head `rms_norm` on
q skipped. Three files, 52 lines added, 9 removed, on top of upstream master
and two open speculative PRs (#27569, #26575) merged without conflict.

It loads and drafts. Same target file, same placement, same twenty prompts,
mainline `llama-server` with `--lazy-mode auto` as in every mainline number
above:

| arm | drafted | accepted | decode tok/s, median (min–max) |
| --- | --- | --- | --- |
| no draft | — | — | 17.70 (9.41–18.09) |
| DSpark block 5, first pass after load | 5022 | 2192 (43.6 %) | 18.29 (9.05–26.65) |
| DSpark block 5, second pass, same server | 5022 | 2192 (43.6 %) | **22.48** (11.09–32.89) |

Two things to read carefully. The acceptance is 43.6 % against ik's 45.5 %
on the same block, close enough that the port is doing the same thing and
far enough that the two verifications are not bit-identical. And the two
passes have identical draft counts because mainline ignores the request's
`speculative.n_max`: the server schema has that field under `#if 0` with a
TODO ("we disable speculative parameter adjustments for now",
`tools/server/server-schema.cpp`), so the sweep's "n_max 3" pass was a
second block-5 pass — and it was 23 % faster than the first, with the same
drafts. The likeliest reason is `--lazy-mode auto` still paging experts in
through twenty prompts after a fresh load, which the no-draft pass also
showed in its first row; that attribution is a candidate, not measured. The
shape itself is measured twice (below): the first pass after a load is
slower, the second is not beaten by a third. The second-pass number is the
one to compare: **22.5 tok/s at block 5 on
mainline against 14.3 on ik**, the same draft, and mainline's no-draft
17.7 against ik's 14.1. The block-3 run, with the size set on the server
command line since the request field is dead, is the last number of the day:

| arm | drafted | accepted | decode tok/s, median (min–max) | prompts over 25 |
| --- | --- | --- | --- | --- |
| DSpark block 3, first pass after load | 3321 | 1963 (59.1 %) | 20.27 (12.98–25.93) | 3 / 20 |
| DSpark block 3, second pass, same server | 3321 | 1963 (59.1 %) | **22.78** (15.33–29.74) | 8 / 20 |

The serving port was then restarted with this build, target and draft at
block 3, and the same twenty prompts ran twice more against it. The first
pass after that load had two chat requests of mine overlapping prompts 4 and
5; on prompts 6 to 20 it matches the first pass after the earlier load to
within 1 % (median ratio 1.00). The second pass after that load:

| pass | decode tok/s, median (min–max) | against the second pass above, per prompt |
| --- | --- | --- |
| first after the 18:40 load | 19.58 (13.14–25.53) | 0.88 |
| second after the 18:40 load | **22.69** (15.29–29.59) | 0.996 |

So 22.7–22.8 is the plateau, not a floor, and it reproduces across two
loads.

So the block size that mattered so much on ik (14.3 against 19.9) does not
matter on mainline (22.5 against 22.8): mainline's verification is cheap
enough that the extra two drafted tokens cost what they return. The
acceptance rates match ik's to within a point and a half on both blocks,
which is the port working. The machine's number for DeepSeek-V4.1-Flash
with a draft, on a quiet box, warmed, is **22.8 tok/s median, 29.7 best**,
29 % over mainline without the draft, ~~61 % over ik with it~~ — corrected within the hour: 61 % over ik *without* a draft (14.1) and 15 % over ik with its own block-3 draft (19.9). The 25 the
day was aiming at is the median of eight prompts out of twenty, not of the
set; what stands between 22.8 and 25 is the mainline no-draft rate itself,
which the hybrid-path finding above says is where the next work is. The
engine choice follows the measurement: the serving port moves to the
mainline build with the port and block 3.

## Costs and what is not claimed

Every test costs a four-minute model load: 256 GB mapped from a file that
is already in page cache, because ik's loader touches every tensor. This
entry is ten builds and about fifteen of those loads, and the loads are most
of its wall clock.

The GPU path, later the same day: with `GGML_CUDA_NO_PINNED=1` (without
it, the `-ot` overrides turn the 303 GB of CPU-resident experts into a
pinned allocation and the load fails), `-ngl 99` and the production
placement — layers 0–3 experts on the first GPU, 4–5 on the second, the
rest on the CPU — the same four-chunk perplexity is **2.2270 ± 0.0625**
against 2.2258 ± 0.0622 at `-ngl 0`, running estimates 1.7320 / 1.7486 /
1.8248 / 2.2270, at 39 s per chunk instead of 87. So the CUDA path
produces the same numbers as the CPU path; `ggml_fill` for the one-hot mix
ran where the scheduler placed it and did not need a CUDA kernel for this
graph. GPU memory in use was 28.8 GB and 15.4 GB.

One throughput number exists now, and it is labelled: ik's `llama-server`
on the same placement, three 200-token greedy completions on a spare port,
**14.0 / 14.3 / 14.1 tok/s**, with a 100 GB repack writing on the model
drive at the same time (load average 28). Mainline measured 17–19 on the
same file earlier in the day under a comparable load.

This entry first explained that gap by saying ~~ik's speed features were all
off~~. That was wrong, and it was wrong in the direction that flattered the
port. The server's own init line for the same run reads `fused_moe = 1` and
`flash_attn = 1`: both are on by default in ik and neither needs a flag.
`-mla` does not apply at all — `is_mla_model()` in `src/llama-model.h:656`
covers DEEPSEEK2, GLM_DSA, MISTRAL4 and BAILINGMOE3 and not the dsv4 family,
because V4.1 carries its own compressed-KV streams instead. What was
genuinely off is `-ser`, which buys speed by dropping experts, and `-rtr`,
which repacks tensors at load and gives up mmap; neither is free, and `-rtr`
against a 347 GB file with two never-resident tables is its own experiment.

So the gap was measured with ik's default accelerations already on, and the
one remaining excuse was the contended machine rather than the flags. The
comparison that closes it ran at midday on a quiet box: no other perplexity,
no repack, both GPUs and both ports empty before each engine started, the
same engramQ8 file, the same placement, three 200-token greedy completions
each, prefill and decode from the server's own timings.

| prompt | mainline prefill | mainline decode | ik prefill | ik decode |
| --- | --- | --- | --- | --- |
| write-ahead log | 21.7 | 12.10 | 16.3 | 13.80 |
| swapped-out page | 30.7 | 17.80 | 23.1 | 14.06 |
| float addition | 31.0 | 17.30 | 23.1 | 14.18 |

Mainline's first row is `--lazy-mode auto` warming up — the morning run on
the same script ramped 5.4 / 9.5 / 11.9 the same way — so its steady
number is 17–18 tok/s. ik's is 14, and it is 14 whether the machine is
loaded (14.0 / 14.3 / 14.1 at load 28 this morning) or quiet (load 4). The
contention excuse is gone: the port decodes about 20 % slower than
mainline on this graph, and prefills about 25 % slower, with `fused_moe`
and `flash_attn` on. Where the 20 % goes is not measured here; the
candidates are the dsv4 graph path that ik's fused kernels were not written
for, the reader layers' top-k reuse, and `-rtr`, which was not tried.

Where the 20 % is not, measured an hour later in a second window with
serving stopped: fused MoE is not it (`-no-fmoe` decodes 13.2 / 13.8 / 13.6
against the default's 13.0 / 13.5 / 13.4), and the profile is not it
either. Twelve seconds of `perf record` on each server mid-decode give the
same picture to within a point: 29 % in the Q3_K dot product, 18–19 % in
the Q4_K one, 43 % in OpenMP barrier spin, 32 threads above 5 % on both.
ik's kernels are its own (`mul_mat_qY_K_q8_K_T<DequantizerQ3K>`), mainline's
are `ggml_vec_dot_q3_K_q8_K`, and they spend the same share of time — so
the port is doing the same work at a lower rate, which a flat profile
cannot explain and a per-kernel benchmark on a small dense Q3_K file could.
`-rtr` was not tried and cannot be on this box: it gives up mmap, and the
engramQ8 file is 472 GB against 251 GB of RAM. In that window mainline
measured 15.3 / 15.6 / 16.0 and 16.6 on a 400-token run, below the 17.8 of
the first A/B, with the load average still at 20 from the previous arm; the
ik numbers above were taken first, at load 10.

The measurement script itself failed twice before it produced this table,
and the second failure is worth one sentence: it waited for the server's
readiness line with a pattern written from memory (`server is listening`),
and neither engine prints that — mainline says `listening on http://`, ik
says `HTTP server listening` — so it declared both halves "never became
ready" fifteen minutes into a healthy load. The ik numbers above were
taken by hand from the server the script was about to kill; the mainline
half was rerun with the pattern fixed. The script is in
`tools/engine-ab/` with the fix.

Not claimed for the mainline draft port: that a V4 draft still loads
through it (the head tensors only become optional when `output_hc_base.weight`
is absent, so it should, but no V4 draft was run), and that its acceptance
matches the reference implementation — the evidence is that it matches ik's
port within a point and a half on both block sizes, and ik's port was the one
audited against `inference/model.py`. The build also carries two unmerged
upstream PRs (#27569, #26575), so the serving numbers are for that tree, not
for master.

Not claimed: a batch of one against the oracle,
session save and restore of the compressed streams (written as empty with a
TODO), the MTP graph (asserted off), `-rtr` and the prefetch exemption for
the engram table, and ~~any speed~~ ~~any speed beyond the one quiet-box
A/B above — no cause for the 20 %, no `-rtr`, no draft~~ — the final table
above now carries the draft on a quiet box; still not claimed are a cause for
the 20 % (pinned memory and the CPU kernels are both excluded now) and `-rtr`. The reader layers reuse the index source's
top-k rather than attending densely as mainline does; the four-chunk
perplexity does not distinguish the two, and a longer context might.

The cache-size log line also lied for two builds: it summed the per-layer
tensor vector after aliasing, so each source buffer was counted once per
reader — 72 MiB reported for 6.28 MiB allocated. Counted by unique pointer
now.

### Where the token's time goes, and a VRAM re-balance: 24.8 tok/s

The question after the port was whether anything else in ik was worth
carrying over. Read side by side, the answer is no: the one ik advantage that
survives into the hybrid path is the CPU dot-product kernel, worth 5–11 % of
the CPU share on the small-model bench above, and mainline already has what
the rest of ik's V4 path fuses — the hyper-connection pre/comb/post kernels
(`fused_dsv4_hc_*`, on by default, CUDA-backed), CUDA graphs per split, one
scheduler copy when `-ot` is in use, and a `mul_mat_id` that splits each
expert across all threads with no barrier between experts. ik's `-thp` never
ran here either: it needs a hugetlbfs pool, and this machine has none.

What the code did give was the accounting. From the GGUF headers: 40 MoE
layers, 384 experts, 6 routed per token, an expert is 16.85 MB (up and gate
Q3_K at 5.07 MB each, down Q4_K/Q5_K at 6.71 MB). With six layers on the cards
a token reads 3.44 GB from system RAM, and a three-token draft verified as a
batch of four touches at most 23.4 distinct experts a layer:

| path | bytes per step | at 115.8 GB/s (measured STREAM) | measured |
|---|---:|---:|---:|
| no draft, one token | 3.44 GB | 29.7 ms | 56.5 ms |
| block 3, batch of four | 13.4 GB | 116 ms | ~127 ms |

The served path is within about 10 % of the memory wall. Fixed overheads
(kernel count, graph launch) therefore cannot move the served number much,
and a four-token block would read 23 % more per step for fewer than 23 % more
accepted tokens, so it was not tried. What is left is bytes per step: fewer
expert layers on the CPU, or smaller experts.

Two restarts failed on the way. `--load-mode none` with transparent huge
pages set to `always` was meant to test the loader's own warning ("tensor
overrides to CPU are used with mmap enabled — consider using --load-mode
none"): AnonHugePages never rose above 150 MB during the nine-minute load, and
the server died allocating a 515 MiB compute buffer on the 24 GB card, which
has 600 MB of slack in the served configuration. Not understood, reverted.
`-devd CUDA0` — the draft on one card, to stop its two-card pipeline — aborts
in `ggml_backend_sched_backend_id_from_cur`: the DSpark draft reads the
target's hidden states, some of which live on CUDA1.

The verbose logs of those failures showed two things the quiet logs had
hidden. Every mainline number above ran with the fused hyper-connection
*pre* kernel disabled on all forty layers: layer 28 is the first layer on the
second card, its `pre` mix comes from layer 27 on the first, the scheduler
places the weightless fused node with its inputs, and the probe in
`resolve_fused_ops` read that placement as "missing support" and turned the
op off globally. The unfused ops land on the same card, so nothing was wrong
but the verdict; the fix asks the layer's device whether it supports the op
(`ggml_backend_dev_supports_op`) before believing the placement — ten lines,
commit e42d711e5 on the merged worktree, and the log now reads "placed on CUDA0
by the scheduler, CUDA1 supports it, keeping it enabled". Second, the draft
context had no tensor overrides, so it ran with pipeline parallelism and four
copies of its compute buffers; a no-op `-otd` turns that off.

The third restart put the three changes together with a smaller micro-batch:
`-ub 512` (compute buffers 4297 MiB on CUDA0 and 2447 MiB on CUDA1, measured;
the header of `configs/v41-serve.sh` records what it costs a 4288-token prompt),
the draft's `-otd`, the resolver fix, and the freed VRAM spent on experts —
blk 6 `down` and blk 7 `gate`/`up` on CUDA0, blk 6 `gate`/`up` on CUDA1, so
the CPU streams 32 layer-equivalents instead of 34, 5.9 % fewer bytes. Cards
after load: 46.8 of 49.1 GB and 20.9 of 24.6 GB. Same 20 prompts, greedy,
block 3, IO pressure 0.00 on every row of the second pass:

| pass | median tok/s | best | prompts ≥ 25 | per-prompt ratio to the 22.7 pass |
|---|---:|---:|---:|---:|
| 1 (first after load) | 21.8 | 28.0 | 4/20 | — |
| 2 | **24.75** | 31.5 | 10/20 | 1.070 (median) |

Seven percent on a load-to-load band of about four; the first-pass penalty
reproduced a third time (12 % again). The three changes share one restart, so
the split between them is not measured; by the accounting above the expert
move is the part that can carry most of it, and the fused-pre fix is below the
band on its own. The serving port now runs this configuration. Not claimed:
the long-prompt prefill cost of `-ub 512` on this build (the 214 against 343
tok/s figure in the script header is from an earlier build), and whether the
24 GB card's remaining 3.6 GB takes blk 7 `down` as well.

One more tensor group, since the 24 GB card had 3.6 GB left: blk 7 `down`
(2.58 GB) on CUDA1, the CPU down to 31 layer-equivalents, predicted +3 %.
Same protocol, IO pressure at most 0.69 on the second pass:

| pass | median tok/s | best | prompts ≥ 25 | per-prompt ratio to the 24.8 pass |
|---|---:|---:|---:|---:|
| 1 (first after load) | 20.6 | 27.5 | 2/20 | — |
| 2 | **25.6** | 31.8 | 11/20 | 1.011 (median), faster on 11/20 |

The median crossed 25, but the per-prompt ratio says the step is inside the
band: 1 % measured against 3 % predicted. It stays, because it costs nothing
except slack — the cards are now at 47.0 of 49.1 GB and 23.2 of 24.6 GB, and
the next tensor group does not fit. That closes the "more experts on the
cards" lever; what remains on bytes per step is the quantization of the
experts themselves.
