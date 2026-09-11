# ik_llama.cpp: IQK-quantized DeepSeek-V4 aborts with all-NaN logits under `llama-server` only

Evidence dossier for an upstream report. Measured 2026-09-11. Not yet filed —
the last check (rebuilding on top of a server-side fix merged the same day)
is still outstanding.

## Summary

The ik-specific `IQ4_KSS` quantization of DeepSeek-V4-Flash-0731 aborts at the
first sampled token under `llama-server` with every candidate logit NaN. The
same file, on the same build, with the identical device placement, generates
correctly under `llama-cli`. A standard-quantization GGUF of the same model
works under the server. So the file, the CUDA kernels and the expert split are
each ruled out on their own.

## Environment

| | |
|---|---|
| CPU | Threadripper PRO 5975WX, 256 GB DDR4-3200 |
| GPU | RTX A6000 48 GB + RTX 3090 24 GB, **sm_86** |
| CUDA | 13.0.88 |
| ik_llama.cpp | `3bb386eb` (2026-09-10, `origin/main` tip at the time) |
| Build | `-DGGML_CUDA=ON -DGGML_NATIVE=ON -DCMAKE_CUDA_ARCHITECTURES=86` |
| Failing file | `KeinNiemand/DeepSeek-V4-Flash-0731-IK_GGUF` → `IQ4_KSS` (149 096 451 808 B) |
| Working control | `unsloth/DeepSeek-V4-Flash-0731-GGUF` → `UD-Q4_K_XL` |

Ampere matters: every prior report of this family of aborts was on sm_120,
and the maintainer has noted that sm_120 does not take the same DSA path.

## Test matrix

| # | Binary | Build | File | Placement | Result |
|---|---|---|---|---|---|
| A | `llama-server` | CUDA | IQ4_KSS | `-ngl 99 -ts 2,1`, experts 0–9→CUDA0, 10–14→CUDA1, rest CPU, `-c 65536 -mla 3 -t 32` | **abort** — loads cleanly (CUDA0 35 150 MiB / CUDA1 18 041 MiB / KV 2 752 MiB), dies on the first request |
| B | `llama-server` | CUDA | IQ4_KSS | `-ngl 0 -c 8192` (everything on CPU) | **abort**, identical signature |
| C | `llama-server` | CUDA | IQ4_KSS | `-ngl 0 -rtr -c 8192` | **abort**, identical |
| D | `llama-cli` | **CUDA off** | IQ4_KSS | `-ngl 0 -t 32 -n 8 --temp 0` | **generates** (`ldd | grep -c cuda` = 0) |
| E | `llama-cli` | CUDA | IQ4_KSS | **same `-ot`/`-ts`/`-mla` as A**, `-c 8192 -n 8 --temp 0` | **generates** |
| F | `llama-server` | CUDA | UD-Q4_K_XL | same class as A | **works** — 24.6 tok/s decode, 400 tokens, 259 tok/s prefill |
| G | `llama-server` | CUDA at `7cd62a3e` (the commit the quantizer used) | IQ4_KSS | same as A | **abort** — so not a recent regression; bisect is pointless |

### Signature

```
=============================== Failed to sample token
Data has been stored in probabilities.txt
Crashing now
src/llama-sampling.cpp:745: Fatal error
```

`probabilities.txt` — all 40 candidates NaN, and the logit column itself is
already NaN, so the poison arrives from `llama_decode` rather than being
produced in the sampler:

```
candidates->size: 40
max  = nan
sump = nan
probabilities:
0  38  nan  nan
1  22  nan  nan
2  10  nan  nan
```

### What the matrix rules out

- **Not file corruption** — D and E generate from the same bytes.
- **Not the CUDA kernels** — E is a CUDA build with the identical split.
- **Not expert placement** — B puts everything on the CPU and still aborts.
- **Not a recent regression** — G.

What remains is the intersection: a code path taken only by `llama-server`,
with IQK tensor types. The standard-quantization control file contains none
of `IQ4_KSS`, `IQ4_K`, `IQ4_KS`, `IQ6_K`.

## Prior art

Searched issues and PRs; queries recorded so the absence is checkable.

| Query | Hits | Relevant |
|---|---:|---|
| `llama-sampling.cpp:745` | 8 | #2344, #2186, #1952, #1984 |
| `Failed to sample token` | 77 | #2288, #2344 |
| `all-NaN logits` | 9 | #2344, #2347, #2186, #1623 |
| `is:issue IQ4_KSS NaN` | 3 | #245 (2025, perplexity) |
| `deepseek4 server NaN` | 2 | #2344, #2110 |
| `is:pr llama-server DSV4 sampling` | 0 | — |
| `IQK quant server crash` | 0 | — |

GraphQL discussion search still to run; the REST endpoint returns false zeros
for discussions.

**Closest prior:** [#2344](https://github.com/ikawrakow/ik_llama.cpp/issues/2344),
closed as completed on 2026-09-03. Same abort, reported on sm_120 under agent
traffic, 13 times over 39 hours, with no minimal reproducer. Along the way the
reporter refuted an fp16-overflow hypothesis by measurement (max 366.4 against
a 65504 ceiling over 5.9 B values), and both a cublas-stream fix and a CUDA
downgrade failed to stop it. The root cause reported there was the new-MMA
`FLASH_ATTN_EXT` path emitting NaN for query rows whose mask is entirely
`-inf` when they lead the batch, with `-nkvo` as the trigger.

This report differs on five points: no `-nkvo`, sm_86, 100% deterministic on
the first short request, a working control file of the same model, and a HEAD
newer than the commits that closed it.

Also relevant, and deliberately not built on:
[#2411](https://github.com/ikawrakow/ik_llama.cpp/issues/2411) (a different
server-only DSV4 mask assertion, at `--parallel >= 2`),
[#2186](https://github.com/ikawrakow/ik_llama.cpp/issues/2186), and
[PR #2432](https://github.com/ikawrakow/ik_llama.cpp/pull/2432), merged
2026-09-11 — "server: exclude generation-span checkpoints for DSV4" — which
fixes the server recording a *guessed* prompt coordinate in context
checkpoints and re-feeding cached tokens. That is not in the build tested
here, and it is the most plausible neighbourhood for this bug.

## Related, separable: the draft model fails quietly

With DSpark speculation enabled and the draft context left at the default:

```
llama_prepare_dflash_graph_inputs: failed to initialize DFlash K/V scheduler
draft: DFlash draft decode failed (status=-1 local_pos=24 history_rows=24 capacity=65536)
```

repeating on every decode step, zero accepted tokens, throughput down from
24.6 to 17.0 tok/s. The real cause is `ggml_backend_sched_reserve` failing at
`src/llama-dflash.cpp:536` for a reserve graph sized to `cross_ctx = n_ctx - 5`
(65 531 rows) — that is, out of VRAM. `-cd 8192` resolves it.

Three things make it expensive to diagnose: the message does not mention
memory, the server keeps serving while every draft step fails, and a 0%
acceptance rate is not promoted to a warning. A candidate fix is an error that
names the required bytes and `-cd`, plus disabling the stage after the first
failure instead of retrying forever. Separate PR — not bundled with the above.

## Before filing

- [ ] Rebuild with PR #2432 included and re-test. If it resolves, there is
      nothing to report.
- [ ] GraphQL search of discussions.
- [ ] Reduce to a minimal command line — drop `--jinja`, `--reasoning-format`,
      `-mla`, `-ot`, and shrink `-c` — so a maintainer can run it directly.
- [ ] Confirm a second IK quantization (`IQ2_KS`) fails the same way, to
      support "IQK types generally" rather than "one file".
- [ ] Localize which tensor produces the NaN.
- [ ] No fix submitted on the strength of source reading alone.

The upstream's `CONTRIBUTING.md` tolerates AI assistance, requires it to be
disclosed, and rejects PRs whose *author* is an AI. Commits go out under a
human author with no AI co-author trailer, with the disclosure in the body.
