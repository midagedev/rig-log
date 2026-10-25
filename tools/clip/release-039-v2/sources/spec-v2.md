# Round clip039v2 — the 0.3.9 release film, studio-grade motion design

Opus round (video authoring and pure aesthetic authoring: the user's standing decision that opus builds release films).

## The bar (the user, 2026-10-25)

"이전보다 훨씬 인상적인 모션그래픽이 되면 좋겠는데. 2026년 실리콘밸리 스타트업에게 외주를 받는 유명한 스튜디오가
만든 것처럼 나오면 좋겠어." — far more impressive motion graphics than the earlier release films, as if a well-known
motion studio that Silicon Valley startups hire in 2026 made it: a launch film, not a slide deck.

What that means here (a starting brief; you own the art direction and say why in the README):
- **Camera and depth.** A continuous camera through one designed space (2.5D or WebGL 3D: three.js is fine), not
  cuts between flat slides. Parallax, depth of field, light that moves.
- **Motion craft.** Every move eased with intent (spring and custom cubic curves, overshoot where it earns it,
  staggered secondary motion, motion blur on fast moves by sub-frame accumulation), match cuts and morphs between
  scenes (a number becomes a bar becomes a card), nothing pops on or off.
- **Typography.** A display face and a mono with real hierarchy; kinetic type for the claims (per-glyph reveals,
  mask wipes), numbers that count up on a tabular mono and land on the beat.
- **Data as the hero.** The models' bytes against the cards and host RAM as physical volume; the expert tier as a
  living system (tokens flowing through cards and host); the before → after gains as one morphing chart, not a
  table; the engine comparisons as racing bars with their conditions under them.
- **Look.** A deliberate palette (deep background, one or two signal colors, subtle grain and glow, light leaks or
  gradients used sparingly), crisp at 1080×1080 and legible at phone size.
- **Sound.** Cuts and hits on the music's beat grid (reuse release-036/034's music or Mixkit 644, as before).

Study first, then design: read `/Users/hckim/repo/rig-log/tools/clip/release-039/` (the draft the previous round
built: its data, beats and scene list are the content contract; reuse its data files and number checks), and the
earlier films' READMEs (release-036, release-034 DESIGN.md) for the pipeline and the size floors. Write a short design
document (`DESIGN.md` in the new directory: art direction, palette, type, the camera path, a storyboard of every
scene with its beat range) before you build.

## Fewer numbers (the user, 2026-10-25: "숫자들이 너무 많아 중요한 숫자 외에는 좀 죽여줘")

The draft showed too many numbers. v2 shows only these as hero numbers (large, counted up, on the beat), one idea a
scene; every other figure is either cut or reduced to a small, low-contrast caption, and a scene has at most two hero
numbers:

1. Size: the two models (≈ 228 GB and ≈ 252 GB) against the two cards' 72 GB. Say it as bytes once, then as volume.
2. MiniMax-M3.1-Flash on the two cards: decode 21 tok/s, prompt 123 tok/s (from the table: 21.03, 122.57/123.62).
   Muse Spark Open: decode 16.7 tok/s. No full table on screen; at most these three.
3. The two 0.3.9 gains as percentages only: decode +33 % (residency), prompt +41 % (the NVFP4 tile). The −2.7 %
   decode cost goes in one small caption, not a hero.
4. Mac, M4 Pro, same sitting (mac-numbers.md section 4). Each pair runs the same weights, so pairs never mix:
   - against mlx-lm on the same MLX 4-bit weights: decode bloomery 101 vs mlx-lm 93 tok/s; prompt at 4,096 ids 1,077
     vs 1,038;
   - against llama.cpp on the same Q4_K_M file: decode bloomery 86 vs llama.cpp 66 tok/s; prompt at 4,096 ids 1,045
     vs 825.
   Two racing-bar moments (decode, prompt), each with its two pairs labelled by their weights; never put bloomery's
   MLX number beside llama.cpp's Q4_K_M number. The 512-id rows, the Q4_K_M-vs-MLX split
   detail and the Ultras' table become captions or one line ("on the M3/M5 Ultra, mlx-lm still reads prompts faster")
   with @avlp12's credit (M5 Ultra, 4,096 ids, before #777: bloomery 3,579 vs mlx-lm
   10,158 — a caption at most).
5. @juliankang4: DGX Spark prefill ×2 (+98 %) and Qwen3.8 four requests at 2× (28 → 56 tok/s). Everything else of his
   is words (the FP4-Local folder, the start screen), not numbers.

Conditions stay (the project's rule: a number carries its conditions) but as one quiet line under a hero number
(machine, model, depth), never as a second headline. PR numbers: none on screen except a small end card listing
them, if at all.

## Content contract (unchanged from the draft)

The content is the draft's: `/Users/hckim/.cache/bloomery/clip039/spec.md` (read it whole) — the NVIDIA half, the
Apple Silicon half (≥ 40 % of the film), the contributors' scene (@juliankang4 by name, one line for @Burntgogi),
≤ 120 s. Mac numbers come from `/Users/hckim/.cache/bloomery/clip039/mac-numbers.md`; its section 4 "Same-sitting
M4 Pro (2026-10-25)" is the Mac comparison (pp512, pp4096, decode, bloomery vs mlx-lm on the same MLX 4-bit weights
and vs llama.cpp on the same Q4_K_M file, 3 rounds, development loop) and section 2a the Ultras' prompt table
(mlx-lm ahead there: show it). Prefill is shown, not hidden. All Mac PRs (#773, #777, #779, #792, #797, #796) are
0.3.9 (the tag was re-made on main). FP4 tensor cores appear only in the DGX Spark scene; on the RTX cards say "card
experts run @juliankang4's NVFP4 kernels". Every number on screen comes from those files, the spec, or a tape you
name, with its conditions; a development-loop number says so on screen.

## What the draft left for v2

- Dropped for length, bring back if the design makes room: #671 (four concurrent 4,096-token requests reach their
  first token in 20.4 s at the median, not 43.9; @juliankang4), the new start screen (#644, #743, his: a capture of
  `bloomery-serve`'s start screen is a strong visual), @Burntgogi's Flint groundwork.
- The draft's own risks: `bp` was never explained on screen (say "A6000 stages, 3090 holds experts, host runs the
  rest" or draw it); "#779 #792 #797 per-call costs" read as bare PR numbers (say what each does, PR numbers small);
  the Ultras scene was the densest.
- Render speed: the draft's `render.py:191` copies the SVG per sub-frame instead of a screenshot each (74 min → 3 min
  19 s on this Mac); start from it. The Mac disk is at 96 %: delete sub-frame dirs once a render is checked.

## Where it goes

New directory `/Users/hckim/repo/rig-log/tools/clip/release-039-v2/`; never edit the draft's directory or the older
films'. Output `out/video-music.mp4` there. Render on this Mac if it runs here; the box only as the draft's spec
allows (plain ssh into `/root/clip039v2-render/`, only while no `/root/bloomery-lead-hold` exists; CPU/browser work,
never the cards; never start or stop another process there). At most one browser at a time; `lock timed out` is
contention.

Self-verification duty: open your own captures (`render.py probe` or its equivalent) at every scene's key frames and
mid-transition frames, compare with DESIGN.md and the size floors, and keep a find → fix log; end with per-axis
SHIP/FIX predictions (motion craft, legibility at phone size, number accuracy, story clarity, beat sync) in
`/Users/hckim/.cache/bloomery/clip039/report-v2.md`. No new looks after the design document except fixes toward it.

## Rules

No git state changes in any repo (no commit, push, checkout, stash, restore, add). Edit only
`/Users/hckim/repo/rig-log/tools/clip/release-039-v2/` and `/Users/hckim/.cache/bloomery/clip039/`. Do not upload.
Never wait with `until ! pgrep -f "<pattern>"` or by scanning `/proc/*/cmdline` (both match your own shell); wait on a
pid captured with `$!` (`kill -0 <pid>`), and send signals only to pids captured at start and written to a file. No
SendMessage to retired agents. If a direct user instruction conflicts with a lead constraint, follow it and tell the
lead.

## Report (last message, ≤ 15 lines + paths)

The mp4 path and length, the art direction in two lines, the scene list (one line each), the SHIP/FIX predictions,
what you could not do, and places outside the assignment where improvement looked possible (path:line + one line).
