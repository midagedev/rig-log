"""The 0.3.4 film's beat sheet at a given tempo: where each shot starts and ends, from DESIGN.md's shot table.

  python3 beatsheet.py BPM [FIRST_BEAT_S]

A card ends on the first beat at or after its last landing + SETTLE + its read time. The read time is 4 words a
second plus 1 s per number, at least 2.5 s (the 0.3.1 floor); numbers are measured or sized quantities, everything
else (names, versions, handles, tags) is a word, and `·` separators are not counted. A shot (no reading) has a fixed
length in beats. Phase 2's make_data.py owns the real timing; this is the design-time calculator, and the two must
agree on the shot table.
"""
import math, sys

SETTLE = 0.16          # seconds from a landing's beat until it is still (arrivals end within this)
FLOOR = 2.5

# name, kind, length in beats (shots) or the beat of the last landing (cards), words, numbers
SHOTS = [
    ("leader",  "shot", 4,  0, 0),   # stepped leader, one step a beat, no type
    ("title",   "card", 1,  3, 0),   # 0.3.4 at b0 with the strike; bloomery and RELEASE at b1
    ("bolt",    "card", 3,  9, 2),   # NEMOTRON 3.5 BOLT (3) + the whole model on the card (6); 74B-A9B, 24 GB
    ("decode",  "card", 1,  6, 3),   # DECODE, TOK/S, at, depth, RTX 3090, W; 86.69, 4096, 250 (token grid fills)
    ("prompt",  "card", 0,  3, 2),   # slot swap: PROMPT, a, prompt; 2,047, 4096-token (the grid floods)
    ("sparks",  "card", 2, 16, 0),   # SEVERAL DGX SPARKS SERVE ONE MODEL (6), NVMe x3, the node line (7)
    ("models",  "card", 1,  7, 0),   # slot swap: Qwen3.8, GLM-5.3-Flash, DeepSeek-V4.1-Flash; over, RDMA, by, @juliankang4
    ("text",    "shot", 2,  0, 0),   # montage: TEXT
    ("frames",  "shot", 2,  0, 0),   # montage: VIDEO FRAMES
    ("audio",   "shot", 2,  0, 0),   # montage: AUDIO
    ("embed",   "card", 1, 13, 0),   # EMBEDDINGS, beside the chat model (4), the model tag (4), 3 lanes, /v1/embeddings
    ("thanks",  "card", 1, 12, 0),   # thank you, @juliankang4 + 4 credit words, @Burntgogi + 4 credit words
    ("end",     "card", 1,  3, 0),   # bloomery, 0.3.4, github.com/midagedev/bloomery (+ the tail to the music's end)
]


def sheet(bpm, first=0.0):
    beat = 60.0 / bpm
    b, rows = 0, []
    for name, kind, n, words, nums in SHOTS:
        if kind == "shot":
            length, read = n, 0.0
        else:
            read = max(FLOOR, words / 4 + nums)
            length = math.ceil(n + (SETTLE + read) / beat - 1e-9)
        rows.append((name, kind, b, b + length, first + b * beat, first + (b + length) * beat, read))
        b += length
    return rows, b, beat


def main():
    bpm = float(sys.argv[1]) if len(sys.argv) > 1 else 128.0
    first = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    rows, total, beat = sheet(bpm, first)
    print(f"{bpm:g} BPM, beat {beat:.4f} s")
    print("shot     kind  beats      seconds          read_s")
    for name, kind, b0, b1, t0, t1, read in rows:
        print(f"{name:8s} {kind:5s} {b0:3d}-{b1:<3d} {t0:7.2f}-{t1:<7.2f}  {read:4.2f}")
    print(f"total {total} beats, {total * beat:.2f} s (before the end card's tail to the music's last hit)")


if __name__ == "__main__":
    main()
