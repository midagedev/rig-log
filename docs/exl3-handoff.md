# Handoff: ExLlamaV3 per-expert CPU offload on GLM-5.3-Flash (2026-09-15)

For whoever picks this up next (a delegated session included). Everything
below is on the workstation unless marked; paths are literal. The rules
that apply: no hostnames or addresses in this repo; benchmarks on a quiet
machine (`docs/quiet-machine.md`); signal only pids you spawned or read
from a pid file, never by command-line pattern; do not edit a running
script — copy it under a new name; the GPUs are shared with another
session's vocoder training (nightly from 00:00 KST, open-ended into the
morning — check `nvidia-smi` and ask before assuming a card is free);
`llm.service` is stopped and disabled by the user's decision, do not
re-enable it unasked.

## Why this exists

The GLM-5.3-Flash log (`log/2026-09-15-glm-5.3-flash-first-run.md`)
ends at 18.7 tok/s on ik_llama.cpp with ten expert layers on the cards,
20.9 with the model's own MTP draft, and a graft line that traded KLD for
bytes at a rate no serving profile would take. The next lever in that log
is placement-aware quantization/placement from a routing histogram
(WKS-29). Research the same day found that ExLlamaV3 1.4.3+ already does
per-expert placement between VRAM and RAM at runtime (`-mcs`), that PR
turboderp-org/exllamav3#315 (open) adds precomputed placement profiles
and measured 17 → 33 tok/s on a 96 GB card + AVX-512 desktop for this
exact model, and that turboderp published a 4.05 bpw EXL3 of it with the
`mul1` codebook the CPU path requires. So before building our own, the
competing baseline gets measured on this box.

## What is in place

- Model: `/models/GLM-5.3-Flash-exl3-4.05/` — turboderp/GLM-5.3-Flash-exl3,
  branch `4.05bpw`, 23 files, 154 GiB, every file size-checked against the
  HF manifest and sha256-verified before rename (`logs/fetch_one.sh`; the
  fetch scripts, shard lists and per-file `.log`s all live in `logs/` since
  2026-09-15 evening, so the top-level non-hidden files are exactly the
  published repo: 30 files, 165 151 541 665 bytes. The hidden entries are
  the downloader's 0-byte `.lock` files and `.gitattributes`). Experts uniform 4 bpw, mul1
  codebook (36 288 modules, 142 GiB); attention/shared 5–6 bpw, 5.5 GiB.
- Engine: `~/.venv-exl3` — exllamav3 1.5.0 (GitHub wheel `+cu128.torch2.10.0`),
  torch 2.10.0+cu128, jinja2. Source checkout for the examples:
  `~/exllamav3-src` at v1.5.0 (`examples/` is not in the wheel).
- Bench: `~/exl3-bench.py` (copy in `tools/exl3/`). Loads through
  `exllamav3.model_init` so every CLI flag of the examples works (`-m -gs
  -mcl -mcs -mct -cs -mtp …`), renders the model's own `chat_template.jinja`
  (needs the `loopcontrols` extension), then greedy 400-token decode ×3
  and one 11 429-token prefill (wiki.test slice, same probe as the ik
  rows), printing tok/s from the Job result timings. Prints
  `EXL3_BENCH_OK` on success. It must keep its `if __name__ == "__main__"`
  guard: the CPU worker is a spawned process that re-imports the script.
- Runner: `~/exl3-run4.sh` (copy in `tools/exl3/exl3-run.sh`): waits for
  both GPUs under 2000 MiB, runs the arms with `-cs 32768`, logs to
  `~/exl3-<tag>.log`, prints a sentinel `EXL3_RUN4_DONE`. Copy under a new
  name to change the arms.

## Measured so far

| arm | placement | decode ×3 | prefill 11.4k | VRAM 48 / 24 GB card |
|---|---|---|---|---|
| ik main, UD-Q4_K_XL, all experts CPU | — | 17.0 | 320 | 15.7 / 10.6 |
| ik main, UD-Q4_K_XL, L7+3 | 10 layers on cards | 18.7 | 353 | 32 / 23 |
| exl3 1.5.0, `-gs 44,21 -mcl 30 -mct 32` | first 30 of 42 MoE layers on CPU, 12 on GPU 0 | 16.9 / 17.5 / 17.5 | 241 | 42.8 / 8.6 (3090 unused) |
| exl3 `-mcs 170` | 118 experts a layer on GPU | did not load: "Insufficient VRAM in split for model and cache" (118/288 × 142 GiB = 58 GiB) | | |
| exl3 `-mcs 230 / 210 / 195` | 58 / 78 / 93 experts a layer on GPU, dynamic placement | running at handoff (`~/exl3-run4.log`) | | |

Reading so far: the layer-split mode lands in ik's league (17.5 vs
17.0–18.7) on an AVX2-only CPU (5975WX has no AVX-512; the cited 33 tok/s
was on a Zen 5 with the `vbmi` tier), with a 30 % slower prefill. The
per-expert mode is the question — and PR #315 says the runtime's own
dynamic placement converges slowly (64 experts moved every 128 steps),
so a 400-token probe may measure the *unconverged* state; a longer run
(2–4k tokens) or the PR's precomputed profile is needed before calling it.

## State after the second and third windows (15:30)

Recorded in the log's ExLlamaV3 sections; short form:

- `-mcs` dynamic placement works and beats ik: `-mcs 185` (103 experts a
  layer resident, VRAM 43.5/20.5) 23.3 tok/s draft-free on one text,
  20.7 on a five-prompt mixed cycle (`exl3-bench2.py`), prefill 361–373.
  `-mcs 175` does not fit `-gs 44,21` with a 32k cache. Convergence takes
  ~1.2k tokens; the run-to-run climb is placement, not warm-up.
- `-mtp` at the default depth 3 loses (20.6, 47 % accepted); depth 1
  (`exl3-bench3.py --draft_n 1`) gives **25.4** at 77 %. Depth 2 24.0,
  dynamic pruning 22.4. Upstream candidate, see
  `docs/upstream-contributions.md`.
- `-mct 48` is slower than 32 (22.1 vs 23.3).
- Greedy output differs between visits of the same prompt as the
  placement moves; same class as ik's near-tie flips, not a bug.

Static placement (17:40): the `can_defer_load` guard bug is confirmed
and filed (exllamav3#376). The workstation venv runs the **stock** 1.5.0
file again (restored for the recorded take); the patched copy is
`~/block_sparse_mlp_cpu.py.patched`, the original backup
`~/block_sparse_mlp_cpu.py.v150.bak`. Static placement on the stock file
needs `EXL3_MOE_CPU_SPLIT` set equal to `-mcs`. The unit test lives in
`~/exllamav3-src/tests/` and `~/exl3-guardtest/tests/` (the second is
what runs against the wheel; pytest is installed in the venv). Runners
`exl3-run11..13.sh` (11: histogram + static at 185, 12: three arms at
250, 13: the real patch). Open: a static profile at `-mcs 185` needs
`-gs` headroom for the router tensors — sweep `-gs`.

The `exl3-run*.pid` files hold the `sudo … bash -c` wrapper's pid, not
the runner's; the runner is its child (`pgrep -P`). Runner copies: `tools/exl3/exl3-run5..8.sh`, bench variants
`exl3-bench{,2,3,4}.py` (4 = mixed prompts + draft flags).

## Next steps, in order (revised)

1. Read `~/exl3-run8.log` (depth-1 MTP on the mixed cycle) — that is the
   serving steady-state number to quote.
2. PR #315 precomputed profile on top of `-mcs 185 -mtp --draft_n 1`:
   the question is how much a profile adds over dynamic on *mixed* text.
3. Coding prompt with depth 1 (acceptance was 97 % on ik) for the clip
   number; a toktape take if it clears 27.
4. Upstream: prior-art search on exllamav3 issues/PRs for draft depth
   with `-mcs`, then file with the table.
5. Then the original list below, where still relevant.

## Next steps, original

1. Read `~/exl3-run4.log`. If an `-mcs` arm loads, note VRAM and decode;
   the interesting number is decode after the placement has moved (run
   the probe with `--runs 10` and watch whether the last runs beat the
   first).
2. Use the 3090: the `-gs 44,21` split left it at 8.6 GB in layer mode.
   Try `-gs 40,21` or per-device options; in `-mcs` mode the resident
   experts are spread by autosplit — check `nvidia-smi` per arm.
3. Set `EXL3_MOE_CPU_MAX_ISA` is not needed (auto-detects `avx2`); do
   confirm the tier from the worker's startup lines in the arm log.
4. If dynamic placement does not beat ik's 18.7 within a few thousand
   tokens, try PR #315: `git fetch` the PR head into `~/exllamav3-src`,
   `pip install -e .` into the venv (needs the CUDA toolchain; the wheel
   path is easier if the PR ships one), build a profile on the same
   wiki/coding prompts, run with `--moe_cpu_profile`.
5. Record every arm in `log/2026-09-15-glm-5.3-flash-first-run.md`
   ("ExLlamaV3" section) and on WKS-29; comparisons must be same-window,
   same probe, quiet machine (`/proc/pressure/io` avg10 at start in the
   row).

## Open items from the same day, not for this handoff

- `-np 2` with ik's MTP draft (PR #2399 merged locally in
  `~/ik-glm53-mtp`) kills the server at load; reproduce with the log kept.
- Graft files `/models/GLM-5.3-Flash-graft{B,C,D}/` (184 GiB each) exist;
  B is the one with a use (Q6_K on-card, KLD 0.013); C and D were
  ablation arms and can go when disk is needed — user's call.
- The NVMe write crawl after half a terabyte of writes is unexplained
  (not thermal; counters in the log).
