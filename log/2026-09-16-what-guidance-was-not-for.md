# The 13.5× that did not fix it, and the fan that finally hit its own target

*2026-09-16, one A6000 (48 GB), LTX-2.5 22B, all measurements this machine this afternoon.*

Three things were settled today after the [first diffusion runs](2026-09-16-diffusion-first-run-and-three-regimes.md):
what the guided pipeline costs, what it is worth for the failure it was fetched to fix, and what
the fan curve built this morning actually buys. The middle answer is the one worth reading, because
it is a correction: I had told the user that the pipeline was the larger cause of a prompt not being
followed, and it was not the cause at all.

## The claim I got wrong, in the order it happened

A cat was asked for in a shot of a giant mecha on a flooded waterfront. The clip came back with
the mecha and no cat. Reading the upstream docs turned up a table saying `DistilledPipeline` — the
path every clip that day had used — has no multimodal guidance: no CFG, no STG, no modality scale.
I reported that as the cause:

> ~~"The cat not appearing, and the tear not falling, were caused more by the choice of pipeline
> than by how the prompt was written."~~

**Struck.** That was a conclusion drawn from reading a feature table, which makes it a hypothesis.
Measured below: the guided pipeline reproduces the same failure exactly, for 13.5× the stage-1 cost.
A prompt rewrite fixed it on the cheap pipeline in 124 s. The repo's own rule is that a claim here is
something measured on this machine, so the entry keeps the wrong version visible rather than editing
it away.

## What guidance costs

The two arms below are the same 121 frames, the same 768×512 → 1536×1024 geometry, the same
`--offload disk`, the same prompt, the same seed. Only the pipeline differs. The distilled row is
the `a3-offload-disk` take from the morning, so this is a like-for-like ratio against a row that
already existed.

| | `DistilledPipeline` | `TI2VidTwoStagesPipeline` | ratio |
|---|---:|---:|---:|
| stage 1 | 8 steps / **21 s** | 30 steps / **284 s** | **13.5×** |
| — per step | 2.63 s | **9.47 s** | **3.6×** |
| — step count | 8 | 30 | 3.75× |
| upsampler | 4 s | 9 s | — |
| **stage 2** | 3 steps / **39 s** | 3 steps / **41 s** | **1.0×** |
| decode | 41 s | 41 s | 1.0× |
| total | 136 s | **394 s** | 2.9× |

The decomposition is exact: 3.6 × 3.75 = 13.5. The per-step factor is the guidance passes — CFG
needs a conditioned and an unconditioned prediction, STG a third against a deliberately perturbed
model, and the audio-to-video term a fourth; `--max-batch-size 4` folds all four into one forward,
and the measured 3.6 against a nominal 4.0 is what that batching saves. The step factor is the
schedule: the guided default is 30 steps where the distilled schedule is 8.

**Stage 2 is unchanged, and that is by design rather than by luck.** The `--distilled-lora` flag is
required, not optional, because stage 2 upsamples and refines on a distilled schedule with no CFG —
so guidance lives in stage 1 only. That is why the 8.9 GB LoRA had to come down alongside the 42 GB
dev transformer, and why the cost multiplier applies to one stage instead of the whole run.

`--max-batch-size 4` is not a tuning preference on this box: with `--offload disk` the transformer is
mmapped and streamed per layer, so the default `1` would stream it four times per step instead of
once. The upstream help says as much — "reduces layer-streaming PCIe transfers" — and that is the one
case where the flag is about I/O rather than arithmetic.

## What guidance was not worth

Full guidance at the pipeline's own defaults — `cfg_scale` 3.0, `stg_scale` 1.0, `rescale` 0.7,
`a2v` 3.0, 30 steps — produced the same failure. A vision round opened nine frames and found the
mecha from the first frame, a flooded street with submerged cars and a swinging traffic signal
giving human scale, a coherent single tilt-up from legs to torso to head, and no animal anywhere.
The only trace of the word "cat" was **two pointed ear-like protrusions on the mecha's helmet**: the
subject had absorbed the token rather than being joined by a second subject.

So the model was never failing to *follow* the prompt. It was following it into one subject.

The fix was the prompt, and it cost 124 s on the distilled pipeline:

- the cat became the subject of the first sentence rather than appearing in a later clause
- both giants were placed in frame from the first frame rather than staged one after another

That take came back with a legible separate cat from its first frame — grey tabby fur, pointed ears
with pink interiors, blown pupils, whiskers, a forepaw with distinct toes — a silhouette fully
separate from the mecha's armoured body, with both giants together in four of the nine sampled
frames. The helmet ears were gone.

**Pipeline choice was not the cause; prompt structure was.** Guidance remains the right instrument
for a different question — how tightly a prompt is obeyed once its subjects are on screen — and it
is now wired into the runner for when that question comes up. It was the wrong instrument for this one.

## The finding that came free, and matters more

The rewritten prompt named five beats: bite, wrench, punch, knocked through a tower, both crash into
water. **Two of them rendered.** The clip opens already mid-flight through the tower and carries the
fall and the impact as one continuous moment; the bite and the punch never happen. Worse, the last
four of nine sampled frames contain no legible giant at all — the shot drifts into street-level
aftermath, so roughly half the clip's duration is spent on nothing the prompt asked for.

This lines up with what the trainer docs say the model was taught on. Captions are produced by
pointing a VLM at an existing clip cut to a **single coherent scene** — the training pipeline splits
on `--filter-shorter-than 5s` — and asking for one paragraph describing the visuals *and* the audio.
So the model has never seen a shot list. Given one, it picks a moment and spends the frames on that,
then runs out of subject.

That reframes prompt writing here: a beat is not free and a beat is not cheap — it is a competitor
for the one moment the clip will actually hold. The next arm to run is a one-moment prompt at the
same frame count, to see whether the frames that went to aftermath come back as subject.

## The fan curve, on and off, same take

The A6000's own curve was measured this morning as arriving late. A longer load says the same thing
more clearly. Both arms below are the same guided take, same seed, same everything; the only
difference is whether [`tools/gpu-fan-curve.py`](../tools/gpu-fan-curve.py) owned the blower,
wrapped by [`tools/with-fan-curve.sh`](../tools/with-fan-curve.sh).

The card's own ramp, sampled from the take's witness:

| elapsed | temp | fan | SM clock |
|---:|---:|---:|---:|
| 1 s | 62 °C | 30 % | **1920 MHz** |
| 31 s | 82 °C | 52 % | 1530 |
| 61 s | 88 °C | 67 % | 1440 |
| 121 s | **90 °C** | 78 % | 1470 |
| 301 s | 87 °C | 81 % | 1530 |

Twenty degrees in the first thirty seconds with the fan at half. A quarter of the clock gone by the
first minute. The card overshoots its own 84 °C target by six degrees and takes five minutes to come
back down.

And the two arms:

| | card's curve | curve managed | delta |
|---|---:|---:|---:|
| max temp | 90 °C | **84 °C** | **−6 °C** |
| mean SM clock | 1480 MHz | **1512 MHz** | +2.2 % |
| **samples with SwThermal (0x20) set** | **169** | **0** | **eliminated** |
| stage 1 | 284 s | **278 s** | −2.1 % |
| total | 394 s | **387 s** | −1.8 % |
| mean power | 273 W | 277 W | +1.5 % |

**The result is not the 2 %, it is the zero.** Thermal throttling was active for 169 of 394 seconds —
43 % of the run — and the managed curve removed it entirely, holding the card at exactly the 84 °C it
says it is targeting. What remains is `SwPowerCap`, which is now the only thing clipping clocks, and
that is a different lever (the board limit) on a card that was never thermally designed to sit at 90 °C.

Three caveats, because none of them is invisible in the numbers:

- the managed arm started 4 °C cooler (58 against 62 °C), which favours it slightly
- the two arms report peak VRAM of 31,256 and 37,064 MiB for a run that is byte-identical in output.
  That is not a real difference — it is the **1 Hz witness missing a brief decode peak in one arm**.
  A sub-second peak is below this instrument's resolution, and any VRAM row taken from `dmon.csv`
  should be read as a lower bound
- the daemon hunted late in the run — 100 → 90 → 80 → 93 → 97 % — because a 4-point deadband on a
  5-second interval is too eager across the stage-2/decode load transition. It is not harmful, but a
  rate limit belongs in the policy

The recommendation that comes out of this is **not** to leave it running. A fan speed is machine
state that outlives the process that set it, exactly like a clock lock, and on a shared box a
persistent daemon silently changes every thermal number another session records. `with-fan-curve.sh`
owns the curve for one take and hands it back on every exit path including a SIGKILL follow-up, so
each measured row carries whether the fan was managed inside itself.

## Method errors worth naming

- **I diagnosed from a feature table and reported it as a cause.** The correction is above; the
  general form is that upstream documentation tells you what a knob does, never that the knob is
  the one that is binding.
- **`pgrep -af "gpu-fan-curve"` matched its own shell** while checking whether the daemon was
  running, returning two pids — the Tailscale SSH child and the `bash -c` carrying the pattern.
  This is a documented trap in this repo's own operating notes and it still caught me live. The
  bracket form, `pgrep -af "[g]pu-fan-curve"`, is what answered the question.
- **Two heredocs written inline through `ssh` died on quoting**, for the second and third time
  today. Launchers get written locally and copied; nothing composed of nested quotes goes over
  a remote shell.
- I told the user the guided run would take 20–40 minutes. It took 394 seconds. An upper bound
  stated without a probe is a guess wearing a number's clothes — the probe existed precisely to
  replace it and should have come before the sentence.
