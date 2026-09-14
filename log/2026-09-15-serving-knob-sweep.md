# Serving knobs, one at a time: the current profile is the optimum of the six

**2026-09-15, 06:34–06:49.** With `llm.service` stopped for the user's own GPU
work, the six-arm sweep that had been queued since the `-ub 4096` change ran
on a quiet machine (`serve-opt.sh`, port 8097). One knob per arm against the
served configuration, each arm a fresh load, then three 400-token greedy
decodes, one 11 929-token prefill and the VRAM after it.

## Arms

Base is the live `llm-serve.sh`: ik_llama.cpp build 4887, DeepSeek-V4-Flash-0731
UD-Q4_K_XL, `-c 32768 -ngl 99 -ts 2,1 -mla 3 -t 32 -b 4096 -ub 4096`, experts
of layers 0–6 on the 48 GB card and 11–14 on the 24 GB card, DSpark draft
(`-cd 8192`, `--spec-type dspark:n_max=3`), `--jinja --reasoning-format none`.

| arm | change | load | decode tok/s (3 × 400) | 11.9k prefill | TTFT | VRAM after prefill (48 / 24 GB card) |
|---|---|---:|---|---:|---:|---|
| **base** | — | 54 s | 26.0 / 26.2 / 26.3 | **478** | 24.9 s | 48 394 / 21 452 MiB |
| rtr | `-rtr` (repack at load) | 54 s | 25.7 / 26.9 / 27.2 | **291** | 41.0 s | 47 766 / 21 288 |
| kvq8 | `-ctk q8_0 -ctv q8_0` | 61 s | 26.7 / 24.2 / 28.3 | 478 | 25.0 s | 47 944 / 21 230 |
| layer5 | layers 11–15 on the 24 GB card | 54 s | (decodes ran) | **crash** | — | — |
| nmax4 | `dspark:n_max=4` | 54 s | 22.2 / 21.9 / 23.6 | 478 | 25.0 s | 48 386 / 21 444 |
| nmax5 | `dspark:n_max=5` | 55 s | 21.3 / 20.4 / 21.0 | 477 | 25.0 s | 48 392 / 21 464 |

## What each one did

**`-rtr` cost 39 % of prefill and bought nothing.** Run-time repacking is
meant for CPU-resident weights; on this profile the CPU experts are already
`_R` types or the repack changes a layout the ik CUDA path then handles
worse. Decode was inside the run-to-run band. Off.

**KV q8_0 changed nothing measurable** at the 12k prompt (prefill 478 → 478,
decode noisy around the same mean) and saved about 450 MiB on the 48 GB
card and 220 MiB on the 24 GB card. At `-c 32768` the f16 cache is not the
constraint, so the saving has no buyer today; it becomes the right knob if
the context is ever raised. Not applied.

**A fifth expert layer on the 24 GB card does not fit with `-ub 4096`.** Load
succeeded (22.6 GB on the card, up from 19.4), the three short decodes ran,
and the 11.9k prefill died allocating the 2 560 MiB compute buffer on that
card (`cudaMalloc failed: out of memory`, then a segfault). The ubatch change
consumed the headroom that a fifth layer would have used; the two are
alternatives, and the ubatch is worth 2.1× on prefill while a layer is worth
about 2 % on decode. Stays at four.

**Longer draft runs slow decode.** `n_max` 4 and 5 lost 15 % and 20 % against
3, the same shape as the DSpark sweep of 2026-09-13: past three drafted
tokens the acceptance falls off faster than the verification batch grows.
Stays at 3.

## Identity across arms

The 400-token thinking answers to the three probe prompts were not identical
across arms — even base and `-rtr` diverged on all three, and the two `n_max`
arms agreed only with each other. That is expected for 400 tokens of greedy
generation through a speculative decoder with different batch shapes and
placements (sub-ulp differences in the logits compound), and it is why the
identity gate in the memory-clock work used 64 tokens and a fixed
configuration. The divergence here is not evidence about any knob; the
answer files are kept (`sopt-ans-{1,2,3}.txt`) but not read as a result.

## Verdict

No change to `llm-serve.sh`. Of the six, one crashes, two lose decode, one
loses prefill, one is neutral. The profile applied on 2026-09-15 06:19 stands
as the best measured configuration of this machine for the served model:
decode 26 tok/s single-stream, 11.9k prefill 478 tok/s, TTFT 25 s.

Not swept: `-ub 2048` (skipped on purpose, 4096 fits), `-t 24/28` (the
memory-clock work saw 32 threads as the cap), `-amb`, `-fmoe` variants and
the draft's own layer placement. Each is a 15-minute arm on the same script.
