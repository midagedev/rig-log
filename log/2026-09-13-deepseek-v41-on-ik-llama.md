# DeepSeek-V4.1 runs on ik_llama.cpp: ten builds, two wrong graphs, one number that matched

**2026-09-13.** Yesterday's entry ran DeepSeek-V4.1-Flash on mainline
`llama.cpp` because ik_llama.cpp — the fork this machine otherwise serves
from, for `-ser`, `-rtr` and the low-bit quants — had no `deepseek41`. The
port is described in [the porting note](../docs/porting-v41-to-ik-llama.md);
this entry is the record of making it produce a correct number, measured on
the machine in [the README](../README.md), CPU-only, on this date.

Everything here was measured with mainline still serving on its port and a
209 GB download running on the model drive. That is fine for a correctness
gate — perplexity does not care who else is on the CPU — and it is why no
throughput figure in this entry should be read as a throughput figure.

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

That is data, not a working draft. Three things stand between the file
and a tok/s number. ik's DSpark loader requires `output_hc_{base,fn,scale}`
(`llama-load-tensors.cpp:2814-2817`), which V4.1 does not have — the
output hyper-connection head is exactly what the lag removed. The draft
graph (`build_dflash_dsv4`) is written to V4's rules and needs the same two
changes the body needed, the one-sublayer lag and the low-rank-only q norm;
a draft that gets them wrong drafts the wrong tokens and lowers throughput
instead of raising it. The body's GPU path is validated below, so the ik
baseline for a draft to be measured against now exists. In that order.

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

The measurement script itself failed twice before it produced this table,
and the second failure is worth one sentence: it waited for the server's
readiness line with a pattern written from memory (`server is listening`),
and neither engine prints that — mainline says `listening on http://`, ik
says `HTTP server listening` — so it declared both halves "never became
ready" fifteen minutes into a healthy load. The ik numbers above were
taken by hand from the server the script was about to kill; the mainline
half was rerun with the pattern fixed. The script is in
`tools/engine-ab/` with the fix.

Not claimed: a batch of one against the oracle,
session save and restore of the compressed streams (written as empty with a
TODO), the MTP graph (asserted off), `-rtr` and the prefetch exemption for
the engram table, and any speed. The reader layers reuse the index source's
top-k rather than attending densely as mainline does; the four-chunk
perplexity does not distinguish the two, and a longer context might.

The cache-size log line also lied for two builds: it summed the per-layer
tensor vector after aliasing, so each source buffer was counted once per
reader — 72 MiB reported for 6.28 MiB allocated. Counted by unique pointer
now.
