# Every model that survived the storage pass, re-run on the box it now is

*2026-09-16, 07:28–08:30.* This morning's storage pass deleted 1.3 TB under one
rule: a file stays if an upstream PR needs it to be reproduced
([`31d3b55`](../docs/v41-experiment-plan.md)). That rule is only worth anything
if the files that stayed still produce the numbers they were kept for, and the
box they are on is not the box they were measured on: since those numbers were
taken the A6000 has moved slots, the memory clock has gone 3600 → 3200 → 3600,
and the case has been open twice. So each kept file was loaded once, on the
same runner, with the same prompt and the same recorder as its recorded row,
and the number written next to the recorded one. The chain ran strictly one job
at a time behind the GPU lease, each job's I/O pressure recorded at start
(`quiet: io avg10=…` in the chain log), nothing else on the machine.

## The first finding was not in a model

With `CUDA_DEVICE_ORDER=PCI_BUS_ID`, CUDA0 is the lowest bus address. The A6000
used to sit at bus 01 and the 3090 at 41; the A6000 is now at 61. **CUDA0 had
become the 3090**, and every placement in this repo — the `-ot` strings that put
four expert layers and the compute buffer on CUDA0, `-ts 2,1`, the ExLlamaV3
`-gs 44,21` — was about to load 44–46 GB onto a 24 GB card. The training job
that shares this box found it first, the hard way: `CUDA_VISIBLE_DEVICES=0` put
a 38 GB run on the 3090 and it OOMed at step 52000.

The fix is one sourced file, [`configs/gpu-order.env`](../configs/gpu-order.env):
`CUDA_VISIBLE_DEVICES=<A6000 UUID>,<3090 UUID>`. CUDA enumerates the listed
devices in list order and accepts UUIDs, so one line pins the index for
llama.cpp, ik_llama.cpp, ExLlamaV3 and torch, and survives the next slot move or
a third card. `nvidia-smi` ignores it and is addressed with `-i <UUID>`. Reading
the file is not the test; the first two loads were. The served V4.1 file put
45.8 GB on the A6000 and 20.0 GB on the 3090, and the ExLlamaV3 `-gs 44,21` put
43.8 GB on the A6000 — both read back by UUID, both the intended split. Full
account in [the 09-16 fabric log](2026-09-16-the-overclock-and-the-fabric.md).

## The numbers came back

| kept file | kept for | recorded | **today** | runner |
|---|---|---:|---:|---|
| `DeepSeek-V4.1-Flash-Q3_K_M` 324 G | PR #2455 perplexity baseline | 2.2355 ± 0.0626 | **2.2355 ± 0.0626** (chunks 1.7393 / 1.7633 / 1.8389 / 2.2355) | `ik-v41-verify.sh`, CPU only, 32 threads |
| `…-engramQ8-tokembdBF16-attnQ8` 445 G (served) + `DSpark` 23 G | the serving configuration; the draft PR | 25.2 tok/s drafted, warm | 18.1 / 21.1 / 21.5 cold, **23.8 / 25.05 warm**; acceptance 119/238 | `ik-v41-verify.sh` draft arm at the served seven-layer `-ot`, `--lazy-mode auto`; load 3 min 40 s |
| `Qwen3.6-35B-A3B-UD-Q4_K_XL` | the one-card entry; WKS-25 | 140 tok/s | **140 tok/s** (≈386 GB/s) | `ik-vram-take.sh`, A6000 by UUID, `-n 400` |
| `Qwen3.6-35B-A3B-UD-Q6_K` | same entry; the toktape hero take | 132 tok/s | **132 tok/s** (≈392 GB/s) | same |
| `small/Qwen2.5-7B-Instruct-Q3_K_M` | the dense control in that entry | 118 tok/s | **117 tok/s** (≈417 GB/s) | same |
| `small/DeepSeek-V2-Lite-Chat.Q3_K_M` | the small MoE probe | — | 202 tok/s (≈264 GB/s) | same, `-c 8192` |
| `GLM-5.3-Flash-exl3-4.05` 154 G | the ExLlamaV3 MTP draft-depth reproducer | 22.0 tok/s | **22.4 tok/s**; load 66 s | `exl3serve-take.sh`, `-gs 44,21 -mcs 185 -mtp`, one stream |

Six of seven recorded numbers came back exactly or within one token a second; the
served decode's warm rows bracket the recorded 25.2. The cold rows are the engram
rows being read off NVMe for the first time since the reboot (WKS-20 measured that
cost at 6.8 % of decode on fresh text; here the first prompt paid more because
the page cache was empty of the whole 445 GB file, not only the rows). The
perplexity match to four decimals is the strongest line in the table: it is a
deterministic CPU computation on the same bytes, so it also says the 324 GB on
the new NVMe is the same 324 GB the PR was verified on.

The draft acceptance reads 50 % here against the 61 % recorded for the same file.
The two are not the same measurement: the verify runner sends three short
prompts with `n_predict 200` at temperature 0 through `/completion`, the
recorded figure is the twenty-prompt served set through the chat endpoint. It
is noted, not struck, and the twenty-prompt set is the place to check it if it
matters.

## The sources, which cannot be run

Three of the kept directories are sources, not servable files: the fp8 release
(476 G, the only local requantization source), the uploader's Q8_0 set (285 G,
the engram and MXFP4 graft source) and the plain Q3_K_M, which is both a
baseline and a graft base. For those the test is bytes, run last so its I/O
pressure (avg10 8–10 while hashing) did not sit under any measurement:

| directory | what was checked | result |
|---|---|---:|
| `DeepSeek-V4.1-Flash-Q3_K_M` | `sha256sum -c SHA256SUMS`, 9 shards, 324 G | 9 OK, 5 min |
| `DeepSeek-V4.1-Flash-fp8` | the 48 safetensors against the release `MANIFEST` sha256 | 48 OK, 8 min |
| `DeepSeek-V4.1-Flash-Q8_0-engram-src` | shards 8–10 against the LFS oids in `paths-info.json` (220 G); shards 1–2 have no oid on file, header parse only | 3 OK; 1–2 parse, 18 tensors each |
| `…-attnQ8-exp8MXFP4` | the nine shards parse; expert tensors of blk 0–7 by dtype | 24 tensors, all `MXFP4` — the graft WKS-18 stage 1 describes |

Nothing was struck. The 1.9 TB that stayed is the 1.9 TB that was measured.

## Two clips for the recorder

The pass ended with three takes for [toktape](https://github.com/midagedev/toktape),
all on its `0.2.3-2-g0f88bd3` build, the A6000 selected by UUID, tapes sanitized
into `assets/` (hostname only):

| take | prompts | decode | prefill | note |
|---|---|---:|---:|---|
| `qwen36-35b-a3b-q6k-4stream-short-prompts` | four tasks, 65 tokens each, `-np 4`, `-n 512` | 149 aggregate, 37.6 each | not a measurement (under 100 tokens) | TTFT p50 1.3 s |
| `qwen36-35b-a3b-q6k-4stream-hero` | the same four padded to 234 tokens | 149 aggregate, 37.5 each | 149 aggregate, 56.1 each | TTFT p50 6.2 s: four prefills close to serial on `-np 4` |
| `qwen36-35b-a3b-q4kxl-1stream-long` | one design-document prompt, 252 in, `-n 4096` | 136 | 1066, TTFT 273 ms | 36 s of output; A6000 80 °C at 298 W by the end |

The single-stream clip replaces the 7-second one from 09-15, which ended before
a viewer could read it; this one fills its 4096 tokens in 36 seconds with the
code blocks forming on screen. The four-stream card on that build printed the
bandwidth as 112 GB/s, 15 % of peak — active bytes times the *per-stream* rate.
The recorder's session traced it the same hour: for a batched MoE the honest
figure is a range, 2.138 GB always-read plus 0.832 GB of routed experts per
token, so 112 GB/s if all four tokens pick the same experts and 206 if none do,
and the card is being changed to print that range. The one-stream ratio (373
GB/s, 49 %) was right on the same build.
