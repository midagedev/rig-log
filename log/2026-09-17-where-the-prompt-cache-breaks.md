# Where the prompt cache breaks: a 13 167-token prefix, checkpoints only at the end, and a parser that never said where the user turns were

**2026-09-17, 08:22–09:45, one A6000, DeepSeek-V4.1-Flash Q3_K_M with the DSpark draft, every
expert layer on the host.** The question was why an agent turn on this model took five to
seven minutes yesterday when its decode runs at 25 tok/s. The answer needed a logging proxy
between the agent and the server, three server runs, and one read of the server's
checkpoint code — and it turned out to be two separate things, one of which is a patch.

## The instrument

Hermes Agent was pointed at a small reverse proxy ([`tools/cache/logproxy.py`](../tools/cache/logproxy.py))
that writes every request body and response to disk, and the server was started with
`-lv 4`. Each response carries the server's own accounting — `prompt_n` (tokens actually
prefilled), `cache_n` (tokens reused from the slot), `prompt_ms` — so nothing here is
inferred from wall time. Replays were made with the captured bodies at temperature 0,
`max_tokens` 8 ([`tools/cache/replay-cache.py`](../tools/cache/replay-cache.py)), so the only number
that moves is the prefill.

## What the first agent turn actually spent

One Hermes turn ("what GPUs are in this machine, use tools") took 7 min 31 s and made six
model calls:

| call | messages | prompt tokens | reused | prefilled | prefill | decode |
|---|---|---:|---:|---:|---:|---:|
| 1 | system, user | 13 167 | 0 | 13 167 | **285 s** at 46 tok/s | 139 tok in 6 s |
| 2 | + assistant, tool, tool | 14 412 | 13 305 | 1 107 | 26 s | 306 tok, 25 tok/s |
| 3 | + tool call, result | 15 258 | 14 717 | 541 | 12 s | 438 tok, 21 tok/s |
| 4 | | 16 038 | 15 696 | 342 | 7 s | 288 tok |
| 5 | | 16 459 | 16 326 | 133 | 5 s | 191 tok |
| 6 | | 16 752 | 16 649 | 103 | 5 s | 429 tok, 19 tok/s |

So the cache works within a session exactly as designed: after the first call, only the new
tokens are prefilled. Of the 13 167 tokens in that first prompt, the rendered template puts
4 200 in the Hermes system text and about 8 950 in the 23 tool schemas; the user message is
20. The five minutes were one cold prefill of that prefix at 46 tok/s, and then reasoning
decode; tool count, not the agent's prompt layout, is the biggest lever on the cold cost.

A second session with the identical question got its first token **1 s** after the request:
the two first requests were byte-identical (system prompt, tools, user message, all
parameters) and the slot's cache matched all 13 167 tokens. Hermes' three-tier prompt —
stable identity and guidance first, workspace context second, skills index, memory and a
session-start timestamp last — is doing what its comments say it does. (That second session
then looped for 15 329 tokens of "I need to." before it was stopped; identical prompt,
server default temperature 0.8, no Hermes-side temperature. Recorded, not chased.)

## Where it breaks

Replays of the captured first request, one change each:

| change | first differing token | reused (`cache_n`) | prefilled | wall |
|---|---:|---:|---:|---:|
| none | — | 13 163 | 4 | 0.6 s |
| new user question | 13 146 | 12 651 | 510 | 13.8 s |
| one word at the end of the system prompt | 4 200 (32 %) | **0** | 13 168 | 236 s |
| one word in a tool description | ~10 400 (79 %) | **0** | 13 170 | 227 s |
| original again, after the above | — | **0** | 13 167 | 228 s |
| same four with `--ctx-checkpoints 64 --checkpoint-min-step 1024` | | **0, 0**, 0 (new question, after a clobber), 12 645 | | |

Nothing before the last user message could be partially reused. A change at 32 % of the
prompt cost the same as a change at 79 %: everything.

The reason is in the model and in the server's answer to it. V4.1-Flash has sliding-window
attention layers (`n_swa = 128`; the server builds an iSWA cache with 768 SWA cells beside
the 65 536-cell full cache). A sliding-window cache cannot be rolled back to an arbitrary
earlier position, so llama-server keeps **context checkpoints** — snapshots of the
non-rollable state, 5.8 MiB each here — and on a partial prefix match restores the nearest
checkpoint at or before the divergence and re-prefills from there. Where checkpoints are
created is a design decision from upstream PRs #22929 and #24176: at the start of each user
message, and 4 and 4+`n_ubatch` tokens before the end of the prompt. Ordinary mid-prompt
checkpoints are skipped on purpose ("avoid periodic mid-prompt checkpoints when that
position is known"), and `--checkpoint-min-step` does not bring them back — measured above.
The log confirmed it: two checkpoints per prompt, at 12 651 and 13 163, nothing else.

That explains the 510-token re-prefill on a new question (restore to 12 651, redo the last
516) and the zero everywhere else. It does not explain why there was no checkpoint at the
user-message start, token 13 146, which the design promises. That is the second layer.

## The parser never said where the user turns were

The server finds user-message starts by scanning the prompt tokens for per-role
delimiters that the chat-format parser publishes (`common_chat_params::message_delimiters`).
The specialized parsers for Kimi-K3, MiniMax-M3 and Muse Glimmer set them. The DeepSeek
V3.2/V4/V4.1 parser (`common/parsers/deepseek.cpp`, `common_chat_params_init_deepseek_v3_2`)
never does, so for these three templates the span list is empty, `is_user_start` is never
true, and the user-turn checkpoints do not exist. The near-end pair is all this model ever
had.

The patch is nine lines of sibling parity — `<｜User｜>` and `<｜Assistant｜>`, which all three
templates render — plus a test-chat case that loads each template and asserts the two
delimiters are published and present in the rendered prompt. FAIL-first on the unpatched
tree: `Expected: <｜User｜> Actual:` (empty), rc 134. On the patched tree test-chat passes.

Rebuilt and re-measured, default checkpoint settings:

| change | reused | prefilled | wall | before the patch |
|---|---:|---:|---:|---|
| cold | 0 | 13 167 | 306 s | same |
| new user question | **13 145** | **16** | **0.8 s** | 12 651 / 510 / 13.8 s |
| three user turns | 13 145 | 75 | 5.5 s | — |
| second of three user turns edited | 13 145 | 79 | 5.0 s | would have been 0 / full |

The log now shows the third checkpoint at `n_tokens = 13145`, the first user message, and
every later request restoring to it.

## What the patch does not fix

Any edit inside the system prompt or the tool schemas still costs the whole prefix. That is
the design, not the parser: there is no anchor inside a 13k-token prefix that has no user
message in it, and #22929 removed periodic checkpoints deliberately (its author's follow-up
#24899 was closed). A narrower idea — checkpoints spaced by `--checkpoint-min-step` only in
the region before the first user span, where there is no structure to anchor on — would
recover Hermes' 4 200-token stable band when the volatile band changes between sessions, but
it argues with a maintainer decision and is not part of this patch.

Also unchanged: the cold prefill itself. 13 167 tokens at 46 tok/s is 4 min 45 s on this
placement whatever the cache does, and the tool schemas are two thirds of it.

## State

Patch and test on the box: serving fork `llama.cpp-v41-merged` (the server now runs it) and a
standalone branch `deepseek-msg-delimiters` on upstream master in `llama.cpp-upstream-wt`
(V3.2 and V4 templates in the test; V4.1's template is the separate DSML patch). Commit
message and PR body are the author's to write. Probe artefacts: `/home/user/cache-probe`
(three server logs, every request and response, the replay scripts). The agent bot was
returned to its z.ai backend; the A6000 is idle and the lease released.
