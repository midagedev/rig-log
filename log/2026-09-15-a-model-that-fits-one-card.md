# A model that fits one card: 132 tok/s, and the ceiling that does not move

**2026-09-15, 22:49.** Every number in this log for two weeks has been a
300-billion-parameter model with most of its experts in host RAM, decoding at
20 tok/s. This is the other end of the same machine: a model that fits whole on
one card, measured the same way, in a thirty-second window at the end of the
night.

## The file, and why this one

`unsloth/Qwen3.6-35B-A3B-GGUF`, UD-Q6_K, 27.3 GiB — 35 B parameters total but
the router picks 8 experts of 256 a layer, so about 3 B are read per token. That
ratio is the whole point: the weights that have to be read for one token fit in
a fraction of the card, and the rest of the model sits resident without costing
bandwidth. Q6_K rather than a smaller quant because the card has room for it and
this is the value question, not the compression question. ik_llama.cpp at
c10fbbcc (its `qwen35moe` arch), `-ngl 99 -fa on`, no `-ot` and no CPU tail,
`CUDA_VISIBLE_DEVICES=0` so the 24 GB card is not even in the picture. The 48 GB
card ends up 28.3 GiB full with 32k of context.

Fetched with [`tools/fetch-gguf.sh`](../tools/fetch-gguf.sh) in six minutes;
the same file over one connection was on course for seventeen.

| 22:49, `contended: no`, io avg10 0.9 | one stream | four streams (`-np 4`) |
|---|---:|---:|
| decode | **132 tok/s** | 37.5 tok/s each, **149 aggregate** |
| derived bandwidth | ≈ 392 GB/s, **51 %** of the card's 768 | — |
| TTFT | 146 ms | 2705 ms (176-token prompts) |
| tokens out | 132 | 1025 over four streams |
| VRAM | 28.3 / 48.0 GiB | 28.5 / 48.0 GiB |
| host RSS | 1.4 GiB | 2.1 GiB |
| GPU power | 252 W, throttled | 293 W, throttled |

Clips: [one stream](https://drive.google.com/file/d/1jLwDpwliowrSvA_OFgAHYaZ5P0U0ldVO/view?usp=drivesdk)
(7 s — the answer takes 1.1 s, which is the point) and
[four streams](https://drive.google.com/file/d/1n29oTEWqVAKzSOkseMdj_1BqJIw733AQ/view?usp=drivesdk)
(36 s). Recorded with [toktape](https://github.com/midagedev/toktape) v0.2.3;
tapes `assets/qwen36-35b-a3b-q6k-1stream.tape` and `-4stream.tape`.

## 132 tok/s is half of the card, which is about what the RAM path gets too

The single-stream figure lands at 392 GB/s of derived read against the A6000's
768 GB/s — **51 %**. The served 440 GiB model on the same box reaches 79.8
GB/s of a 147.7 GB/s host bus — **54 %** — and today's ExLlamaV3 arm was in the
same neighbourhood. Six times the tok/s, about the same fraction of the
available bandwidth: a decode step keeps roughly half of a memory system,
whether that memory is GDDR6 on a card or DDR4 behind eight channels. The
absolute number changes with the bus, the efficiency does not.

> ~~46 % of the card's 768 GB/s.~~ **Corrected the same night.** 392 against
> 768 is 51 %, not 46 %, and the 46 % was the recorder's, not mine to repeat:
> toktape derives the peak from its *predicted* placement, which reads the
> GGUF and the command line but not `CUDA_VISIBLE_DEVICES`, so it split the
> model across both cards and mixed the 3090's 936 GB/s into the denominator —
> (1.274×768 + 1.696×936) / 2.970 = 864 GB/s, and 392/864 = 46 %. The same
> tape carries the contradiction: `placement` predicts 13.1 GiB on GPU1 while
> `gpus_at_end` measures GPU1 at 1 MiB. Sent to the recorder, which confirmed
> it and is fixing it at the source: an estimated placement the measured GPU
> readings contradict stops producing a ceiling or a ratio at all — both print
> `?` with a caveat naming the device and the two figures — while the combined
> GB/s stays, because that one is active bytes × the measured rate and does not
> depend on the split. The honest denominator for a single-card run is that
> card.

## Four streams buy 13 %, and that closes the day's argument

Four concurrent streams decode 37.5 tok/s each against 132 solo, for 149
aggregate — **13 % more total throughput for four times the clients**. This is
the third engine and the second kind of memory to give the same answer today.
Two streams on ExLlamaV3 with experts in host RAM: per stream exactly half,
aggregate within 5 % of solo. The MTP draft at 97 % acceptance: +12 %. And now
four streams entirely inside a card: +13 %.

The reason is the same each time, and it is the property of a sparse model
rather than of a machine. A decode step reads the experts its token routes to.
Two tokens from two streams route independently, so the step reads close to
twice the rows and produces twice the tokens; tokens per byte barely moves, and
a bandwidth-bound step cannot go faster than its bytes. What batching buys on a
dense model — one weight read serving many tokens — is exactly what a
mixture-of-experts gives up. Four clients are still worth serving: each one
gets 37.5 tok/s, which is faster than reading, and the alternative is three of
them waiting.

One honest limit on the pair, and one that the next section closes. The A6000
reports `throttled: yes` at 252 W solo and 293 W at four streams, so some of
the gap to the card's peak could be the card protecting itself rather than the
memory path — that is what the power sweep below was for. And the 4-stream card's derived bandwidth line reads 111 GB/s because it
multiplies the *per-stream* rate by the model's active bytes — for concurrent
streams the honest figure is a range between that and the aggregate rate, since
the recorder cannot know how much the four tokens' expert sets overlapped.
Sent to the recorder as a finding rather than used as a number.

## "Slower than I expected" — three arms, and the wrong premise was mine

132 tok/s read as disappointing, which is the right reaction: this is a 3 B-active
model on a card with 768 GB/s, and half a memory system is not a satisfying
answer. Three arms in the twenty minutes that were left, all one stream, all the
same prompt, all on the quiet machine with the lease held.

### Fewer bytes per token: UD-Q4_K_XL

I predicted 175–190 tok/s if the run was bandwidth-bound, on the premise that
UD-Q4_K_XL reads about 35 % fewer bytes per token than UD-Q6_K. **The premise was
wrong**, and the tape said so before the take ran. The file is 24 % smaller; the
per-token read is 7.3 % smaller, because a token does not read the file. It reads
all of the attention, all of the output layer, and 8 experts of 256:

| per-token read, from the GGUF | UD-Q6_K | UD-Q4_K_XL |
|---|---:|---:|
| attention — every token | 1.092 GB | 1.092 GB |
| output — every token | 0.540 | 0.540 |
| other — every token | 0.287 | 0.287 |
| router + shared expert — every token | 0.218 | 0.218 |
| the 8 routed experts of 256 | 0.832 | 0.615 |
| **active bytes/token** | **2.970 GB** | **2.753 GB** |
| the whole file on disk | 27.3 GiB | 20.8 GiB |

The always-read tensors are byte-for-byte identical across the two quants —
2.138 GB of the read either way, which is 72 % of a Q6_K token and 78 % of a
Q4_K_XL one. That is what "UD" means: unsloth's dynamic quant spends its bits on
attention and output and takes them out of the routed experts — the right trade
for quality, and almost no trade for speed, because the routed experts are the
only part a smaller quant touches and they are a quarter of what a token reads.

Which makes the arm a sharper test than the one I proposed. Seven percent fewer
bytes:

| one stream, one card | UD-Q6_K | UD-Q4_K_XL |
|---|---:|---:|
| decode | 132 tok/s | **140 tok/s** |
| active bytes/token | 2.970 GB | 2.753 GB |
| derived bandwidth | 392 GB/s | 387 GB/s |

7.3 % fewer bytes bought 6.4 % more tokens, and the achieved bandwidth is the
same number twice. That is what bandwidth-bound looks like from the inside: not
"the smaller quant is faster" but "the rate is bytes divided by a constant", and
the constant is about 390 GB/s.

> ~~Summing the placement classes by hand gives 2.76 and 2.54 GB, a constant
> 0.21 GB below toktape's two numbers, so the derived GB/s may be ~8 % high.~~
> **Withdrawn within the hour, and the answer was on the card.** My hand sum
> scaled the whole `experts` class by 8/256, but that class holds the per-layer
> router and the shared expert as well, and those are read on every token
> whichever experts the router picks. 217.9 MB of them: (1 − 8/256) × 217.9 MB
> = 211,097,600 bytes, which is the constant gap to the byte in both tapes, and
> reconstructing the figure that way reproduces `active_bytes_per_token`
> exactly — 2,969,684,480 and 2,752,563,712, delta zero. `toktape card
> --explain` prints the split (`experts sparse 19.671 GB + dense 0.218 GB
> (router + shared expert, read in full)`); I derived a discrepancy instead of
> reading the line that resolves it. The derived GB/s is not 8 % high, and the
> per-token table above now carries the decomposition rather than my sum.

### It is not the power cap

`throttled: yes` sat in every card of the day, so the cap was the live suspect.
The A6000's board limit is settable from 100 to 300 W, so: one model, one prompt,
three caps, nothing else moved.

| A6000 board cap | drawn | core clock | decode | derived |
|---:|---:|---:|---:|---:|
| 300 W | 281 W | 1950 MHz | 141 tok/s | 387 GB/s |
| 200 W | 199 W | 1710 MHz | 133 tok/s | 367 GB/s |
| 150 W | 150 W | 1335 MHz | 120 tok/s | 331 GB/s |

Taking away 47 % of the power budget costs 15 % of the rate; taking away 32 % of
the core clock costs the same 15 %. Decode scales with neither, so the missing
half of the card is not the cap — at the top, the last 131 W of the 300 W budget
is worth 21 tok/s. Power is a minor contributor there (300 → 200 W is a real
6 %) and not the explanation. The cap was restored to 300 W, which is all the
sweep touched.

It also says something about the flag. `throttled: yes` appears in all three
rows — in the 150 W run where the cap is demonstrably binding and in the 300 W
run where this sweep proves it is not. A warning that fires in both cases
carries no information; sent to the recorder with these rows as the evidence,
suggesting draw-against-cap headroom instead of a boolean. Confirmed there and
being fixed the same way: `sw power cap` is set on any card boosting into its
own limit, so the card will print the draw against the sampled limit (`281 of
300 W`) and reserve the `throttled:` verdict for the bits that mean the device
was held below what its own settings allow — hardware slowdown, thermal, power
brake, sync boost — with the full mask kept in the tape so a surprising verdict
can be explained from the recording rather than from the box. One thing a single
sample still cannot say is whether the headroom lasted: the 150 W row sat exactly
on its limit for the window and the 300 W row had 19 W spare at the moment it was
read, and those must not render alike. Filed at the recorder as TTP-102 with
these two rows as its evidence — the samples are already in the tape, so it is a
reduction over the decode window rather than new instrumentation.

### It is not the expert gather either

The second suspect was the gather: a token's 8-of-256 routing reads 320 small
slabs across 40 layers, and scattered reads do not saturate a bus. The control is
a dense model on the same card, same engine, same prompt, batch 1 — where a
token reads its whole weight set contiguously.

| one stream, one card | Qwen3.6-35B-A3B UD-Q4_K_XL | Qwen2.5-7B dense Q3_K_M |
|---|---:|---:|
| active bytes/token | 2.753 GB | 3.568 GB |
| decode | 140 tok/s | 118 tok/s |
| derived bandwidth | 387 GB/s | 421 GB/s |
| board power at the sample | 281 W | 298 W |

Dense reaches 421 GB/s against the MoE's 387 — 9 % better, not 60 %. Whatever
holds this machine at half of 768 GB/s holds a contiguous dense read almost as
hard as a scattered expert read, so the gather is not the missing half either.

That leaves the question open rather than answered, and the entry should say so.
The control is also a different quantisation family (Q3_K against Q4_K/Q6_K), so
"the k-quant dequantisation path" and "this engine's batch-1 ceiling on this
card" are both still standing and this arm cannot separate them. The experiment
that would: the same weights at Q8_0 or fp16, where dequantisation is cheap or
absent, at a size that still fits one card. Named, not guessed — it is
[WKS-30](../docs/v41-experiment-plan.md), with these three rows as its measured
state and the bus probe as its second arm.

What is settled is the shape of the lever. The only way to decode faster here is
to read fewer bytes per token, and on this model 72–78 % of that read is the
dense core the quant deliberately keeps wide — so a smaller expert quant buys
6 %, and
the things that actually move it are a draft that gets more tokens per read
(MTP: +12 % today) or more clients per read (four streams: +13 %).

One row from the control is worth keeping for its own sake: **the 35 B
mixture-of-experts decodes faster than the dense 7 B.** 140 against 118, because
it reads 2.75 GB per token against 3.57. Five times the parameters, three
quarters of the read, twenty percent more tokens per second — the whole case for
sparse weights on one card, in one line.

Tapes for the three arms: `assets/qwen36-35b-a3b-q4kxl-1stream.tape`,
`-q4kxl-pl200.tape`, `-q4kxl-pl150.tape`, `assets/qwen25-7b-dense-1stream.tape`.

## What it costs

At 2026 street prices the A6000 is the expensive half of this machine, and this
model does not need it: 27.3 GiB of weights plus 32k of context fits inside 32
GB, so a single 5090 or a used 3090 pair would serve the same file. The
measurement that matters for that claim is not this one — it is the same file
on the 24 GB card with a smaller quant, which is the next window's work and is
[WKS-25](../docs/upstream-contributions.md)'s actual question.
