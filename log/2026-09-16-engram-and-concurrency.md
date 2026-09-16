# What engram costs when four streams want different rows

*2026-09-16, 09:10–10:00.* The engram queue had one question left in it. E2 in
[the experiment plan](../docs/v41-experiment-plan.md) was answered by WKS-20 —
the rows cost 6.8 % of decode on fresh text, 22.1 major faults a token — and
E4 carried a prediction nobody had tested:

> four streams at different positions need four different sets of engram rows,
> so major faults per token should stay roughly constant while tok/s rises. If
> they scale super-linearly instead, engram is a concurrency bottleneck and
> that is a new finding.

Four arms, one server restart each, on the served file at the seven-expert-layer
placement. Every arm got **prompts nothing on this box had used since boot** —
seven of them, on unrelated topics, so no arm could read rows another arm had
already pulled into the page cache. That is the whole design: with a shared
prompt the second arm measures the cache, not the drive.

## The prediction holds

| streams | aggregate | per stream | major faults a token | faults during decode |
|---:|---:|---:|---:|---:|
| 1 | 19.1 tok/s | 19.1 | 22.6 | 6 587 |
| 2 | 21.7 | 11.1 | 25.9 | 15 564 |
| 4 | 26.3 | 7.0 | **24.2** | 27 917 |
| 1, control | 18.8 | 18.8 | 56.6 | 17 440 |
| 4, control | 26.7 | 7.0 | 33.6 | 37 282 |

Faults a token are flat — 22.6, 25.9, 24.2, no trend — while the total faults
scale 1 : 2.4 : 4.2, which is linear in the stream count. Each token pays for
its own rows and the drive absorbs four times the random reads without the
per-token price rising. **Engram is not a concurrency bottleneck.** The
super-linear case, which would have been the interesting failure, did not
happen.

The size of the cost, from the drive's measured QD1 latency: 24 faults at
0.056 ms is 1.4 ms a token. At four streams a forward pass produces four tokens
in about 152 ms, so even if every fault serialised, engram's share is 3.6 % of
the pass. At one stream it is 1.3 ms of a 52 ms token, 2.4 %. A few percent at
every concurrency, and it does not grow.

## The control, because the arms warmed the cache as they went

The three arms ran in order and their load times fell 208 s, 171 s, 130 s: the
model's own weights were getting warmer in the page cache as the morning went
on, so each arm started better placed than the one before it and the 1.38× at
four streams was concurrency plus warming in unknown proportion. The control is
to run the single-stream arm **last**, on the warmest cache of the day, with a
prompt nothing had used:

| | load | decode |
|---|---:|---:|
| one stream, first, coldest | 208 s | 19.1 tok/s |
| one stream, last, warmest | 77 s | **18.8** |
| four streams, first | 130 s | 26.3 |
| four streams, last | 83 s | **26.7** |

The single-stream rate does not move when the cache is two and a half times
faster to load from — 19.1 against 18.8 — and the four-stream rate does not
either. So the gain is concurrency, about **1.4× at four streams**, and the
confound I built in did not produce it. It is below the 1.6× the previous model
reached, which is the next thing to explain and not explained here.

## The strongest number is an accident of the control

The two single-stream arms used different prompts, and their fault counts came
out 22.6 and 56.6 a token — two and a half times apart, on the same placement at
the same concurrency. Decode went 19.1 to 18.8, which is 1.6 %. The four-stream
pair repeats it: 24.2 and 33.6 faults a token, 26.3 and 26.7 tok/s.

So the fault count is nearly **decoupled** from the rate. Which prompt you send
changes how many engram rows are cold by a factor of two or more, and the
decode rate barely notices. That is a stronger statement than the E4 prediction
asked for: not only does engram fail to bottleneck concurrency, its fault count
is a poor predictor of anything at this scale. It also means WKS-20's 6.8 % is
an upper bound on what the rows cost, not a typical value — and that any future
claim resting on a fault count needs a rate beside it.

## Turning lazy mode off tries to put 195 GiB on a 48 GB card

The fourth arm was meant to be a simple control — does this branch's row-wise
path actually beat plain `mmap`? — and it failed before it loaded:

```
ggml_backend_cuda_buffer_type_alloc_buffer: allocating 232372.03 MiB on device 0:
  cudaMalloc failed: out of memory
```

232 GB on a 48 GB card. The reason is worth writing down, because it reframes
what `--lazy-mode` is. With lazy mode on, the engram tensors are handled
specially and stay on the file. With it off they are **ordinary layer tensors**,
and `-ngl 99` sends every layer tensor the `-ot` string does not claim to a GPU.
The serving placement names only `ffn_.*_exps` patterns and a catch-all
`exps=CPU`, neither of which matches `blk.1.engram_embd.weight`. So the two
tables — 97.3 GiB each at the Q8_0 graft, 195 GiB together — were bound for
CUDA0.

`--lazy-mode` is therefore not an optimisation on top of a working placement. It
is the thing that keeps engram off the cards at all, and any placement that
turns it off has to name `engram_embd` itself.

## The row-wise path against plain mmap

With `engram_embd=CPU` added to the placement, the arm runs:

| one stream | decode | major faults a token | host placement |
|---|---:|---:|---|
| `auto`, engram **not** named — the serving default | 19.1 tok/s | 22.6 | ~199 GiB |
| `auto`, engram named `=CPU` | 18.6 | 108.4 | 394.1 GiB (199.1 in RAM, 194.9 on disk) |
| `off`, engram named `=CPU` | 17.9 | 66.2 | 394.1 GiB (205.6 in RAM, 188.4 on disk) |
| `off`, engram not named | — | — | refuses to load: 232 GB asked of CUDA0 |

The interesting row is the second, not the third. Naming `engram_embd=CPU` makes
the table a *placed* host tensor, and the host placement jumps from 199 GiB to
394 GiB — the 195 GiB of engram arriving in the accounting. A 251 GB host cannot
hold 394 GiB, so it thrashes: 108 faults a token with lazy mode still on, 66
with it off. The serving default pays 22.6 for the same work because under
`auto` the table is **not placed at all**; it is read row-wise off the file and
never enters the budget.

That is what lazy mode buys, and it is not mainly speed. The whole rate spread
across every arm here is 17.9 to 19.1 tok/s, under 7 %. What it buys is that the
model fits: without it the tables are either on a card that cannot hold them or
in a host budget that cannot either.

The `off` arm's own numbers explain it: asking for the whole table resident
places 394 GiB on a 251 GB host, so the page cache holds half of it and thrashes
for the rest — 66.2 faults a token against the 22.6 the row-wise path pays for
the same work. Reading 110-byte rows on demand is not a compromise forced by
the drive; it is cheaper than mapping the table and hoping.

## Pinning the tables in RAM is arithmetic, not an experiment

WKS-20 left "RAM pinning is the follow-up", which is how the 09-14 entry read
before this one. It is not runnable on this machine and does not need a run to
close. The grafted engram tensors are 97.3 GiB each, 195 GiB for the pair, and
the host side of this placement already needs about 200 GB for the thirty-three
expert layers that are not on a card. 395 GB of demand against 251 GB of RAM.
The Qwen3.8-Flash-Next n-gram table measured the same day is 26.8 GiB and does
fit, which is why `-lm mmap+mlock` is a real arm there and cannot be one here.

## Method notes, both of them mine

**The aggregate rates needed a control I should have designed in.** Running the
arms in ascending concurrency meant ascending cache warmth, which biases exactly
the number the experiment is for. The control cleared it, but the right shape
was to interleave or to randomise the order from the start.

**One arm died mid-token.** `bash` reads a script incrementally rather than
loading it, so a long chain whose file is rewritten between arms can resume
inside a word: `run e5-lzm-auto-otcpu` was read as `run e5-l` and then
`zm-auto-otcpu: command not found`. The local and remote copies hash
identically, so nothing was corrupted — the fix is not to reuse a chain script's
path across launches, and to check each arm ran rather than trusting the
chain's own completion line.

**And two sessions were driving this machine.** A second rig-log session was
working the same box; I found it by finding a chain script in the shared
directory that I had not written, holding the GPU lease. Nothing was damaged and
the reason is the lease: my arm asked for it, found it held, refused and exited.
But we had both queued the same matched lazy-mode arm, and we had both written
to the same log path, so that file interleaved two chains. The second row of the
lazy-mode table and the 09:52 re-records are that session's runs, on the same
runners and the same box. Its reasoning about the clips was better than mine and
is the reason both were re-recorded rather than re-rendered: **the card stamps
the toktape version that recorded the tape**, so re-rendering an old tape leaves
the old version on the card no matter which build renders it.
