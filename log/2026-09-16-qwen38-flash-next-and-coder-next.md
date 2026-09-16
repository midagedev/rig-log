# Two Qwen models three weeks old: 51 tok/s from 125B, and the fast half of a pair

*2026-09-16, 08:15–09:00.* The question was what a current model does on this
box, and whether a fast model and a slow one can be served together. Two
downloads answer both. [Qwen3.8-Flash-Next](https://huggingface.co/Qwen/Qwen3.8-Flash-Next)
is 125B with 6B activated **plus a 51B n-gram embedding table** and a 4B MTP
head — the first model in this log whose headline parameter count is mostly a
lookup table, which is the same idea as DeepSeek V4.1's engram tensors and the
reason it was picked over the smaller
[Qwen3-Coder-Next](https://huggingface.co/Qwen/Qwen3-Coder-Next) (80B-A3B).
Both were fetched with [`tools/fetch-gguf.sh`](../tools/fetch-gguf.sh), which
needed a fix first: the Hugging Face tree API lists one directory at a time and
every sharded unsloth quant lives in a subfolder, so the size lookup failed on
all of them.

Engine: mainline `llama.cpp` at `930e2fa59`, which carries the `qwen4exp`
architecture. Placement is an argument to
[`tools/qwen38/qwen38-take.sh`](../tools/qwen38/qwen38-take.sh), never a
default, and every run records per-card VRAM by UUID.

## 51 tok/s from a 103.7 GiB file

The placement that loaded first try: the 26.8 GiB n-gram table to the host,
expert layers `blk 0-27` on the A6000, `blk 28-39` on the 3090, `blk 40-47` in
RAM. That is 47.7 GB on the 48 GB card and 20.9 GB on the 24 GB card, with
39.7 GiB left on the host.

| Qwen3.8-Flash-Next UD-Q4_K_XL, 434-token coding prompt, `-n 2048`, thinking off | decode | prefill | major faults a token |
|---|---:|---:|---:|
| first run, page cache cold for the table | 48.7 tok/s | 278 tok/s | 10.3 |
| after `cat`-ing the shards, run 1 | 49.2 | 300 | 8.9 |
| run 2 | **51.1** | **414** | **0** |

For comparison, DeepSeek V4.1 on the same box decodes 25.05 tok/s warm with a
speculative draft. This model is twice that rate with no draft at all, which is
what 6B activated against V4.1's larger active set buys.

> ~~at a similar file size.~~ **Struck 2026-09-16, later the same day**, while
> this comparison was being carried into the README. The two files are not a
> similar size and it is not close: `du --apparent-size` reads **110.1 GiB** for
> this model's directory against **444.2 GiB** for the served V4.1 (324 G for
> the plain Q3_K_M before the engram graft). Four times, not alike. The clause
> made the sentence claim more than the runs support — *same size, double the
> rate* is a much stronger statement than *a quarter of the size, double the
> rate*, and only the second one was measured. The rate comparison and the
> reason for it stand; the size equivalence was never measured and is withdrawn.

The n-gram table behaves exactly like the engram tables did (WKS-20): reading
its rows off NVMe costs about 5 % of decode, 48.7 against 51.1, and the cost is
paid in major faults rather than in bandwidth — 8.9 faults a token, which is
close to the sixteen rows a token the architecture reads. Getting it resident
is not automatic: the page cache held 244 GB and the table still faulted,
because the other models measured this morning were competing for the same
cache. The load mode is what makes residency a property of the configuration
rather than of what ran before it:

| same placement, same prompt, only `-lm` moves | decode | prefill | host residency | major faults a token | load |
|---|---:|---:|---|---:|---:|
| `-lm mmap+mlock` | **51.5 tok/s** | 424 tok/s | 39.7 GiB, all in RAM | 0 | 65 s |
| `-lm none` | 49.7 | 369 | 1.4 in RAM / 38.3 on disk | 4.0 | 15 s |

So the whole spread is 48.7 to 51.5 tok/s, under 6 %, and `mlock` buys the top
of it for fifty seconds of extra load time. That is the useful shape of the
answer: a 51B lookup table is cheap to serve off NVMe and cheaper to pin, which
is the opposite of what its parameter count suggests and the same conclusion the
engram work reached from the other direction.

One caveat the recorder printed and should not be believed yet: the Decode row
reads "≈ 1416 GB/s from RAM, 978 % of peak". The card takes everything placed
on the host as bytes read per token, and 26.8 GiB of that is a hash table read
sixteen rows at a time. The recorder's session has the report; the expert
layers in RAM are a real per-token read, the table is not.

## The fast half: Coder-Next at 133 tok/s

Qwen3-Coder-Next IQ4_XS is 39.7 GiB and fits whole on the A6000 with 32k of
context, so it needs no placement at all.

| Qwen3-Coder-Next IQ4_XS, one stream, A6000 | decode | prefill | TTFT |
|---|---:|---:|---:|
| 403-token coding prompt, `-n 2048` | 133 tok/s | 1013 tok/s | 444 ms |
| 246-token design prompt, `-n 4096` | 131 | 758 | 367 ms |

That is the pair the machine can actually serve: 131-133 tok/s from a card, and
51 tok/s from a 125B model across both cards and RAM. They cannot both hold
their current placements at once — the slow one is using 68 of 72 GB of VRAM —
so serving both means giving the 3090 to the fast model and taking twelve
expert layers off it, which the layer-cost measurements put at about 3 % of
decode a layer.

## What broke, and it is an open PR

The MTP draft does not load:

```
check_tensor_dims: tensor 'token_embd.weight' not found
```

unsloth ships draft-head-only GGUFs, and the `qwen4exp` loader on master
demands the trunk tensors and the PLE block unconditionally. This is exactly
what [ggml-org/llama.cpp#28097](https://github.com/ggml-org/llama.cpp/pull/28097)
("qwen4exp: support draft-head-only GGUFs (unsloth layout) + fix draft-load
regression") describes, and that PR is open. Its author reproduced it on a
pure-CPU box; this is the same failure on CUDA with two cards and the
`mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf` pack, which is worth adding to the
PR because a second platform is what an open patch needs.

## A negative result on the indexer nondeterminism

[Issue #28497](https://github.com/ggml-org/llama.cpp/issues/28497) reports that
greedy `qwen4exp` output is not reproducible on CUDA once the context exceeds
the QSA indexer's top-k, because `top-k.cu` calls
`cub::DeviceTopK::MaxPairs` with `determinism::not_guaranteed` over tied block
scores. The reporter saw it on 2× RTX 3090, the same `sm_86` as one of these
cards, on CUDA 13.3 with CCCL 3.x.

It did not reproduce here. Two greedy runs at 434 in / 2048 out — total context
2482, past the 2048-token indexer budget — produced byte-identical
completions, 8655 bytes each, on a build whose `top-k.cu` does contain the
`determinism::not_guaranteed` call, with CUDA 13.0. Two runs is weak evidence
and the issue's own reproducer is kernel-level and needs no model, so this is a
data point about the CUDA version, not a refutation.

*(The first attempt at this comparison extracted zero bytes from both tapes,
because a tape is gzipped, and reported "IDENTICAL" — a parser that read
nothing looking exactly like agreement. The check above fails loudly when
either side is empty. Same class of mistake as reading a throttle flag once,
found the same day.)*

## The clips

Both models recorded with [toktape](https://github.com/midagedev/toktape)
`0.2.3-2-g0f88bd3`; tapes sanitized into `assets/`.

| clip | what it shows |
|---|---|
| `qwen3-coder-next-iq4xs-133tps-1stream-37s.mp4` | the fast model writing a design document at 133 tok/s, 4096 tokens in 37 s |
| `qwen3.8-flash-next-q4kxl-51tps-mlock-48s.mp4` | the 125B model at 51.0 tok/s with the table pinned, 2048 tokens in 48 s |

Both were recorded three times before they were right, and the reason is worth
keeping: **the card stamps the toktape version that recorded the tape, not the
one that rendered it**, so a re-render on a newer build leaves the old version
on the card. The classification of a tensor is also fixed at record time — the
tape carries the per-device, per-class byte split, not the tensor names — so the
host-bandwidth error above could not be corrected by re-rendering either. On the
recorder's fixed build the pre-fix tape prints no bandwidth clause at all and a
caveat naming both numbers, which is the honest reading of a tape whose recorded
split is wrong.

The fix is confirmed against a prediction the recorder's session wrote before
seeing the new tape, which is the only kind of confirmation worth much here:

| | predicted | measured |
|---|---|---|
| `other` bytes a token | ~1.4 GB | 1.413 |
| `embeddings` | not counted, ~27.5 GB resident | not counted, 29.476 GB resident |
| CPU active a token | 0.26-0.28 GB | 0.256 |
| host figure | 13-14 GB/s, no refusal | 13.1 GB/s, exact |
| whole-model record | ~6.3 GB a token | 6.334 |

The one row that looks like a miss is not one: 26.8 GiB is 28.78 GB, and with the
0.675 GB main embedding matrix that is 29.46 — the prediction of 27.5 carried a
GiB figure into a GB sum without converting it. The behaviour predicted was
right and the arithmetic checking it was not, which is the more dangerous of the
two: had the measurement come back at 27.5 it would have been called a match.

Before the fix the same tape derived 1495 GB/s at 1033 % of a 145 GB/s bus,
because the 26.8 GiB table sat in `other` and was counted in full every token.
The decode rate is the same run three times over — 51.5, 50.7, 51.0 tok/s — so
nothing about the measurement moved; only what the card claimed about it.
