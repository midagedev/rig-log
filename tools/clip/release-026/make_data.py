"""Write data.json for film.html.

  placeholder              plausible numbers shaped like the release sitting's, flagged "placeholder": true
                           (film.html stamps every frame PLACEHOLDER while the flag is set)
  fill <sitting.json>      the sitting's keys (README, "sitting.json") -> data.json, "placeholder": false;
                           a key that is unknown, missing, null or of the wrong type stops it by name
  variant <out> K=xF ...   a copy of data.json with numeric keys scaled (arms[1].pp4096=x0.5) or set (ring_half=398,
                           before_label=text), for probe renders: film.html?data=<out>

Three arms on one machine, the server's behaviour: arms[0] is 0.2.5 on the Q4 file (the prompt path off, as 0.2.5's
server ran it), arms[1] is 0.2.6 on the same file (pick + ring), arms[2] is 0.2.6 on the Q3 file. The stage scenes'
per-layer counts come from arms[0] (host_cols_before) and arms[1] (the rest).
The film reads only the file it is pointed at (data.json by default); every number on screen comes from it.
"""
import json, re, sys
from pathlib import Path

HERE = Path(__file__).parent

# one object per arm in "arms", in this order: arm 1, arm 2, arm 3; every key required
ARM = {
    "label": "text: the arm's name on screen",
    "file": "text: the model file's short name",
    "file_gb": "GB = 1e9 bytes, the model file's size (du -h prints GiB, ~7 % lower)",
    "pp512": "tok/s, prompt of 512 tokens",
    "pp4096": "tok/s, prompt of prompt_tokens tokens",
    "decode": "tok/s, decode after the prompt_tokens prompt",
}
# top-level key -> (unit, required). Model facts and drawing inputs have defaults; the measured numbers do not.
KEYS = {
    "arms": ("a list of three objects with the keys of ARM: arm 1, arm 2, arm 3", True),
    "arm1_caption": ("text: one line beside arm 1's prompt number", False),
    "arm2_caption": ("text: one line beside arm 2's prompt number", False),
    "arm3_caption": ("text: one line beside arm 3's prompt number and on the end card", True),
    "pp_ratio": ("arms[1].pp4096 / arms[0].pp4096 as the sitting reports it (paired by round); computed when absent", False),
    "host_cols_before": ("arm 1: host columns a layer (token x expert pairs the CPU computes), mean over layers", True),
    "host_cols_after": ("arm 2: host columns a layer, mean over layers", True),
    "streamed_per_layer": ("arm 2: experts a streaming layer copies into the ring for this prompt only, mean over the layers that streamed", True),
    "streamed_layers": ("arm 2: layers whose stream ran (xstream end layers); 0 leaves the ring off the stage", True),
    "admit_per_layer": ("arm 2: experts a layer the pick moves into the card's seats (they stay for the decode); 0 draws no seats path", True),
    "ring_half": ("arm 2: slots in one half of the ring", True),
    "card_experts_per_layer": ("experts a layer the card holds before the prompt (drawing only, never printed)", False),
    "before_label": ("text: arm 1's name in the stage, lanes and end card", False),
    "after_label": ("text: arm 2's name in the same places", False),
    "title": ("text: the title line under the version (': faster prompts' is added when pp_ratio >= 1.02)", False),
    "answers_tag": ("text: after 'answers +M%' on the numbers scene and the end card, e.g. '(MTP off)'; empty adds nothing", False),
    "conditions": ("text: model, card, placement, server; shown under every number (the scenes add the prompt length)", True),
    "method_line": ("text: how the numbers were taken, one short line on the end card; empty hides it", False),
    "decode_conditions": ("text: the decode bars' conditions", False),
    "prompt_tokens": ("tokens in the timed prompt", False),
    "layers": ("model layers", False),
    "experts_per_layer": ("routed experts a layer", False),
    "topk": ("experts each token picks a layer", False),
    "model": ("text: the model's name in the title", False),
    "decode_note": ("text: why the answer is faster too", False),
    "side1": ("text: first side line", False),
    "side2": ("text: second side line (empty string hides it)", False),
    "version": ("text", False),
    "repo": ("text", False),
    "source": ("text: where the numbers come from", False),
}
TEXT = {k for k, (u, _) in KEYS.items() if u.startswith("text")}
DEFAULTS = {
    "arm1_caption": "the prompt stream off",
    "arm2_caption": "the same file, the prompt stream on",
    "before_label": "0.2.5 (stream off)",
    "after_label": "0.2.6",
    "title": "Qwen3.8-Flash-Next in bloomery 0.2.6",
    "answers_tag": "",
    "method_line": "",
    "model": "Qwen3.8-Flash-Next",
    "decode_conditions": "",
    "prompt_tokens": 4096, "layers": 48, "experts_per_layer": 512, "topk": 10,
    "card_experts_per_layer": 300,
    "decode_note": "the prompt's picks stay on the GPU for the answer",
    "side1": "the MTP draft now picks how many tokens to guess from measured cost",
    "side2": "a host without room for the 28.8 GB per-layer embedding table reads it from disk through a 4 GiB cache",
    "version": "0.2.6",
    "repo": "github.com/midagedev/bloomery",
    "source": "the release sitting",
}


def units():
    u = {k: v for k, (v, _) in KEYS.items()}
    u.update({f"arms[i].{k}": v for k, v in ARM.items()})
    return u


def placeholder():
    d = dict(DEFAULTS)
    d.update({
        "placeholder": True,
        "arms": [
            {"label": "0.2.5 · UD-Q4_K_XL", "file": "UD-Q4_K_XL", "file_gb": 111, "pp512": 600.0, "pp4096": 800.0, "decode": 55.0},
            {"label": "0.2.6 · UD-Q4_K_XL", "file": "UD-Q4_K_XL", "file_gb": 111, "pp512": 900.0, "pp4096": 1400.0, "decode": 61.0},
            {"label": "0.2.6 · UD-Q3_K_XL (i-quant)", "file": "UD-Q3_K_XL", "file_gb": 84, "pp512": 850.0, "pp4096": 1300.0, "decode": 58.0},
        ],
        "arm3_caption": "a smaller file: its i-quant experts now run on the GPU",
        "pp_ratio": 1.75,
        "host_cols_before": 19000, "host_cols_after": 3200,
        "streamed_per_layer": 26, "streamed_layers": 4, "admit_per_layer": 75, "ring_half": 97,
        "conditions": "Qwen3.8-Flash-Next · A6000 + host RAM · bloomery-serve, --place a",
        "decode_conditions": "decode: 96 tokens after the 4,096-token prompt",
        "source": "placeholder — from the release sitting",
    })
    d["units"] = units()
    return d


def number(where, v, positive):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 or (positive and not v > 0):
        sys.exit(f"fill: {where} must be a number {'> 0' if positive else '>= 0'}, got {v!r}")


def check_arms(arms, path):
    if not isinstance(arms, list) or len(arms) != 3:
        sys.exit(f"fill: 'arms' in {path} must be a list of three objects (arm 1, arm 2, arm 3), got {arms!r:.80}")
    for i, a in enumerate(arms):
        if not isinstance(a, dict):
            sys.exit(f"fill: arms[{i}] must be an object, got {a!r:.80}")
        bad = [k for k in a if k not in ARM]
        if bad:
            sys.exit(f"fill: unknown key(s) {bad} in arms[{i}] (README lists the keys)")
        for k, unit in ARM.items():
            if k not in a or a[k] is None:
                sys.exit(f"fill: arms[{i}].{k} ({unit}) is missing or null in {path}")
            if unit.startswith("text"):
                if not isinstance(a[k], str) or not a[k]:
                    sys.exit(f"fill: arms[{i}].{k} must be a non-empty string, got {a[k]!r}")
            else:
                number(f"arms[{i}].{k} ({unit})", a[k], True)


def fill(path):
    s = json.loads(Path(path).read_text())
    bad = [k for k in s if k not in KEYS]
    if bad:
        sys.exit(f"fill: unknown key(s) {bad} in {path} (README lists the keys)")
    d = dict(DEFAULTS)
    for k, (unit, req) in KEYS.items():
        if k not in s:
            if req:
                sys.exit(f"fill: required key {k!r} ({unit}) is missing from {path}")
            continue
        v = s[k]
        if v is None:
            sys.exit(f"fill: key {k!r} ({unit}) is null in {path}" + ("" if req else "; it is optional: leave it out instead"))
        if k == "arms":
            check_arms(v, path)
        elif k in TEXT:
            if not isinstance(v, str):
                sys.exit(f"fill: {k!r} must be a string, got {v!r}")
        else:
            number(f"{k!r} ({unit})", v, k in ("ring_half", "host_cols_before"))
        d[k] = v
    if "pp_ratio" not in s:
        d["pp_ratio"] = round(d["arms"][1]["pp4096"] / d["arms"][0]["pp4096"], 3)
        print(f"fill: pp_ratio absent, computed {d['pp_ratio']} from arms[1].pp4096 / arms[0].pp4096")
    d["placeholder"] = False
    d["units"] = units()
    return d


def variant(out, sets):
    d = json.loads((HERE / "data.json").read_text())
    for kv in sets:
        k, v = kv.split("=", 1)
        m = re.fullmatch(r"arms\[(\d)\]\.(\w+)", k)
        box, key = (d["arms"][int(m.group(1))], m.group(2)) if m else (d, k)
        if key not in box:
            sys.exit(f"variant: no key {k!r} in data.json")
        text = isinstance(box[key], str)
        box[key] = v if text else box[key] * float(v[1:]) if v.startswith("x") else float(v)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(d, indent=1, ensure_ascii=False))
    print("variant ->", out)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a == ["placeholder"]:
        (HERE / "data.json").write_text(json.dumps(placeholder(), indent=1, ensure_ascii=False))
        print("data.json (placeholder)")
    elif len(a) == 2 and a[0] == "fill":
        (HERE / "data.json").write_text(json.dumps(fill(a[1]), indent=1, ensure_ascii=False))
        print("data.json (filled from", a[1] + ")")
    elif len(a) >= 3 and a[0] == "variant":
        variant(a[1], a[2:])
    else:
        sys.exit(__doc__)
