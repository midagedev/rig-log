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

## Things that went wrong on the way

The TabbyAPI runner recorded the pid of a subshell, not the server, so its
teardown missed the server and released the GPU lease while both cards were
held; background jobs also start with SIGINT ignored. Both are written up with
the fixed launch and teardown in [`docs/quiet-machine.md`](../docs/quiet-machine.md).
A class probe first died because it was launched from root's working
directory, which the exllamav3 CPU worker (a spawned process) cannot enter.
