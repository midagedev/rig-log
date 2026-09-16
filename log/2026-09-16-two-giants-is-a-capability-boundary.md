# Two giants of the same size, and the model that could not draw them

*2026-09-16, one A6000 (48 GB). Z-Image-Turbo and Krea-2-Turbo, first image generation on
this machine.*

An image model came onto this box for one reason: LTX-2.5 was
[measured earlier today](2026-09-16-what-guidance-was-not-for.md) to animate well and stage
badly. Asked for a giant mecha and a giant cat it produced one subject with the other's
features absorbed into it — "cat" became two pointed ears on the mecha's helmet — and asked
for five beats it held one moment. Both are decisions about what is in the frame, so the plan
was to make the frame with an image model and hand it to the video model as `--image`
conditioning. The user named this workflow from memory of how such clips are normally made,
and it is the right one.

What came out of the first round is better than the plan: **the failure is not LTX's.**

## Two models, one prompt, four seeds each

Both models are turbo distillations whose own cards specify `guidance_scale=0.0` — like LTX's
distilled pipeline they have no CFG, which is the same lesson for the third time today: the
prompt is the only lever. Same prompt, same seeds 23–26, same 1536×1024 (LTX's default video
geometry, so a chosen frame needs no resize), both at bf16.

| | Z-Image-Turbo | Krea-2-Turbo |
|---|---:|---:|
| pipeline load | 11.5 s | **7.5 s** |
| per image, 1536×1024 | **10.3–11.4 s** | 19.9–20.4 s |
| peak allocated | **23.4 GB** | 39.6 GB |
| card VRAM peak | **27.8 GB** | 41.4 GB |
| max die temperature | 85 °C | 89 °C |
| four images, incl. load | **61 s** | 95 s |
| steps (card default) | 9 (8 DiT forwards) | 8 |
| **two separate giants** | **0 of 4** | **4 of 4** |

The last row is the only one that decides anything, and it inverts the rest. A vision round
opened all eight frames: Z-Image fused the cat into the mecha in **every seed** — a cat's head
on an armoured torso, one body, and in one frame no opponent present at all. Four seeds
agreeing is not seed luck; it is this model's deterministic answer to this prompt, and no
amount of re-rolling fixes it. Krea-2 separated them in all four, left water and air between
the two silhouettes, and read photographically rather than as a glossy hard-edged render.

So Krea-2 costs 2× the time and 1.7× the memory of Z-Image, and **the cheaper model is not
cheaper when it cannot do the job.** That is worth stating plainly because the first table
above, read alone, recommends the wrong model.

## The finding that outlives this clip

Three models were asked to put two giants of the same scale in one frame today. LTX-2.5 (22 B
video) merged them. Z-Image-Turbo (24 GB transformer) merged them. Krea-2-Turbo (26 GB
transformer, repo created 2026-06-18) did not.

**So "two subjects of comparable size, in contact, in one frame" is a capability boundary
rather than a prompt bug.** That reframes the morning's work: the prompt rewrite that put a
cat on screen in LTX was real, but it was finding the one phrasing that got a model past a
boundary it sits near, not fixing a mistake in the prompt. The durable fix is to let a model
that is on the right side of the boundary make the frame, and ask the video model only to move
what is already there.

It also gives the merge a name to watch for. The signature is consistent across all three
models: the *smaller-cued* subject does not vanish, it is absorbed as **features on the
surviving body** — ears on a helmet, a head on a torso, a tail added to a robot. A frame that
reads as one creature with borrowed parts is the diagnostic, and it means the round needs a
different model, not a different seed.

## Method notes

- **Peak VRAM comes from torch's allocator here, not the witness.** The 1 Hz `nvidia-smi`
  sampling was measured today to miss a sub-second peak, reporting 31,256 and 37,064 MiB for
  two byte-identical runs of the same take. The witness is still recorded, because it is what
  says what the *card* did — temperature, power, throttle reasons — but the capacity number
  comes from `torch.cuda.max_memory_allocated`.
- **Krea-2's 41.4 GB on a 48 GB card leaves little room.** Its own card shows a 2048×2048
  example; that is not obviously going to fit here and has not been tried. Unmeasured.
- **The image environment is separate from LTX's on purpose.** `uv run --with diffusers`
  inside the LTX project re-resolved torch from 2.13.0+cu132 to 2.14.0+cu130 — a silent change
  to the environment every video measurement was taken in. A keyframe is an input to a video
  run, not part of it, so the two get their own resolutions.
- **The fetcher had two bugs, both found by using it.** It had no authentication, so a gated
  repo was simply unreachable; and it flattened paths, which is right for GGUF shards and
  fatal for a diffusers tree — `transformer/config.json`, `text_encoder/config.json` and
  `vae/config.json` all became one name and overwrote each other, leaving a single 726-byte
  file. The large shards survived only because their names happen to differ. Both fixed;
  `KEEP_TREE=1` is now required for anything with a `model_index.json`.
- An image take holds the GPU like any other, so it runs under the same lease, the same idle
  check and the same witness as a video take. On a box with three sessions and a peer job at
  midnight, a 34 GB model loaded outside the lease is how someone else's row gets spoiled.
