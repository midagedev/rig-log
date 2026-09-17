# A Rust engine on the same card: slower alone, twice as fast at four streams — and the run that proved our "thinking off" was never off

**2026-09-17, 14:07–14:31, one A6000, Qwen3.6-35B-A3B UD-Q6_K, seven takes.** The
long-term goal stated this morning is an engine built for this machine, with Rust as the
direction after NVIDIA's CUDA Rust post. The first step was never going to be a repo; it was
a number: where does a Rust serving engine actually stand on this card, measured the way
everything else here is measured. mistral.rs 0.9.3 against ik_llama.cpp c10fbbcc, the same
GGUF, the same four prompts, the same token cap, the same lease.

Two things came out of it. The four-stream aggregate nearly doubled — 149 tok/s for ik,
283 for mistral.rs — while the single stream went the other way, 130 against 111. And
matching the two run shapes found that this repo's `--no-think` takes on the one-card bench
runner were thinking anyway, because that runner never passed `--jinja`. The first
explanation I wrote for that was wrong and is struck below; the run that corrected it took
forty seconds.

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

## The seven takes

Same file, same four ~234-token prompts (`hl1..hl4`), `-n 512`, temperature 0, warm page
cache, one GPU by UUID, lease held, `io avg10 0.00` at every start. The engine's own figure
is `srv`, toktape's client-side count is `cli`, and the aggregate is
tokens ÷ (last token − first token) for both engines, which is the only figure computed the
same way on both sides of the table.

| 14:07–14:31 | streams | thinking | srv each | cli each | aggregate | TTFT p50 | GPU W | tokens out |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| ik_llama.cpp c10fbbcc | 1 | on | 130.1 | 129.9 | **130** | 252 ms | 298 | 512 |
| mistral.rs 0.9.3 | 1 | on | 111.2 | 104.5 | **105** | 160 ms | 248 | 512 |
| ik_llama.cpp c10fbbcc | 4 | on | 37.5 | 37.4 | **149** | 4 475 ms | 293 | 4 × 512 |
| mistral.rs 0.9.3 | 4 | on | 76.9 | 73.1 | **283** | 451 ms | 299 | 4 × 512 |
| mistral.rs 0.9.3 | 4 | off | 79.1 | 73.8 | 237 | 465 ms | 260 | 234–345 (EOS) |
| ik_llama.cpp, `--jinja` | 4 | off | 41.2 | 40.9 | **146** | 5 448 ms | 285 | 157–248 (EOS) |
| ik_llama.cpp, `--jinja` | 1 | off | 131.4 | 130.8 | **132** | 250 ms | 298 | 244 (EOS) |
| ik_llama.cpp, `--jinja`, `-c 32768` | 4 | off | 42.1 | 41.8 | **144** | 5 704 ms | 281 | 152–279 (EOS) |

Thinking on or off moves neither engine's rate by more than 2 % — 149 against 146 aggregate
for ik, 130 against 132 alone, 105 against 105 for one mistral.rs stream — so the two halves
of the table say the same thing and the comparison survives the labelling mistake below.

Alone, ik is **24 % faster** on the client clock and reaches 386 GB/s of derived read, the
same half-of-the-card ceiling this log has measured since 09-15. At four streams mistral.rs
is **90 % ahead** on the aggregate, and its per-stream rate barely moves (111 → 77) where
ik's collapses (130 → 37.5). Prefill is the other half of the story: for the same four
~235-token prompts, ik's own accounting says **3 357 ms** of engine prefill with thinking on
and **5 393 ms** with it off, against mistral.rs's **104 ms** — which is nearly all of the
ten-fold TTFT gap, and a bigger discrepancy than the decode one. A single 260-token prompt
on ik prefills at 1 206–1 314 tok/s, so whatever costs those seconds only appears when four
slots want a prompt at once. The two mistral.rs no-think rows end at EOS rather than the
cap, and their lower aggregate is the tail of finished streams, not a slower engine.

## What these numbers are not

They are not a Rust-kernel measurement, and the first version of this paragraph got the
reason wrong.

> ~~The cuTile modules — the actual Rust-authored kernels — need CUDA ≥ 13.2, and this box
> has 13.0, so the installer left them off.~~ **Struck the same day.** The installed
> toolkit is 13.0, but the binary carries its own runtime and `mistralrs doctor` reports
> `CUDA: build 13.2` and `Build features: cuda, flash-attn, cutile` — the modules are
> compiled in. What it also reports is why they are idle: `cuTile runtime tooling is
> unavailable; native CUDA and CUTLASS fallbacks remain active`, with the hint to install
> NVIDIA `tileiras`, which is not on this box. And there is a second gate the version
> question would have hidden: the binary's own strings say the cuTile MoE backend is a
> *blockwise FP8* grouped GEMM and that `MISTRALRS_MOE_BACKEND=fused requires F16 or BF16
> weights`, so a Q6_K GGUF would not reach either path even with the assembler present.

Which kernels it did run was an inference for about four hours and is now measured: the
server started with `-v` prints `Preloaded 698 Candle CUDA PTX functions`, so the kernels
under these numbers are candle's, as the code read said. The same log line answers a
question nobody here had asked — `Qwen3Next: 10 full attention layers, 30 linear attention
(GDN) layers`, which is to say three quarters of this model's stack is a recurrent state
update rather than a KV read. What was measured is therefore a Rust host and scheduler over
kernels of the same class ik_llama.cpp compiles itself, so the finding is about batching and
scheduling, not about whether Rust can write a fast GEMM.

That makes the four-stream gap the interesting one and the open question the important one.

> ~~The 09-16 ExLlamaV3 arm measured why concurrency usually buys nothing on a sparse MoE: two
> tokens from two streams route to different experts, so the bytes read per step scale with the
> streams and the aggregate stays flat. ik's +13 % at four streams fits that arithmetic.
> mistral.rs's +170 % does not, and the two candidate explanations are testable: either its single
> stream is overhead-bound and batching amortises a fixed cost, or its indexed-MoE path gathers the
> union of the experts once per step where ik re-reads per sequence.~~ **Struck the same day**, by
> the sweep this paragraph asked for. Both candidates were guesses about the fast engine, and the
> gap is on the other side: a second stream costs mistral.rs 11 % and costs ik 50 %, ik's decode
> does not batch on a MoE model at all (measured on a second MoE model with no linear attention,
> and against a dense model that scales normally in the same harness), and its concurrent prefill
> falls back to single-token chunking at a named site. Neither CUDA graphs nor the fused-MoE path
> survived intervention. The measurement, the reproducer and the upstream disposition are in
> [2026-09-17-b](2026-09-17-b-where-the-four-stream-gap-actually-is.md).

## The `--no-think` that was never off, and the flag that explains it

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
> The request carried `chat_template_kwargs: {enable_thinking: false}`, the server dropped
> it, and the model thought for all 512 tokens of every stream. The card's `thinking off` is
> honest about what was asked — the tape describes the request — and wrong about what
> happened. Nothing else in that entry changes: 37.5 tok/s each and 149 aggregate are what
> the machine did, on thinking tokens.
>
> Re-recorded at 14:41, at the request of the session that had asked for the hero clip:
> same four prompts, `--jinja`, `--no-think`, `-np 4`, `-c 32768`. The model did not think,
> every stream ended at EOS between 152 and 279 tokens, and the aggregate came out at
> **144 tok/s** — within 4 % of the 149 that were measured on thinking tokens, so the
> mislabelling cost the record a label and not a number. The runner's gate printed
> `no-think honoured` for the first time on a live take. The tape is
> `assets/qwen36-35b-a3b-q6k-4stream-ik-jinja-nothink-c32k-0.2.4.tape`.

> ~~ik_llama.cpp has no support for `chat_template_kwargs`; mainline llama-server does, and
> the gap is worth a contribution.~~ **Struck within the half-hour, before anything was sent
> anywhere.** The fork has the field (`common/chat.cpp:546`, `common/chat.h:181`). The cause
> was on this side: [`tools/ik/ik-vram-take.sh`](../tools/ik/ik-vram-take.sh) never passed
> `--jinja`, so the server used the legacy template path, where the kwargs are not read at
> all and nothing says so. The production serving config had it right all along
> ([`configs/qwen36-3090-serve.sh`](../configs/qwen36-3090-serve.sh) passes
> `--jinja --chat-template-kwargs`), and so does the Qwen3.8 runner — only the one-card bench
> runner was missing it. Measured immediately: the same prompt, the same flags, `--jinja`
> added, `--no-think` sent — no think block, EOS at 244 tokens, 131.4 tok/s. **Reading the
> code would have produced a wrong upstream report; one run cost 40 seconds.**

The prompt hashes are the by-product, and they are also evidence for the diagnosis. toktape
hashes the rendered prompt it gets from `/apply-template`: the shim's jinja rendering of the
GGUF template and ik's own `--jinja` rendering agree exactly —
`0304d4f3…` on all five `--jinja` and mistral.rs takes, so those rows are two engines fed
byte-identical text rather than two engines each templating their own way. The two legacy-path
ik takes hash `4d74d304…` instead, 234 prompt tokens against 236: the path that dropped the
kwargs also rendered a different prompt, which is what a silently different template looks
like from outside.

Three layers, because a request parameter that is not a measurement will happen again:

- **Closed at the source**: `--jinja` is now unconditional in the ik bench runner, which also
  makes the bench path the same template path production serves on.
- **A gate, FAIL-first**: [`tools/check-take-nothink.py`](../tools/check-take-nothink.py)
  reads a tape, and when no-think was requested and an answer opens with a thinking tag — or
  a stream reported `reasoning_n` tokens, which is how mistral.rs carries thinking — it fails
  with the stream and the text. It fails on the hero tape (`THOUGHT ANYWAY … 4 answer(s)`),
  passes on the seven other 0.2.4 tapes, and does not judge a take that never asked. Both
  runners call it after the take and fail the run.
  The first version of that wiring never ran: it looked for the tape path as
  `$RUNS/…` while toktape prints `~/toktape-runs/…`, so the variable came back empty and the
  guard skipped the check without a word. It is now an error for the path to be missing, and
  a 20-second take through the runner prints `no-think honoured (1 tape(s))` — a gate proved
  only by hand is a gate that has not been proved.
- **Easier to see next time**: the recorder was asked to put the same contradiction on the
  card, since the tape holds both halves of it.

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

`tools/mrs/mrs-shim.py`, the runner `tools/mrs/mrs-take.sh`, the amended
`tools/ik/ik-vram-take.sh` and `tools/check-take-nothink.py` are on the box under
`/home/user/`, all owned by `user`. Seven tapes and
their cards are in `assets/` under `…-mistralrs-…`, `…-ik-think-…` and `…-ik-jinja-nothink-…`; every one was
run through `tools/tape-sanitize.py` and `tools/check-tapes-sanitized.sh` before the commit.
Probe captures and server logs stay on the box under `/home/user/mrs-take/`. The A6000 is
idle, the lease released. Recorded with
[toktape](https://github.com/midagedev/toktape) 0.2.4.
