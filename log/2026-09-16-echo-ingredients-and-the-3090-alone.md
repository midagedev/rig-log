# A licence that excludes this country, a model that could not hold a face, a sheet that got copied as a split screen, and the served model on the small card

*2026-09-16, 15:30–19:40.* Four threads in one afternoon, all on the same
machine, all measured. The first two are about which video model this box
should be running; the third is a defect in how a reference sheet was drawn
and a gate that now catches it; the fourth moves the served LLM onto the 24 GB
card so that the 48 GB card is free for the diffusion work.

## MiniMax-H3 was read before it was downloaded, and the reading ended it

The plan for the afternoon was the biggest open-weights video model with
audio: MiniMax-H3, a 33 B dense omni-transformer with a Qwen3-VL-32B text
encoder, native multi-shot by prompt, CFG-distilled, and a diffusers 0.40
pipeline already on this box. The licence file was read before the weights
were fetched. Section IV lists *Excluded Territories* — the EU, the UK, the
United States and **the Republic of Korea** — and IV.4 forbids both use and
the use of outputs outside the permitted territory. Community derivatives
relabelled `apache-2.0` on the hub still carry it. Nothing downloaded; the
decision is the user's and is recorded here so the question is not asked
again.

## JoyAI-Echo 1.5: stood up, measured, and set aside

The alternative surveyed was JD's JoyAI-Echo 1.5 (LTX-2.3 base, 8-step DMD
distillation, Gemma-3-12b-it encoder, up to seven reference slots with
memory audio, internal cuts by prompt, 9.6 s at 25 fps, 1280×736). It runs
in two stages: a conditioning encoder (Gemma + VAEs + a voice filter → one
`.safetensors` per request) and the DiT. Runner:
[`tools/echo/echo-take.sh`](../tools/echo/echo-take.sh), with the same lease,
idle, witness and sentinel contract as the LTX runner.

| stage, consumer bf16 config, resident blocks 0, prefetch 1 | wall | VRAM peak | host RSS |
|---|---:|---:|---:|
| encode, 66 example requests | 71 s | 23.6 GB | 32.8 GB |
| encode, 1 request | 12 s | — | 8.4 GB |
| generate, load | 22 s | | |
| generate, denoise | 136–158 s | **14.8 GB** | **74.4 GB** (34.6 GiB pinned block weights) |
| generate, decode | 15 s | | |
| generate, total | 156–213 s | | |

Two things worth keeping. The 14.8 GB peak is with every transformer block
offloaded to pinned host memory and streamed one at a time, so it fits the
24 GB card with 9 GB to spare — the `resident_blocks` knob was never turned
and 33 GB of the 48 GB card sat idle on every take. And the prompt is
truncated at **1 500 characters** by a guard in the request loader; a
2 534-character shot list was silently cut to its first act on the first
attempt.

The reason it was set aside is quality, judged by the user from the clips
(this repo does not have a model grade its own video): style collapsed across
cuts, the cat's face drifted into a different cartoon cat, and the action
beats did not land. That is the LTX-2.3 base and the 8-step distillation, not
a knob. The first LTX-2.5 take on the same concept was judged much better,
so the afternoon moved back to LTX-2.5.

One gap found on the way: **ffmpeg was not installed on the box.** Echo's
audio mux failed quietly and wrote the wav beside the silent mp4; installed
6.1.1 from apt and muxed the first clip by hand.

## LTX-2.5 with the Ingredients IC-LoRA: a reference sheet as conditioning

Lightricks published `LTX-2.5-22b-IC-LoRA-Ingredients` on 2026-09-10: a
reference sheet (one panel per character face, turnaround, props, location,
on black, no text) is supplied as a **static video** of ≥121 frames at the
output geometry, with a two-part prompt — `Reference sheet: … / Generated
video: …`. The runner gained `PIPE=ic_lora`, `LORAS="PATH STRENGTH"` and
`VIDCOND="PATH STRENGTH"` ([`tools/ltx/ltx-take.sh`](../tools/ltx/ltx-take.sh));
the sheet itself is rendered by Krea-2 Turbo from a prompt and looped into
121 frames with ffmpeg. `ic_lora.py` is the two-stage distilled pipeline, so
`WH="1536 896"` puts stage 1 on the LoRA's trained 768×448 bucket.

| take | wall incl. load, `--offload disk` | VRAM peak | host RSS | output |
|---|---:|---:|---:|---|
| first sheet, grey cat between buildings | 145 s | 29.2 GB | 43.6 GB | 1536×896, 5.04 s, with audio |
| Ultraman-scale sheet, grey cat | 130 s | | | judged: **quad split screen** |
| same sheet style, orange cat | 131 s | | | **quad split screen** |
| catalogue sheet, orange cat, ref 1.0 | 147 s | | | single frame |
| catalogue sheet, orange cat, ref 0.75 | 132 s | | | single frame |

### The sheet got copied as a split screen, and why

The second and third clips came out as four panels — the sheet's layout,
animated in place, no cat and mecha in the same frame. A vision judge
(a separate agent, given the three sheets and one mid frame from each clip,
asked only about layout) found the gutter geometry of the clips matched
their sheets **to the pixel**, and named the difference between the sheet
that worked and the two that did not. It is not how much black there is —
the working sheet is 32 % pure black, the failing ones 13–17 %. It is
whether the black draws a frame. In the working sheet two of the four panels
are subjects **cut out on pure black** (edge ring value 0, indistinguishable
from the gutter), so only two rectangles are visible and they sit
diagonally; the sheet reads as an asset board and the model composes a
scene. In the failing sheets every panel is a finished film frame filling
its rectangle (edge rings 13–155), and — decisively — the top-right panel
had been prompted as *the colossal cat standing in the city*, which is the
scene the video was supposed to compose. With the target already one of
four matted frames, there was nothing left to compose, and the model
animated the grid.

The fix was in the sheet stage, not the clip prompt: the character and
mecha panels went back to cut-outs on pure black, and the "buildings reach
its knees" scale moved to the `Generated video:` text only. The recurrence
layer is [`tools/img/ref-sheet-gate.py`](../tools/img/ref-sheet-gate.py):
per quadrant it takes the median brightness of an inner edge ring and counts
panels that read as bounded frames. FAIL-first on the actual files:

| sheet | pure black | edge rings TL TR BL BR | panels read as frames | gate (max 2) |
|---|---:|---|---:|---|
| first (worked) | 32.1 % | 60 · 0 · 0 · 67 | 2 | pass |
| Ultraman grey (split screen) | 16.6 % | 26 · 37 · 155 · 50 | 4 | **refused** |
| Ultraman orange (split screen) | 13.4 % | 43 · 30 · 14 · 56 | 4 | **refused** |
| catalogue orange, all four candidates | 39–41 % | 0–1 · 0 · 0 · 52–59 | 1 | pass |

The chain ([`tools/ltx/ingredients-chain-example.sh`](../tools/ltx/ingredients-chain-example.sh))
runs the gate over the four candidates and takes the first that passes. A
second mechanical check on the clips — fully black interior columns and rows
in a mid frame — reads 26 columns and 20 rows on a split-screen clip and 0
and 0 on both catalogue-sheet clips. Whether the two giants actually collide
is the user's judgement from the clips, not the gate's.

A chain-script mistake cost 17 minutes earlier in the same round: a
`until grep … take.log` wait on a sentinel file that the sheet runner never
writes (it logs to stdout), with a fallback phrase that is not in `run.log`.
The box sat idle with both cards empty. Wait on the artefact (image count in
the output directory), not on a log a different process may or may not
write.

## The served model on the 24 GB card alone

The morning's entry measured that removing the 3090 from the served
DeepSeek-V4.1 profile costs under 3 % of decode. The afternoon asked the
converse: **can the 3090 alone serve it**, so that the A6000 is free for the
diffusion work all day? Runner
[`tools/v41/v41-3090-only.sh`](../tools/v41/v41-3090-only.sh), derived from
the one-card runner: `CUDA_VISIBLE_DEVICES=<3090>`, `-ot "exps=CPU"` (all
forty expert layers on the host), attention, hyper-connections, KV and the
DSpark draft on the card, `GGML_CUDA_NO_PINNED_WEIGHTS=1`, the same five
prompts at `n_predict` 200, temperature 0, no prompt cache; two arms for
context.

| arm | 3090 VRAM | load | cold decode (3 prompts) | warm decode (2) | draft accepted |
|---|---:|---:|---|---|---|
| 3090 alone, 16k | 19.7 GB | 199 s | 14.5 / 21.0 / 19.8 | 19.9 / 25.5 | 39–59 % |
| 3090 alone, **64k** | **22.5 GB** | 179 s | 12.5 / 20.7 / 19.9 | **19.8 / 25.4** | same tokens |
| A6000 alone, 4.5 expert layers on card (this morning) | 47.3 GB | — | 16.1 / 22.4 / 20.1 | 21.6 / 25.9 | |

Warm decode within 2 % of the A6000 arm with **zero expert layers on a
GPU**. The 64k context costs 2.8 GB over 16k and leaves 1.5 GB on the card.
The first cold prompt is the engram rows coming off NVMe for the first time
after the reboot, as in every entry this week; it is gone by the second
pass. Draft statistics are byte-identical between the two arms (same device,
same numerics), so unlike this morning's two-card/one-card comparison there
is no draft-acceptance channel confounding this one.

It is now the serving configuration: [`configs/v41-3090-serve.sh`](../configs/v41-3090-serve.sh)
behind [`configs/llm-3090.service`](../configs/llm-3090.service) (`Conflicts=llm.service`,
so the two profiles cannot hold the cards at once). First start failed eight
times with `203/EXEC`: the script had landed on the box as mode 644. The four
diffusion runners (`ltx`, `img`, `echo`, `music`) gated on "every GPU under
2 GB", which would have refused every take while the 3090 holds the served
model; their `maxgpu` now reads the A6000 by UUID only, because the card
they use is the card whose idleness they need.

The endpoint's first client is [Hermes Agent](https://github.com/nousresearch/hermes-agent),
installed on the box under the user account (`~/.hermes/config.yaml`:
`provider: custom`, `base_url: http://127.0.0.1:8001/v1`, `context_length:
65536` — it refuses less than 64k for tool use, which is why the 64k arm was
the one that mattered). The installer failed once on `Failed to write to the
distribution cache`: `~/.cache/uv/builds-v0` and some archive entries were
root-owned from earlier `uv` runs over root ssh; `chown -R user:user` and a
rerun fixed it. Hermes reached the server during load (`HTTP 503: Loading
model`) — the wiring was right. The first tool-using turn was not: **every tool
call came back as plain text**, and the reason is an upstream defect, below.

## DeepSeek V4.1 changed its tool-call markup, and llama.cpp had not noticed

With tools in the request the model answered

```
<｜DSML｜ calls>
<｜DSML｜ invoke name="get_weather">
<｜DSML｜ parameter name="city" string="true">Seoul</｜DSML｜ parameter>
```

and the server returned all of it as `content`, `tool_calls: null`, even with
`tool_choice: required`. Hermes saw zero tool calls. What was ruled out, in
order, each by a measurement: the DSpark draft (token ids identical with the
draft on and off), the GGUF vocabulary (ids 10699/34756/10767 are `Ġcalls`,
`Ġinvoke`, `Ġparameter` in the release `tokenizer.json` too), the tokenizer
(five strings, HF `tokenizers` against `/tokenize`, identical ids), and the
pre-tokenizer preset (`joyai-llm`'s three regexes are byte-for-byte the
release's). The model was right. The release ships `encoding/encoding.py`
with `tool_calls_block_name = " calls"`, and its README opens with: *"DSML tag
names use a leading space … The V4 format used `<｜DSML｜tool_calls>` without a
space."* The chat template embedded in the GGUF is the V4 one (it is one byte
away from `models/templates/deepseek-ai-DeepSeek-V4.jinja`), and
`common/parsers/deepseek.cpp` hard-codes the V4 names, in the fork and on
`ggml-org/llama.cpp` master alike. No issue or PR mentions it.

The fix is three files on a branch of the engine fork: the V4 template with
the three tag names changed
(`models/templates/deepseek-ai-DeepSeek-V4.1-Flash.jinja`), a V4.1 branch in
the parser keyed on the `' calls>` literal that template builds, and four
parser tests mirroring the V4 block. FAIL-first held: with template and tests
in and the parser untouched, `test-chat` aborted on the V4.1 tool-call case;
with the parser patched, `test-chat` passed. Cherry-picked onto upstream
master (59 commits ahead of the fork base) without conflict. The server takes
the template as a file (`--chat-template-file`) because the GGUF's embedded
one is wrong; the convert PR (#28696) is where the embedded template should
be fixed.

| after the patch | result | tok/s |
|---|---|---:|
| `tool_choice` auto, weather question | `get_weather({"city":"Seoul"})` parsed | 26.6 |
| `tool_choice` required, terminal | `terminal({"command":"ls -la /tmp"})` | 27.7 |
| no tool needed | `391`, no call | 17.1 |
| tool result in history | prose answer using it | 16.2 |

Hermes then ran a real turn: eight tool calls in 7 min 8 s, reading
`nvidia-smi`, the process list, `/v1/models` and the server command line, and
answering that its model sits on GPU 0, the 3090, with the caveat — correct —
that the expert tensors are on the host under `-ot exps=CPU` and the 22.6 GB
on the card is attention, dense weights and the 64k KV cache. Decode ran at
27 tok/s through DSML boilerplate (the draft accepts nearly all of it) and
16–17 through prose.

Not settled: with the *wrong* template, `tool_choice: required` did not
constrain sampling either, although a GBNF grammar and a JSON schema on
`/completion` both constrained fine on the same server. Whether the PEG-native
parser's grammar reaches the sampler under the dflash draft path is a
separate question, left open.

## A 48 GB card for two million won, researched and declined

A Quadro RTX 8000 (Turing TU102, 48 GB GDDR6 at 672 GB/s, 260 W blower,
fp16/int8 tensor cores, **no bf16**) was offered used at ₩2.0 M, against
about $1 975 on the US used market and $2 600–4 370 for a used A6000. Not
measured here; the reading is from published measurements and this box's
own numbers. Short-context dense decode tracks bandwidth (an external
8–14 B benchmark: RTX 8000 52.5 tok/s against an A5000's 57.1), but at
32k context the same source measured a Qwen 32B Q4 at **11 tok/s on the
RTX 8000 against 35 on one 3090** — three times slower on 72 % of the
bandwidth, so long-context attention is compute-bound on Turing even though
llama.cpp does carry Turing MMA flash-attention kernels. A 64k-context
agent is exactly that regime, and the 3090 already serves V4.1 at 25 tok/s
there (table above). As a diffusion worker it cannot run this box's bf16
models natively (an fp16 file request on the LTX-2.5 hub has sat unanswered
since 2026-08-12; Z-Image has an open fp16 NaN issue), and ExLlamaV3
quantizations do not run on it, which closes the exl3 path measured on
09-15. Declined; a second 3090 or a used A6000 are the cards that would fit
what this box does.
