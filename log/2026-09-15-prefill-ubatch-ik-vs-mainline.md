# Prefill on the served model: the ubatch is worth 2.1×, the engine 1.15×

**2026-09-15, 05:58–06:10.** A side effect of chasing a fork-only abort
(`docs/checkpoint-restore-dsv4.md`, last section): mainline llama.cpp
prefilled an 11.9k-token prompt on the served DeepSeek-V4-Flash file at 434
tok/s with `-ub 4096`, while the serving profile runs `-ub 1024`. That
deserved a proper A/B on one model, one placement, no draft.

## Setup

Same everything except the engine and the ubatch: DeepSeek-V4-Flash-0731
UD-Q4_K_XL (145 GB), `-c 32768 -ngl 99 -t 32`, experts of layers 0–6 on the
48 GB card and 11–14 on the 24 GB card, the rest on the CPU, no draft model,
`--jinja`. One 11 929-token prompt (a 50 000-character slice of
wikitext-2), 32 output tokens, two runs per arm (`cache_prompt` off, so the
second run is a warm repeat, not a cache hit). Quiet machine, `llm.service`
stopped, one arm at a time (`prefill-ab.sh`, `prefill-ab2.sh`). Mainline is
master 41abbfd (2026-09-14); ik_llama.cpp is build 4887 (3ded8071), with
`-mla 3` as the serving script uses.

## Result

| engine | `-b`/`-ub` | prefill tok/s (run 1 / 2) | TTFT | decode tok/s | VRAM 48 GB / 24 GB card |
|---|---|---|---|---|---|
| mainline | 1024 | 191.5 / 189.5 | 62.3 s | 22.1 | 30.6 / 16.8 GB |
| mainline | 4096 | 433.7 / 431.8 | 27.5 s | 22.0 | 31.1 / 18.6 GB |
| ik_llama.cpp | 1024 | 235.6 / 236.2 | 50.6 s | 22.3 | 30.0 / 17.5 GB |
| ik_llama.cpp | **4096** | **495.8 / 500.4** | **24.1 s** | 22.6 | 32.8 / 19.0 GB |

Two things, both clean. Going from `-ub 1024` to `-ub 4096` gives 2.27× on
mainline and 2.11× on ik, and costs 0.5 and 2.8 GB of VRAM respectively;
decode does not move. And ik is 1.15–1.24× faster than mainline at the
same ubatch on this hybrid path — the opposite sign from the 2026-09-13
CPU-heavy V4.1 comparison, where ik trailed on prefill by a quarter; this
is a different model with most of the bytes on the CPU experts but the
attention on the cards, and the number is what it is.

## What it means for serving

The serving profile (`llm-serve.sh`: ik, `-b 2048 -ub 1024`, DSpark draft)
has been leaving half of its long-prompt prefill on the table. The card
budget allows the change: the serving run sits at 40.3 GB on the 48 GB card
with the draft loaded, and `-ub 4096` asks 2.8 GB more. Expected on the
served configuration: 11.9k prompt TTFT from about 50 s to about 24 s;
short prompts unchanged (their floor is the per-prefill expert copy, not
the batch). Not applied yet — serving changes are the user's call.

The "prefill 54 tok/s" that the decode probes have been printing for the
served model is not a prefill rate: those prompts are ~30 tokens, and the
figure is the fixed per-prefill cost divided by a tiny count. A long-prompt
prefill on the served configuration has not been measured with the draft
loaded; the row above without the draft is the nearest thing.

## Not measured

- The same four arms with the DSpark draft loaded (VRAM and any prefill
  interaction with the draft's own prefill).
- `-ub 2048` (the fork's coding profile used it; on this model the 4096 row
  fits, so the intermediate point was skipped).
- ~~Whether `GGML_OP_OFFLOAD_MIN_BATCH` exists on ik.~~ It does not, and the
  question is moot: ik's `ggml_backend_cuda_offload_op` already scales the
  offload threshold for MoE by `total_experts / active_experts` (a batch
  must carry `min_batch × 256 / 8` tokens before RAM-resident experts are
  copied to the card), so the short-prompt PCIe floor measured on the
  mainline-derived fork (WKS-27, 7.7 s) is not on the ik serving path in
  the first place — which is why the served model answers a 30-token prompt
  in half a second. The 768 threshold stays a fork/mainline setting.
