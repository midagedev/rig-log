# Porting DeepSeek-V4.1 to ik_llama.cpp

Measured 2026-09-13 on this machine, against ik_llama.cpp at `3bb386eb` and
mainline llama.cpp at `5210c7c`.

The Q3_K_M file runs on mainline today at about 20 tok/s. Everything that
would plausibly make it faster — `-ser`, `-thp`, `-rtr`, the IQ2/IQ3/IQ4_KSS
quants — is ik-only, and ik stops at the first line of the file:

```
llama_model_load: error loading model architecture: unknown model architecture: 'deepseek41'
```

So the question is how far ik actually is, and the useful way to answer it is
not to read the two graph implementations side by side but to ask the model
file what it needs.

## What the file asks for, and what ik already answers

ik has had DeepSeek V4 since `#2165`, and it is not a token implementation:
the DSA indexer, the compressed streams, hyper-connections with Sinkhorn
normalization, MTP, and a compacted sliding-window cache are all there. The
first guess was therefore that V4.1 is V4 plus engram. That guess is wrong,
and the file says so.

Dumping the metadata of both models and diffing the key names — V4 as
`DeepSeek-V4-Flash-0731` UD-Q4_K_XL, V4.1 as our Q3_K_M — the metadata delta
really is only engram:

| keys present in V4.1 and not in V4 |
| --- |
| `engram.head_count`, `engram.key_length`, `engram.layer_ids`, `engram.max_ngram_size` |
| `engram.multipliers`, `engram.offsets`, `engram.primes`, `engram.token_map`, `engram.pad_id` |

Nine keys. Everything else V4.1 declares — the indexer head count and top-k,
the compress ratios, `output_group_count`, `output_lora_rank`, the swiglu
clamps, the hyper-connection count and Sinkhorn iterations — ik's V4 loader
already reads. (The keys V4 has and V4.1 does not are all `general.*`
provenance.)

The tensor names tell a different story. Taking the union of every shard on
both sides and collapsing `blk.<n>.` to `blk.N.`:

| only in V4.1 | only in V4 |
| --- | --- |
| `blk.N.engram_embd`, `engram_k`, `engram_q`, `engram_wkv` | `blk.N.attn_compressor_ape` |
| `blk.N.indexer.attn_k`, `blk.N.indexer.k_norm` | `blk.N.indexer_compressor_{ape,gate,kv,norm}` |
| `blk.N.exp_probs_b_vl` | `blk.N.ffn_gate_tid2eid` |
| | `output_hc_{base,fn,scale}` |

V4.1 did not add a module to V4's attention; it replaced one. The compressor
stack is gone, the indexer reads two tensors under a dotted prefix instead of
four under an underscored one, the hashed-expert map is gone (consistent with
`hash_layer_count = 0` in the metadata), and hyper-connections no longer wrap
the output layer. Mainline needed a separate commit for exactly this
(`f0159e2`, "implement the DeepSeek V4.1 sparse attention"), which is the
signal that reading the metadata diff alone would have missed.

So the port is ~~three~~ four pieces, not one. The tensor delta above lists
`output_hc_*` as dropped and says nothing about what replaces it; the first
build that got as far as a graph found out (below).

## The four pieces

**Registration and hparams.** `LLM_ARCH_DEEPSEEK41`, the nine engram keys,
the tensor list, and the loader-side validation mainline does on the hash
tables. Mechanical.

**The V4.1 sparse attention.** In mainline this is `build_attention_v41()`.
Only a source layer compresses; it pools `ratio` tokens into one row behind a
learned softmax gate, and the layers after it read the same rows through the
cache's reuse callback, so a reading layer builds no compressor at all. Index
keys are taken from the pooled latent *before* it is rotated, because the
rotated form is what lands in the cache. The query is normalized on its
low-rank part only — V4 normalizes again after `wq_b` and V4.1 does not.
Mainline also skips the two-level candidate mask and caps context at 16K in
consequence, which is worth knowing before promising long context.

**Engram.** The index arithmetic is host-side and self-contained: map each
token through `engram.token_map`, fold `max_ngram_size` of them with the
per-layer multipliers into a rolling hash, take it modulo the per-bucket
prime and add the bucket offset. Two layers, eight heads, three n-gram sizes
— 48 rows a token, gathered from `engram_embd` with `get_rows`. The graph
half is more than the gather. `engram_wkv` projects the 48 gathered rows
into one key per hyper-connection stream plus one shared value; the key and
the residual stream are each RMS-normalized per stream and scaled by
`engram_k` and `engram_q`; their dot product goes through a signed square
root and a sigmoid to gate the value, which is then added to every stream.
The gate scales have to stay f32 through quantization, which is what
mainline's `f37da57` is about — and it means ik's `llama-quantize` needs the
same exemption before any of the low-bit quants this port is meant to unlock
can be produced from the fp8 original. That is a separate piece of work and
it is not claimed here.

**The hyper-connection lag — the piece the table missed.** *Added 2026-09-13,
after the first build reached the graph and segfaulted in `ggml_mul_mat`
with a null weight.* The delta table records that V4.1 ships no
`output_hc_{base,fn,scale}`, and the first three pieces treated that as a
tensor to skip. It is a structural change. In V4 each sublayer computes the
mix coefficients it collapses the four stream copies with, and a learned head
collapses them once more at the output. In V4.1 the coefficients lag by one
sublayer: attention collapses with the mix the previous FFN produced, the FFN
with the mix attention produced, layer 0 with a one-hot on the first copy —
and the last FFN's mix, which nothing has consumed, collapses the copies at
the output. That is why the head is absent: its job is already done.
Mainline's `deepseek41.cpp` states this in its header comment; the tensor
diff only shows the shadow. Reading the file told us *what* was missing, not
*why*, and the why was the fourth piece.

## The two gaps that are not in the model file

Both of these are ik-side absences that no amount of reading the GGUF would
reveal, and both are bigger than they look.

**ik's KV cells do not store token ids.** Engram needs the three tokens
preceding each token of the ubatch, and those routinely live in an earlier
decode call. Mainline solves it in the cache: `llama_kv_cache::get_prev_tokens()`
walks back by position and reads the token id off the cell
(`seq_pos_tok_le`). ik's `llama_kv_cell` is `pos`, `delta`, `src`, `seq_id` —
there is nowhere to read it from. Adding the field is small; making it correct
across `seq_rm`, `seq_cp`, defrag, context shift and state save/restore is the
actual work, and getting it wrong produces a model that is subtly wrong rather
than one that crashes.

**ik has no lazy tensor mode.** `grep -rn 'READ_LAZY\|lazy_mode' ik/src ik/common`
returns nothing. Mainline marks `engram_embd` `TENSOR_READ_LAZY`, which is why
84.6 GB of a 347 GB file is never read into memory on this machine. For ik to
land in the same place, three things have to hold, and as of this date none
of them is verified:

1. *No copy.* ik's CPU tensors point into the mapping only while
   `use_mmap_buffer` survives `create_tensors()`; `-mqkv` and merged
   up/gate experts turn it off for the whole CPU buffer, and then every tensor
   is `memcpy`'d (`llama-model-loader.cpp:1114`). Both are off by default.
   This machine has 256 GB; the resident set is already 215 GB, and engram
   copied in is 300 GB. The same arithmetic rules out `-rtr`, which disables
   mmap, unless engram is exempt from the repack.
2. *No read-ahead.* ik calls `POSIX_MADV_RANDOM` on the mapping only under
   `--numa` (`llama-mmap.cpp:338`), whole-file, never per range. Mainline
   applies it to the lazy range specifically. Without it each 5 KiB engram
   row costs a read-ahead window, and the 3.3 ms/token measured on mainline
   grows toward the read-ahead size.
3. *No prefetch.* `--prefetch-experts` and any warm-up pass must skip the
   engram range or they page in 84.6 GB on purpose.

Getting these right is a precondition of the levers, not a refinement of the
port.

## Upstream

ik issue [#2438](https://github.com/ikawrakow/ik_llama.cpp/issues/2438) asks
for V4.1-Flash support and is unassigned. PR
[#2431](https://github.com/ikawrakow/ik_llama.cpp/pull/2431) is V4 *vision*,
still open, and is a different change. Searching PRs and issues for
`deepseek41`, `V4.1` and `engram` finds nothing else; the two "4.1" hits in
the commit log are `oneapi 2024.1`.

The mainline implementation is by `vcruz305` — `bea3b8c` (arch, engram,
hyper-connections), `5594f56` and `8333cb4` (stream layer roles), `b6ae514`
(ratios from the model), `f0159e2` (sparse attention), `f37da57` (keep the
engram gate scales out of quantization).

Vision is out of scope here. `exp_probs_b_vl` is present in the file and the
loader has to tolerate it, but this machine is running text.

## The correctness gate

~~mainline on port 8001 is the oracle. ik at `-ngl 0` runs beside it against
the same file and shares page cache, so neither `--no-mmap` nor `-rtr` may be
used while comparing. Fixed prompt, greedy, compare the first 50 tokens.~~

*Revised 2026-09-13 before the first run.* A greedy token comparison is a
weak gate: two builds can agree on fifty tokens of a common prompt with a
broken layer, and disagree at the first tie because of kernel rounding. The
gate is wikitext-2 perplexity instead, both builds CPU-only against the same
Q3_K_M file, and it has a FAIL-first requirement: the port must first
produce a number that is wrong, so the gate is known to measure something.
It did. The run is in
[`log/2026-09-13-deepseek-v41-on-ik-llama.md`](../log/2026-09-13-deepseek-v41-on-ik-llama.md).

| build | wikitext-2 PPL, 4 chunks, n_ctx 2048 |
| --- | --- |
| mainline `llama.cpp` (oracle) | 2.2438 ± 0.0631 |
| ik, after the hyper-connection fix, before the q fix | 244.72 ± 12.03 |
| ik, after the q fix | 2.2258 ± 0.0622 |

Four chunks is a smoke gate, not a benchmark. The per-chunk numbers track
mainline within 0.02 at every chunk (1.72/1.73, 1.75/1.76, 1.82/1.84,
2.23/2.24); the full test set, `-ngl` above zero, and a batch of one are still
to be run.
