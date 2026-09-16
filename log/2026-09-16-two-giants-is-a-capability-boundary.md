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

~~**So "two subjects of comparable size, in contact, in one frame" is a capability boundary
rather than a prompt bug.**~~ **Struck within the hour, by the round below.** Asked for the
same impossible scene in a *shonen anime* style instead of photographically, Z-Image separated
the two bodies in **4 of 4 seeds** — the same model, the same seeds, the same scene, zero
fusions. So the boundary is not in the model. It is in the **collision between the requested
style and the requested content**: asked for a photograph of something that cannot be
photographed, the model reconciled it by making one creature; given a drawn idiom where a
skyscraper-sized cat is native, it drew two. The correction is recorded below rather than
edited in, because I published the wrong version first.

What survives is the practical half: let an image model settle the frame, and ask the video
model only to move what is already there.

It also gives the merge a name to watch for. The signature is consistent across all three
models: the *smaller-cued* subject does not vanish, it is absorbed as **features on the
surviving body** — ears on a helmet, a head on a torso, a tail added to a robot. A frame that
reads as one creature with borrowed parts is the diagnostic, and it means the round needs a
different model, not a different seed.

## The same model, the same seeds, a different style: no fusions

The user asked to drop photorealism and go for shonen anime — Jujutsu Kaisen, Naruto — because
the joke is the gap between an adorable cat and total narrative gravity, and photoreal was
landing as neither. Rerunning the identical pair (same two models, same seeds 23–26, same
1536×1024) on an anime key-visual prompt produced the correction above:

| | Krea-2-Turbo | Z-Image-Turbo |
|---|---:|---:|
| per image | 20.1 s (19.8–20.3) | 11.2 s (11.0–11.6) |
| peak allocated | 39.6 GB | 23.4 GB |
| **two separate bodies, photoreal prompt** | 4 of 4 | **0 of 4** |
| **two separate bodies, anime prompt** | 4 of 4 | **4 of 4** |

The per-image seconds are identical to the photoreal round on both models, to within the
spread — so **generation time is a function of geometry and step count, not of content or
style.** One fewer thing to wonder about when a round is slow.

The fusion is gone, but a difference remains and it is a layout one: Z-Image stacks the two
subjects on a single vertical axis with the mecha centred behind the cat and occluded from the
hips down, both facing camera, while Krea-2 puts them side by side at equal height facing each
other. So the anime style fixed Z-Image's outlines without fixing its staging — which is why
the chosen frame is still Krea-2's, this time `k03-seed26`. A vision round also found Z-Image's
cat to be the cutest of the eight by a wide margin, with nothing in the frame opposing it:
drama as atmosphere rather than stakes, and a chibi cat that sits on the city instead of in it.

The style verdict went the same way for a separate reason. Krea-2 draws bold uniform ink
outlines, hatched fur, flat fills with hard shadow edges and screentone-style radial lines;
Z-Image is cleaner but vector-like — airbrush glow, gradient sky, gradient metallic highlights
— and renders the cat as flat unshaded grey with an orange edge-glow over a painted
background, so the subject and the plate sit in two different rendering registers. A frame
whose subject already reads as pasted on is a bad frame 0, because motion will peel it off.

## And the composition survives being animated

The chosen frame went to LTX-2.5 as `--image <path> 0 1.0` on the distilled pipeline, with a
**motion-only** prompt: the text describes what moves and never names the subjects, because
naming them again invites the model to re-invent them. 121 frames, 126 s, 31 GB peak.

A vision round compared the source still against nine frames of the result:

- **Frame 0 is pinned faithfully.** The first sampled frame is the source in every detail that
  matters — both bodies, their contact point, the traffic signal, the searchlight beams, the
  fire on the right, the foreground cars, the centre line, the lighting. The only nameable
  differences are a thicker smoke column and marginally deeper contrast.
- **Two separate bodies stay identifiable to the last sampled frame.** No merge, no subject
  leaving frame, no dissolve into spray, no cut. Crops of the two heads at the eighth and
  ninth samples show fur, ears and whiskers on one and a helmet with an orange visor on the
  other, with no crossed features in either direction.
- **The scale references survive too** — the signal grows and slides left as the camera pushes
  in but is still there at the end, as are the streetlights, the fire and the centre line.
- **And the prompted straining actually happens.** The cat leans in on both forepaws and from
  the sixth sample closes its eyes and lowers its head; the mecha tilts back and *loses
  height*, its head level with the cat's in the source and below the cat's by the last frame;
  the spray at their feet swells; the camera dollies in slowly.

So the morning's negative result was a scale error, not a property of the mechanism. Four
small Hangul glyphs given as frame 0 did not carry forward; a composition occupying half the
frame does. What conditioning cannot preserve is fine detail, and the earlier entry's
sentence should be read that narrowly.

It also fixed a second problem for free. The unconditioned take of this scene spent the last
four of nine sampled frames on subjectless aftermath — half the clip. The conditioned take
keeps its subjects to the end.

One honest defect: from the sixth sample on, **the mecha's own silhouette reorganises** — its
head sinks below its shoulder plates and the armour layering reshuffles. That is one subject
deforming rather than two merging, so it is a different failure from the one this entry is
about, but it is drift that has four times as long to run in a twenty-second clip. That is why
the next arm doubles the duration rather than quadrupling it: 241 frames at the same
resolution, which keeps the validated keyframe and separates "does the composition hold" from
"does the drift compound".

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
