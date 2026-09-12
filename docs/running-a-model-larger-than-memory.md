# What to run a 510 GB model on, and what is worth building

**2026-09-12.** DeepSeek-V4.1-Flash was published on 2026-09-10. It is 510 GB in
its original fp8, against 72 GB of VRAM and 251 GB of system RAM on this
machine. This is the reasoning that went into deciding what to run it on,
recorded while the decision was still open rather than after it worked. The
measurements here were taken on this machine on this date; anything that is
arithmetic rather than measurement says so.

## Start with a misreading, because it was instructive

The goal was stated as offloading "the ngram" of this model to the new NVMe.
The first reading was n-gram speculative decoding — this fork has
`--spec-type ngram-cache`, `ngram-map-k`, `suffix` and a `--lookup-cache-static`
file, so the words fit. That reading was wrong, and reading the source is what
killed it: `common_ngram_cache_load` reads its file into an `unordered_map`,
`ngram-map` works only from the current context's token history, and the suffix
corpus becomes a tree in RAM. None of them offload anything. A speculative
n-gram cache is also a few hundred megabytes, which nobody would describe as
needing a 4 TB drive.

The word meant **Engram**, DeepSeek's conditional-memory module. The plain
reading was the right one: a component of the model, not a decoding trick. Worth
recording that the community uses the same shorthand — a comment on
ikawrakow/ik_llama.cpp#2431 on 2026-09-11 reads "And ngram, as it turns out!"

## What Engram actually is, measured

From the GGUF metadata of the Q3_K_M conversion:

```
deepseek41.engram.layer_ids       [1, 14]
deepseek41.engram.head_count      8
deepseek41.engram.max_ngram_size  4
deepseek41.engram.key_length      256
deepseek41.engram.primes          48 values
```

Two of forty layers carry a table. Each table is `384,006,168 x 256`, so the two
together are 196.6 B parameters — roughly 40% of the model. The buckets per
layer are `(max_ngram_size - 1) * head_count = 24`, and the first 24 primes sum
to exactly 384,006,168, which is the stored row count. The table is 24 hash
regions of about 16 M rows each, laid end to end.

That fixes the access pattern, which is the whole question. Per token, per
engram layer, 24 rows are gathered; two layers carry one, so **48 rows a token**.

| | Q3_K_M, measured |
|---|---|
| one `engram_embd` | 42,240,678,480 bytes (3.44 bits a weight) |
| both | 84.5 GB |
| one row | 110 bytes |
| payload a token | 5.2 KiB |
| worst case in 4 KiB pages | 192 KiB |

The 48 lookups are independent, so they can be issued together. This drive was
measured at 152,519 IOPS at queue depth 32 and 15,836 at depth 1
([the benchmark entry](../log/2026-09-12-nvme-sustained-write.md)), which puts a
token's worth of engram between 0.3 ms and 2.7 ms depending on how the reads are
issued. Against a generation step of roughly 36 ms on the model this machine
serves today, that is between 1% and 7%.

**This is arithmetic, not a measurement.** It says the idea is not obviously
wrong. It does not say what it costs.

## The hardware decides the shortlist before preference does

Weights are 347 GB at Q3_K_M and VRAM is 72 GB. vLLM, SGLang and EXL3 all assume
the weights fit in VRAM. The published EXL3 conversion names its target in the
repository title — two RTX PRO 6000, 96 GB each. These are not candidates here,
whatever their merits.

What remains is engines built for the case where most of the model sits in host
RAM and a few percent of it is active per token: ik_llama.cpp, mainline
llama.cpp, and KTransformers.

The structural argument for ik_llama.cpp is that 6 of 384 experts run per token,
so most of the work is reading quantized weights out of system RAM, and that is
the path this fork has spent its life on. It currently serves DeepSeek-V4-Flash
on this machine at 27.7 tok/s in that configuration. The argument against
treating that as settled is that mainline has closed much of the gap — it now
has `--override-tensor`, `--n-cpu-moe`, and a `--lazy-mode` this fork has no
equivalent of.

**This will be measured rather than argued.** The reference runtime for V4.1 is
mainline-derived, so the first run on this machine produces mainline's number
with this model, and a later port would produce the fork's. Same machine, same
file, same prompt.

## Nothing is merged anywhere

Worth stating plainly, because it shapes everything downstream. As of today:

| | |
|---|---|
| llama.cpp #19654, Engram runtime | open, not merged |
| llama.cpp #28696, V4.1 conversion | open, draft, converter only |
| ik_llama.cpp #2438, V4.1 support | a feature request, no implementation |

The only runtime that loads this model is a branch on a contributor's fork,
which was still committing fixes today. In two days that branch renamed its
architecture, fixed a KV-prefix bug that shipped wrong keys into published
files, and repaired conversions twice. The published GGUFs are downstream of
that churn: the one being used here was checked and carries all nine
`deepseek41.engram.*` keys, so it is post-fix, but that had to be checked.

The reason no finished port exists is not that it is easy and nobody bothered.
It is that the model is two days old and the reference is still moving.

## Why there is no Rust engine to switch to

Asked, and worth writing down because the answer generalizes. There are several:
candle at 21.0 k stars, mistral.rs at 7.7 k, shimmy at 5.9 k, against
llama.cpp's 128.0 k. None of them can run this model, and candle's issue for
adding DeepSeek **V3** has been open since 2026-06-25 while its V4-Flash request
was closed as not planned.

The moat is not the host language. It is in two places, and a rewrite inherits
neither. The first is the kernels: the work is hand-written AVX-512 and CUDA,
and what makes this particular fork fast is one file of tuned CPU matmul. A
different host language calls the same kind of code. Memory safety is not the
binding constraint in a program whose normal mode is several threads reading one
mmap'd file. The second is the accumulated format and architecture surface —
every quantization type is defined by its reference implementation here, and
every architecture is a graph someone wrote. V4.1 is 948 lines in the reference,
written by someone who knew the codebase, and still being debugged two days
later. That cost recurs for every model, forever, and llama.cpp has more people
paying it.

The community's own answer to "this should be different" was a fork, not a
rewrite. ik_llama.cpp keeps the formats and the architectures and replaces the
kernels, at a sixth of candle's stars and with the ability to actually run
these models.

Rust did win a layer of this stack, just not this one. Tokenizers and serving
front-ends are Rust and are the standard. The boundary is clean: orchestration
and tooling above, kernels and formats below.

## So what is worth building here

The same boundary answers the question of whether to write something specialized
for this machine. Writing an inference engine means writing a quantized matmul
that beats the tuned one, or dequantizing to fp16 and turning 347 GB into 700.
And numerical correctness has no partial credit — a mis-scaled expert does not
crash, it produces fluent nonsense, so every step needs the reference running
beside it to diff against.

Above that line there are three things this machine wants that no general engine
will do well, because they depend on facts about one machine.

**A placement planner.** The tensor list, shapes and types are all in the GGUF,
and the VRAM, RAM and drive figures are measured. Which tensor goes on which
device is therefore a computable problem, and it is currently being done by hand
— badly. The first draft of the launch script for this model put twenty expert
layers on a 48 GB card, which is 130 GB of weights, because the per-layer size
was carried in someone's head instead of read off the file. Mainline's `--fit`
and this fork's `-ot` are the raw material; what is missing is something that
reads the file and the machine and emits the arrangement.

**Expert prefetch.** More speculative and more interesting. Six of 384 experts
run per layer per token, and the router output names them just before they are
needed. A layer of lookahead is a short window, but the drive reads 6.0 GB/s
sequentially. If it works, the 205 GB that must sit in RAM under the current
plan could shrink, and Q4_K_M at 445 GB comes into range. This is the one place
where knowing the hardware exactly is worth real throughput.

**VRAM arbitration.** Already needed and the least interesting: one service
holds both cards, so anything else starts by stopping it. A supervisor that owns
that is a day's work and gets used every day.

All three sit outside the engine and drive it as a child process. None of them
touch a kernel, so none of them can produce a wrong number — the worst failure
is a bad arrangement, which shows up as a slower run or a refusal to load.

The order matters: the planner comes first, because prefetch cannot be shown to
help until the arrangement it is being compared against is known to be good.

## Still unmeasured

Everything above the horizontal line of "the model has not been run yet." In
particular whether the engram tables actually stay off RAM, which is the premise
the budget rests on. The observation that settles it is resident set size at
load: if it comes in 84.5 GB under the file size, the tables are on the drive.
If it does not, `--lazy-mode` did not catch a 42 GB tensor and has to be forced.
