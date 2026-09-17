# What each engine does on this machine, by model

The measured entries in [`log/`](../log) are chronological and each one answers the question that was
open that day. This page is the other view: **which model, which engine, what rate.** It is a summary
of measurements made elsewhere, so every row names the entry that owns it, and nothing appears here
that was not measured on this box.

Last measured 2026-09-17. One RTX A6000 48 GB, one card per run, one lease, io pressure 0 at every
start. ik_llama.cpp `c10fbbcc`, mistral.rs `0.9.3` (and a source build of `d5ae0f1` plus
[#2430](https://github.com/EricLBuehler/mistral.rs/pull/2430) for the offload rows), toktape 0.2.4.
Rates recorded with [toktape](https://github.com/midagedev/toktape) and read out of the tapes by
[`tools/tape-row.py`](../tools/tape-row.py), never off a progress line.

## Which models each engine will even load

| model | size | ik_llama.cpp | mistral.rs |
|---|---:|---|---|
| Qwen3.6-35B-A3B UD-Q6_K | 29.3 GB | loads | loads |
| Qwen2.5-7B-Instruct Q3_K_M | 3.3 GB | loads | loads |
| DeepSeek-V2-Lite-Chat Q3_K_M | 6.4 GB | loads | **refused**: GGUF missing `deepseek2.attention.key_length_mla` |
| Qwen3-Coder-Next IQ4_XS | — | loads | **refused**: `blk.0.ssm_ba.weight` is IQ4_XS where an unquantized tensor is expected |
| DeepSeek-V4.1-Flash Q3_K_M | ~100 GB class | **the daily serving model** | **refused**, same `deepseek2` key |

That last row decides more than any rate below: the model this workstation actually serves does not
load in mistral.rs at all, so on the one model that matters here the comparison does not exist yet.

## Qwen3.6-35B-A3B UD-Q6_K — the model both engines run

29.3 GB, MoE, 256 experts with 8 routed per token, 40 blocks, ten of them full-attention and thirty
linear-attention (GDN). It **fits entirely on the card**, so every row here is a model that needs no
offloading; the offload rows exist to measure the feature, not because this model wants it. 238-token
prompts, thinking on, `-n 512`.

### One stream, everything resident

| engine | tok/s |
|---|---:|
| ik_llama.cpp | **129** |
| mistral.rs | **111** |

ik is faster, by 16 %. This is the ordinary serving condition.

### Concurrency, aggregate across streams

| streams | ik_llama.cpp | mistral.rs |
|---:|---:|---:|
| 1 | 129 | 105 |
| 2 | **130** | 184 |
| 4 | 146 | 279 |
| 8 | 152 | 324 |

The headline "a Rust engine 90 % faster at four streams" comes from this table and is not a statement
about mistral.rs. **ik's aggregate does not move at all from one stream to two** — 129 to 130, while
its per-stream rate halves — so the engine that looks faster under load is the one merely not leaving
the batching on the table. Reproduced without a server at all in `llama-batched-bench`, and neither
CUDA graphs nor the fused-MoE path is the cause; both were ruled out by intervention. The cause of
the batch-2 expert matmul is still open. Measured in
[log/2026-09-17-b](../log/2026-09-17-b-where-the-four-stream-gap-actually-is.md).

ik's concurrent **prefill** is a separate and larger problem on this model: a mixed-sequence ubatch
falls back to single-token chunking, 2 582 → 119 tok/s, which is the 4.5 s and 12.5 s TTFTs at four
and eight streams. Already fixed by open PR
[#2418](https://github.com/ikawrakow/ik_llama.cpp/pull/2418); our measurement is
[a comment there](https://github.com/ikawrakow/ik_llama.cpp/pull/2418#issuecomment-5714136627).

### Moving blocks to host RAM, one stream

| of 40 blocks on the host | weight moved | ik_llama.cpp | mistral.rs |
|---:|---:|---:|---:|
| 0 | 0 | 129 | 111 |
| 1 | 0.76 GB | 125 | **2.2** |
| 4 | 3.0 GB | 116 | 0.6 |
| 10 | 7.6 GB | 102 | 0.2 |

Both engines run the offloaded expert matmul **on the CPU** — that was checked by sampling the server
process rather than inferred from a buffer type's name, after the first version of the entry got it
backwards. ik spreads it over 26.7 cores and reads only the 8 of 256 routed experts in quantized
form; mistral.rs manages 1.3 cores and dequantizes all 256 to F32 on every forward, so the card sits
at 2 % waiting. Per offloaded layer per token that is **0.20 ms against 442 ms**, and both are exactly
linear in how many layers are offloaded. Measured in
[log/2026-09-17-d](../log/2026-09-17-d-what-offloading-costs-each-engine.md).

Two things to know before reading these rows anywhere else. mistral.rs **disables PagedAttention
entirely** when any layer is on the CPU, which is worth 7 % on its own (111.2 → 102.7 with everything
resident and paged attention off by hand) and makes VRAM useless as a pairing axis. And mistral.rs
could not do this at all until [#2430](https://github.com/EricLBuehler/mistral.rs/pull/2430): every
request failed with `moe experts forward / dtype mismatch in matmul, lhs: BF16, rhs: F32`
([log/2026-09-17-c](../log/2026-09-17-c-what-mistral-rs-can-and-cannot-offload.md)).

## The control models

Used to separate MoE from dense and to check that a finding was not one model's quirk.

| model | harness | measurement |
|---|---|---|
| DeepSeek-V2-Lite Q3_K_M (MoE, no linear attention) | `llama-batched-bench` decode, B = 1/2/4/8 | 202.1 → **156.1** → 229.9 → 317.0 tok/s — batch 2 is *slower in total* than batch 1 |
| Qwen2.5-7B Q3_K_M (dense) | same harness, same card, same minute | 120.7 → 195.5 → 290.7 → 388.5 tok/s — scales normally |
| Qwen2.5-7B Q3_K_M (dense) | mistral.rs, 20 of 28 layers on the host | 17.4 tok/s on a sixteen-token burst — partial offload serves, which is what the row is evidence for |

The first two rows are why the concurrency table above is a MoE finding and not a general one: same
weights class, same card, same harness, and only the presence of an expert matmul differs.

## Reading this page

Three sentences, if that is all you need.

**On a model that fits the card**, ik_llama.cpp is faster for one user (129 against 111) and
mistral.rs is faster for several (324 against 152 at eight streams), and the second half of that is
ik's defect rather than mistral.rs's merit.

**On a model that does not fit the card** — which is the case this machine actually lives in — there
is no comparison: mistral.rs will not load the model, and on a model it will load, moving one block
of forty to host RAM costs it a factor of fifty.

**What would change this** is one upstream fix each, and both are identified: ik's MoE decode not
batching (unfiled, needs per-op timing), and mistral.rs's per-token dequantize of the whole expert
stack (unfiled, same reason). Neither is filed, because a rate is not a diagnosis. The record of what
has been filed is [`docs/upstream-contributions.md`](upstream-contributions.md).
