# ExLlamaV3 behind a llama-server surface: exl3-serve, TabbyAPI's timings, and what `time_generate` measures

2026-09-15, evening. The workstation, GLM-5.3-Flash EXL3 4.05 bpw
(`/models/GLM-5.3-Flash-exl3-4.05`), exllamav3 1.5.0 (GitHub wheel
`+cu128.torch2.10.0`, torch 2.10.0+cu128), every load with
`-gs 44,21 -mcs 185 -mct 32 -cs 32768 -mtp` and the draft depth at 1 — the
serving profile from `log/2026-09-15-glm-5.3-flash-first-run.md`.

## Why

The recorder, [toktape](https://github.com/midagedev/toktape), attaches to
llama-server: it reads `/props`, streams `/v1/chat/completions` and checks the
server's `timings` against its own token count. ExLlamaV3 has no such server,
so the per-expert placement numbers from the day could not be recorded. Two
routes were taken in parallel: a small Python front that presents that surface
over one exllamav3 model (exl3-serve, not yet published), and a patch to
TabbyAPI — the exllama project's own OpenAI-compatible server — for the one
field it lacks (its issue #454, patch prepared by the toktape session, checked
here). TabbyAPI turned out to already carry a llama-server-style `/props` and
`/apply-template` (added 2026-09-07); what it lacks for a recorder is
`timings`, `/slots`, `prompt_progress` and any placement information.

## The engine block, measured against the files

The recorder's card prints the model and placement from an `engine` object in
`/props`, with the rule that a value is either measured or omitted. Reference
values were computed from the safetensors headers; the served block was then
compared with them at load time.

| field | reference (disk) | served |
|---|---|---|
| files / bytes (non-hidden top-level) | 30 / 165 151 541 665 | same |
| params, text model, MTP and vision excluded | 313 326 811 966 | same |
| active bytes per token (dense in full, one embedding row, top-8 experts) | 10 979 084 996 | same |
| quant | `quantization_config.json`: bits 4.05, head_bits 6 | "EXL3 4.05 bpw · head 6.0" |
| CPU-worker experts (185 × 12 619 788 B × 42 layers) | 98 055 752 760 | included in CPU |
| KV cache on cards (cache + draft cache) | 419 430 400 + 157 286 400 + 52 428 800 | 629 145 600 |

`model.get_storage_info()` reports a mean of 4.15 bpw at this split — the CPU
tail drops out of its average — so the quant string comes from the file.

A 400-token streamed reply gave 399 text deltas against `predicted_n` 400
(the one `</think>` token emits no text), reasoning in `reasoning_content`,
211 drafted / 189 accepted.

## Four defects caught by the real model, not by the tests

The first implementation passed its own suite; each of these showed up only
when the numbers were compared with the model on disk or a real reply:

- **The reasoning split never engaged.** GLM-5.3's chat template ends the
  prompt with `<think>`, so the reply closes the block without ever opening it.
  A splitter waiting for `<think>` sent all reasoning as content.
- **Turns did not stop.** `generation_config.json` lists three end ids
  (154820, 154827 `<|user|>`, 154829 `<|observation|>`); only the tokenizer's
  one was passed to the job.
- **Active bytes counted every expert: 159 387 791 876 instead of
  10 979 084 996.** The real layout is `experts.<e>.<proj>.<quad>`, one level
  deeper than the synthetic fixture the tests used; the expert pattern never
  matched.
- **The class split followed walk order.** The loader packs weights into
  128 MiB chunks; counting storage size deduplicated by storage credited a whole
  chunk to the first tensor met in it — 27 RMSNorm weights of 8 KB each were
  booked at 0.125 GiB apiece, so "other" read 4.45 GB on the 48 GB card. Device
  bytes now count each tensor's own bytes; the overlap and slack check is in
  progress below.

## What exllamav3's `time_generate` covers

The generation rate llama-server reports divides by the number of decode
steps, and whether that is n or n−1 depends on when the engine starts its
clock. Two readings of the same source disagreed (this session first read
n−1 and changed exl3-serve accordingly; the toktape session read n), so it was
measured: exactly n tokens, no stop conditions, greedy, two repetitions each.

| n | `time_generate`, no draft (s) | / n | / (n−1) | wall, first text to end (s) |
|---|---|---|---|---|
| 1 | 0.0628, 0.0618 | 0.062 | — | 0.0000 |
| 2 | 0.1047, 0.1048 | 0.052 | 0.105 | 0.0520, 0.0526 |
| 3 | 0.1566, 0.1573 | 0.052 | 0.078 | 0.1042, 0.1032 |
| 8 | 0.4138, 0.4163 | 0.052 | 0.059 | 0.3606, 0.3628 |

One token takes one pass of time, not zero; the per-token figure is flat over
n, not over n−1; and the wall clock from the first text result is (n−1)
passes. The clock starts before the pass that produces the first token, so
`time_generate` covers n passes and n / time is the rate that matches
llama-server. The exl3-serve change was reverted and the TabbyAPI patch moved
from n−1 to n. With the MTP draft on, the same runs gave 0.09–0.15 s for one
token and 0.41 s for eight (3 accepted, 2 rejected); passes and tokens are not
one to one there, so the verdict is read off the draft-free rows. The amended
probe that would have printed per-step deltas and prefix-cache hits started
before the amendment reached it; those columns are missing.

## TabbyAPI #454: main against the patch

TabbyAPI main (53da791) and the same tree with the patch, one load each, six
requests, installed into a separate venv with the same torch and exllamav3
builds as above (TabbyAPI's own extras pin the exllamav3 wheel built for torch
2.9.0).

| request | main | patch |
|---|---|---|
| chat, stream, `include_usage` | no `timings` | `timings` on the last chunk only |
| chat, stream | no `timings` | on the `finish_reason` chunk only |
| chat, non-stream | no `timings`, `usage` null | top-level `timings`, `usage` still null |
| chat, non-stream, n=2 | two choices | two choices, `timings` null |
| text, stream, `include_usage` | no `timings` | last chunk only |
| text, non-stream | no `timings` | top-level `timings` |

All requests returned 200 on both; every `timings` carried the draft counters
(51/45 on chat, 33/31 on text). The patch's unit test file fails to import on
main and passes 23 tests on the patch. Three observations for the PR:
TabbyAPI rounds `prompt_time` and `gen_time` to 0.01 s before building the
finish chunk (`backends/exllamav3/model.py:1229`, `:1255`), so `timings` has a
10 ms resolution; non-streaming responses carry `usage` only when
`stream_options.include_usage` is set; and the last streamed chunk carries
`finish_reason` and `usage` together, on both trees.

## The take: ExLlamaV3 recorded by a llama-server recorder

20:56, the first toktape take of an engine that is not llama.cpp. exl3-serve
6a7358d loaded `/models/GLM-5.3-Flash-exl3-4.05` at the serving profile
(`-gs 44,21 -mcs 185 -mct 32 -cs 32768 -mtp`, ready in 121 s), one warm request
outside the take, then toktape v0.2.1-5-g0719fec attached over `/props` and
recorded one greedy stream. The prompt is the one the 13:08 ik graft B take
used, read back out of that tape so the two clips are on the same axis: the
merge-two-sorted-lists request at `reasoning_effort: low`, 32 tokens in.

| 20:56 take, `contended: no` | exl3-serve + ExLlamaV3 | ik graft B + MTP (13:08) |
|---|---|---|
| file | EXL3 4.05 bpw, 153.8 GiB | Q6_K graft, 184.3 GiB |
| placement | per-expert, `-mcs 185` | ten whole layers on the cards |
| decode | **22.0 tok/s** | 24.2 tok/s |
| draft | mtp n_max 1, 96 % accepted (116/121) | mtp n_max 2, 97 % (153/157) |
| TTFT, 32 prompt tokens | 3551 ms | 768 ms |
| VRAM | 43.5 / 19.4 GiB | 29.5 / 20.9 GiB |
| host RSS | 99.1 GiB | 156.4 GiB |
| major faults | 0.0 / token | 0.0 / token |
| context | 32 in / 237 out | 32 in / 238 out |

Two of those rows are the day's arithmetic coming back. Decode 22.0 against
24.2 is ExLlamaV3 9 % behind ik on this box while reading 30 GiB less file,
which is the same trade the placement sweep found at `-mcs 195` (19.1-22.2
against ik's 18.7) and not a new fact. The host RSS is: per-expert placement
keeps 92.5 GiB in the CPU worker instead of the whole remainder, so the
process is 57 GiB smaller than the one serving the GGUF.

The TTFT is the row worth an experiment. 3551 ms to the first token of a
32-token prompt is not a prefill measurement — the card says so itself — but
ik answers the same prompt in 768 ms, and 2.8 s of per-request startup would
dominate any interactive use. Where it goes was not measured: the CPU worker's
first touch of a new sequence, the tokenizer and template render on the engine
thread (exl3-serve runs one, so encoding waits behind decode steps), or the
job enqueue itself are the candidates, and the per-step deltas the amended
probe would have printed are still missing. Filed as its own experiment.

The clip is one stream because it has to be: `--parallel 2` does not yet
produce two slots (exllamav3 clamps the generator's batch to the cache's slot
count, which `-ambs` sets to 1 by default), so a two-stream take would record
serialization and call it concurrency.

Recorded with [toktape](https://github.com/midagedev/toktape): the tape is
`assets/glm53-flash-exl3-mcs185-mtp.tape` (hostname replaced with
"workstation" by [`tools/tape-sanitize.py`](../tools/tape-sanitize.py) before
publishing), the card `assets/glm53-flash-exl3-mcs185-mtp.card.png`, the mp4
[on Drive](https://drive.google.com/file/d/1XsINW_aOqHPCsafa4d2ITu6T_hFoTBPO/view?usp=drivesdk).
The runner is [`tools/exl3/exl3serve-take.sh`](../tools/exl3/exl3serve-take.sh),
the check runner's gates and teardown with a recording in place of the probe.

## Two streams: the clamp, the fix, and the aggregate that does not rise

The one-stream take above was one stream because `--parallel 2` did not
produce two slots. exllamav3 builds every cache with `max_batch_size =
args.autosplit_max_batch_size` — the `-ambs` flag, default **1** — and
`Generator.__init__` then clamps its own batch to `cache.num_slots`
(`model_init.py:292`, `cache.py:161`, `generator.py:233` of v1.5.0), so
exl3-serve asked for two and got one while `/slots` honestly reported two
free. exl3-serve now raises `-ambs` to at least `--parallel` before
`model_init` and asserts the served batch afterwards; a clamp that still
happens fails the load with both numbers instead of queueing and calling it
concurrency.

Both states were recorded, same prompts, same placement, toktape v0.2.2:

| two streams, `-mcs 185 -mtp` | per stream | aggregate | `peak_decoding_streams` | TTFT p95 | ITL p50 |
|---|---:|---:|---:|---:|---:|
| one stream, for reference (20:56) | 22.0 | 22.0 | — | 3551 ms | 62 ms |
| before the fix (21:10) | 22.2 | 21.4 | **1** | 12250 ms | 62 ms |
| after the fix (21:44) | 11.1 | **20.3** | **2** | 4621 ms | 94 ms |

The fix took: the recorder's own caveat, `the 2 streams decoded one at a
time: the aggregate is one stream behind a queue, not 2 at once`, fires on
the 21:10 tape and is absent from the 21:44 one, `peak_decoding_streams`
went 1 → 2, and the second request's wait fell from 12.3 s to 4.6 s.

And the throughput did not move — 20.3 aggregate against 22.0 for a single
stream, with each stream at exactly half the solo rate. A two-token step
costs twice a one-token step, which is the same arithmetic that held the MTP
draft to +12 % at 97 % acceptance: decode here is the read of 98.1 GB of
CPU-resident experts, two tokens from two streams route to different experts,
so the bytes double with the tokens and tokens-per-byte is unchanged. What
concurrency buys on this engine is latency fairness — 4.6 s instead of 12.3 s
for the second client — not throughput.

This is not a property of the box. ik/llama.cpp with whole expert layers on
the cards records 12.8 tok/s each and 25.7 aggregate on two streams, a real
gain; the per-expert CPU worker does not merge two streams' expert reads the
way llama.cpp's expert batch does. One take each, so the 20.3 and 21.4 are
single measurements, not a mean.

The fix has a price that explains why nobody noticed the clamp: two real
slots need more VRAM than one, and at `-gs 44,21 -mcs 185` the load failed
with `Insufficient VRAM in split for model and cache` at both `-cs 32768`
and `-cs 16384`, fitting only at `-cs 8192`. exllamav3 loads module by
module inside each device's `-gs` fraction and moves to the next device on
OOM (`model_ls.py:274`), so the batch-2 load simply runs out of room in the
same split that batch-1 fits. The tapes are
`assets/glm53-flash-exl3-2stream-serialized.tape` and
`assets/glm53-flash-exl3-2stream-batched.tape`.

The runner earned a fix of its own on the way: a failed load leaves the HTTP
front alive answering 503 with the reason, so readiness waited out its full
900 s twice. Readiness is now 200 or a named failure — the second attempt
died at 40 s with the VRAM message on screen.

## Things that went wrong on the way

The TabbyAPI runner recorded the pid of a subshell, not the server, so its
teardown missed the server and released the GPU lease while both cards were
held; background jobs also start with SIGINT ignored. Both are written up with
the fixed launch and teardown in [`docs/quiet-machine.md`](../docs/quiet-machine.md).
A class probe first died because it was launched from root's working
directory, which the exllamav3 CPU worker (a spawned process) cannot enter.
