# bloomery 0.3.9 — release film v2, design

1080×1080, 60 fps, 90.47 s (193 beats of instrument-s1004 at 127.997 BPM: the track straight from its lead-in to bar
99, then the draft's last two stretches, so the drop, the Apple Silicon hit and the E bar keep their beats).
The draft (`../release-039/`) is the content contract; this film rebuilds the look, the motion and the number count.

## Art direction: "the bloom"

A bloomery is the furnace that turns ore into a bloom of iron. The film is one dark foundry floor: an obsidian
plane under fog that runs to the horizon, lit by a single ember that moves. Everything bloomery does is molten metal
(ember light, a white-hot core, a soft bloom); everything else (other engines, "before" states, the hardware) is cool
steel and glass. One camera flies through the space from station to station; it never cuts. Numbers are objects:
the models are cast monoliths whose height is their bytes, the cards are a glass vessel, a gain is a bar of metal that
pours longer, the Mac races are lanes of light. A launch film, not a slide deck: one idea a station, at most two hero numbers, everything else quiet.

Why this and not the draft's "Instrument" grammar: the user asked for a studio launch film; the furnace is the
project's own name, so the metaphor carries the brand without a logo, and molten-vs-steel gives the one signal
colour a meaning (ours) that the viewer learns in the first ten seconds.

## Palette (sRGB)

| token | hex | use |
|---|---|---|
| void | `#07080A` | background, fog colour |
| floor | `#14171C` | grid minor lines (major `#1D2128`) |
| bone | `#EDEAE4` | primary text |
| ash | `#8E949C` | captions, conditions (6.3:1 on void) |
| steel | `#7F96AD` | other engines, "before", glass edges |
| ember | `#FF6A2B` | bloomery's numbers and bars, contributors' names |
| core | `#FFD9B8` | the white-hot centre of ember marks (bloom source) |

Grain (per-pixel hash, re-seeded every frame, ±2.2 %), a vignette (−22 % at the corners), a 0.6 px chromatic offset
at the edges, and a bloom pass on the ember layer. Light leaks only at the two big hits (the drop, beat 1; the Apple
Silicon hit, beat 77): one horizontal anamorphic streak each, under the flash limit.

## Type

- Display: **Geist** (variable, SIL OFL 1.1). Headlines 600–650, tracking −2 % at ≥ 100 px.
- Numbers and captions: **Geist Mono** (variable, SIL OFL 1.1). Heroes at weight 300, 200–300 px, every digit the
  same width, so a count-up never jitters; units at 500 / 64 px. Captions and conditions 400 / 44 px.
- Hierarchy: hero number > headline (88–150 px) > label (52–60 px) > caption (44 px ash). Nothing under 44 px at
  1080 (22 px on a phone), release-034's floor.
- Kinetic type: headlines rise glyph by glyph out of a mask (rise 0.5 em, 0.36 s expo-out, 28 ms stagger); captions
  wipe in left to right (0.30 s); heroes count up from their landing beat (a quint run in 0.18 s that lands on the
  target as it settles; the value is rounded, so it changes on every frame of the run and no digit flips alone); a swap rolls each digit like a slot (0.18 s out, 0.24 s in).

## Motion

- Easing: flights `cubic-bezier(.65,0,.2,1)`; arrivals expo-out `1−2^(−10t)`; a damped spring
  (ζ 0.55, 4.2 Hz) for the slabs that rise and the bars that land, overshoot ≤ 4 %; secondary elements trail the
  primary by 60–120 ms.
- Camera: a perspective camera (focal 1500 px, ≈ 40°), positions and look-at targets per station, flights on a
  Bezier arc between them. While a station is read it breathes: a dolly of ≤ 2 % scale and a ≤ 12 px parallax drift
  over the hold, so settled text moves < 20 px/s (the read check). The Apple half's holds have no monolith behind them,
  so they carry the rest of the secondary motion: a wider drift (the M4 lanes drift on through both races; ULTRAS
  trucks left and dollies in, yaw held, so the text's 8 % of the two cancels at the left margin), an ember flicker on
  bloomery's bars (three slow sines, glow 0.77–1.23×, tinted toward the core at the peaks) and pale embers rising
  slowly behind (the THANKS sparks' language, paler and slower). None is a data mark.
- Depth of field: the focus sits on the station's text plane; circle of confusion from depth, composited in five
  blur buckets on the GPU. Dust motes in the air give parallax and bokeh.
- Motion blur: each frame is the mean of up to 16 sub-frame draws over a 180° shutter (fewer when nothing moves),
  accumulated in a float buffer before the post pass.
- Nothing pops: every element enters and leaves by a move, a wipe or a fade of ≥ 0.12 s, except the beat slams.
- Beat grid: flights start one beat before a station and arrive on its first beat; every hero lands on a beat.

## Numbers on screen (spec-v2 "Fewer numbers")

Heroes (large, counted up, on the beat), at most two a station: 226 GB, 250 GB (BYTES, the weight files' bytes);
21, 123 tok/s (M3.1); 2×, 28 → 56 tok/s (THANKS); the Mac pairs as racing bars
(bloomery's value large, the other engine's smaller in steel): decode 101 vs 93 (MLX 4-bit), 86 vs 66 (Q4_K_M);
prompt at 4,096 ids 1,077 vs 1,038, 1,045 vs 825. Smaller: the vessel's 72 GB, Muse's 16.7 tok/s decode, +98 %,
@avlp12's M5 Ultra on its own bar (one file, `Q4_K_M`: 3,831 → 5,972 tok/s prompt @4,096, 212 tok/s decode). mlx-lm's
10,162 on the same Ultra ran its own MLX 4-bit weights, so it is one ash caption that names them and has no bar: two
different weight files never share a scale or a bar on screen (only the M4 pairs race, each on one file and on its own
scale: its bloomery bar at full length, its partner at their ratio, as on the Ultra's bar). The 0.3.9
gains caption (+33 % / +41 %) did not fit the read time and is out. Conditions: one quiet ash line under a hero. No PR numbers on screen.

## The space and the camera path

World metres, floor y = 0, +z forward. Each station has a rest pose (camera position, look-at, focus) and a text
plane 6 m in front of it, where 1 px of the 1080 layout is 4 mm, so a station is laid out in pixels. While a station
is read its camera drifts from one rest pose to the other; the text plane rides that drift (all but 8 % of it), so read
text holds still on screen while the world behind it (monoliths, floor, dust, lights) keeps its full parallax. On a
flight the plane stays at its end pose, so the text flies out with the world.

| station | where | camera |
|---|---|---|
| TITLE | origin | eye height, slow push |
| BYTES | z 24.5, the two monoliths; the glass vessel in front of them at z 23 | low, looking at them straight |
| M3.1 | z 52, the M3.1 monolith behind, out of focus (halfway between BYTES and THANKS, so both one-beat flights are ~30 m) | front |
| THANKS | z 82, x −7.4 | warm, close, sparks rising behind |
| APPLE | z 106, a die of 20 GPU cores | whip in on the hit, pale key light |
| M4 RACES | z 124 | level with the lanes as they race |
| ULTRAS | z 118 | pull back and up, the lanes gone; while read a slow truck left and dolly in |
| STEPS | z 146 | the prompt's tiles 9 m behind the list |
| END | z 152 looking back | whip around: every station's light on the floor behind the lockup |

## Storyboard (film beats; a beat is 0.46876 s; beat b starts at b × 0.46876 s)

Every flight is one beat long, from a station's out to the next station's first landing, except the first (title →
BYTES, b10 → b12, through drifting embers); M4 DECODE → M4 PROMPT is no flight, the camera drifts on. No frame is
empty for more than a beat. The lead light (the moving ember, pale in the Apple half) is visible only on the flights,
where the shutter turns it into a streak.

| beats | station | what happens |
|---|---|---|
| 0–1 | lead-in | dark; the ember drifts in from the horizon |
| 1–11 | TITLE | the drop (b1): a streak, `bloomery` rises glyph by glyph out of a mask; `0.3.9` rolls in ember; b3 an ember rule draws and the halves wipe in as two centred pairs: `NVIDIA two giant models` / `APPLE SILICON its own Metal backend` |
| 11–26 | BYTES | one move. Flight b10→b12 through drifting embers, both monoliths already rising; b12 `226 GB` and `250 GB` count up together and land b13 over `Muse Spark Open` and `MiniMax-M3.1-Flash`; b15 the glass vessel of the cards' 72 GB (the A6000's 48 under the 3090's 24) rises in front of them, `72 GB RTX A6000 + RTX 3090` in one line under it; b17 `Neither model fits.` and the part of each monolith the vessel could hold glows ember |
| 26–46 | M3.1 | the result card, the M3.1 monolith behind, out of focus. The one-beat flight lands on b26 and the answer `bloomery runs both.` rises where `Neither model fits.` stood (same place, size and weight); b27 `MiniMax-M3.1-Flash`, `21 tok/s` decode and `123 tok/s` prompt land and count together (settled by b27.4); b29 `Muse Spark Open · 16.7 tok/s decode`, the quiet third; b33 `RTX A6000 + RTX 3090 · serving defaults` in ash and `card experts run @juliankang4's NVFP4 kernels`; b44 the `'s` fades, then the name lifts out of the line and rides the one-beat flight (b45 → b46) into the next station's headline |
| 46–77 | THANKS | `@juliankang4` in ember, `measured on his DGX Spark`, sparks rising; b50 `2×` slams: 4,096-token prefill (`NVFP4 checkpoint · +98 %` quiet); b58 `28 → 56 tok/s`, Qwen3.8, four requests at once; b68 his other work in words (`the FP4-Local folder reader`, `the new start screen`) and `@Burntgogi · shared model code · Flint groundwork`; the one-beat flight out runs through embers |
| 77–92 | APPLE | the hit (b77): a pale streak, the light turns pale. `Apple Silicon` rises, `bloomery-serve-metal`, `its own Metal backend`; a die of 20 GPU cores lights core by core behind; b82 `Qwen3.6-35B-A3B on Mac GPUs`, `MLX 4-bit checkpoints via prepare`, `prefix reuse`; the card holds to the flight out on b91 |
| 92–115 | M4 DECODE | b92 `M4 PRO · DECODE`, `tok/s`, `… three rounds · development loop` and the first pair's label and lane names land; two pairs, each labelled by its weights, race: b93 `same MLX 4-bit weights` bloomery 101 vs mlx-lm 93; b97 `same Q4_K_M file` bloomery 86 vs llama.cpp 66, each pair on its own scale (both bloomery bars full length). The decode bars and numbers hold to b116 |
| 115–137 | M4 PROMPT | b116 the decode lanes collapse at full speed, their values cut with them, and the tag cuts to `M4 PRO · PROMPT · 4,096 IDS` (bare lanes under a beat); the same lanes race again: b117 1,077 vs 1,038; b121 1,045 vs 825; `random token ids · one sitting · development loop` |
| 137–160 | ULTRAS | pull back and up, the lanes gone; the one-beat flight lands b137: `M5 Ultra, measured by @avlp12` (the handle in ember), `Q4_K_M` over the M5 Ultra's own ember bar, on its own scale, which grows to #777's SIMD-group head (a dashed steel tick) and on b138 springs to 0.3.9's, with `3,831 → 5,972 tok/s prompt @4,096 · 212 tok/s decode` and `0.3.9 · neural-accelerator GEMMs`; b149 mlx-lm in ash words only, naming its weights: `mlx-lm on its own MLX 4-bit weights: 10,162 tok/s — still ahead` (no bar: another file is never on our bar's scale) |
| 160–185 | STEPS | `0.3.9 · PROMPTS ON THE MAC`, an ember timeline: b160 `batched prompt passes` (a prompt's rows slide in as one block, 9 m behind), b166 `experts in 64-row tiles` (the block splits into tiles), b172 `less fixed cost per prompt call` (the gaps between calls close), b178 `M5 neural accelerators · picked by the device` (the tiles get dashed ember outlines); the one-beat flight out runs through pale embers |
| 185–193 | END | the E bar (b185): the camera whips round; `bloomery 0.3.9`, `github.com/midagedev/bloomery`; every station's light lies on the floor behind; fade over the last two beats |

Each station's groups land on the beats above and hold for their read time (4 words a second plus 1 s a number,
at least 2.5 s, from the group's settle to the flight out); `make_data.py` refuses a storyboard that does not.

## Floors and checks (release-034's, held by `render.py check`)

- Read text ≥ 44 px at 1080 once settled, inside the 72 px margins, no two settled read boxes overlap.
- Data marks: steel/glass edges ≥ 3 px, ember data marks (bars, monolith bands) ≥ 24 px thick. Atmosphere (dust,
  grid, the light) is not a data mark.
- While a group is read its text moves < 20 px/s and changes scale < 3 %/s.
- WCAG 2.3.1: at most three large-area flashes in any second (the hits included).
- Every string drawn is a key of `data.json`'s copy; every number in it traced by `make_data.py` to its source.
