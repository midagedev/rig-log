# ik_llama.cpp: IQ4_KSS expert tensors produce all-NaN logits on DeepSeek-V4-Flash

Evidence for an upstream report. Measured 2026-09-11 on the machine in
[the README](../README.md).

> **Correction, same day.** An earlier version of this page said the abort was
> specific to `llama-server`, with `llama-cli` as a working control. That was
> wrong. The control had been run at `--temp 0`, which takes an argmax and
> therefore never reaches the code that aborts — it produced *empty output*
> that looked like success. At any temperature above zero `llama-cli` aborts
> identically. The bug is in neither binary; it is in the weights as read by
> the CPU matmul. Everything below is the corrected account.

## Summary

The `IQ4_KSS` quantization of `DeepSeek-V4-Flash-0731` yields NaN out of the
routed-expert matmul. The NaN then propagates to the logits, and every
candidate is NaN by the time the sampler runs.

- Reproducible **CPU-only** — no CUDA involved in the computation.
- Reproducible under both `llama-server` and `llama-cli`.
- The file is **byte-identical to what the publisher released**
  (sha256 `666f5e87…b08b2fc`, 149 096 451 808 bytes), so this is not a
  damaged download.
- Which layer produces the first NaN depends on the prompt, i.e. on which
  experts route — layers 1, 13 and 16 observed from four prompts.
- A standard-quantization GGUF of the same model, same machine, works.

## Minimal reproducer

```bash
llama-server -m DeepSeek-V4-Flash-0731-IQ4_KSS.gguf -ngl 0 -c 8192 -t 32

curl -s http://127.0.0.1:8080/completion \
  -d '{"prompt":"Hello","n_predict":64,"temperature":0.7}'
```

```
=============================== Failed to sample token
Data has been stored in probabilities.txt
Crashing now
src/llama-sampling.cpp:745: Fatal error
```

`probabilities.txt` — all 40 candidates NaN, and the logit column is itself
NaN, so the poison arrives from `llama_decode` and is not produced in the
sampler:

```
candidates->size: 40
max  = nan
sump = nan
probabilities:
0  38  nan  nan
1  22  nan  nan
2  10  nan  nan
```

Nothing else is needed: no `--jinja`, no template, no `-ot`, no `-mla`, no
GPU. `-ngl 0` is enough, which is what makes this cheap for anyone with the
file and enough RAM to hold it.

### Temperature decides whether you see it

| Sampling | Result |
|---|---|
| `temperature: 0` | **no abort** — N tokens "generated", output empty |
| `temperature: 0.7` | abort at `llama-sampling.cpp:745` |

Greedy sampling takes the argmax of an all-NaN row, gets an index, and emits
a token that renders as nothing. So the failure mode at temperature zero is
silent wrong output, not a crash. This is why the first pass at this bug
reached the wrong conclusion.

## Where the NaN starts

`llama-eval-callback` prints every tensor with its sum; the first `nan` in
that log names the operation and its inputs.

```
ggml_debug: ffn_norm-13 (reshaped)  = (f32) RESHAPE(...)      sum = 17.986420
ggml_debug: ffn_moe_weights_scaled-13 = (f32) SCALE(...)      sum = 1.500000
ggml_debug: ffn_moe_gate_par-13    = (f32) MOE_FUSED_UP_GATE(
                blk.13.ffn_up_exps.weight{4096, 2048, 256, 1},
                blk.13.ffn_gate_exps.weight{4096, 2048, 256, 1}) = {2048, 6, 1, 1}
                                                              sum = -nan
```

Both inputs to the expert matmul are finite; its output is not.

**Not the fused kernel.** With `-no-fmoe` the first NaN moves to
`ffn_moe_up-13 = MUL_MAT_ID(blk.13.ffn_up_exps.weight, ffn_norm-13)` — a
plain matmul over the same tensor. The fused up-gate path is exonerated.

**Not a single bad tensor.** The layer moves with the prompt:

| Prompt | First NaN |
|---|---|
| `Hello` | `ffn_moe_gate_par-13` |
| `The capital of France is` | `ffn_moe_gate_par-13` |
| `def quicksort(arr):` | `ffn_moe_gate_par-16` |
| `안녕하세요` | `ffn_moe_gate_par-1` |

Six of 256 experts fire per token per layer, so this tracks routing: it is
whichever experts that token selects, in whichever layer selects a bad one.

**Not the type alone.** Layers 0–12 compute correctly with `IQ4_KSS` expert
tensors; layer 13's are the same type. The file's expert tensors are 91
`IQ4_KSS`, 36 `IQ4_KS`, 2 `IQ4_K`.

A finite-valued f32 accumulation over 4096 products cannot produce NaN, so
some dequantized weight must be `inf` or `nan`. That leaves two candidates,
and distinguishing them needs the type's author:

1. the published file contains blocks whose `IQ4_KSS` payload dequantizes to
   a non-finite value — a quantizer problem, not an engine one; or
2. the `IQ4_KSS` CPU dequant/matmul mishandles a bit pattern that occurs
   throughout this file.

## Environment

| | |
|---|---|
| CPU | Threadripper PRO 5975WX, 256 GB DDR4-3200 |
| GPU | RTX A6000 48 GB + RTX 3090 24 GB, sm_86 (unused at `-ngl 0`) |
| CUDA | 13.0.88 |
| ik_llama.cpp | `3bb386eb` — `origin/main` tip on this date |
| Build | `-DGGML_CUDA=ON -DGGML_NATIVE=ON -DCMAKE_CUDA_ARCHITECTURES=86` |
| Failing file | `KeinNiemand/DeepSeek-V4-Flash-0731-IK_GGUF` → `IQ4_KSS` |
| Working control | `unsloth/DeepSeek-V4-Flash-0731-GGUF` → `UD-Q4_K_XL` |

Flags that do **not** change the outcome: `-no-fmoe`, `-rtr`, `-mla 0`.

## Prior art

Queries recorded so the absence is checkable.

| Query | Relevant |
|---|---|
| `llama-sampling.cpp:745` | #2344, #2186, #1952, #1984 |
| `Failed to sample token` | #2288, #2344 |
| `all-NaN logits` | #2344, #2347, #2186, #1623 |
| `is:issue IQ4_KSS NaN` | #245 (2025, perplexity) |
| `deepseek4 server NaN` | #2344, #2110 |
| `IQK quant server crash` | — |

Closest prior: [#2344](https://github.com/ikawrakow/ik_llama.cpp/issues/2344),
closed 2026-09-03 — the same abort, reported on sm_120 under agent traffic,
no minimal reproducer, root-caused there to the new-MMA `FLASH_ATTN_EXT` path
emitting NaN for all-`-inf` mask rows with `-nkvo` as the trigger. This is
not that: no `-nkvo`, no CUDA in the computation at all, deterministic on the
first short request, and localized to the expert matmul rather than
attention.

[PR #2432](https://github.com/ikawrakow/ik_llama.cpp/pull/2432) was **closed,
not merged** — an earlier version of this page assumed otherwise and listed a
rebuild as the blocking next step. There was nothing to rebuild.

## Why this is an issue and not a pull request

The cause is not established: the evidence narrows it to non-finite values
coming out of `IQ4_KSS` expert weights, but not to whether the file or the
kernel put them there. Distinguishing those needs a reference dequantization
of one offending block, and the type's author can do that faster than a
reproduction can. Filing a fix on the strength of source reading alone is
exactly what the
[method](upstream-contributions.md) forbids.
