# Putting the engram tables back at Q8_0: 6 % of perplexity for 125 GB nobody loads

*2026-09-13. Model: DeepSeek-V4.1-Flash, the Q3_K_M upload from
`vcruz305/DeepSeek-V4.1-Flash-GGUF`, served by mainline llama.cpp with the
production flags in `configs/v41-serve.sh`. Scripts in
`tools/engram-repack/`.*

## Why

The Q3_K_M upload quantizes everything at Q3_K, including the two engram
tables: 384 M rows × 256 of n-gram memory in layers 1 and 14, 42 GB each at
Q3_K. Those tables are never resident (`log/2026-09-12-deepseek-v41-first-run.md`
measured them staying on the drive; a token touches a handful of rows), so
their precision costs disk and nothing else. The uploader's Q8_0 build of the
same model has the same tensors at Q8_0, and the converter writes engram from
the fp8 original as Q8_0 unconditionally, so those bytes are what a fresh
conversion would produce. The question was whether Q3_K had damaged them,
and the cheap way to find out was to graft the Q8_0 tensors into the Q3_K_M
shards and measure both files with the same commands.

## The repack

Only two of the nine shards carry engram tensors (02 has layer 1, 05 has
layer 14). For each, `repack.py` reads the shard's header, copies every KV
verbatim, copies every tensor byte-identical except the four engram tensors,
and takes those from the Q8_0 shards that hold them. The write streams in
1 GiB slices with `fadvise(DONTNEED)` so a 100 GB copy does not evict the
served model from the page cache. Output goes to `.tmp`, is verified (tensor
inventory, sha256 of each engram tensor against the Q8_0 source, sha256 of the
whole file), and only then renamed. The other seven shards are hard links to
the originals.

| | shard 02 | shard 05 |
|---|---|---|
| swapped | `blk.1.engram_{embd,wkv}` Q3_K→Q8_0, `blk.1.engram_{q,k}` Q3_K→BF16 | same for `blk.14` |
| size | 42.3 GB → 104.6 GB | 44.9 GB → 107.2 GB |
| write | 577 s | 665 s |
| verify (re-read + hash) | 1203 s | 1604 s |

Fetching the three Q8_0 shards that hold the engram tensors took 68 min for
219 GB at the 80 MB/s cap we run downloads at. The result directory is 472 GB,
of which 125 GB is new. Loaded with `-lv 4`, the tensor-type summary changes
by exactly eight entries (Q3_K 476→468, Q8_0 +4, BF16 40→44) and the count
stays 1046. Nothing else in the file differs; `test_roundtrip.py` checks the
streaming writer byte-for-byte against the gguf-py library path on a small
synthetic file.

## Perplexity

wikitext-2 test, `llama-perplexity -c 2048 --chunks 4 -b 2048 -ngl 0 -t 32`,
the same command for both files. The bracketed values are the tool's running
estimates after each chunk, not per-chunk numbers; four chunks is 8192
tokens, hence the wide ±.

| after chunk | engram Q3_K (upload) | engram Q8_0 (repack) |
|---|---|---|
| 1 | 1.7334 | 1.7271 |
| 2 | 1.7571 | 1.6684 |
| 3 | 1.8354 | 1.6858 |
| 4 (final) | **2.2438 ± 0.0631** | **2.1090 ± 0.0585** |

Six percent lower, and the intervals do not overlap. The computation is
deterministic and the two files differ in eight tensors, so this is what
those tensors cost at Q3_K.

### Which of the four tensors

Two more variants, each built by the same repack against the same sources
and measured with the same command, split the eight tensors into the big
table and everything else. Every variant was verified the same way: the
swapped tensor's bytes hashed against the Q8_0 source, and the tensors that
were supposed to stay put hashed against the original and logged as
untouched.

| variant | `engram_embd` | `engram_wkv` | `engram_q/k` | added | PPL | closes |
|---|---|---|---|---|---|---|
| the upload | Q3_K | Q3_K | Q3_K | — | 2.2438 ± 0.0631 | — |
| small only | Q3_K | Q8_0 | BF16 | 0.2 GB | 2.2171 ± 0.0626 | 0.0267 |
| wkv only | Q3_K | Q8_0 | Q3_K | 0.2 GB | 2.2183 ± 0.0626 | 0.0255 |
| table only | Q8_0 | Q3_K | Q3_K | 125 GB | 2.1391 ± 0.0591 | 0.1047 |
| the repack | Q8_0 | Q8_0 | BF16 | 125 GB | 2.1090 ± 0.0585 | 0.1348 |

The two halves are additive. They close 0.0267 and 0.1047 separately, 0.1314
together, against 0.1348 measured for both at once — a residual of 0.0034,
two and a half percent of the effect and far inside the error bars. Nothing
here interacts; each group of tensors costs what it costs.

What the split is really about is the price. The table carries roughly four
fifths of the loss and asks 125 GB for it. The small tensors carry the
remaining fifth and ask two hundred megabytes, which is about a hundred and
sixty times more perplexity recovered per byte. A user who does not want a
472 GB directory can still have the cheap fifth.

Two honest limits. The small variant moved `engram_wkv` and the two gate
vectors together, so it cannot say which of them carries that fifth; the
gate vectors are two 5120x4 tensors per layer and the projection is 67 MB,
which makes `wkv` the likely owner but not the measured one. And because the
V4.1 branch already exempts the gate vectors, a conversion done with today's
branch would start from a file that has part of this fixed — the upload
predates that commit. Separating `wkv` alone is one more variant and about
forty minutes, since without the table the shards are the original 42 GB
rather than 104 GB.

That variant has since run. With only `engram_wkv` moved to Q8_0 and the gate
vectors left at Q3_K, perplexity is 2.2183 ± 0.0626, against 2.2171 for the
small variant: it closes 0.0255 of the 0.0267. The gate vectors add 64 KB
between them and account for the remaining 0.0012, which is noise. The
projection owns the cheap fifth, and it is now measured rather than inferred.
Sizes are the shard-byte deltas: 99,532,800 bytes per swapped shard for the
wkv variant, 99,597,120 for the small one.

## Fact recall

Perplexity says the distribution got sharper; it does not say whether the
model knows more. Three probes, all greedy with thinking off
(`reasoning_effort: none`), each variant served in turn with the production
flags.

Two hand-written sets first — 24 well-known facts, then 29 harder ones
leaning on Korean literature and history. Both variants answered every
scored question correctly in both sets. Answer text differed on 1 and 7
questions respectively, all wording (a trailing period, "Kim So-wol" vs
"김소월", "5,730 years" vs "about 5,700 years"). Saturated: these sets cannot
see the difference, if there is one.

Then PopQA (Mallen et al. 2023), which exists for exactly this question:
14,267 Wikidata facts with the subject's monthly page views attached, so the
long tail is labelled. Sample of 400 with a fixed seed — 200 from the least
popular 2,000 (views 5–128) and 200 from around the median (656–1494) — scored
by exact match against the dataset's alias list.

| band | n | engram Q3_K | engram Q8_0 |
|---|---|---|---|
| views 5–128 | 200 | 31.0 % | 30.5 % |
| views 656–1494 | 200 | 38.5 % | 37.5 % |
| all | 400 | 34.7 % (139) | 34.0 % (136) |

Thirteen questions flipped: eight the Q3_K file got right and the Q8_0 file
wrong, five the other way. That is a coin toss, not a difference. The number
worth keeping is the other one: **the answer text differs on 88 of 400
questions (22 %)** while the score does not move. Sharper engram tables
change what the model says on a fifth of long-tail questions and do not
change how often it is right. Read together with the perplexity table: the
damage at Q3_K is to the probabilities, not to the facts the model can
retrieve with one short answer.

So the repack is worth keeping — 125 GB of disk that is never read into RAM
buys 6 % of perplexity — but it is not a fact-recall upgrade, and the claim
this entry supports is the narrower one. Where sharper probabilities should
show up as speed is speculative decoding, which verifies draft tokens
against the target's confidence; that measurement waits on the DSpark port
in ik_llama.cpp (`log/2026-09-13-deepseek-v41-on-ik-llama.md`).

## What the quantizer does today, and where upstream actually is

This section first read ~~mainline `src/llama-quant.cpp` already keeps
`engram_q.weight` and `engram_k.weight` unquantized~~. That was wrong about
which tree, and the mistake matters because it is the difference between
"already fixed upstream" and "nobody upstream has seen this yet".

Upstream `ggml-org/llama.cpp` has no engram in `llama-quant.cpp`, and no
DeepSeek-V4.1 at all. Its V4.1 support is an open draft pull request,
[#28696](https://github.com/ggml-org/llama.cpp/pull/28696), 443 added lines
that touch only `conversion/` and `gguf-py/` with no C++ in them. An earlier
engram pull request, #19654, was closed in February without merging.

What every entry here calls mainline is the llama.cpp *line* rather than the
ik fork, and concretely it is `vcruz305/llama.cpp`, the V4.1 branch written
by the same person who published the GGUF files this machine serves. The
gate-vector exemption is that branch's, committed 2026-09-11:

```c
// DeepSeek-V4.1 engram gate scales: one value per channel, applied with
// ggml_mul, which has no quantized path.
quantize &= name.find("engram_q.weight") == std::string::npos;
quantize &= name.find("engram_k.weight") == std::string::npos;
```

The upload still carries them at Q3_K, so it was built before that commit or
with another tool. No tree has a rule for `engram_embd.weight` or
`engram_wkv.weight`, which is why the table takes the body's type.

Given the table is never resident, a default of Q8_0 for `engram_embd` costs
the user disk and nothing else, and the perplexity table above is the
evidence. The recipient is therefore the branch author rather than a
maintainer of merged code, and the right moment is when the C++ half of V4.1
support goes up.

The attribution above is what makes it reportable: a claim about "the table"
had to show that it is the table, and now it does, along with the cheaper
half that a user without 125 GB can still take. The candidate is recorded in
[`docs/upstream-contributions.md`](../docs/upstream-contributions.md); it is
not filed, and filing is not this session's call.

The searches behind "nobody upstream has this", verbatim, so the absence is
checkable by someone else:

```
gh search issues --repo ggml-org/llama.cpp engram
gh search prs    --repo ggml-org/llama.cpp engram
gh search issues --repo ggml-org/llama.cpp "engram quantization"
gh search prs    --repo ggml-org/llama.cpp "llama-quant engram"
gh search code   --repo ggml-org/llama.cpp engram_embd
gh api graphql -f query='query{ search(query: "repo:ggml-org/llama.cpp engram
  quantization", type: DISCUSSION, first: 5){ discussionCount } }'
gh api repos/ggml-org/llama.cpp/contents/src/llama-quant.cpp | base64 -d | grep -i engram
```

The code search returned nothing, the discussion count was zero, the file
holds no `engram` at all, and the only two hits anywhere were the open draft
#28696 and the closed #19654.

## The thermal guard fired, twice

The PopQA run was the longest stretch of CPU decode this machine has done
with V4.1 — experts on the CPU, 32 threads, one request after another. The
thermal guard (`configs/thermal-guard.sh`, coolant limit 52 °C for 30 s)
stopped `llama-server` at 08:32:00 after the Q3_K pass (5.5 min) and 375 of
400 questions of the Q8_0 pass (another 5.5 min), and again at 08:38:37 on
the retry, five minutes after a start at 42.9 °C. CPU package read 88–89 °C
from 08:24 on. The coolant fell back to 42.9 °C within ninety seconds of the
stop each time. CPU boost was confirmed off (`cpb` reads 0, scaling max
3.6 GHz), so this is the machine's steady state, not a regression from
yesterday's move and reboot.

The guard's comment says "measured sustained 43–45 °C". That was measured
serving V4 with the active experts on the GPUs. V4.1 decode with experts on
the CPU heats the loop at roughly 2 °C per minute and reaches the limit in
five. Two consequences for the record: any decode number here that was
measured over more than about five minutes of continuous load was measured
on a throttling or about-to-be-stopped machine, and next session's ik and
DSpark throughput runs must be short or paced. The retry was, by waiting
for ≤44 °C before starting and running only the 50 remaining questions.
`popqa.py` now saves partial results every 25 questions, which is what let
the retry be 50 questions instead of 400.

### Capping the clock costs nothing

The obvious question was whether the CPU needs its clock for this load at
all. `acpi-cpufreq` on this board exposes three P-states, 3.6, 2.7 and
1.8 GHz. Two short runs per cap with the coolant allowed to fall back
between them — three 200-token decodes on short prompts, then two
1,308-token prompts each with up to 200 tokens of decode, package power
read from RAPL (`intel-rapl:0`, package-0) over each request:

| cap | decode, 200 tok ×3 | decode after 1.3k prompt ×2 | prefill 1.3k ×2 | pkg W during request | CPU after run |
|---|---|---|---|---|---|
| 3.6 GHz | 16.5 / 18.0 / 18.1 | 17.2 / 18.4 | 84 / 114 | 94–106 | 67.5 °C, 58.5 °C |
| 2.7 GHz | 18.8 / 18.5 / 19.3 | 16.1 / 17.9 | 100 / 105 | 94–95 | 60.9 °C, 55.2 °C |
| 1.8 GHz | 17.0 / 17.9 / 18.0 | 11.8 / 16.6 | 81 / 41 | 66–78 | 57.4 °C, 50.6 °C |

Decode does not care about the clock between 2.7 and 3.6 GHz; the cores are
waiting on memory either way. At 1.8 GHz it starts to, and prefill halves
on one run. The coolant rose 3.2 °C over the first run at 3.6 GHz and 1.6 °C
at 2.7 GHz, with the CPU package 7 °C cooler at the same throughput.

The power column is the surprise: the package draws about 100 W during
V4.1 decode at any clock, a third of the 280 W PPT the BIOS is set to.
Lowering the PPT further would not touch this load — the limit is never
reached — and the 88 °C readings under a 100 W draw say the heat problem
is the cold plate's contact with the sWRX8 IHS (which the Kraken X3 does
not fully cover; that is why boost is off), not the power. The cap that
does help is the clock. Two caveats: RAPL on Zen 3 through the
`intel-rapl` driver is a vendor-specific counter this repo has not
cross-checked against a wall meter, and these are two-sample runs on a
quiet machine, good for the shape of the curve and not for the third digit.

### A second session was on the machine, and one measurement paid for it

From 09:29 to 11:07 a `llama-server` this session did not start held both
GPUs and about one core. Another Claude session on the same workstation had
launched it, serving the original Q3_K_M on port 8001 for a different
project. Nothing announced it: the load average was the only symptom, and a
load average does not say who.

Both perplexity runs above overlapped it. Perplexity is deterministic, so
the numbers stand unchanged; what the contention bought was wall time, and
the small variant's pass took 160 s against 87 s for the same work earlier
in the day.

One measurement was lost outright. A throughput comparison launched its own
server on port 8001, then waited for `/health` to answer — and `/health`
answered, from the server that was already there. It measured a stranger,
cold, under a 472 GB `sha256sum`, and reported 5.44, 9.53 and 11.92 tok/s
climbing run over run, which is the shape of a model still being paged in.
The second engine then failed to start at all: `cudaMalloc failed: out of
memory`, 29 GB asked for on a card whose 38 GB was already spoken for.

Three things are now in the script rather than in someone's memory. It
refuses to measure a port it did not open, and prints who is listening. It
refuses to start when any process holds a GPU, and prints which. It waits
for its own server's log line before trusting a health endpoint, and counts
`sha256sum` and any `llama-server` as noise alongside the obvious ones.

The general form is worth stating, because the first version of that script
was written carefully and still got this wrong: on a machine more than one
agent shares, "is the box quiet" is not a question about load. It is two
questions about ownership — is anything else listening on my port, and does
anything else hold a device I am about to ask for.

## Not measured, not claimed

- ~~Which of the four engram tensors carries the perplexity difference.~~ Measured the same day, above: the table four fifths, `engram_wkv` the rest, the gate vectors noise.
- Any effect on speed. The probes' per-answer rates were on 3–13 token
  answers and are not decode rates by the rule in
  `docs/live-run-cockpit-brief.md`.
- Whether a longer or thinking-mode answer would show a fact-recall
  difference; the probes were single short answers.
- The engram tensors on ik_llama.cpp; both variants were measured on
  mainline. The ik port loads the same files, so the comparison should
  transfer, but it was not run.

*Applied 2026-09-13 09:03: `configs/cpu-clockcap` and its unit cap all 64
policies at 2.7 GHz at boot, after `cpu-noboost`. Verified with `cpupower
frequency-info` ("within 1.80 GHz and 2.70 GHz") on all policies; the served
model stayed up through the change.*
