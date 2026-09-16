#!/usr/bin/env python3
"""yue2-gen.py — one music take, and the score it was rendered from.

Why a music model is on this box: LTX-2.5 generates video **and audio** in one pass, which is
its best trick and the wrong tool for a cut sequence. Each clip arrives with its own score
that starts and stops, so an eight-cut film has eight pieces of music. One cue has to come
from somewhere else.

YuE2 was chosen over the alternatives for one reason beyond being current: it **plans before
it renders**. `plan()` returns an ABC score, that score can be edited, and `__call__` with
`abc=` renders the edited version. For a film whose cuts are at known times that is the whole
game — an accent can be put on the impact rather than hoped for.

    yue2-gen.py --style "..." --lyrics-file l.txt --out DIR [--seed N]
    yue2-gen.py --style "..." --plan-only --out DIR        # score only, nothing rendered
    yue2-gen.py --style "..." --abc edited.abc --cot melody --out DIR

Local weights by default, because this machine fetched them with a byte **and sha256** gate
(both verified 2026-09-16 against the repos' own `weights_manifest.json`) and a pipeline that
silently re-downloads from the hub would throw that away.

Everything the take used is written beside the audio: the style prompt, the lyrics, the score,
the seed and the resolved settings, via the pipeline's own `save_artifacts`.
"""

import argparse
import json
import time
from pathlib import Path

MODEL = "/models/YuE2-3B"
VAE = "/models/YuE2-Vae"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--style", required=True, help="style prompt: genre, instruments, mood")
    p.add_argument("--lyrics", default=None, help="lyrics inline")
    p.add_argument("--lyrics-file", default=None)
    p.add_argument("--abc", default=None, help="an edited ABC score to render from")
    p.add_argument("--cot", default="full", help="full | melody (melody renders a given score)")
    p.add_argument("--seed", type=int, default=23)
    p.add_argument("--out", required=True)
    p.add_argument("--model", default=MODEL)
    p.add_argument("--vae", default=VAE)
    p.add_argument("--plan-only", action="store_true",
                   help="produce the ABC score and stop, so it can be edited before rendering")
    a = p.parse_args()

    lyrics = a.lyrics
    if a.lyrics_file:
        lyrics = Path(a.lyrics_file).read_text(encoding="utf-8")
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    import torch
    from yue2 import YuE2Pipeline

    t0 = time.time()
    pipe = YuE2Pipeline.from_pretrained(a.model, vae=a.vae, local_files_only=True)
    load_s = time.time() - t0
    print(f"YuE2 loaded in {load_s:.1f} s", flush=True)

    kw = dict(style=a.style, seed=a.seed, cot=a.cot)
    if lyrics is not None:
        kw["lyrics"] = lyrics
    if a.abc:
        kw["abc"] = Path(a.abc).read_text(encoding="utf-8")

    t = time.time()
    if a.plan_only:
        plan = pipe.plan(**{k: v for k, v in kw.items() if k != "abc"})
        plan.save(str(out / "plan"))
        gen_s = time.time() - t
        print(f"plan in {gen_s:.1f} s -> {out/'plan'}", flush=True)
        audio_s = None
    else:
        song = pipe(**kw)
        gen_s = time.time() - t
        song.save(str(out / "song.flac"))
        song.save_artifacts(str(out / "artifacts"))
        # the point of recording this: a cue is useful only if its length matches the cut list
        try:
            import soundfile as sf
            info = sf.info(str(out / "song.flac"))
            audio_s = info.frames / info.samplerate
        except Exception as e:
            print(f"  could not read the rendered length ({e})")
            audio_s = None
        print(f"song in {gen_s:.1f} s -> {out/'song.flac'}"
              + (f"  {audio_s:.2f} s of audio" if audio_s else ""), flush=True)

    peak = torch.cuda.max_memory_allocated() / 2**20
    (out / "manifest.json").write_text(json.dumps({
        "model": a.model, "vae": a.vae, "style": a.style,
        "lyrics": lyrics, "abc_given": bool(a.abc), "cot": a.cot, "seed": a.seed,
        "plan_only": a.plan_only,
        "load_seconds": round(load_s, 1), "generate_seconds": round(gen_s, 1),
        "audio_seconds": round(audio_s, 2) if audio_s else None,
        "peak_alloc_mib": round(peak), "torch": torch.__version__,
    }, indent=2, ensure_ascii=False) + "\n")
    print(f"peak alloc {peak:.0f} MiB; manifest {out/'manifest.json'}")


if __name__ == "__main__":
    main()
