# bloomery 0.3.4 release film: design (phase 1)

This file is everything phase 2 needs to build and render the film. The other inputs are next to it:

- `styles/style.html`: the drawing helpers and the settled layout of six shots;
- `beatsheet.py`: the shot timing at any tempo;
- `research.md`: why each move was chosen;
- `musicgen/`: the music path.

The film is 1080×1080 at 60 fps, 38–44 s long, for X/Twitter, where it is seen about 540 px wide. Every string on
screen is English.

## Concept

One pulse of current runs the whole film. It strikes the title, races along circuit traces into a 24 GB card, fills
a grid one token at a time, crosses a row of Sparks and arrives in an embedding. Every number lands where the pulse
arrives, the camera follows the current and cuts on the beat, and everything holds still while there is text to read.

## Why this is a step beyond release-031

0.3.1's "ember" film was flat paper, a fixed type scale, and tilted cards cut on the beat. The user's verdict on its
draft was "너무 모션그래픽 답지 않게 정돈되어 있다": too tidy to be motion graphics. This film makes these moves:

1. **Continuity instead of cuts in the main run.** The camera follows the current along a trace (follow pan) or flies
   into the card's 24 GB box and comes out in the next shot (zoom-through). Hard cuts are kept for one beat-locked
   montage. (Framer, Ordinary Folk, OpenAI Astra)
2. **Kinetic type on a width axis.** Anybody's `wdth` axis (50–150) is animated continuously. "74B" arrives too wide
   for the frame, cropped by both edges, and squeezes to exactly the card's width while "-A9B" grows in beside it.
   "bloomery" condenses into place under the version. 0.3.1 never changed a letterform. (DIA State of Crypto, Rive)
3. **Light, not paper.** A near-black ground with glow, bloom and grain re-seeded on twos. Volt is the only accent and
   is kept back for the current, the hero numbers and the lit expert ranges. (Linear, Arc, basement/Vercel)
4. **A number you can see running.** Under 86.69, one cell lights per token at exactly that rate. When the slot swaps
   to the prompt's 2,047, the same grid floods in four frames. Both numbers are our own. (OpenAI Ultrafast,
   without the race)
5. **Hero numerals the DIA way.** Regular weight, about 27 % of the frame height, flush left, arriving whole with no
   count-up. The caption comes after the number. Only the current moves during the hold.
6. **A density curve.** A sparse open (a stepped leader, then one strike), a dense middle, a 1 s-per-shot montage,
   and a still end lockup. 0.3.1 had one even rhythm.
7. **The subject's own marks are the graphics.** Traces with 45° bends, pads, the card's fans and edge-connector
   fingers, expert cells, NVMe slabs and a vector of cells. There is no stock iconography and no lightning cliché:
   there is exactly one geometric strike at each end. (Buck/Nothing, ManvsMachine)
8. **Measured safety.** A flash check (≤ 3 flashes a second) and a pulse-to-text clearance check join 0.3.1's checks.

## Palette

| Token | Hex | Use |
|---|---|---|
| ink | `#07080A` | ground (radial `#101216` → `#040506` from the centre, `ground()` in style.html) |
| carbon | `#121418` | card body, NVMe slabs, node fills |
| graphite | `#2B2E34` | unlit traces, unlit cells, card details |
| steel | `#8D929B` | secondary text (units, conditions), lit token cells, icon strokes |
| bone | `#F2EFE8` | primary text, card outline, the strike's core runs `rgb(255,252,236)` |
| volt | `#FFD21E` | the one accent: the pulse, hero numbers, version, lit expert rows, the vector |

At least 75 % of every frame stays near-black. Volt never fills more than one hero element plus the current at once.

## Type

Fonts are OFL only. The files and their licences are in `fonts/`, all from the google/fonts repository.

- **Anybody** (`Anybody-VF.ttf`, `Anybody-Italic-VF.ttf`; `OFL-anybody.txt`, © 2020 The Anybody Project Authors).
  Axes: `wdth` 50–150, `wght` 100–900. It is used for every display line, numeral and sentence, through CSS
  `font-variation-settings`. Canvas 2D cannot animate `wdth` continuously, so type lives in SVG (below).
- **Martian Mono** (`MartianMono-VF.ttf`; `OFL-martianmono.txt`, © 2021 The Martian Mono Project Authors). It is
  used for tags, units, conditions, lane labels and the URL: caps, 44 px, letter spacing 2–6.

| Role | Face | Size at 1080 | wdth / wght | Colour |
|---|---|---|---|---|
| hero numeral (86.69, 2,047) | Anybody, `tnum` | fit to 952 px (~400 px) | 100 / 380 | volt |
| display word (74B-A9B, EMBEDDINGS, bloomery) | Anybody | fit to 936–946 px | 50 / 900 | bone |
| oversize arrival (74B) | Anybody | fit to 1200 px, cropped | 150 / 900 | bone |
| version (0.3.4) | Anybody | fit to 744 px | 150 / 900 | volt |
| caption (at depth 4096) | Anybody | 76 px | 100 / 700 | bone |
| sentence (the whole model on the card) | Anybody | 46–48 px | 74–100 / 600 | bone |
| tag, unit, conditions, URL | Martian Mono caps | 44 px | — | bone / steel / volt |

`fitW(el, w)` in style.html fits a line to a width and throws below 44 px. If a line will not fit, condense it with
`wdth` first, then letter spacing. Never shrink it under the floor.

## Grid and floors

- Margin 72 px on every side. The tag line's baseline is y 128 in every data shot (the two-tier label: a mono tag over
  the value, in the same place each time). The bottom line's baseline is y 1000–1008.
- Floors at 1080 (the phone view is half of each):
  - text ≥ 44 px;
  - dark marks ≥ 12 px (traces are 12 px);
  - volt accent marks ≥ 24 px (cells, fingers, pads);
  - the pulse's lit trail is ≥ 12 px wide and its head is ≥ 24 px.
- Edge: settled text stays inside the margins (a −6 to −10 px optical offset for big type is allowed). A deliberate
  crop (74B's arrival) is an arrival state, not a settled one.
- Clearance: the pulse's head and its glow keep ≥ 24 px from any text bounding box.

## Marks: what style.html already draws

Phase 2 lifts these helpers unchanged into `film.html`. The numbers in each `FRAMES.<shot>` function are the settled
positions.

- `route(x, y, "r120 dl60 …")` builds a path with 45° bends. `trace(pts)` draws it as a 12 px graphite line with
  round joins.
- `pulse(ctx, pts, s, L, {lit})` draws the current: a lit trail behind the head at `lit` volt alpha, a 14-step comet,
  three glow passes (`[w·7, .10, blur 26]`, `[w·3, .25, 8]`, `[w, .9, 0]`) and a white head. `s` is the arc position.
  The pulse moves at ≤ 600 px/s and makes one run per hold.
- `strike(ctx, pts, k, w)` draws the geometric strike: a mitred zigzag, three glow passes (`[w·9, .08, 60]`,
  `[w·4, .22, 22]`, `[w·1.8, .6, 6]`) and a bone core. `k` (0–1) is its heat. The title's path is
  `[[214,-30],[150,196],[236,196],[150,476]]`, w 20.
- `fan()`, `pad()`, `rect()`, `circ()`, `line()` draw the card, the nodes and the icons.
- `bloom(ctx, x, y, r, a)` is a soft volt glow.
- `grain(ctx, seed, a)` is a 270 px noise tile with overlay blending. Its seed is `floor(frame / 2)`, so all six
  subframes of a frame share one grain (no motion blur on grain) and it changes on twos.
- `tokenGrid(lit)` (shot DECODE) draws 26 × 5 cells of 24 px on a 36 px pitch at (72, 748): graphite unlit, steel lit,
  and the newest cell volt with a 70 px bloom.

The stack is three layers inside one 1080 stage:

1. a back canvas: ground, glow, pulse, bloom;
2. an SVG layer: type and crisp shapes, so `wdth` animates and edges stay sharp;
3. a front canvas: the strikes and the grain.

`txt()` adds every string it draws to `window.LOG`; the check compares that with `data.json`.

## Motion system

All times are on the music's beat grid (beat = 60/BPM s). A change starts on its beat, and the picture may lead the
hit by up to 2 frames, never lag it. In practice every switch is computed at the beat time minus half a frame.

| Move | Duration | Curve | Notes |
|---|---|---|---|
| arrival (slam) | 0.16–0.22 s | expo-out `1 − 2^(−10t)` | scale 1.25→1 or a 40 px rise. Opacity 0→1 over the first 0.06 s only |
| squeeze | 1 beat | expo-out | `wdth` from 150 to 50. The font size is re-fitted every frame, so the width tracks the target |
| tag/caption | 0.16 s | expo-out | fade plus an 8 px rise, ½–1 beat after its value |
| slot swap | 0.10 s out + 0.16 s in | expo-in, then expo-out | the old string goes up 40 px and fades; the new one rises from +40 px. Only the slot changes |
| follow pan | 0.30 s | expo-out | the camera translates up to 1080 px along the trace the pulse is on, ending with the pulse head where the next shot's trace begins |
| zoom-through | 0.30 s | constant log rate | the camera scales 1→12× about a point inside a dark box. The next shot is drawn inside that box at 1/12 and is at 1× when the zoom ends |
| hard cut | 0 | — | montage only, plus TITLE→BOLT |
| strike | heat 1 on the beat frame, then 0.2 s decay | `k = (1 − t/0.2)²` | no flicker. Two strikes in the film (TITLE, END) |
| pulse run | ≤ 600 px/s | linear along the arc | starts on a beat. One run per hold, then the trace stays lit at `lit` alpha |
| token fill | at the measured rate | `floor(rate · t)` cells | decode at 86.69 cells/s (130 cells in 1.50 s). Prompt at 2,047 cells/s (130 cells in ~4 frames). When full, the lit cells ease from steel to `#4A4E56` over 0.4 s and hold still |
| grain | re-seeded every 2 frames | — | a = 0.06–0.08 |

During a hold, nothing moves except the current (the pulse, the token head) and the grain. Type never drifts.

## Read time

Read time is the 0.3.1 rule: 4 words per second plus 1 s per number, at least 2.5 s. The clock starts when the
card's last element settles (its landing beat + 0.16 s). A card then ends on the first beat after that.

- **Numbers** are measured or sized quantities: 86.69, 2,047, 4096, 250, 24, 74B-A9B.
- **Words** are everything else, versions and names included: 0.3.4, 3.5, v1, RTX 3090, model names, handles, the
  URL.
- `·` separators are not counted.

`beatsheet.py BPM` prints the table below at any tempo. Phase 2's `make_data.py` owns the real timing and must reach
the same shot lengths.

## Beat sheet

Beats are counted from each shot's start (b0 = the shot's first beat). "Last" is the beat of the card's last landing;
its read clock starts then. On the picked track (`volt-s1004`, Music below) the film opens on clip beat 23. The
energy then lines up with the story:

- TITLE rides the build;
- the beat enters on BOLT b3 (the 24 GB landing);
- a one-bar break sits under DECODE's last beats;
- the drop lands on PROMPT b0, so the token grid floods on it;
- the music's last hit is END b8.

| Shot | Length | Last | Read | On screen, by beat |
|---|---|---|---|---|
| LEADER | 4 beats | — | — | b0–b3: a stepped leader comes down the title strike's path one 45° step per beat. Each step is 12 px steel at 60 % that flashes bone for 2 frames, then dims. b3: the tip reaches y 476. No text |
| TITLE | to the read | b1 | 2.5 s (3 words) | b0 (a bar's downbeat in the build): the strike (return stroke) along the leader's path. "0.3.4" slams in, volt, right-aligned. The trace at y 476 draws right from the strike's foot, and the pulse runs it once. b1: "bloomery" condenses from wdth 150 to 50 into place under the trace. The "RELEASE" tag lands top right |
| BOLT | to the read | b3 | 4.25 s (9 w + 2 n) | Hard cut on b0: "74B" slams at 1.4×→1×, wdth 150, cropped by both frame edges (b74pre), with the "NEMOTRON 3.5 BOLT" tag at y 128. b2: the squeeze. "74B" condenses to wdth 50 while "-A9B" grows in, and the line ends at 936 px wide (y 456); the card outline draws in under it (0.3 s). b3: "24 GB" lands in its box, the 12 fingers light left to right (one per frame), the pulse runs the trace into the fingers, and "the whole model on the card" lands at y 1008 |
| DECODE | to the read | b1 | 4.5 s (6 w + 3 n) | Zoom-through into the 24 GB box on b0, ending at 1× on b0 + 0.3 s. "DECODE" and "TOK/S" land on the tag line, and "86.69" lands whole, flush left. b1: "at depth 4096", and the token grid starts filling at 86.69 cells/s. "RTX 3090 · 250 W" lands on the bottom line |
| PROMPT | to the read | b0 | 2.75 s (3 w + 2 n) | The drop. Slot swap on b0: "DECODE" → "PROMPT", "86.69" → "2,047", "at depth 4096" → "a 4096-token prompt". The grid clears with the old slot and floods at 2,047 cells/s. "TOK/S" and the conditions line stay |
| SPARKS | to the read | b2 | 4.0 s (16 w) | Follow pan on b0: a trace leaves the grid's last cell, and the camera rides it up a 45° bend onto the bus. "SEVERAL DGX SPARKS" and "SERVE ONE MODEL" (volt) land. b0, b0.5, b1: the three nodes branch onto the bus left to right, one per half beat, each lighting its own rows of expert cells. b2: the NVMe slabs drop under the nodes, the third node's NVMe drop line runs hot, and "each node pages its experts from its own NVMe" lands |
| MODELS | to the read | b1 | 2.5 s (7 w) | Slot swap of the header and the sentence; the nodes stay. b0: the header becomes three stacked names, "Qwen3.8", "GLM-5.3-Flash" and "DeepSeek-V4.1-Flash" (Anybody 88 px, wdth 62, bone; lines at y 200, 300, 400). b1: the sentence becomes "over RDMA · by @juliankang4" |
| TEXT | 2 beats | — | — | Hard cut on b0: "TEXT" (Anybody wdth 150, wght 900, fit to 936 px, bone) over the text-lines icon at 4× |
| VIDEO FRAMES | 2 beats | — | — | Hard cut: "VIDEO FRAMES" (wdth 50, fit to 936 px) over the film-strip icon at 4× |
| AUDIO | 2 beats | — | — | Hard cut: "AUDIO" (wdth 150) over the waveform icon at 4×, its bars pumping on the beat |
| EMBED | to the read | b1 | 3.25 s (13 w) | Hard cut on b0: the three lanes (TEXT, FRAMES, AUDIO) with their icons at 1×, and "EMBEDDINGS" with "beside the chat model" landing. b1: the tag "EmbeddingGemma 2 · EmbeddingGemma v1" lands, the current runs the three lanes into the vector, the cells light (the middle one first), and "/v1/embeddings" lands in volt |
| THANKS | to the read | b1 | 3.0 s (12 w) | The vector's cells collapse into one volt line, which becomes the trace on this card. b0: "thank you". b1: "@juliankang4" over "multi-node tier · embeddings · audio" (mono, steel), and "@Burntgogi" over "tokenizer · placement · gate fixes" |
| END | to the music's last hit | b1 | 2.5 s (3 w) | b0: the second strike lands. "bloomery" (wdth 50, wght 900) and "0.3.4" (volt) lock up. b1: "github.com/midagedev/bloomery" (mono 44, steel). The pulse runs the trace under the lockup once and stops fully lit on the music's final hit. The last frame is still |

Times at three tempos, from `beatsheet.py` (film seconds, before the END tail):

| Shot | 128 BPM | 140 BPM | 172 BPM |
|---|---|---|---|
| LEADER | 0.00–1.88 | 0.00–1.71 | 0.00–1.40 |
| TITLE | 1.88–5.16 | 1.71–5.14 | 1.40–4.53 |
| BOLT | 5.16–11.25 | 5.14–11.14 | 4.53–10.12 |
| DECODE | 11.25–16.41 | 11.14–16.29 | 10.12–15.35 |
| PROMPT | 16.41–19.69 | 16.29–19.29 | 15.35–18.49 |
| SPARKS | 19.69–24.84 | 19.29–24.43 | 18.49–23.37 |
| MODELS | 24.84–28.12 | 24.43–27.86 | 23.37–26.51 |
| TEXT / VIDEO FRAMES / AUDIO | 28.12–30.94 | 27.86–30.43 | 26.51–28.60 |
| EMBED | 30.94–35.16 | 30.43–34.29 | 28.60–32.44 |
| THANKS | 35.16–38.91 | 34.29–38.14 | 32.44–36.28 |
| END (read) | 38.91–42.19 | 38.14–41.57 | 36.28–39.42 |
| total beats | 90 | 97 | 113 |

At 128 BPM the film is 42.2 s before the tail, so the END tail can be at most 1.8 s. At 172 BPM the tail can run
2–4 s. If a track forces the film over 44 s, shorten the montage shots to 1 beat each before cutting any read time.

**On the picked track** (`volt-s1004`, 171.979 BPM, beat 0.34888 s, first beat 0.3325 s), the film is 113 beats,
39.42 s. Film beat f is clip beat f + 23, at clip time 0.3325 + (f + 23) × 0.34888 s.

| Shot | Film beats | Film s | Clip s | What the music does there |
|---|---|---|---|---|
| LEADER | 0–4 | 0.00–1.40 | 8.36–9.75 | atmospheric build |
| TITLE | 4–13 | 1.40–4.54 | 9.75–12.89 | build; the strike on a bar's downbeat (clip beat 27) |
| BOLT | 13–29 | 4.54–10.12 | 12.89–18.47 | the beat enters around 14 s, which both listening calls heard: BOLT b3 is clip 13.94 s |
| DECODE | 29–44 | 10.12–15.35 | 18.47–23.71 | groove; a one-bar break at 22.66 s (bar RMS −24 dB) under the dimmed grid |
| PROMPT | 44–53 | 15.35–18.49 | 23.71–26.85 | **the drop** (clip beat 67, +8.4 dB over the 8 beats before); the grid floods on it |
| SPARKS | 53–67 | 18.49–23.37 | 26.85–31.73 | the loudest section (bars −11 to −12 dB) |
| MODELS | 67–76 | 23.37–26.51 | 31.73–34.87 | |
| TEXT / VIDEO FRAMES / AUDIO | 76–82 | 26.51–28.60 | 34.87–36.97 | |
| EMBED | 82–93 | 28.60–32.44 | 36.97–40.80 | |
| THANKS | 93–104 | 32.44–36.28 | 40.80–44.64 | |
| END | 104–113 | 36.28–39.42 | 44.64–47.78 | the music cuts at 47.43 s (END b8, film 39.07 s); the lockup holds one more beat over the reverb tail |

Phase 2 sets `MUSIC_ID=volt-s1004` and `OPEN_AT_BEAT=23` in `make_data.py`. A cut that should open a bar (bars open
on clip beats ≡ 3 mod 4) can take one beat from its card's spare time; every card's read time stays as the table
says.

### Strings and their sources

Every string's source line, verbatim. "notes" is the public 0.3.4 release body
(`/Users/hckim/orca/briefs/reports/release-notes-0.3.4.md`, the same text as
https://github.com/midagedev/bloomery/releases/tag/v0.3.4); "README" is `bloomery/README.md` at 9723698f2.
`make_data.py` must check each string against its source when it builds `data.json`, and stop by name on a mismatch.

| String | Source line |
|---|---|
| bloomery, 0.3.4 | notes:1 "bloomery 0.3.4 adds **Nemotron 3.5 Bolt 74B-A9B**" |
| RELEASE | the film's tag (a label, no claim) |
| NEMOTRON 3.5 BOLT, 74B, -A9B | notes:1 "Nemotron 3.5 Bolt 74B-A9B" |
| 24 GB | README:159 "**One RTX 3090 24 GB**" |
| the whole model on the card | README:168 "\| Nemotron 3.5 Bolt 74B-A9B `24GB` (0.3.4) \| the whole model on the card \|" |
| DECODE, TOK/S, 86.69, at depth 4096, RTX 3090 · 250 W | notes:14 "\| Decode at depth 4096, RTX 3090 (250 W) \| 86.69 \|" |
| PROMPT, 2,047, a 4096-token prompt | notes:12 "\| Prompt 4096, RTX 3090 (250 W) \| 2047.32 \|" and README:168 "1,773 / 2,047" under README:161 "Prompt tok/s (P = 512 / 4096)" |
| SEVERAL DGX SPARKS, SERVE ONE MODEL | README:41 "Several DGX Sparks serve one model" |
| each node pages its experts from its own NVMe | README:41 "a tier node on another Spark owns routed experts by id range and pages them from its own NVMe"; notes:71 "charges node 0 for row-table fills from NVMe" |
| Qwen3.8, GLM-5.3-Flash, DeepSeek-V4.1-Flash | notes:73 "Qwen3.8 decodes across two Sparks"; notes:76 "GLM-5.3-Flash and DeepSeek-V4.1-Flash open a node expert tier" |
| over RDMA · by @juliankang4 | notes:67 "**Multi-node serving over RDMA (DGX Spark)**, by @juliankang4" |
| TEXT, VIDEO FRAMES, AUDIO, FRAMES | notes:33 "text, sampled video frames, mono 16 kHz f32 PCM audio" |
| EMBEDDINGS, beside the chat model, /v1/embeddings | notes:33 "`/v1/embeddings` beside the chat model" |
| EmbeddingGemma 2 · EmbeddingGemma v1 | notes:1 "over EmbeddingGemma 2 (#323) and EmbeddingGemma v1 (#390)" |
| thank you, @juliankang4, multi-node tier · embeddings · audio | notes:167–169 (Thanks: "the multi-node tier link", "the EmbeddingGemma 2 encoder and the `/v1/embeddings` endpoint", "the gemma4a audio groundwork and audio tower") |
| @Burntgogi, tokenizer · placement · gate fixes | notes:172–173 ("the tokenizer codepoint refusal", "the placement overflow refusals", "the gate strictness fixes") |
| github.com/midagedev/bloomery | the repository |

What the film does not say:

- no comparison with any other engine;
- no speed for multi-node (the notes give none);
- no "built by one person";
- nothing about Rust making it fast;
- no Nemotron 3 Nano line, to keep fewer facts told well.

The A6000 rows (87.42, 2,772) are left out so the one card in the film is the 3090, which the 24 GB claim is about.

## Generated imagery

None. Everything is procedural (traces, pulse, strikes, card, cells, icons, grain), because:

- it animates exactly on the beat grid;
- it renders deterministically, frame for frame, under the check;
- it carries no risk of letterforms in a generated image;
- it holds the six-colour palette exactly.

A generated plate (a 3D card render, say) would arrive in a different light and finish from the type and would not
move with the current. Grok imagery was considered and not needed.

## Music

The track is generated on the box with ACE-Step 1.5 (MIT; the model card allows commercial use of outputs). The
prompts name only the genre: no artist, track or known riff.

- `musicgen/prompts.json` holds three prompts, each ending "ends on one hard final hit":
  - `surge`, 128 BPM: electronic breakbeat, distorted analog synth bass, a riser into a big drop;
  - `arc`, 140 BPM: half-time electro, FM bass stabs, tape stops, stop-time hits;
  - `volt`, 172 BPM: drum and bass, reese bass, glitch stabs.
- The run is 3 prompts × 8 seeds × 48 s. It uses the XL-sft DiT at 50 steps (guidance 7.0, shift 1.0) and the 4B
  5 Hz LM, with batch 4, on the RTX A6000.
- `install.sh` ran on the box (rc 0, `/root/musicgen/install.rc`).
- Generation ran on 2026-10-18 under the timing lease as an exclusive job: card `musicgen-034.card` (minutes 8..30;
  the same card is in `bloomery/docs/cards/` for the lead to commit), from the bloomery tree in its own remote
  directory. `musicgen/lease-run.sh` starts lease-hold and run.sh detached from the ssh, writes the pid and lease-hold's
  rc beside the output, and the caller waits on that pid:

      scp musicgen/{prompts.json,gen.py,run.sh,lease-run.sh} <box>:/root/musicgen/   # the box alias, not an address
      cd /Users/hckim/repo/bloomery && BLOOMERY_REMOTE='~/repo/bloomery-clip034' BLOOMERY_CARD=a6000 \
        BLOOMERY_BOX_WAIT=3600 BLOOMERY_BOX_ENV='BLOOMERY_LEASE_CARD=docs/cards/musicgen-034.card' \
        tools/box.sh 'bash /root/musicgen/lease-run.sh clip034 --device cuda --dit acestep-v15-xl-sft \
          --lm acestep-5Hz-lm-4B --backend pt --steps 50 --shift 1.0 --batch 4 --seeds 8 --duration 48'

  Result: lease-hold rc 0, run.sh rc 0, the lease held 446 s, 24 clips. That is under the card's 8–30 min band, and
  the load is the term that was off: it took ~43 s, not the predicted 2–4 min, because the weights were still in the
  page cache from the install. Each batch of 4 took 67 s (16.8 s a clip; predicted ~14 s of DiT + ~4 s of LM). Peak
  card memory was 21.7 GB, and the card was at ≥ 90 % utilisation in 41 of 88 samples.
- `run.sh`'s card monitor is now one `nvidia-smi -l 5` process. The old shell loop left a `sleep 5` holding the
  lease's descriptor for a few seconds after the run's rc.

**What was measured.** The clips are under `music/clip034/` (gitignored; the flac originals are also in the box's
`/root/musicgen/out/clip034/`).

1. `screen.py` passed 20 of 24 (`music/clip034/screen.tsv`). The fails were arc-s1003, surge-s1001, surge-s1004 and
   surge-s1006: their pulse was off the beat.
2. `beats.py` (`BEATS_DROP_WIN=8 BEATS_DROP_FROM=1`; the default 16-beat window cannot find a drop in the first 7 s
   of a 48 s clip) gave each clip's grid and drop (`beats.json`).
3. A fit of each clip to the 113-beat film (scratch `fit.txt`) asked one question per clip: if the film ends on the
   clip's last loud beat, where does its drop land? Six candidates were shortlisted.
4. `listen.py` (agy gemini-3.8-flash-high, two calls per clip, counting only fields where both calls agree):
   - **The calibration did not pass.** One call heard 0.3.1's big-band take as "Synth-pop / Funk pop", the other as
     "Funk". So "electronic" was not agreed, and the gate stopped, as it should.
   - The six candidates then ran as a labelled screen (`listen.py --screen`, `screen_only` in each `.listen.json`).
     **These rows are a screen, not a verdict.**
   - surge-s1002 and arc-s1006 have a voice (vocal chops, a shout) in both calls and are dropped.
   - All six have no glitches in both calls.

**Pick: `volt-s1004`** (drum and bass, 172 asked).

- Measured: 171.979 BPM, first beat 0.3325 s. A one-bar break at 22.66 s, then the drop at 23.71 s (clip beat 67,
  +8.44 dB). The loudest section is 27–33 s, and the sound ends at 47.43 s (beat 135) with the drums cutting out.
- Screen: pass; pulse share on the beat 0.23. Kick on grid 14/40, median 98.7 ms: a breakbeat's kicks sit off the
  beat, as the swing take's did for 0.3.1, so this count is read, not gated.
- Listening, both calls agree: electronic, synth bass, drums, no voice, no glitches, energy 4. Both heard the music
  get bigger at 14.0 s, which is where the beat enters (BOLT b3).
- Why it fits:
  - 172 BPM gives the densest grid of the three prompts, so the montage cuts at 0.70 s;
  - its arc of build → beat in → break → drop → loud middle → hard cut maps onto the story without moving a shot;
  - the drop lands on the one moment designed to flood (PROMPT);
  - the track's cut is the film's last hit.
- Phase 2 must watch `render.py sync`'s kick phase on a breakbeat. Judge the picture onsets against the grid. Expect
  the kick-phase line to read off-beat kicks, and note it rather than move the grid.

**Backup: `volt-s1006`** (drum and bass).

- Measured: 172.004 BPM, first beat 0.3473 s. No drop: the energy is steady (bars −14 to −17 dB), and neither
  listening call heard one. The sound ends at 44.65 s (beat 127).
- Screen: pulse 0.55; kick on grid 34/40, median 5.5 ms, the tightest grid of the 24.
- Listening, both calls agree: no voice, no glitches, energy 4, and an abrupt end with a brief reverb tail.
- Alignment: `OPEN_AT_BEAT=12`, a bar start. The film ends on clip beat 125, and the END holds two beats to the cut.
- Use it if the pick's breakbeat fails sync, at the cost of the drop on PROMPT.

**Next, for the user or the lead:** a human listen to `volt-s1004` and `volt-s1006`. The listening screen is not a
verdict this round, because its calibration did not pass.

## What phase 2 builds

Copy 0.3.1's pipeline: `make_data.py`, `render.py` (already copied here), `beats.py` (copied). The pipeline is
`film.html` + `data.json` + `render.py check / probe / full / encode / pops / sync`.

1. `make_data.py`:
   - reads the notes and the README;
   - checks every string in the table above against its line (an `assert` per string that stops by name);
   - builds the beat grid from `beats.json` and the picked track (`MUSIC_ID`, `OPEN_AT_BEAT`, `FADE_OUT_S` ≈ 0.1 for
     a hard-hit ending);
   - runs the shot table through the read rule;
   - writes `data.json` with `T` (between 38 and 44 s, or it stops).
2. `film.html`:
   - set `window.FILM = 'release-034'`;
   - lift the helpers and the six settled layouts from `styles/style.html`;
   - add LEADER, PROMPT, MODELS, the three montage shots, THANKS and END;
   - add the camera (pan and zoom transforms applied to all three layers together);
   - add the per-element state machine (arriving → settled) so the floor check applies to settled elements only;
   - add `window.seek(t)` with pure functions of t (no accumulated state), so every frame renders alone.
3. `render.py`: set `FILM = "release-034"` and port 8795 (it still says release-031 and 8794).
4. Serve with `python3 -m http.server 8795 --bind 127.0.0.1`. Write the pid to a file and stop only that pid.

### Render checklist (phase 2 must pass every line)

- `render.py check` 0 faults over every frame and subframe:
  - settled text ≥ 44 px;
  - dark marks ≥ 12 px and volt marks ≥ 24 px;
  - settled text inside the margins;
  - every string in `window.LOG` is in `data.json`;
  - no glyph missing from its face;
  - pulse head and glow ≥ 24 px from text boxes.
- The read rule holds per card: settle beat + read time ≤ the card's end. `make_data.py` prints the table, and it
  matches `beatsheet.py` at the picked BPM.
- Flash: at most 3 general flashes in any 1 s window (a frame-to-frame relative-luminance change ≥ 10 % over ≥ 25 %
  of the frame, WCAG 2.3.1), measured on `out/video.mp4`. Add it as `render.py flash`. The strikes and the PROMPT
  flood are the candidates.
- `render.py pops` 0.
- `render.py sync`: every picture onset within 1 frame of the beat, and every cut or slam has an audio onset.
- Length 38–44 s. Music starts at the drop − 4 beats and ends on its final hit, with a 0.1 s fade to stop the click.
- `render.py probe` sheets at 1080 and 540 for one still per shot, plus the mid-squeeze, mid-zoom, mid-pan and the
  first montage frame.
- One fresh opus vision judge per section (open; numbers; Sparks and models; montage and embeddings; end). Fold in its
  verdicts, and do not merge with a FIX open.

## Choices for the lead

- Traces are 12 px, held to the dark-mark floor, not thinner and finer. Volt data marks are ≥ 24 px.
- SPARKS draws three nodes for README's "Several". The notes' own run is across two Sparks. Phase 2 can draw two if
  the count should match the run.
- The three montage words are on screen for 2 beats each (0.7–0.94 s), under the 2.5 s floor. They are kinetic type,
  and EMBED repeats and holds all three for 3.25 s. If the floor must hold for every word on screen, merge the
  montage into EMBED's arrival.
- The decode shot uses the token grid (style frame `tokens`) instead of the trace and pulse (style frame `decode`).
  The vision judge preferred the grid.

## Style frames

`styles/` holds `title`, `b74pre`, `b74`, `tokens`, `sparks` and `embed` (plus the earlier `decode`), each at 1080
and as `-540`, and `sheet.png`. Render them with `styles/shoot.py`.

| Frame | Verdict |
|---|---|
| title | SHIP |
| b74pre | SHIP |
| b74 | FIX: the trace sat 5 px above the sentence; raised, with 28 px measured clearance → SHIP |
| decode | FIX (dashboard-like rule, header off the tag line); fixed, then replaced by tokens |
| tokens | SHIP (preferred over decode). Then: head glow added, headline raised 24 px, and the full grid dims after the fill |
| sparks | FIX: the sentence ran to x 1059, and the pulses between nodes were hot. Now x 73–872, with only the NVMe pulse hot → SHIP |
| embed | FIX: the head block was cramped and the tag was 17 px above. Now 49 px, inside the margins, with the vector two-tone and its middle (arrival) cell lit → SHIP |
