#!/usr/bin/env python3
"""The prompt files take.sh reads, 2026-11-03. Same files for every engine of the Spark comparison.

    make-prompts.py <out dir> <text file>...

decode-code / decode-prose: three short requests each, so decode is read where the MTP draft's acceptance differs
(bloomery's README Spark table splits code and prose the same way). pp512 / pp4096: a passage cut from a different
English file per round, about 512 / 4,096 tokens at 3.4 characters a token (the first row read 586 and 4,903 tokens at 4.0), so no round
shares a prefix with another and a prompt cache cannot turn a prefill take into a cache read. The engine's own count
of prompt tokens is in each tape; that, not the target, is what a row reports.
"""
import json, sys, pathlib
out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
texts = [pathlib.Path(p).read_text(errors="ignore") for p in sys.argv[2:]]
assert len(texts) >= 6, "need six source files, three per prefill length"
code = ["Write a Python module that merges overlapping intervals: the function with a docstring and type hints, then a set of pytest tests covering edge cases.",
        "Write a C program that builds a singly linked list from command-line integers, reverses it in place, prints it and frees it. Include the struct definition and comments.",
        "Write a Rust module that parses a line of comma-separated integers into a Vec<i64> with a custom error type, and unit tests for good and bad input."]
prose = ["Explain to a new engineer, in at least five paragraphs, why a write-ahead log makes a database crash-safe.",
         "Describe a walk through a pine forest in early winter, in the first person, in at least five paragraphs.",
         "Write a long, warm letter to a neighbour apologising for noise during a weekend house renovation, with at least five paragraphs."]
def w(name, prompts):
    with open(out / f"{name}.jsonl", "w") as f:
        for i, p in enumerate(prompts):
            f.write(json.dumps({"name": f"{name}-{i}", "prompt": p}) + "\n")
w("decode-code", code); w("decode-prose", prose)
ask = "Read the document below, then answer in one sentence: what is it about?\n\n"
for name, toks, src in (("pp512", 512, texts[0:3]), ("pp4096", 4096, texts[3:6])):
    ps = []
    for t in src:
        body = " ".join(t.split())[: int(toks * 3.4)]
        assert len(body) >= toks * 3.4 * 0.9, f"source too short for {name}"
        ps.append(ask + body)
    w(name, ps)
print("wrote", sorted(p.name for p in out.iterdir()))
