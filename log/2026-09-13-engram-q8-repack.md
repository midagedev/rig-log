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
table and everything else.

| variant | `engram_embd` | `engram_wkv` | `engram_q/k` | extra bytes | PPL |
|---|---|---|---|---|---|
| the upload | Q3_K | Q3_K | Q3_K | — | 2.2438 ± 0.0631 |
| small only | Q3_K | Q8_0 | BF16 | +0.2 GB | 2.2171 ± 0.0626 |
| table only | Q8_0 | Q3_K | Q3_K | +125 GB | *pending* |
| the repack | Q8_0 | Q8_0 | BF16 | +125 GB | 2.1090 ± 0.0585 |

The small tensors alone close 0.0267 of the 0.1348 gap — a fifth of it — for
two hundred megabytes across the two layers. That is the cheap half of the
finding, and it is worth separating from the table for a second reason:
mainline's quantizer already exempts `engram_q` and `engram_k`
(`llama-quant.cpp:315-318`), so part of this variant's gain is a defect of
this particular upload rather than of mainline's defaults today. What the
variant cannot separate is `wkv` from `q/k`; both moved together.

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

## What the quantizer does today

Mainline `src/llama-quant.cpp` already keeps `engram_q.weight` and
`engram_k.weight` unquantized (lines 315–318, with the comment that
`ggml_mul` has no quantized path); the upload has them at Q3_K, so it
predates that rule or was built with another tool. There is no rule for
`engram_embd.weight` or `engram_wkv.weight`, which is why the table ends up
at whatever the body type is. Given the table is never resident, a default of
Q8_0 for `engram_embd` costs the user disk and nothing else, and the
perplexity table above is the evidence. That is an upstream candidate; it
goes to `docs/upstream-contributions.md` once the four-tensor attribution
above is measured, since a PR that says "the table" should have shown it is
the table.

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

## Not measured, not claimed

- Which of the four engram tensors carries the perplexity difference.
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
