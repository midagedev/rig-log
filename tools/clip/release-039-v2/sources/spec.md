# Round clip039 — the bloomery 0.3.9 release film

Opus round (video authoring: the user, 2026-10-07, "영상제작은 opus가 훨씬 잘할꺼라"). Build the 0.3.9 release
film end to end in a new directory `/Users/hckim/repo/rig-log/tools/clip/release-039/`, following the pipeline and
screen grammar of `/Users/hckim/repo/rig-log/tools/clip/release-036/` (read its README.md first, then
`release-034/README.md` and `DESIGN.md`). Copy what you reuse (render.py, beats.py, splice.py, fonts, film.html
skeleton) into the new directory; never edit release-036 or release-034.

## Two halves, equal weight (one film, 1080×1080, 60 fps, ≤ 120 s including END)

The user (2026-10-25): the Mac support goes in big, and engine comparison numbers are allowed in this film. So the
film has two halves of equal weight: **NVIDIA** (the two giant models below) and **Apple Silicon** (the Metal
backend, new in this release line and much faster in 0.3.9). Give the Mac half at least 40 % of the film.

### Apple Silicon half

Source: `/Users/hckim/.cache/bloomery/clip039/mac-numbers.md`, written by the Mac session (it may not exist yet when
you start: build the NVIDIA half first, then check for the file every 60 s; if it is still missing after 30 min, stop
and say so in the report). Every Mac number on screen comes from that file with its conditions, and a
development-loop row says so on screen ("M4 Pro, development loop"). What the half should say: bloomery runs on a Mac
GPU through its own Metal backend (`bloomery-serve-metal`, MLX 4-bit checkpoints converted by `prepare`, prefix
reuse, batched prompt passes), how fast it decodes and reads prompts next to mlx-lm and llama.cpp on the same machine
in the same sitting (only rows the file gives as same-sitting), the 0.3.9 prompt-speed steps (#777, #779, #792,
#797) and the M5 neural-accelerator GEMMs (#796: picked on an M5 by the device, not yet measured on an M5 — say so),
and the contributors' M3 Ultra / M5 Ultra rows if the file names them.

Prefill is not hidden (user, 2026-10-25: "감출 필요까진 없어 프리필"): show the prompt (prefill) comparison rows too,
including the ones where mlx-lm or llama.cpp is ahead, beside the decode rows, each with its conditions. This overrides
the "on screen" list at the end of mac-numbers.md where it says decode only. A same-sitting M4 Pro section
("same-sitting M4 Pro (date)") may be appended to mac-numbers.md while you work; re-read the file before you build
the Mac comparison scene and use that section when it is there.

### Contributors' scene (user, 2026-10-25: juliankang4's work goes in)

A scene of its own (about 12–18 s), after the NVIDIA half or wherever it reads best, crediting @juliankang4 by name:
- DGX Spark (GB10): 4,096-token prefill +98.2 % on the NVFP4 checkpoint and +54.0 % on FP4-Local (#668); decode with
  MTP on code prompts, one request, 30.33 → 36.07 tok/s (#652).
- Qwen3.8 with several requests: with FP4-Local, `--parallel 4` and the MTP draft, four sampled requests decode at
  55.80 tok/s together, where 0.3.8 decoded 28.29 (#703); four concurrent 4,096-token requests reach their first token
  in 20.4 s at the median, not 43.9 (#671).
- Qwen3.8 served straight from its FP4-Local checkpoint folder (#660, #682).
- MiniMax-M3.1-Flash's card experts run his NVFP4 kernels: routed NVFP4 prompt GEMMs on FP4 tensor cores (#687,
  #760) and gate, up and SwiGLU as one launch (#766). Say this in the NVIDIA half too, where M3.1 appears.
- The new start screen is his (#644, #743): if you show `bloomery-serve`'s start screen, credit it.
These numbers are his own pull requests' measurements on his machine (one DGX Spark for the GB10 rows): say "measured
by @juliankang4 on a DGX Spark" (or "on his machine") on screen. @Burntgogi may get one line (the common owners every
model shares, #774, #775; Flint groundwork, #676–#680 except #679). Read the pull request bodies with
`gh pr view <n> --repo midagedev/bloomery` to check each number before it goes on screen.

### NVIDIA half

0.3.9 serves two very large mixture-of-experts models on one workstation with two cards, at the serving defaults:

- **Muse Spark Open 816B-A42B**, `UD-IQ2_XXS` GGUF, 227.75 GB on disk.
- **MiniMax-M3.1-Flash**, read straight from its native NVFP4 safetensors folder (no conversion, no requant),
  252.45 GB on disk.
- The machine: RTX A6000 (48 GB) + RTX 3090 (24 GB, at its 250 W cap), 251.5 GiB host RAM. Neither model fits the
  cards (72 GB); the cards hold the hot part and the host tier runs the rest (`--place` unset picks `bp`).

Suggested beats (change them if a better order reads more clearly; say why in the README):
1. TITLE: `bloomery 0.3.9`, two models, two cards.
2. SIZE: each model's bytes against the two cards' 72 GB and the host RAM; what sits where (stage card, expert tier,
   host). Use only the byte figures above; do not invent per-layer splits.
3. RESIDENCY (MiniMax-M3.1 folder): the card keeps the experts decode routes to most. Measured, same lease, 2 rounds:
   decode 16.52 → 21.97 tok/s at depth 512 (+33 %), 16.24 → 19.48 at 4096 (+20 %).
4. THE NVFP4 TILE (MiniMax-M3.1 prompt): the host's NVFP4 prompt products run a column tile, every column's sums and
   scales prepared once a call, bit-identical to the one-column kernel. Measured, same lease, 2 rounds: pp512 88.35 →
   124.19 tok/s (+40.6 %), pp4096 96.95 → 123.69 (+27.6 %); decode at 512 21.87 → 21.29 (−2.7 %). Show the decode
   cost honestly on screen.
5. LIVE: a replay of a real recorded answer from each model, tokens at their recorded rate. Tapes:
   `/Users/hckim/.cache/bloomery/placegen/clip039-tapes/muse.toktape`, `muse2.toktape`, `mm31.toktape`,
   `mm31bp.toktape` (read their headers: model, placement, tree, rate; pick one per model, label it with its recorded
   rate and "recorded with toktape"). The published tapes are https://tape.midagedev.com/r/kvhptiqzuab9ri8sf4tu (Muse)
   and https://tape.midagedev.com/r/iv9w3jzg4nirj4gaufik (M3.1); they were recorded before the decode work, so their
   rate is lower than the table's: say "recorded on the 0.3.9 candidate" and never present it as the headline.
6. THE TABLE (RTX A6000 + RTX 3090, `bp`, serving defaults, means of 2 rounds, tok/s):

   | | pp512 | pp4096 | decode @512 | decode @4096 |
   |---|---|---|---|---|
   | Muse Spark Open UD-IQ2_XXS | 90.40 | 94.90 | 16.65 | 15.74 |
   | MiniMax-M3.1-Flash NVFP4 folder | 122.57 | 123.62 | 21.03 | 19.48 |

7. (the Apple Silicon half goes here or before the table; your call, say why)
8. END: `bloomery`, `0.3.9`, `github.com/midagedev/bloomery`, "recorded with toktape" + `github.com/midagedev/toktape`.

## Rules (copied from the project and the user)

- Every number on screen is one of the numbers above or read from a tape file you name in the README; no other number.
  Every number carries its conditions on screen (machine or cards, model and quant, depth, tok/s). Another engine's
  number appears only from mac-numbers.md, as a same-sitting row beside ours with that engine's name and flags.
- English text on screen; the README in Korean, as release-036's is.
- Legible at phone size: release-034's size floors (DESIGN.md) hold; no text under them.
- Music: reuse a track from release-036/music or release-034/music (name it in the README), or the Mixkit track 644
  (`https://assets.mixkit.co/music/644/644.mp3`). No new generation.
- Self-verification duty: open your own captures (`render.py probe`), compare with the contract (size floors, hold
  checks, every number traced to this spec or a tape), and write a find → fix log and per-axis SHIP/FIX predictions
  (legibility, timing to the beat, number accuracy, story clarity) in `/Users/hckim/.cache/bloomery/clip039/report.md`.
- Render: on this Mac if the pipeline runs here. If it needs the box, go through `tools/box.sh` from
  `/Users/hckim/repo/bloomery` with `BLOOMERY_REMOTE='~/repo/bloomery-clip039'` only for syncing, or plain ssh as
  release-036's README does into `/root/clip039-render/` (never another directory), and only while no
  `/root/bloomery-lead-hold` exists (check it on the box first; if it is up, retry every 60 s). Never touch cards:
  the render is CPU/browser work. Never start or stop any other process on the box.
- Browser-driving: at most one browser at a time; a `lock timed out` is contention, not a failure.
- No git state changes in any repo (no commit, push, checkout, stash, restore, add). Edit only files under
  `/Users/hckim/repo/rig-log/tools/clip/release-039/` and `/Users/hckim/.cache/bloomery/clip039/`.
- Never wait with `until ! pgrep -f "<pattern>"` or by scanning `/proc/*/cmdline` (both match your own shell); wait on
  a pid captured with `$!` (`kill -0 <pid>`), and send signals only to pids captured at start and written to a file.
- No SendMessage to retired agents. If a direct user instruction conflicts with a lead constraint, follow it and tell
  the lead.
- Do not upload anything; the lead uploads after a separate vision verdict.

## Report (last message, ≤ 15 lines + paths)

The final mp4 path and its length, the beat list (one line each), the tapes used, the self-check SHIP/FIX predictions,
anything you could not do, and places outside the assignment where improvement looked possible (path:line + one line).
