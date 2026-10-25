bloomery 0.3.9 adds two large mixture-of-experts models: Muse Spark Open 816B-A42B (GGUF) and MiniMax-M3.1-Flash,
the latter read straight from its native NVFP4 safetensors folder. Placement is redesigned around llama-server's own
flags. All numbers: RTX A6000 + RTX 3090 (the 3090 at its 250 W cap), `bloomery-serve` at the serving defaults
(`--place` unset picks `bp`, every lever unset, `--ctx-size 4300`), `tools/ref/depth-serve.sh`, 2 rounds, a
fresh server each round. MiniMax-M3.1's row is the tagged tree's; Muse's is the candidate 64a58296c's (the
commits after it change Muse's load-time refusals only, no kernel or path Muse runs). pp is the prompt rate at P ids;
decode is tg tok/s over 128 generated tokens after that prompt.

| RTX A6000 + RTX 3090, `bp` | pp512 | pp4096 | decode @ 512 | decode @ 4096 |
|---|---|---|---|---|
| Muse Spark Open UD-IQ2_XXS | 90.40 | 94.90 | 16.65 | 15.74 |
| MiniMax-M3.1-Flash NVFP4 folder | 122.57 | 123.62 | 21.03 | 19.48 |

tok/s, means of 2 rounds (each row's sd at most 1.9 %); the depth is the prompt length the decode follows.

Recorded runs at these defaults (one 5.5K-token prompt each, on the 0.3.9 candidate before its decode work):
[Muse Spark Open](https://tape.midagedev.com/r/kvhptiqzuab9ri8sf4tu) ·
[MiniMax-M3.1-Flash](https://tape.midagedev.com/r/iv9w3jzg4nirj4gaufik).

### Highlights from our contributors

- **Qwen3.8 from its FP4-Local checkpoint folder** (@juliankang4, #660, #682): `bloomery-serve -m <folder>` serves it
  with no conversion, its PLE table and MTP draft read as the checkpoint stores them.
- **DGX Spark (GB10) prompts up to about twice as fast** (@juliankang4, 20 PRs): tensor-core and pipelined GEMMs, the
  native FP4 build, fused HC kernels. His measurements on one DGX Spark: 4,096-token prefill +98.2 % on the NVFP4
  checkpoint, +54.0 % on FP4-Local (#668).
- **Several requests at once on Qwen3.8** (@juliankang4): with MTP, four sampled requests under `--parallel 4` decode
  at 55.80 tok/s together, where 0.3.8 decoded 28.29 (#703 and four more); ready tokens go out before another prompt
  starts, so four concurrent 4,096-token requests reach their first token in 20.4 s at the median, not 43.9 (#671).
- **MiniMax-M3.1-Flash's card experts run his NVFP4 kernels**: the routed NVFP4 prompt GEMMs on FP4 tensor cores (#687,
  #760) and the gate, up and SwiGLU as one launch (#766).
- **Common owners every model shares** (@Burntgogi, #774, #775): Held positions with their read checks, and slot row
  admission with its operand views, so the next model attaches without its own copy. He also laid Flint's groundwork:
  its header reader, tokenizer and template support (#676, #677, #678, #680).
- **A new start screen** (@juliankang4, #644, #743): the wordmark and a furnace in half-block pixels, with placement
  and serving panels.

The DGX Spark and Qwen3.8 numbers are the pull requests' own, measured on the contributor's machine; details under
[From our contributors](#from-our-contributors).

## Install

Linux x86-64 with AVX2 (glibc 2.34+), an NVIDIA GPU of compute capability 8.6+ and **driver R580 or newer** (CUDA 13).
On Windows, run inside WSL2. Docker and Homebrew as in the README.

```sh
curl -fsSL https://raw.githubusercontent.com/midagedev/bloomery/main/tools/release/install.sh | sh
bloomery-serve -m PATH/MiniMax-M3.1-Flash --port 8080
```

## New

- **Muse Spark Open 816B-A42B.**
  - Text serving from the GGUF release (UD-IQ2_XXS measured). The chat template's recipient protocol is parsed into
    `reasoning_content`, `content` and `tool_calls`.
  - On two cards the unset placement picks `bp`: the stage on the larger card and the other card as an expert tier.
  - The prompt pass streams host experts through the common expert stream (`xstream`).
  - Each layer's attention chain and router run on a side stream beside the gate and latent-down projections.
  - The tokenizer reads UTF-8 strictly, as Muse's reference tree does: an invalid byte becomes U+FFFD.
- **MiniMax-M3.1-Flash from its checkpoint folder.**
  - `-m` takes the vendor's safetensors folder. The NVFP4 experts run in their own format on the card and on the host
    (no GGUF conversion, no requant).
  - A folder's load runs the same expert residency as a GGUF file's: the card keeps the experts decode routes to most.
    Measured against the folder without it (2 rounds, same lease): decode 16.52 → 21.97 tok/s at 512 (+33 %), 16.24 →
    19.48 at 4096 (+20 %); pp512 101.8 → 88.4, pp4096 101.7 → 97.9 (the prompt pass now shares the host with the
    residency's admissions; it pays back after about 94 generated tokens at 512 and 347 at 4096).
  - The host's NVFP4 prompt products run a new tile: the expert's offset codes dot each column's codes as stored,
    with every column's sums and scales prepared once a call, bit-identical to the one-column kernel. M3.1's prompt
    walks 256-row units with it. Measured against the candidate without it (2 rounds, same lease): pp512 88.35 →
    124.19 tok/s (+40.6 %), pp4096 96.95 → 123.69 (+27.6 %); decode 21.87 → 21.29 at 512 (−2.7 %), 19.45 → 19.48 at
    4096.
  - Host experts stream into ring slots the card route runs.
  - On two cards the unset placement picks `bp`, as for Muse; the top four layers' card sum runs over the stage card
    and the expert tier.
- **Placement with llama-server's flags.** `bloomery-serve` reads `-dev`, `-sm`, `-mg`, `-ts`, `-ngl`, `--cpu-moe`,
  `-ncmoe`, `-ot`, `--fit`, `-fitc`, `-fitt`, `-devd` and their `LLAMA_ARG_*` variables with llama's meaning; every
  launcher reads them. `BLOOMERY_CARD_BUDGET` takes one budget per card (`CUDA0=38G,CUDA1=20G`). `LLAMA_API_KEY` is
  read as `--api-key`. Every tiered seat takes `--slot-save-path`.
- **Host expert speed.** IQ2_XXS experts run a wide tile on the host (a block unpacked once per row for up to 32
  columns), with the signs taken on the weight side as ik's IQ_N form does. The NVFP4 planes dot takes a column tile of
  up to 8, bit-identical per column.
- **Two-card timing.** `tools/ref/depth-serve.sh` runs a model planned on both cards (`BLOOMERY_TIMING_CARDS=a6000+3090`),
  checking the server's need record names both.
- **Apple Silicon (Metal).**
  - Qwen3.6-35B-A3B (qwen35moe) decodes on Mac GPUs: `generate_metal` and `bloomery-serve-metal`, with KV checkpoints
    and prefix reuse across requests (#726).
  - MLX 4-bit checkpoints: `prepare <mlx folder> <out>` converts an mlx-community affine 4-bit folder to a GGUF split the
    Metal backend runs. Greedy output matches mlx-lm for 40 tokens (#757).
  - Prompts: known ids run ahead and inner rows skip the head (#762), and a prompt longer than 8 ids runs as batched
    passes, one per ubatch, with a flash prefill attention and MoE over rows (#773). One Metal residency set per stream
    keeps the weights wired through a long pass.
  - Development-loop numbers, M4 Pro 48 GB, Qwen3.6-35B-A3B (a Mac has no timing runner): MLX 4-bit decode 101.6 ± 0.64
    tok/s, Q4_K_M decode 86.4 ± 0.66 tok/s.

## From our contributors

- **Qwen3.8 FP4-Local checkpoint folder** (#660, #682, by @juliankang4). `bloomery-serve -m <folder>` loads it directly,
  with its NVFP4 PLE table and its MTP draft read from the folder in the formats the checkpoint stores.
- **GB10 / DGX Spark prefill** (#668, #687, #693, #696, #700, #701, #711, #724, #740, #753, #754, #756, #758, #759,
  #760, #761, #763, #765, #766, #769, by @juliankang4). Tensor-core and pipelined GEMMs, fused HC kernels, fewer prompt
  launches, the native FP4 build (`sm_121a` by default on GB10), MXFP8 prompt sites W8A8 on activations quantized once,
  and the routed NVFP4 gate, up and SwiGLU as one launch. The PRs' own measurements on one DGX Spark: 4,096-token
  prefill +98.2 % on the NVFP4 checkpoint and +54.0 % on FP4-Local (#668); median 752.8 → 888.5 tok/s (#693); +11.8 to
  +18.7 % on FP4-Local (#740); about +3 % (#766).
- **GB10 / DGX Spark decode** (#643, #652, #665, #686, #697, #707, #732, by @juliankang4). Fewer bytes per token and
  more overlap: code prompts with MTP, one request, 30.33 → 36.07 tok/s (#652); the router and shared-expert gate stay
  BF16, 120.2 MiB less read per token (#732).
- **Qwen3.8 MTP with several requests** (#690, #703, #705, #735, #765, by @juliankang4). With FP4-Local,
  `--parallel 4` and `BLOOMERY_DRAFT=mtp`, four sampled requests decode at 55.80 tok/s over their all-active window,
  where 0.3.8's tree decodes 28.29 (#703).
- **Serve** (#671, #689, by @juliankang4). Ready tokens go out before another prompt starts: with four concurrent
  4,096-token requests, median TTFT 43.9 → 20.4 s (#671).
- **Host tier** (#661, #670, #755, by @juliankang4). Checkpoint slots pinned at load, PLE advice grouped by page,
  readbacks into host-written huge pages.
- **`BLOOMERY_NVTIER_EVICT=heat`** (#650, by @juliankang4): the NVMe tier evicts the expert with the lowest decayed
  routing count. The default `tick` is unchanged.
- **The start screen redrawn** (#644, #743, by @juliankang4): the wordmark and a furnace in half-block pixels, a status
  line, and placement and serving panels.
- **GLM-5.3-Flash's card leg runs NVFP4 and 32-value down stacks** (#651, by @juliankang4).
- **Common owners** (#639, #667, #669, by @juliankang4; #772, #774, #775, by @Burntgogi): dense calls on resident
  weights, the q8_1 byte count, Held positions and read checks, slot row admission, and the router's normalization
  policy as named values.
- **Flint groundwork, no inference yet** (#676, #677, #678, #680, by @Burntgogi).
- **Tests, tooling and docs** (#663, #664, #658, #659, #672, #674, #734, #748, #749, #770, #771, by @Burntgogi; #681,
  #688, #692, #704, #709, #714, #717, #718, #720, #723, #725, #728, #729, #730, #736, #745, #751, #752, #679, by
  @juliankang4). `contrib-check --tier t0` no longer runs the Python self-tests twice (about a quarter of its wall).

## Changed

- On GB10 the routed NVFP4 prompt products run on the FP4 tensor cores, and their activations round to FP4 where the
  old path kept Q8 (#687, by @juliankang4). It is the default, as the faster path is (AGENTS.md "Performance first").
- A Qwen3.8 server with `--parallel` above 1 no longer turns MTP on by default (#695, by @juliankang4).

## Fixed

- `serve`: a finished request no longer delays the next one by about 2 s when the prompt-cache staging pool is
  fragmented (#706); five prompt-cache defects (#737); half-closed clients keep their answer and reset, stalled or
  over-limit connections release their slot (#742); three or four concurrent plain GLM slots no longer stop the server
  (#744); no abort at SIGTERM under an injected profiler (#747); Qwen3.5 and Qwen3.6 reuse a shared system prompt (#694);
  a paged Qwen3.8 plan serves the requested slot count (#713); `ignore_eos` requests use the MTP draft (#719); a plain
  request in a drafted round no longer waits for the drafted advances (#731) — by @juliankang4.
- `serve`: a complete second `<tool_call>` opener at EOF is an unterminated call, not leaked into the content (#657, by
  @Burntgogi).
- Qwen3.8 MTP: a draft window no verify takes leaves no stale state (#631); the prompt no longer fills the draft's store
  from rows that lack the last layer's combine (#691) — by @juliankang4.
- `gpu`: with the default expert stream, one prompt gives the same greedy tokens on every load (#647); the expert tier
  keeps a copy's source until it lands and ranks heat the same however a prompt is split (#746); a model that fits the
  unified pool is no longer refused (#716) — by @juliankang4.
- Loading: FP4-Local files with MXFP8 or FP8 block-scaled matrices load (#649); GLM-5.3's folder opens as a target when a
  NextN tensor is refused (#727); `--hf` refuses a safetensors-only repo before downloading when it cannot open it
  (#738); a Qwen3.8 folder whose MTP layer the draft cannot read serves its target (#739); `prepare` no longer overwrites
  existing shards (#708); F8 rows that overflow f32 are refused by name (#710) — by @juliankang4.
- The start screen's tier row and bar use one count (#721), and an empty numeric field is named (#733) — by
  @juliankang4.
- NeoX cache appends require distinct positions as an `unsafe` contract (#669, by @juliankang4).
- Metal: `generate_metal`'s `decode_tok_s` no longer counts the prompt's first token (it read about 0.8 % high) (#768).
  Thanks @avlp12.
- `gpu-gates`: option-shaped CLI values stay data (#771, by @Burntgogi).
- Muse Spark Open: a file whose expert width differs by layer is refused by name at read, where it ran every layer at
  layer 0's width; the rope width is checked once for the step and the prompt.
- Checkpoint folders: an HF `add_bos_token` or `add_eos_token` that is not a bool is refused by name, not read as off.

## Known limits

- **MiniMax-M3 (not M3.1) was not checked for this release.** No gate ran on its file; MiniMax-M3.1-Flash is the
  MiniMax the gates hold.
- Muse Spark Open always thinks: a turn's first tokens are its `to=self` reasoning, so a short `max_tokens` can end
  with empty `content`. Muse serves one slot.
- Off cells in the user-facing pass: Qwen3.6-35B-A3B Q8_0 at `--place bp` does not start (the model fits the A6000, so
  the 3090's tier holds no expert and the plan is refused by name); `--place` unset or `a` serves it.
- `gate-gpu-nemotron-h-moe-card32` (new in this release) is red on Nemotron 3.5 Lightning UD-Q4_K_XL: its plan runs 53
  layers where the file has 52, refused by name before the card loads. Lightning's card-held 32-value experts are not
  checked on the card in 0.3.9; Nemotron 3.5 Nano's path (`gate-gpu-nemotron-e2e`) is green.
- `gate-gpu-mimo2-twocard` (new in this release) is red: the profile's MiMo file holds MXFP4 routed experts, which have
  no card format, refused by name at load. MiMo on one card (`gate-gpu-mimo2-flash`) is green.
- `gate-refset`: the Qwen4-exp NVFP4 reference sets are not on the gate machine (red since 0.3.8). `gate-flint-meta`,
  `gate-gpu-qwen4exp-nvfp4` and four other needs-env gates did not run (no profile names their files).
- MiniMax-M3.1's first short request after a cold start answers slower (7.4 tok/s at `bp` in the pass below, the page
  cache still cold); the next requests run at the table's rate.
- MiniMax-M3.1's decode at 512 is 2.7 % under the candidate without the new NVFP4 prompt tile (21.87 → 21.29, same
  lease); the prompt gain is 27–41 %.
- From 0.3.6: `gate-qdot`'s IQ4_XS clause is red by 5 ULP.
- From 0.3.5: V4.1 on two cards (`--place bp`) is not faster than one card.
- From 0.3.4: Bolt needs a 24 GB card and refuses `--place bp`.

## Checked before the tag

- Fixture-tier release batch on 581a66ed0, the tagged tree's code (the tag adds the README alone; `just affected`
  from the candidate): 237 items, 0 red; 97 deferred to the real tier (48 real-only, 5 no fixture, 37 real-file, 7 needs-env).
- Real-tier batch on the candidate 64a58296c: 91 items, 3 red (`gate-refset`, `gate-gpu-nemotron-h-moe-card32`,
  `gate-gpu-mimo2-twocard`, above). On 581a66ed0 the real-tier gates of the families the later commits touch ran
  again: `gate-gpu-minimaxm3-twocard`, `gate-musespark-meta`, `gate-minimax31-folder` green; the two new gates still red.
- The NVFP4 tile's gate clauses (`gate-qdot`, `nvfp4_planes`) went red on each of four mutants (an off-by-one offset,
  a −128 code not refused, one preparation for every run, a cut run dropping its extra column) and green on the
  clean tree.
- The user-facing pass: the release tarball's `bloomery-serve` at the serving defaults (`--ctx-size 16384`, every
  lever unset), one short and one ~6K-token toktape prompt each, decode / prefill tok/s:

  | cell | short | long (prefill) |
  |---|---|---|
  | Muse `bp` | 10.81 | 12.73 (95.58) |
  | Muse `a` | 10.21 | 11.77 (95.61) |
  | MiniMax-M3.1 `bp` | 7.42 (cold) | 16.96 (103.50) |
  | MiniMax-M3.1 `a` | 15.27 | 17.32 (90.76) |
  | Qwen3.8-Flash-Next `bp` | 87.59 | 88.50 (1948.11) |
  | Qwen3.6-35B-A3B Q8_0 `bp` | off | off |

  Short answers are under 50 generated tokens, so their decode carries the first tokens' cost.
- Card evidence: 64 pull requests merged since 0.3.8 carry `needs-gpu` without `gpu-verified`; each one's crates are in
  the batch tree, whose gates ran as above (#776's `gate-gpu-qwen4exp-mtp` in the final fixture batch).

## Contributors

0.3.9 holds 446 commits since 0.3.8: 233 by @juliankang4, 33 by @Burntgogi, 180 by the maintainer. 111 contributor pull
requests are in it (91 and 20).

**@juliankang4** (91 pull requests, 233 commits)

- MiniMax-M3.1-Flash's NVFP4 path stands on his work: the FP4-Local checkpoint folder reader (#660, #682), routed
  NVFP4 prompt GEMMs on FP4 tensor cores (#687, #760) and the gate, up and SwiGLU as one native launch (#766).
- Dense prompt GEMMs: BF16 tensor cores, pipelined MMA tiles, F32 epilogues with an exact redo only out of range, MXFP8
  W8A8 sites (#668, #693, #696, #700, #711, #754, #761, #769), and the fused HC kernels (#756, #759).
- GB10 / DGX Spark prefill and decode (#643, #652, #665, #686, #697, #707, #732, #758, #763).
- Qwen3.8 MTP under several requests: batch acceptance learned per request, one pass for several slots' plain steps,
  chain drafts at the verified width, one store walk (#690, #703, #705, #735, #741, #744, #765).
- Serve: ready tokens flushed before the next prompt, one owner for a request's next call, cache saves off the next
  request's path, bounded waits, clean teardown (#671, #689, #706, #731, #737, #742, #745, #747).
- The start screen in half-block pixels (#644, #721, #733, #743), the NVMe tier's `heat` eviction (#650), GLM-5.3's
  NVFP4 card leg (#651), and the host tier's protected reads (#661, #670, #746, #755).
- Correctness and loading fixes (#631, #647, #649, #669, #691, #708, #710, #716, #727, #738, #739, #776), and the
  tools and tests that keep the gates honest (#681, #692, #709, #714, #717, #718, #725, #729, #736, #752, #778).
- Two severity-sorted problem lists (#637, #699); items fixed in this release include #647 and #691.

**@Burntgogi** (20 pull requests, 33 commits)

- Common owners shared by every model: Held positions and their validation (#774), slot row admission and operand
  views (#775), router normalization described without borrowed bindings (#772).
- Flint groundwork: the common-owner attachment design (#676), Jinja block `set` capture and `replace` (#677), Flint's
  tokenizer and GGML EOG arrays (#678), the header reader with truthful coverage refusals (#680), and its docs (#748,
  #749).
- Serve and CLI fixes: a complete second Hermes opener at EOF is refused (#657), option-shaped CLI values stay data
  (#771), placement inputs are validated with their named errors kept (#659).
- Gates and tools: Qwen MTP context pins enforced (#770), GPU library tests serialized on the card lock (#734), recipe
  keys and includes kept (#658, #750), narrow-scan cancellation (#664), self-test ports (#672), engram docs (#674).
- Reported #656 (a placement with no host selections divided by zero) and fixed it (#663).

**@avlp12** reported the Metal decode-rate miscount on #593 (fixed in this release) and offered M5 Ultra testing.

Thank you all.
