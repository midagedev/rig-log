# A Rust engine on the same card: slower alone, twice as fast at four streams — and the run that proved our "thinking off" was never off

**2026-09-17, 14:07–14:27, one A6000, Qwen3.6-35B-A3B UD-Q6_K, five takes.** The
long-term goal stated this morning is an engine built for this machine, with Rust as the
direction after NVIDIA's CUDA Rust post. The first step was never going to be a repo; it was
a number: where does a Rust serving engine actually stand on this card, measured the way
everything else here is measured. mistral.rs 0.9.3 against ik_llama.cpp c10fbbcc, the same
GGUF, the same four prompts, the same token cap, the same lease.

Two things came out of it. The four-stream aggregate nearly doubled — 149 tok/s for ik,
283 for mistral.rs — while the single stream went the other way, 130 against 111. And the
run that made the comparison fair found that every `--no-think` take this repo has recorded
on ik_llama.cpp was thinking anyway.

## The recorder could not attach, and the fix was ours, not the recorder's

mistral.rs serves an OpenAI-compatible API and nothing else: `GET /props` is 404,
`/v1/models` is 200. toktape attaches through `/props` and takes its rate from the
`timings` object llama-server puts on each stream chunk, so it refused the server outright
(`cannot attach: HTTP 404`). The generic fix is filed with the recorder as TTP-99 and is
still To Do; the same problem was solved here on 2026-09-15 for ExLlamaV3 by writing a
llama-server-protocol front, so that is what was done again rather than waiting.

Before writing it, one server load answered what the front actually has to translate
(`curl`, four request shapes, captures in `/home/user/mrs-take/probe`):

| question | measured answer |
|---|---|
| toktape's unknown fields (`timings_per_token`, `return_progress`) | ignored, 200 |
| `stream_options.include_usage` | honoured; `usage` rides the `finish_reason` chunk, before `[DONE]` |
| usage fields | `prompt_tokens`, `completion_tokens`, `total_prompt_time_sec`, `total_completion_time_sec`, `avg_*_tok_per_sec` |
| `chat_template_kwargs: {enable_thinking: false}` | honoured — no `reasoning_content` in the stream |
| nothing about thinking | thinks: 48 of 48 tokens arrive as `reasoning_content` |
| `/props`, `/health`, `/apply-template` | 404, 200, 404 |

So [`tools/mrs/mrs-shim.py`](../tools/mrs/mrs-shim.py) is thin on purpose. It forwards the
chat body byte-for-byte, because the engine already accepts everything toktape sends. It
answers `/props` the way `exl3-serve` does — model path, slot count, `n_ctx`, and an
`engine` block naming mistral.rs, with **no** `build_info`, which would stamp the card
"llama-server". It reads the GGUF header itself for the arch, the expert counts and the
parameter total, since there is no server route that reports them. It renders the GGUF's own
chat template with jinja2 for `/apply-template`, which is how the card gets a prompt hash
rather than the warning `prompt unknown`. And on every chunk it attaches a `timings` object:
provisional from its own clock while the stream runs, and on the chunk that carries `usage`,
the engine's own figures — `prompt_n`/`prompt_ms` from `prompt_tokens` and
`total_prompt_time_sec`, `predicted_n`/`predicted_ms` from the completion pair. The rate on
the card is the engine's measurement, not the proxy's.

Stdlib only: the box has no aiohttp. Configuration is by environment and never argv,
because a GGUF path on the proxy's command line is exactly how a recorder mistakes the
proxy for the server.

## The five takes

Same file, same four ~234-token prompts (`hl1..hl4`), `-n 512`, temperature 0, warm page
cache, one GPU by UUID, lease held, `io avg10 0.00` at every start. The engine's own figure
is `srv`, toktape's client-side count is `cli`, and the aggregate is
tokens ÷ (last token − first token) for both engines, which is the only figure computed the
same way on both sides of the table.

| 14:07–14:27 | streams | thinking | srv each | cli each | aggregate | TTFT p50 | GPU W | tokens out |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| ik_llama.cpp c10fbbcc | 1 | on | 130.1 | 129.9 | **130** | 252 ms | 298 | 512 |
| mistral.rs 0.9.3 | 1 | on | 111.2 | 104.5 | **105** | 160 ms | 248 | 512 |
| ik_llama.cpp c10fbbcc | 4 | on | 37.5 | 37.4 | **149** | 4 475 ms | 293 | 4 × 512 |
| mistral.rs 0.9.3 | 4 | on | 76.9 | 73.1 | **283** | 451 ms | 299 | 4 × 512 |
| mistral.rs 0.9.3 | 4 | off | 79.1 | 73.8 | 237 | 465 ms | 260 | 234–345 (EOS) |

Alone, ik is **24 % faster** on the client clock and reaches 386 GB/s of derived read, the
same half-of-the-card ceiling this log has measured since 09-15. At four streams mistral.rs
is **90 % ahead** on the aggregate and its per-stream rate barely moves (111 → 77) where
ik's collapses (130 → 37.5). Prefill is the other half of the story: ik spent
**3 357 ms** of engine time on four 234-token prompts against mistral.rs's **104 ms**, and
that is most of the ten-fold TTFT difference. The no-think row is in the table because it is
the only one whose streams ended at EOS rather than the cap; its lower aggregate is the tail
of three finished streams, not a slower engine.

## What these numbers are not

They are not a Rust-kernel measurement. On compute capability 8.6 the GGUF Q6_K MoE path in
mistral.rs runs candle's CUDA **C** kernels through FFI; the cuTile modules — the actual
Rust-authored kernels — cover fp8, nvfp4 and GDN paths, need CUDA ≥ 13.2, and this box has
13.0, so the installer left them off. What was measured is a Rust host and scheduler over
the same class of kernels ik_llama.cpp compiles itself. The finding is therefore about
batching and scheduling, not about whether Rust can write a fast GEMM.

That makes the four-stream gap the interesting one and the open question the important one.
The 09-16 ExLlamaV3 arm measured why concurrency usually buys nothing on a sparse MoE: two
tokens from two streams route to different experts, so the bytes read per step scale with
the streams and the aggregate stays flat. ik's +13 % at four streams (09-15) fits that
arithmetic. mistral.rs's +170 % does not, and the two candidate explanations are testable:
either its single stream is overhead-bound and batching amortises a fixed cost, or its
indexed-MoE path gathers the union of the experts once per step where ik re-reads per
sequence. The next take is a stream sweep — 1, 2, 4, 8 — on both engines, with the derived
bandwidth beside each row.

## Every `--no-think` take on ik_llama.cpp was thinking

The takes above had to be matched, so the first four-stream mistral.rs run used
`--no-think` like the ik hero take it was meant to pair with, and then the answers were
read. mistral.rs's four streams came back with content from the first token. ik's came back
with `<think>\nHere's a thinking process:` — all four of them, in a take whose card says
`thinking off`.

Checking every Qwen3.6 tape committed here:

| tape | `enable_thinking` requested | output opens with a think block |
|---|---|---|
| `qwen36-35b-a3b-q6k-4stream-hero-nothink-0.2.4` | false | **yes** |
| `qwen36-35b-a3b-q6k-4stream-hero-nothink` | false | **yes** |
| `qwen36-35b-a3b-q6k-4stream-mistralrs-nothink-0.2.4` | false | no |
| `qwen36-35b-a3b-q6k-1stream`, `-4stream`, `-4stream-hero`, `-4stream-short-prompts`, `q4kxl-1stream` | not requested | yes |

> ~~The 09-17 hero take recorded four streams with thinking off.~~ **Struck the same day.**
> The request carried `chat_template_kwargs: {enable_thinking: false}`; ik_llama.cpp at
> c10fbbcc ignored it and the model thought for all 512 tokens of every stream. The card's
> `thinking off` is honest about what was asked — the tape describes the request — and wrong
> about what happened. Nothing else in that entry changes: 37.5 tok/s each and 149 aggregate
> are what the machine did, on thinking tokens.

Two consequences. For this repo, a request parameter is not a measurement, and the check is
one line: read the first tokens of the answer. For the recorder, the contradiction is
detectable — a tape that asked for no thinking and holds an answer opening with the model's
think tag can say so on the card instead of printing `thinking off`; sent as a requirement.
For ik_llama.cpp it is a missing feature rather than a bug in ours, and worth a look as a
contribution: mainline llama-server accepts `chat_template_kwargs`, that fork does not.

## What the mistral.rs cards get wrong, and why

Read those cards knowing four rows are about the proxy or about llama.cpp:

- **ENGINE `?`** — the tape carries the engine block naming mistral.rs 0.9.3, but toktape
  0.2.4 stamps a kind from that block only for `exllamav3`, so detection falls through to
  "answered `/props` and did not say what it is". The requirement to stamp any engine block
  is sent; the version is in the tape either way.
- **FLAGS** — `-fa default -b default …` is the llama.cpp flag set printed because no argv
  was parsed. mistral.rs's real argv is in the tape's engine block.
- **`contended: yes` and "1 other GPU compute process"** — that process is mistral.rs.
  toktape finds the server pid by matching the model path in a command line *and* requiring
  a llama.cpp-family command name, so `mistralrs` is rejected and the search falls back to
  whoever holds the listening port, which is the shim. Every memory and page-fault row on
  these cards is the Python proxy's, which is why host RSS reads 0.0 GiB.
- **Context `8192`** — mistral.rs has one paged pool of 8 160 tokens shared by all four
  streams, not 8 192 each. The ik cards say 2 048 because `-c 8192 -np 4` divides.

One measurement about the measuring: mistral.rs's `total_completion_time_sec` is
consistently **4–10 % shorter** than the wall time its tokens took to arrive
(512 tokens: 4 606 ms reported against 4 892 ms observed). The shim's own clock and
toktape's client count agree with each other to within 1 %, so the gap is inside the
engine's accounting, not the proxy's. ik's server and client figures agree to 0.2 %. Where
one number had to be picked for a like-for-like row above, it is the client one.

## State

`tools/mrs/mrs-shim.py` and the runner `tools/mrs/mrs-take.sh` are on the box as
`/home/user/mrs-shim.py` and `/home/user/mrs-take.sh`, both owned by `user`. Five tapes and
their cards are in `assets/` under `…-mistralrs-…` and `…-1stream-ik-think-…`; every one was
run through `tools/tape-sanitize.py` and `tools/check-tapes-sanitized.sh` before the commit.
Probe captures and server logs stay on the box under `/home/user/mrs-take/`. The A6000 is
idle, the lease released. Recorded with
[toktape](https://github.com/midagedev/toktape) 0.2.4.
