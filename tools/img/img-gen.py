#!/usr/bin/env python3
"""img-gen.py — one image-generation take, with every parameter recorded beside the output.

Why an image model is on this machine at all: LTX-2.5 was measured on 2026-09-16 to be good
at animating and bad at *staging*. Asked for a giant mecha and a giant cat, it produced one
subject with the other's features absorbed into it — the word "cat" became two pointed ears
on the mecha's helmet. It also holds one moment rather than a sequence: five prompted beats
rendered as two. Both failures are about deciding what is in the frame, which is exactly what
an image model does well and what `--image` conditioning lets us hand it instead of asking.

So this is a keyframe generator whose output is an input to a video run.

  img-gen.py --model /models/Z-Image-Turbo --prompt "…" --out /path/dir
  img-gen.py --model /models/Krea-2-Turbo --wh 1536 1024 --steps 8 --count 4 --seed 23

Both models shipped here are turbo distillations and their own cards say
`guidance_scale=0.0` — like LTX's distilled pipeline they have no CFG to turn up, so prompt
adherence is bought by writing the prompt, not by a knob. The default step counts are the
cards' own (Z-Image 9, which is 8 DiT forwards; Krea-2 8).

Every run writes `manifest.json` next to the PNGs with the resolved parameters, the model's
class name read from its own `model_index.json`, the per-image seconds, and the peak
allocated VRAM — because a keyframe that ends up in a video take needs to be reproducible
from the record rather than from memory.
"""

import argparse
import json
import time
from pathlib import Path

import torch

# Each model_index.json names its own pipeline class; reading it means this script does not
# have to keep a table of which path is which model, and a wrong --model fails loudly.
PIPELINES = {
    "ZImagePipeline": "ZImagePipeline",
    "Krea2Pipeline": "Krea2Pipeline",
}
DEFAULT_STEPS = {"ZImagePipeline": 9, "Krea2Pipeline": 8}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True, help="local diffusers directory")
    p.add_argument("--prompt", required=True)
    p.add_argument("--negative-prompt", default=None,
                   help="ignored by a turbo model at guidance 0; recorded either way")
    p.add_argument("--out", required=True, help="directory for the PNGs and manifest.json")
    p.add_argument("--wh", nargs=2, type=int, default=[1536, 1024], metavar=("W", "H"),
                   help="default matches LTX-2.5's default video geometry so a keyframe "
                        "needs no resize before conditioning")
    p.add_argument("--steps", type=int, default=None, help="default: the model card's own")
    p.add_argument("--guidance", type=float, default=0.0,
                   help="0.0 for a turbo model, which is what both cards here specify")
    p.add_argument("--seed", type=int, default=23)
    p.add_argument("--count", type=int, default=1, help="images, each with seed+i")
    a = p.parse_args()

    model = Path(a.model)
    idx = json.loads((model / "model_index.json").read_text())
    cls_name = idx["_class_name"]
    if cls_name not in PIPELINES:
        raise SystemExit(f"{model}: unhandled pipeline {cls_name!r}; known: {sorted(PIPELINES)}")
    steps = a.steps if a.steps is not None else DEFAULT_STEPS[cls_name]
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    import diffusers
    Pipe = getattr(diffusers, PIPELINES[cls_name])
    t0 = time.time()
    pipe = Pipe.from_pretrained(str(model), torch_dtype=torch.bfloat16).to("cuda")
    load_s = time.time() - t0
    print(f"{cls_name} loaded in {load_s:.1f} s", flush=True)

    w, h = a.wh
    rows = []
    for i in range(a.count):
        seed = a.seed + i
        g = torch.Generator(device="cuda").manual_seed(seed)
        kw = dict(prompt=a.prompt, height=h, width=w,
                  num_inference_steps=steps, guidance_scale=a.guidance, generator=g)
        if a.negative_prompt:
            kw["negative_prompt"] = a.negative_prompt
        t = time.time()
        img = pipe(**kw).images[0]
        dt = time.time() - t
        f = out / f"k{i:02d}-seed{seed}.png"
        img.save(f)
        # torch's own counter, not nvidia-smi: the witness CSV samples at 1 Hz and was
        # measured today to miss a sub-second peak, so the allocator is the better source here
        peak = torch.cuda.max_memory_allocated() / 2**20
        rows.append({"file": f.name, "seed": seed, "seconds": round(dt, 2),
                     "peak_alloc_mib": round(peak)})
        print(f"  {f.name}  {dt:.1f} s  peak alloc {peak:.0f} MiB", flush=True)

    (out / "manifest.json").write_text(json.dumps({
        "model": str(model), "pipeline": cls_name,
        "prompt": a.prompt, "negative_prompt": a.negative_prompt,
        "width": w, "height": h, "steps": steps, "guidance_scale": a.guidance,
        "torch": torch.__version__, "diffusers": diffusers.__version__,
        "load_seconds": round(load_s, 1), "images": rows,
    }, indent=2, ensure_ascii=False) + "\n")
    print(f"manifest {out/'manifest.json'}")


if __name__ == "__main__":
    main()
