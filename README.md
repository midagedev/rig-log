# rig-log

A build log for one workstation: what it can actually do, measured.

The plan is to point it at every generative workload that fits on local
hardware — large language models first, then video, images, and audio — and
write down the numbers instead of the vibes. Every entry carries the exact
command line, the measured throughput, and the thing that turned out to be
wrong.

Running unreleased models on mismatched hardware walks into other people's
untested paths, so the second half of this log is what got sent back:
[how a failure here becomes an upstream report](docs/upstream-contributions.md),
and the record of what was sent.

![Qwen3.8-Flash-Next decoding at 51 tok/s with both cards and system RAM in the panel beside it](assets/qwen38-flash-next-q4kxl-1stream-tail-0.2.3-5.gif)

*Qwen3.8-Flash-Next on this machine: 125 B parameters plus a 51 B n-gram table,
103.7 GiB at UD-Q4_K_XL, decoding **51.0 tok/s with no draft model** — twice
what the served DeepSeek-V4.1 manages with one, out of a quarter of the bytes.
It still does not fit on the cards: 20.5 GiB is on the 3090, 46.6 on the A6000
and 39.7 in system RAM, which is what the panel on the right is showing while
it runs. [Full write-up.](log/2026-09-16-qwen38-flash-next-and-coder-next.md)*

![Qwen3-Coder-Next answering a coding prompt at 133 tok/s from a single card](assets/qwen3-coder-next-iq4xs-1stream-tail-0.2.3-5.gif)

*The other end of the same box, and the fast half of the pair it can serve:
Qwen3-Coder-Next at IQ4_XS is 39.7 GiB, fits one A6000 with 32k of context, and
decodes **133 tok/s** — 297 GB/s of derived read, 39 % of the card. The 3090 is
at 0.0 GiB in that frame; nothing was split.
[Full write-up.](log/2026-09-16-qwen38-flash-next-and-coder-next.md)*

Both clips are the **closing window** of their run, ending on the card that
carries the numbers: **21.8 s of a 47.7-second recording** for the first and
**15.9 s of a 37.2-second one** for the second, measured by summing the stored
per-frame delays rather than dividing frames by a nominal rate — the frames do
not run at a uniform 1/30, so the two are not the 20 and 14 seconds a frame
count suggests. They are cut, never sped up: every frame is at 1:1 and the head
was removed from the finished GIF frame by frame, because compressing a run into
a shorter clip would hide a stall and is a lie about the machine. Recorded and
rendered with [toktape](https://github.com/midagedev/toktape) `0.2.3-5-g9bf4e52`,
which is what the filenames carry — the recorder build, not the rate and not a
duration, both of which belong in prose where they can be corrected.

Before those two there was a 347 GB model with 84 GB of it never read into
memory at all, served off an NVMe a few dozen rows at a time at about 20 tok/s,
and that is still the most unusual thing here:
[DeepSeek-V4.1-Flash's first run](log/2026-09-12-deepseek-v41-first-run.md),
and [what its conditional-memory tables cost](log/2026-09-16-engram-and-concurrency.md).

[![The four tiers the served model sits in, and what the second card is worth](assets/placement-sheet.png)](assets/placement-sheet.png)

*The served profile as one sheet: which tier holds each of the forty layers'
routed experts, the two engram tables that are never placed anywhere, and the
four-arm run that priced the second card. Source and re-screenshot instructions
are [`assets/placement-sheet.html`](assets/placement-sheet.html).*

## The machine

Current state. What each of these used to be, and the run that changed it, is
in [`docs/machine-changes.md`](docs/machine-changes.md).

| | |
|---|---|
| CPU | AMD Ryzen Threadripper PRO 5975WX, 32 cores / 64 threads. Boost disabled, no clock cap |
| Memory | 256 GB DDR4-3600 at DRAM 1.30 V — 32 GB × 8, all 8 channels, Samsung M378A4G43AB2-CWE 2Rx8 UDIMM, **non-ECC** |
| Measured memory read | **147.7 GB/s** (32-thread, 8 GiB read probe); 230.4 GB/s theoretical. A second probe reads 144.8, and that is the one toktape's host percentages are derived against |
| GPU 0 | NVIDIA RTX A6000, 48 GB, bus 61 |
| GPU 1 | NVIDIA GeForce RTX 3090, 24 GB, bus 41 |
| Device order | **By UUID, never by slot.** Every runner sources [`configs/gpu-order.env`](configs/gpu-order.env), which pins `CUDA_VISIBLE_DEVICES=<A6000 UUID>,<3090 UUID>` so CUDA0 is the 48 GB card whatever the bus addresses are. `nvidia-smi` does not honour that variable and is addressed with `-i <UUID>` |
| Board | ASUS Pro WS WRX80E-SAGE SE WIFI |
| Storage | Samsung 980 PRO 2 TB NVMe (root) + Phison E18 4 TB NVMe (`/models`) |
| Case | 3RSYS T840 |
| Power | Super Flower Leadex Platinum SF-2000F14HP, 2000 W |
| Cooling | ARCTIC Freezer 4U-M tower air cooler on CPU_FAN. **No chassis fan is on a header** — the case fans are wired to the PSU, so all six `CHA_FAN` channels read `Disabled`. Fan RPM and per-slot temperature are readable only through the BMC (`ipmitool sdr type fan`, `sdr type temperature`; the `PCIE0n` sensors read when the GPU driver cannot) |
| OS | Ubuntu 24.04, kernel parameter `pci=realloc=off` |

Four things about it that cost a day each, and are still true:

- **`pci=realloc=off` is required.** Without it the kernel reassigns PCI
  resources, the chipset USB controller fails with `xhci init -16`, and the
  10 GbE ports go down. `pci=nocrs` "fixes" USB and breaks the NVIDIA driver
  instead.
- **The X550 10 GbE ports hit `Tx Unit Hang`** under sustained load until GRO,
  TSO, GSO and LRO are disabled on the interface.
- **No *chassis* fan can be curved**, per the cooling row: all six `CHA_FAN`
  headers read `Disabled`, the case fans are on the PSU at a fixed speed, and a
  failed one would be invisible. ~~A sustained load holds the A6000 at 86–87 °C
  with `SW Thermal Slowdown` on ~100 % of the time, so any workload with a 100 %
  duty cycle is throttled before it starts.~~ Struck 2026-09-16: written without
  the fan speed in the witness. 87 °C is nowhere near the card's 95 °C slowdown —
  it is **5 °C above its own 84 °C target**, and it is there because the fan curve
  is slow: **3.7 minutes** of a 296 W load to reach 100 %, peaking at 89 °C on the
  way while the blower is still at 72 %. Given the time it converges to target on
  its own. **GPU** fans *are* controllable headless through NVML
  ([`tools/gpu-fan.py`](tools/gpu-fan.py), curve in
  [`tools/gpu-fan-curve.py`](tools/gpu-fan-curve.py)), which is worth 16 °C to a
  job that ends inside that ramp and nothing to one that does not
  ([measured](log/2026-09-16-diffusion-first-run-and-three-regimes.md)).
- **The PSU's published spec is ATX12V 2.2 / EPS12V**, i.e. no native 12V-2x6
  connector. Read off the vendor sheet, not measured here — worth confirming by
  eye before buying a card that wants one.

And one open question: **why the 3090 fell off the bus** on 2026-09-16 under
another job's DDP. Its own link was clean throughout and the marginal slot that
night belonged to the other card.
[The investigation](log/2026-09-16-the-overclock-and-the-fabric.md),
[what is and is not established](docs/machine-changes.md#still-open).

## Log

| Date | Entry | Headline |
|---|---|---|
| 2026-09-11 | [DeepSeek-V4-Flash across two GPUs and 256 GB of RAM](log/2026-09-11-deepseek-v4-moe-offload.md) | 284 B parameters at 29 tok/s on 72 GB of VRAM |
| 2026-09-12 | [Two ways to be off the network, one on top of the other](log/2026-09-12-offline-after-a-move-and-an-ssd.md) | a held lease and a renumbered PCI bus, each enough on its own |
| 2026-09-12 | [The machine was resetting every ten minutes and nothing on it knew](log/2026-09-12-bmc-watchdog-reset-loop.md) | a BIOS-armed BMC watchdog nobody disarmed, now taken over by systemd |
| 2026-09-12 | [Two NVMe drives, and the benchmark that kept measuring the cache](log/2026-09-12-nvme-sustained-write.md) | write floors differ 2.5x; a test that stops before the cliff reports the cache |
| 2026-09-12 | [A 347 GB model with 84 GB of it left on the drive](log/2026-09-12-deepseek-v41-first-run.md) | DeepSeek-V4.1-Flash at 20 tok/s on mainline llama.cpp, engram never loaded, and a prefill flag set wrong the whole time |
| 2026-09-13 | [Getting ik_llama.cpp to run DeepSeek-V4.1](log/2026-09-13-deepseek-v41-on-ik-llama.md) | four graph changes, a perplexity gate that matches mainline on CPU and GPU, a quiet-box A/B that puts the port 20 % behind mainline on decode, and a DSpark draft that loads, drafts, and at a three-token block accepts 60 % once the target keeps its token embedding in bf16 (the draft borrows it; the 3-bit copy cost four to five points, the block mask and the head cost nothing); on a quiet box the three-token block decodes 19.9 tok/s against 14.1 without a draft, and pinned staging buffers change nothing; the same draft ported to mainline (three V4.1 rules, 52 lines) decodes 22.8 tok/s against 17.7, and 24.8 once the token's bytes were counted (the served path sits within 10 % of the memory wall) and the VRAM re-balanced to hold two more expert layer-equivalents, 25.6 with a third (the last step is inside the noise band), so the serving port now runs that build with the draft |
| 2026-09-13 | [Putting the engram tables back at Q8_0](log/2026-09-13-engram-q8-repack.md) | 6 % lower perplexity for 125 GB that is never loaded; the two tensor groups are additive and the 0.2 GB `engram_wkv` half is worth ~160× more perplexity per byte than the 125 GB table; PopQA does not move; the thermal guard stops CPU decode at five minutes, and a 2.7 GHz cap fixes that for free |
| 2026-09-14 | [The ik gap was page faults, prefill on the served profile, and a queue with labels](log/2026-09-14-v41-gap-closed-prefill-and-queue.md) | the 20 % ik-vs-mainline decode gap closed to noise once the engram rows were prefetched with `posix_madvise(WILLNEED)` (faults 41–62 → 1–11 a token, first pass 13.6 → 18.4 tok/s), and the served profile's prefill and request queue measured on the same box |
| 2026-09-14 | [The AIO comes out, an air cooler goes in](log/2026-09-14-air-cooler-swap.md) | the loop was letting a 2.7 GHz decode reach 89 °C; the air cooler holds a 64-thread stress at 43 °C; fan RPM lives in the BMC, not the Super I/O |
| 2026-09-14 | [Memory clock: 3200 to 3600, and where the wall is](log/2026-09-14-memory-clock-3600.md) | bandwidth followed the clock one-for-one to 3600 (131 → 148 GB/s); 3666 lost the 1:1 fabric and returned 139 wrong bytes in ten minutes with the MCE counter at zero; 3733 and up do not POST; DRAM voltage on Auto stays 1.2 V whatever the clock, so 3600 runs at a manual 1.30 V; no FCLK item exists on this firmware |
| 2026-09-15 | [A model that fits one card](log/2026-09-15-a-model-that-fits-one-card.md) | Qwen3.6-35B-A3B whole on the A6000: 132 tok/s at Q6_K, 140 at UD-Q4_K_XL, four streams +13 % — and the ceiling is a flat ~390 GB/s, half the card's 768. Not the power cap (47 % less budget costs 15 % of the rate) and not the expert gather (a dense 7 B on the same card reaches 421 GB/s); the 35 B MoE out-decodes that dense 7 B because it reads 2.75 GB a token against 3.57 |
| 2026-09-15 | [The clock cap comes off, and a hero take without it](log/2026-09-15-clock-cap-removed.md) | the 2.7 GHz cap and boot service retired with the AIO gone; uncapped hero take of the served V4.1 profile: 12.8 tok/s per stream × 2, Tctl 62–65 °C, decode-window mean clock 3.44 GHz, thermal guard silent |
| 2026-09-15 | [Prefill on the served model: the ubatch is worth 2.1×, the engine 1.15×](log/2026-09-15-prefill-ubatch-ik-vs-mainline.md) | same model, same placement, no draft: `-ub 1024 → 4096` takes an 11.9k prefill from 236 to 500 tok/s on ik (190 → 434 on mainline) for 2.8 GB of VRAM, decode unchanged; ik leads mainline 1.15–1.24× on this hybrid path; applied to serving the same morning (12k-document TTFT 50 → 25 s, decode unchanged, VRAM steady at 48.4/49.1 GB) |
| 2026-09-15 | [ExLlamaV3 behind a llama-server surface](log/2026-09-15-exl3-serve-and-tabbyapi-timings.md) | a llama-server-compatible front over exllamav3 whose `/props` engine block matches the files exactly (params 313 326 811 966, active 10 979 084 996 bytes a token), after four defects only the real model exposed; exllamav3's `time_generate` measured to span n decode passes (one token = one pass, 0.062 s), settling the rate as n / time; TabbyAPI #454's `timings` patch checked against main on six requests |
| 2026-09-15 | [GLM-5.3-Flash: first numbers](log/2026-09-15-glm-5.3-flash-first-run.md) | second MoE family on the same probes, ik main the day after its port merged: PPL 2.04, decode 17.0 → 18.7 tok/s with ten expert layers on the cards (about 1 % a layer, half what the expert bytes predict — not bandwidth-bound), prefill 353 tok/s; thirteen layers abort the prefill in the CUDA pool at `-ub 4096`; without the cards 8.3 tok/s (193 GB resident); `-t 16` = `-t 32`; the model's MTP layer as draft (ik PR #2399 merged locally) +12 % at 75 % acceptance; the "divergence" between builds was a 0.03-nat fork tipped by placement, not a graph change; on-card Q8_0 tensors regrafted: Q4_K +10 % decode for KLD 0.047 (7 % of top-1 tokens change, an imatrix recovers almost none of it), Q6_K +4 % for KLD 0.013 — bytes saved and KLD paid track each other; Q6_K graft + MTP draft 20.9 on the essay, 24.2 tok/s on a coding prompt (97 % acceptance); ExLlamaV3 1.5.0 per-expert CPU offload (`-mcs 195`) reaches 22.2 tok/s and climbing on the AVX2 tier, prefill 356, ahead of ik with the draft; the 3090 fell off the bus at 00:01 Sep 16 under another job's DDP, ~1 900 corrected AER errors on the A6000 root port since boot |
| 2026-09-15 | [Serving knobs, one at a time](log/2026-09-15-serving-knob-sweep.md) | six one-knob arms against the live profile: `-rtr` −39 % prefill, KV q8_0 neutral (−450 MiB), fifth GPU layer OOMs with `-ub 4096`, `n_max` 4/5 −15/−20 % decode — the live profile stands |
| 2026-09-15 | [Splitting the DeepSeek-V4.1 port into two PRs](log/2026-09-15-splitting-the-v41-port.md) | the maintainer asked for two PRs, so the branch was rebased onto main (eighteen commits: the vision PR now creates `exp_probs_b_vl`, GLM5NEXT joined the swiglu guard, and the pinned-weights commit was already merged), the three follow-up commits folded into what they fix, and 101 comment lines cut to 66 by the rule that a comment stays only if breaking it breaks the code; both engines re-measured the same day because a two-day-old number against a moved base is not evidence — PPL 2.2355 ± 0.0626 against the reference branch's 2.2556, decode 20.4–20.7 against 21.2 tok/s; [#2455](https://github.com/ikawrakow/ik_llama.cpp/pull/2455) |
| 2026-09-16 | [The night of ten boots, and a slot that was out of margin](log/2026-09-16-the-overclock-and-the-fabric.md) | both cards fell off the bus under another job's DDP (Xid 79 then 154); a four-condition experiment on the A6000's link — idle/loaded × Gen4/Gen3 — put 27 corrected errors in 483 s of Gen4 under load against zero in every other cell, so it was eye margin at 16 GT/s and not damage; DDR4-3600 was not sufficient to explain it (the errors returned at 3200); moving the card out of the near-bottom slot to `60:01.1` gave zero errors in 502 s of the same load, though the move changed slot and seating together and that is unrecoverable; the idle 2.5 GT/s that had an asterisk on a week of PCIe-bound numbers turned out to be the GPU's own downclocking; still open is why the 3090 fell, its link being clean throughout. Same entry: the first training run on the new slot is fabric-clean at 87 °C with `SW Thermal Slowdown` on ~100 % of the time and the power cap pinned beside it, the BMC's per-slot temperature sensor agreeing with the die at 86 °C, and six `CHA_FAN` headers reading `Disabled` because the case fans are on the PSU |
| 2026-09-16 | [Every model that survived the storage pass, re-run](log/2026-09-16-every-kept-model-re-verified.md) | the slot move had flipped CUDA0 to the 3090 under `PCI_BUS_ID`, so every placement would have loaded 44–46 GB onto a 24 GB card — fixed once with `configs/gpu-order.env` (UUID order) and proven by the first load; then all seven kept files reproduced their recorded numbers (PPL 2.2355 to four decimals, Qwen 140/132, GLM exl3 22.4, served V4.1 25.05 warm) and the three source directories hashed clean; DDR4-3600 back on with zero errors on the moved link in 480 s of the load that gave 27; three toktape takes, including a 36-second single-stream clip that replaces the 7-second one |
| 2026-09-16 | [What engram costs when four streams want different rows](log/2026-09-16-engram-and-concurrency.md) | E4 answered: major faults a token stay flat across one, two and four streams (22.6 / 25.9 / 24.2) while the total scales linearly, so **engram is not a concurrency bottleneck** and four streams give 1.4× aggregate — confirmed against a control that reran the single-stream arm last on the warmest cache (18.8 against 19.1). Two prompts at the same concurrency differ 2.5× in fault count for 1.6 % of the rate, so the fault count barely predicts the rate and WKS-20's 6.8 % is an upper bound. `--lazy-mode` turns out not to be an optimisation: with it off, `engram_embd` is an ordinary layer tensor and `-ngl 99` asks 232 GB of a 48 GB card, while naming it `=CPU` moves the host budget from 199 to 394 GiB on a 251 GB host. Pinning the tables in RAM is closed by arithmetic, not a run |
| 2026-09-16 | [What the 3090 is actually worth](log/2026-09-16-what-the-3090-is-worth.md) | four alternating arms, two cards against the A6000 alone on the served V4.1 profile: removing the 24 GB card costs **2.7 % of decode on the mean of ten runs and 0.3 % on the warm four**, against the 3–7 % the per-layer figures predicted. With one card the model loads to 47 260 of 49 140 MiB, so the 20 GB does not migrate to the other card — it goes to the host, which absorbs it. The per-prompt scatter runs −11.7 % to +6.2 % and the draft columns say why: the placement changes the numerics, so the two configurations answer with different text and the draft is right a different fraction of the time (50.6 % against 59.6 % on one prompt). That channel is the same size as the bandwidth one, so this design bounds the cost without separating them; a no-draft arm would |
| 2026-09-16 | [Two giants of the same size, and the model that could not draw them](log/2026-09-16-two-giants-is-a-capability-boundary.md) | first image generation here, to make the frames LTX-2.5 cannot stage. Same prompt and four seeds on two turbo distillations at 1536×1024: **Z-Image-Turbo fused the cat into the mecha in 4 of 4 seeds** — a cat's head on an armoured torso, once with no opponent at all — while **Krea-2-Turbo separated them 4 of 4**. Four seeds agreeing is a deterministic answer to the prompt, not seed luck, so a re-roll cannot fix it. Z-Image is the cheaper model on every other axis (**10.3–11.4 s** vs 19.9–20.4 s per image, **23.4** vs 39.6 GB peak allocated) and the cheaper model is not cheaper when it cannot do the job. The durable finding is that LTX's merge was never LTX's: three models asked for two giants of comparable size in contact, two merged them, and the signature is identical in all three — the losing subject is absorbed as **features on the surviving body** (ears on a helmet, a head on a torso, a tail on a robot), which is the sign to change model rather than seed. Krea-2 at 41.4 GB of 48 leaves little room and its card's 2048×2048 example is untried here. Also: the image env is deliberately separate, because `uv run --with diffusers` inside the LTX project silently re-resolved torch 2.13.0+cu132 → 2.14.0+cu130 |
| 2026-09-16 | [The 13.5× that did not fix it, and the fan that finally hit its own target](log/2026-09-16-what-guidance-was-not-for.md) | what LTX-2.5's guided pipeline costs, what it was worth, and a correction. Same 121 frames, same geometry, same seed, only the pipeline different: stage 1 goes 21 s to **284 s**, decomposing exactly into 3.6× per step (four guidance passes folded into one forward by `--max-batch-size 4`) and 3.75× more steps, while **stage 2 is unchanged** at 39 vs 41 s because guidance lives in stage 1 only and stage 2 refines on the distilled schedule with the required LoRA. And it did not fix what it was fetched for: the missing cat stayed missing under `cfg 3.0`/`stg 1.0`, with the word bleeding into the mecha's helmet as two pointed ears. My claim that pipeline choice was the larger cause is **struck** — a prompt rewrite (cat as the subject of the first sentence, both giants in frame from frame 0) put a legible separate cat on screen in **124 s** on the cheap pipeline. Free finding, and the bigger one: five prompted beats rendered as **two**, with the last four of nine sampled frames holding no giant at all — the model was trained on captions of single ≤5 s scenes, so a shot list costs frames rather than buying them. The fan curve measured on a matched pair: 90 → **84 °C**, 1480 → 1512 MHz, and `SwThermal` active 169 of 394 samples → **zero**. Also: a 1 Hz witness missed a sub-second decode peak, reporting 31,256 and 37,064 MiB for byte-identical runs |
| 2026-09-16 | [Three regimes on one card, and a fan that arrives three minutes late](log/2026-09-16-diffusion-first-run-and-three-regimes.md) | first diffusion work here: LTX-2.5 (22 B DiT, video **and** synchronised audio in one pass) generating a 5 s 1536×1024 clip in 124–157 s, with the offload flag's fastest arm being `disk` because it mmaps the 42 GB transformer in 3 s where `cpu` copies it in 15, and the capacity floor being the decode stage's 37 GB rather than the transformer. The queue's opening question answered by locking clocks instead of capping power: denoise 0.86–0.88 on the graphics clock and 0.20 on the memory clock, decode stage ~0.10 and 0.81–1.07, Qwen3.6 decode 0.42–0.58 and 0.51–0.83 — so the 09-15 ~390 GB/s ceiling was co-limited, about half of it on the core side. Adding `fan.speed` to the witness found an overshoot: the card's own fan curve takes **3.7 minutes** to reach 100 %, and during that ramp the die sits up to 5 °C *above* the 84 °C target it is aiming for, peaking at 89 °C while the blower is still at 72 %. Forcing 100 % from the start is 16 °C on a 137-second take and nothing on a four-hour one — a claim that the blower was holding 40 % back was published and struck within the hour. NVML drives GPU fans headless; no chassis fan can be read at all. The model cannot write Hangul. Three instrument errors of mine: an awk comparing numbers as strings (8 022 MiB reported for a 48 016 peak), an `scp` into a running script that killed one arm mid-statement and left a stale lease that refused the next, and a power-sweep tool that had been capping the 3090 under comments naming the A6000 |
| 2026-09-16 | [Two Qwen models three weeks old](log/2026-09-16-qwen38-flash-next-and-coder-next.md) | Qwen3.8-Flash-Next (125B-A6B plus a 51B n-gram table, 103.7 GiB) decodes **51.1 tok/s** with no draft across both cards and RAM, twice V4.1's drafted 25.05 out of a quarter of the bytes (110.1 GiB against 444.2 — an "at a similar file size" clause was struck from that entry the same day); its n-gram table costs ~5 % of decode when faulted from NVMe and 8.9 major faults a token, the engram finding again on a second architecture; Qwen3-Coder-Next IQ4_XS fits one card at 133 tok/s, so the fast/slow pair is measured. The MTP draft fails to load exactly as open PR #28097 describes (a second platform for it), and the #28497 indexer nondeterminism did not reproduce at CUDA 13.0 |
| 2026-09-17 | [Where the prompt cache breaks](log/2026-09-17-where-the-prompt-cache-breaks.md) | a Hermes turn on V4.1-Flash is one cold prefill of **13 167 tokens at 46 tok/s (285 s)** — 4 200 of system text, ~8 950 of 23 tool schemas — and the cache then works within and across sessions (identical second session: first token in 1 s). But the model's SWA layers can only roll back to a **context checkpoint**, the server makes those only at user-message starts and the prompt end, and the DeepSeek parser never published the user delimiter, so a change anywhere before the last user message re-prefilled everything (**cache_n 0** at 32 % and at 79 %). Nine-line sibling-parity patch + test (FAIL-first): a new question now reuses **13 145 of 13 161** tokens, 0.8 s instead of 13.8 s. Edits inside the system prompt or tool schemas still cost the whole prefix, by upstream design. |
| 2026-09-17 | [The 3090 comes out](log/2026-09-17-the-3090-comes-out.md) | a second hard hang the evening before (GSP RPC failure, no Xid, no AER, link clean — a second CUDA context on a loaded card both times, not a slot signature), so the card came out to be sold. Its last test: cuda_memtest 3 passes **0 errors**, gpu_burn **99.9 % at 0 errors, 421 W peak, 77 °C**, cut by the power-off ten seconds before its verdict; the runner's `errors reported: 1` was a grep catching cuda_memtest's NVML notice (struck, fixed). A stale lease from a smoke run killed by a deploy-over-running-script cost a peer job its night: the reader's rule is now that a lease whose pid is dead is no lease. |
| 2026-09-16 | [A licence that excludes this country, a model that could not hold a face, a sheet copied as a split screen, and the served model on the small card](log/2026-09-16-echo-ingredients-and-the-3090-alone.md) | MiniMax-H3's licence excludes the Republic of Korea, read before download; JoyAI-Echo 1.5 stood up (denoise 136–158 s, **14.8 GB** VRAM with every block offloaded, 74 GB host, prompt cut at 1 500 chars) and set aside on quality; the LTX-2.5 Ingredients IC-LoRA takes a Krea-2 reference sheet as a static 121-frame video (145 s, 29.2 GB), and two takes came back as a **quad split screen** because every sheet panel was a finished frame — a per-panel edge-ring gate was written and then shown not to predict the clip (struck); the sheet alone composed **zero of four** seeds, and pinning frame 0 to a Krea-2 keyframe beside the sheet composed every one — compose with a keyframe, hold identity with the sheet. Then the served DeepSeek-V4.1 on the **3090 alone**, all forty expert layers on the host: 22.5 GB at 64k context, warm decode **19.8 / 25.4 tok/s** against 21.6 / 25.9 on the A6000 alone — now `llm-3090.service`, so the 48 GB card is free for diffusion; Hermes Agent pointed at it — and then found unusable there (a warm one-line question took **5 min 3 s** of prefill and reasoning), so the card now serves Qwen3.6-35B-A3B whole: **140–150 tok/s**, prefill 1 172 tok/s, the same eight-tool Hermes turn 7 min 8 s → **10 s**. A used RTX 8000 at ₩2.0 M researched and declined: Turing's long-context decode is a third of a 3090's on published numbers, and it has no bf16 |

## Queued

The next project is a music video made on this machine — image generation,
video generation, and music generation — so the queue is now mostly about
what that costs here. Everything in this section is a **question**, not a
measurement; the searched figures behind them were not taken on this box.

- ~~**Is a diffusion denoise step compute-bound or bandwidth-bound?**~~
  **Measured**, and the answer is three regimes rather than one:
  [rate against locked clocks](log/2026-09-16-diffusion-first-run-and-three-regimes.md)
  gives an LTX-2.5 denoise 0.86–0.88 on the graphics clock against 0.20 on the
  memory clock, its video+audio decode stage ~0.10 against 0.81–1.07, and
  Qwen3.6-35B decode 0.42–0.58 against 0.51–0.83. A power sweep could not have
  answered it: at 300 W the denoise runs with `SwPowerCap` **and** `SwThermal`
  both active, so the cap moves two things. So a faster core buys the denoise, a
  wider bus buys the decode, and the served LLM takes both — which also closes
  why its ~390 GB/s ceiling was half of peak.
- **How long a clip fits in 48 GB, and at what resolution.** Partly measured:
  the decode stops at ~43 GB both at 241 frames of 1536×1024 (10.04 s) and at
  481 frames of 1024×704 (20.04 s), so **frames × pixels is the budget and
  duration trades against resolution inside it** — and the 20-second take was
  the faster of the two, 229 s against 255 s. `AUTO_TILING` appears to size
  itself near that ceiling, which is why both land in the same place; what is
  not measured is where it stops being able to, and the 42 GB download that
  overlapped the 20-second take's decode window means that timing is not a row.
- ~~**Fan control — what the curve is worth beyond the overshoot.**~~
  **Measured** on a matched pair of the same 394-second guided take, same seed,
  the only difference being whether [`tools/with-fan-curve.sh`](tools/with-fan-curve.sh)
  gave the blower to [`tools/gpu-fan-curve.py`](tools/gpu-fan-curve.py):
  **max temp 90 → 84 °C, mean SM clock 1480 → 1512 MHz, and `SwThermal` active for
  169 of 394 samples → zero**
  ([entry](log/2026-09-16-what-guidance-was-not-for.md)). The rate is 1.8 % of it,
  so the finding is not speed — it is that thermal throttling was binding for 43 %
  of a run and is now gone, leaving `SwPowerCap` as the only thing clipping clocks.
  Not left running: a fan speed outlives its process, so it is owned per take.
  Still open is the hour-long render, where the card converges to target on its own
  and the curve should be worth less. The chassis side is unchanged and is still
  the real limit — fixed-speed fans on the PSU, no reading, no curve. And the LLM
  measurement that a throttle is cheap (47 % of the power budget for 15 % of the
  rate) does **not** transfer: that is the bandwidth-bound slope, and the denoise
  is the compute-bound one at 0.87.
- **Would a unified-memory box be better at this than a 48 GB card?** Derived,
  not measured — there is none here. DGX Spark is 128 GB of unified LPDDR5x at
  **273 GB/s** on sm_121, against this A6000's 48 GB at 768 GB/s. Today's
  elasticities predict the shape of the answer rather than a number: the decode
  stage is 0.81–1.07 on the memory clock, so at 0.36× the bandwidth it should
  cost roughly 2.7× the time (41 s here → ~110 s), while the denoise is only 0.20
  on that axis and would barely feel it. Against that, three things this card
  cannot do at all: hold the whole ~70 GB pipeline resident instead of running
  `--offload disk`, push the decode's 43 GB capacity wall out by ~2.7×, and load
  the **nvfp4 transformer LTX-2.5 already ships** (18,721,732,720 bytes, a quarter
  of the bf16 file) which Ampere refuses. So the prediction is a machine with a
  different bottleneck, not a faster or slower one — favourable for video, where
  capacity binds all of the time and bandwidth 30 % of it, and unfavourable for
  the LLM this box serves, whose decode is pure bandwidth. What would settle it is
  one run of the same take with the same instrument on such a machine. Apple's
  unified memory has the better bandwidth-per-capacity (M3 Ultra ~800 GB/s to
  512 GB) and cannot run this at all: `ltx_pipelines` is bound to CUDA SDPA and
  ltx-kernels, so a port is the precondition rather than a tuning question.
- **Music generation is not a hardware question.** ACE-Step-class models are
  4–20 GB and seconds per song; the 24 GB card already covers that third of
  the workload, which is worth stating because it means it carries no weight
  in a GPU decision.
- ~~**What removing the 3090 would cost.**~~ **Measured** —
  [under 3 % of decode, and 0.3 % on the warm rows](log/2026-09-16-what-the-3090-is-worth.md).
  What is still open is how much of even that is bandwidth: the placement
  change moves the numerics, which moves the draft's acceptance rate, and the
  two effects are the same size. A no-draft arm separates them.
- **Back to LLMs** — the ik_llama architecture port is done and filed
  (#2455), so the levers it was for are now the work: `-ser`, the low-bit
  expert quants, and per-expert rather than per-layer placement (WKS-23's
  routing histogram is the pre-study). ~~Concurrency~~ answered in E4.
  ~~A second 32 GB card to see how far the CPU can be pushed out of the
  loop~~ — closed on arithmetic rather than a run: expert layers on a card
  are worth about 1 % of decode each on GLM-5.3-Flash and about 3 % on
  Qwen3.8-Flash-Next, and the fast/slow pair wants about 112 GB of VRAM
  (68 for the slow model's current placement, ~44 for Coder-Next with 32k)
  against the 72 GB installed, so 32 GB moves neither.

## Layout

```
log/        one file per experiment, dated
configs/    the scripts that are actually running on the machine
tools/      recording: VHS tapes and the scripts they drive
docs/       longer write-ups: upstream bug reports, method, hardware notes
assets/     the clips
CLAUDE.md   context for an agent working in this repo
```

## Upstream

Running unreleased models on this hardware keeps landing in other people's
untested paths. The full record — including the findings that were
investigated and deliberately **not** filed, which are worth as much to the
next session — is
[`docs/upstream-contributions.md`](docs/upstream-contributions.md). What has
landed or is open:

| Date | Project | What | Outcome |
|---|---|---|---|
| 2026-09-11 | ik_llama.cpp | [#2436](https://github.com/ikawrakow/ik_llama.cpp/pull/2436) — a detected allocation failure became a segfault because a `nullptr` graph was dereferenced | **merged** 2026-09-14 |
| 2026-09-14 | ik_llama.cpp | [#2443](https://github.com/ikawrakow/ik_llama.cpp/pull/2443) — gguf-py sizes tensors without the per-row metadata twenty of the fork's quant types carry, so every read-then-write script wrote each IQ4_KSS tensor rows × 4 bytes short. This is where the all-NaN logits came from | **merged** 2026-09-14 |
| 2026-09-14 | ik_llama.cpp | [#2444](https://github.com/ikawrakow/ik_llama.cpp/pull/2444) — `GGML_CUDA_NO_PINNED_WEIGHTS`: `-ot` overrides to the CPU drop mmap, so weights land in pinned memory, which cannot succeed when they exceed RAM | **merged** 2026-09-15 |
| 2026-09-15 | ik_llama.cpp | [#2455](https://github.com/ikawrakow/ik_llama.cpp/pull/2455) — the DeepSeek-V4.1 architecture (`deepseek41`): shared compressed KV streams, lagged hyper-connections, the low-rank-only query norm, the engram tables, and the row prefetch as its own commit. +794/−108 across 13 files | open |
| 2026-09-15 | exllamav3 | [#376](https://github.com/turboderp-org/exllamav3/pull/376) — `can_defer_load` read an env var that `-mcs` never sets, so `-mcs` plus the stats env let the router load after the permutation and the model generated garbage at a normal token rate. One line, plus a test that fails on the unpatched 1.5.0 | open |
| 2026-09-17 | llama.cpp | The DeepSeek V3.2/V4/V4.1 chat parser publishes no `message_delimiters`, so llama-server never finds user-message starts and creates no context checkpoints there; on this SWA model any edit before the last user message re-prefills the whole prompt (13 167 tokens, 4–5 min). Nine-line sibling-parity fix (Kimi-K3, MiniMax-M3, Muse Glimmer set them) + test-chat case, FAIL-first, [entry](log/2026-09-17-where-the-prompt-cache-breaks.md). Branch `deepseek-msg-delimiters` on master | patch ready, not yet submitted |
| 2026-09-16 | llama.cpp | DeepSeek V4.1 renders its DSML tool-call tags with a leading space (`<｜DSML｜ calls>`, per the release's `encoding/encoding.py`); the V4 template and `common/parsers/deepseek.cpp` expect `tool_calls`, so every V4.1 tool call is returned as content. Template + parser branch + 4 tests, FAIL-first, [entry](log/2026-09-16-echo-ingredients-and-the-3090-alone.md). Cherry-picks cleanly onto master | patch ready, not yet submitted |
| 2026-09-14 | llama.cpp (V4.1 branch) | [vcruz305#1](https://github.com/vcruz305/llama.cpp/pull/1) — `dflash`: accept DeepSeek-V4.1 DSpark drafts. 17.70 → 22.78 tok/s at block 3 · [#2](https://github.com/vcruz305/llama.cpp/pull/2) — `resolve_fused_ops` read a layer-boundary placement as missing support and disabled the fused HC pre op on every layer · [#3](https://github.com/vcruz305/llama.cpp/pull/3) — `llama_model_n_swa()` was not extended to `DEEPSEEK41`, so every follow-up turn on a long document re-prefilled ~2 600 tokens instead of ~560 (TTFT 21 → 8.8 s) | open |
| 2026-09-11 | ik_llama.cpp | [#2437](https://github.com/ikawrakow/ik_llama.cpp/pull/2437) — the loader accepted a tensor whose GGUF region is smaller than its type requires, so every short tensor read its tail from the next one | closed, declined |
| 2026-09-11 | — | [A published IQ4_KSS file reserves 4 bytes per row too few](docs/iq4-kss-short-tensors.md). ~~Not an engine defect~~ — superseded by #2443 above, which is where it actually came from | superseded |

## Reusable pieces

- [`configs/gpu-order.env`](configs/gpu-order.env) — which card is CUDA0, by
  UUID, never by slot. One slot move inverted `CUDA_DEVICE_ORDER=PCI_BUS_ID`
  and every `-ot` string, `-ts` and `-gs` in this repo assumed the old order;
  a training launcher with `CUDA_VISIBLE_DEVICES=0` put a 38 GB job on the
  24 GB card and OOMed at step 52000. Source it before launching anything
  that names a CUDA index — and note that reading the file is not the test,
  the first load is.

- [`docs/running-a-model-larger-than-memory.md`](docs/running-a-model-larger-than-memory.md)
  — what to run a 510 GB model on when there is 72 GB of VRAM: the measured
  shape of DeepSeek-V4.1's 196 B-parameter Engram tables, why the hardware
  rules out most engines before preference does, why no Rust rewrite has
  displaced llama.cpp, and which three things are worth building above the
  engine rather than inside it.

- [`docs/raising-tokens-per-second.md`](docs/raising-tokens-per-second.md) —
  where the time goes on a 347 GB MoE model, measured from the tensor headers:
  the dense part is 4 GB and the routed experts are 259 GB, so 3.1 GB per token
  comes out of DDR4 at 56% of the bandwidth the same memory gives a sequential
  read. Then every lever against that number — `-ser`, expert pruning, lower-bit
  quants, huge pages, speculation — with the arithmetic for each, what `-rtr`
  costs on a model this size, and why `-ot` cannot place individual experts.

- [`docs/porting-v41-to-ik-llama.md`](docs/porting-v41-to-ik-llama.md) — why a
  new DeepSeek generation needed porting at all (every lever that would plausibly
  make the file faster — `-ser`, `-thp`, `-rtr`, the IQ2/IQ3/IQ4_KSS quants — is
  ik-only, and ik stopped at the model's first line), and then the port as a
  write-up rather than a diff.

- [`tools/fetch-gguf.sh`](tools/fetch-gguf.sh) — model files come down with
  this: parallel range workers, the expected size read from the API, and a file
  that only appears at its final path when its byte count matches. Measured
  2026-09-15: one connection 28 MB/s against eight at 80 MB/s on the same file
  and link, so a 29 GB model is six minutes rather than seventeen. A
  half-written `.gguf` where a loader can see it is the failure this prevents.

- [`configs/hf-fetch/`](configs/hf-fetch) — a HuggingFace mirror that verifies:
  a manifest of every file's published sha256, workers that divide the work by
  taking locks rather than by hand-split argument lists, and a gate that hashes
  before declaring the download done. Written after two downloaders on one file
  produced 39 GB of interleaved garbage with a plausible file size.

- [`tools/ik/gpu-power-sweep.sh`](tools/ik/gpu-power-sweep.sh) — a `throttled`
  flag is a question, not a finding. Every card this machine records says
  `throttled: yes`, at 150 W and at 300 W alike, so the flag cannot tell a
  binding cap from a cap that was brushed once. This answers it by taking the
  budget away: the same take at several board limits, with the default restored
  on every exit path. Measured 2026-09-15: 47 % less power cost 15 % of the
  rate, so the flag had been pointing at the wrong thing all day.

- [`tools/mem3600-load.sh`](tools/mem3600-load.sh) and
  [`tools/pcie-aer-snapshot.sh`](tools/pcie-aer-snapshot.sh) — the fabric pair:
  a two-rank NCCL all-reduce that holds both links at line rate while the
  corrected-error counters, the throttle reasons and both temperature channels
  are sampled beside it, and a reader for the AER counters on every GPU port.
  The load is what separated a marginal slot from a damaged card (27 corrected
  errors in 483 s in one slot, 0 in 480 s in another), and it is what any new
  card in this box gets pointed at before a number from it is believed.

- [`docs/v41-experiment-plan.md`](docs/v41-experiment-plan.md) — the runs that
  would confirm or break the projections above, written before the first one:
  what each measures, what result would falsify the model of where the time
  goes, and which levers are blocked on what. With
  [`configs/bench-serve.sh`](configs/bench-serve.sh), which records resident
  set, major faults and drive reads alongside throughput, because tok/s alone
  cannot say whether a slow run lost its expert pages or its engram rows.

- [`docs/quiet-machine.md`](docs/quiet-machine.md) — why "quiet box" has to be
  a protocol and not a load-average check: one day, five collisions between a
  sweep, a repack and a CPU benchmark, all because a 200 GB model load is
  I/O-bound and the load average does not see it. One lease, IO pressure as
  the signal, the witness recorded in every measurement row, and delegates
  handed the runner script rather than a sentence about the flag.

- [`docs/wrx80e-bios-setup.md`](docs/wrx80e-bios-setup.md) — the firmware side
  of running this board as an unattended LLM host: CPU power limit (PPT/cTDP,
  hidden in AMD CBS), above-4G mapping for two GPUs, auto power-on, the onboard
  ASMB9-iKVM remote console, and where the fan curves actually are. Menu paths
  and manual page numbers included.

- [`configs/v41-serve.sh`](configs/v41-serve.sh) — the serving command for
  DeepSeek-V4.1-Flash, as a systemd `ExecStart`: one `-ot` rather than several
  (this branch keeps only the last), the catch-all `exps=CPU` last, and a
  comment for each number saying what it was traded against.
  [`configs/llm-serve.sh`](configs/llm-serve.sh) is the older V4-Flash one.
- [`configs/tps.py`](configs/tps.py) — streams a completion and reports the
  decode rate from the server's own timings, not a stopwatch.
- [`tools/v41/v41-take.sh`](tools/v41/v41-take.sh),
  [`tools/qwen38/qwen38-take.sh`](tools/qwen38/qwen38-take.sh),
  [`tools/ik/ik-vram-take.sh`](tools/ik/ik-vram-take.sh) and
  [`tools/exl3/exl3serve-take.sh`](tools/exl3/exl3serve-take.sh) — one runner
  per model family, all the same shape: gate on the lease and an idle card,
  take the placement as a required argument rather than a default, record
  per-card VRAM by UUID, signal only the pid captured at spawn, and end on a
  sentinel. Delegates get one of these, not an instruction about the protocol.
- [`tools/pi-local.tape`](tools/pi-local.tape) — the VHS tape for the oldest
  clip here, with the two traps it had to work around written down.
- [`tools/v41-demo.py`](tools/v41-demo.py) + [`tools/v41-korean.tape`](tools/v41-korean.tape)
  — the V4.1 recording: answer on the left, the machine on the right. Runs on
  the workstation so the panel reads `/proc` next to the server. Carries what
  three bad measurements taught it: count Korean as two columns and ANSI as
  none, do not let a render throttle skip the finish check, and measure rate
  over the tokens that carried text rather than wall time that kept running.
- [`assets/placement-sheet.html`](assets/placement-sheet.html) — the source of
  the sheet above. Edit it and re-shoot; the window has to be 750 tall, not 720,
  because the sheet is a 16:9 box *inside* 48 px of body padding and a 720-tall
  window clips its last row:

  ```
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless \
    --hide-scrollbars --force-device-scale-factor=2 --window-size=1280,750 \
    --virtual-time-budget=6000 --screenshot=assets/placement-sheet.png \
    file://$PWD/assets/placement-sheet.html
  ```

  `--virtual-time-budget` is not optional: the sheet pulls IBM Plex from Google
  Fonts, and without it Chrome shoots before the webfonts arrive and the
  headline comes out in a fallback face.

- [`tools/sheet-fit-gate.py`](tools/sheet-fit-gate.py) — run this before you
  re-shoot the sheet. It reports every element's `getBoundingClientRect` against
  the box and says `ok`, `tight` or `CLIPPED` for each. Three vision rounds went
  on one fault class here: `.setup dd` re-wraps at about 45 monospace characters,
  so a line that looks like one line is two, and six surplus lines pushed the map
  caption through the bottom border and the legend clean off the page. This
  answers that in a second. It pins the sheet to 1248×702 itself rather than
  trusting the window, because `--dump-dom` reports an `innerHeight` of 663
  where `--screenshot` uses 750, and a gate measuring a box 87 px shorter than
  the artifact reports failures that are not there. `tight` and `CLIPPED` are
  separate answers on purpose: line-height leaves leading below the glyphs, so a
  box edge inside the padding band is cramped but nothing is actually clipped.
- [`tools/dequant-scan.cpp`](tools/dequant-scan.cpp) — reads one tensor out of
  a GGUF at `ggml_row_size` stride, dequantizes each row with ggml's own
  reference path, and reports every non-finite value with the raw block that
  produced it. This is what turned "the logits are NaN" into "expert 255 of
  this tensor is read out of the next tensor's bytes".

  ```
  g++ -O2 -o dequant-scan tools/dequant-scan.cpp -I<ik>/ggml/include \
      -L<ik>/build/ggml/src -lggml -Wl,-rpath,<ik>/build/ggml/src
  ./dequant-scan model.gguf blk.13.ffn_up_exps.weight        # all experts
  ./dequant-scan model.gguf blk.13.ffn_up_exps.weight 255 256 # one expert
  ```

- [`tools/gguf-region-scan.py`](tools/gguf-region-scan.py) — reports any tensor
  whose GGUF region is smaller than its type needs. It reads only the
  tensor-info block, so a published file costs one range request instead of a
  download. This is what showed the short-tensor defect covers a publisher's
  whole quantization ladder, and that a second publisher's file of the same
  type does not have it.

  ```
  ./tools/gguf-region-scan.py model.gguf
  ./tools/gguf-region-scan.py https://huggingface.co/<repo>/resolve/main/model.gguf
  ```

- [`configs/thermal-guard.sh`](configs/thermal-guard.sh) — a watchdog that
  reads CPU and GPU temperature (and, while the AIO was fitted, coolant and pump) every 5 seconds and stops
  the inference load, and only the inference load, after 30 seconds of a
  genuine cooling problem. Written for unattended weekends. Note its blind
  spot for the queue above: it reads die temperature, and GDDR6X memory
  junction is not exposed through `nvidia-smi` on a consumer card.

## Projects this log produced

Measuring this machine kept running into the absence of a tool, and twice the
tool became its own repository. Both are MIT and neither is a fork.

- **[toktape](https://github.com/midagedev/toktape)** — the black-box tape for
  local LLM serving. It attaches to a `llama-server` that is already running,
  records one run into a `.tape` file, and prints a card that says where the
  model sits, what the process actually touched, and how fast the request
  really was. Every clip in this README was recorded with it, and the reason it
  exists is in the log: a tok/s figure with no witness beside it — placement,
  page faults, the clock the card was actually holding — cannot be checked by
  anyone, including its author a week later. This repo is the demanding
  downstream user rather than a co-maintainer: when a round here needs a
  witness we are gathering by hand, the requirement goes to toktape instead of
  into a local workaround.
- **[exl3-serve](https://github.com/midagedev/exl3-serve)** — a
  `llama-server`-compatible HTTP front for
  [ExLlamaV3](https://github.com/turboderp-org/exllamav3). It exists because of
  a dependency in the sentence above: ExLlamaV3 ships no server, so nothing
  written against `llama-server` can drive an EXL3 model, and that includes the
  recorder. Serving one EXL3 model on that surface — `/props`, `/health`,
  `/slots`, `/v1/chat/completions` with llama-server's `timings` object filled
  from exllamav3's own job results — was what made the engine measurable here
  at all. [What it cost to get right](log/2026-09-15-exl3-serve-and-tabbyapi-timings.md):
  four defects that only the real model exposed, and a `time_generate` that had
  to be measured rather than assumed before the rate meant anything.

The tracker and the wiki this log files against are also local software, but
they are a general-purpose tool that predates the machine rather than something
it produced, so they are named in [`CLAUDE.md`](CLAUDE.md) and not here.
