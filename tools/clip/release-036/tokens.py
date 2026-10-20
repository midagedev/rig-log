"""The answer programs' token pieces and their derived engine calls, from Qwen3.6's own tokenizer: writes
sources/tokens-qwen36.json, which make_data.py reads for the film's token-by-token stage (ko-mail-06's pieces) and,
while a sitting's rows carry no call counts, for the placeholder counts (every frame then says PLACEHOLDER).

  <venv with tokenizers>/bin/python tokens.py <tokenizer.json> [rows dir]

The program is sjcmp.py's (program_parts, merged, trie_path, stream, plan_jump, plan_step, plan_counts, imported
from the bloomery tree that holds it, SJCMP=<file> to name it): every forced text and every option tokenized on its
own, as the server compiles the schema; the answer is the jump arm's first counted round (the rows' tops). The
counts are what sjcmp.py's check_counts predicts and the server must report (`timings.constrained`), so they are a
derivation, not a measurement: the film marks them PLACEHOLDER until a sitting's rows carry the server's own.
"""
import hashlib, json, os, sys
from pathlib import Path

HERE = Path(__file__).parent
BLOOMERY = Path(os.environ.get("BLOOMERY", HERE / "../../../../bloomery")).resolve()
SJCMP = Path(os.environ.get("SJCMP", BLOOMERY / "tools/ref/clef/sjcmp.py"))
if not SJCMP.exists(): SJCMP = (HERE / "../../../../bloomery-sjcmp/tools/ref/clef/sjcmp.py").resolve()


def main():
    if len(sys.argv) < 2: sys.exit(__doc__)
    from tokenizers import Tokenizer
    tok_path = Path(sys.argv[1])
    rows_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / json.loads((HERE / "inputs.json").read_text())["rows"]
    # sjcmp.py and e2e.py at the commit the sitting ran (inputs.json sjcmp_rev), not the tree's working copy
    import subprocess, tempfile
    rev = json.loads((HERE / "inputs.json").read_text())["sjcmp_rev"]
    tmp = Path(tempfile.mkdtemp())
    for f in ("sjcmp.py", "e2e.py"):
        (tmp / f).write_text(subprocess.run(["git", "-C", str(SJCMP.parent), "show", f"{rev}:tools/ref/clef/{f}"],
                                            capture_output=True, text=True, check=True).stdout)
    sys.path.insert(0, str(tmp))
    import sjcmp
    tk = Tokenizer.from_file(str(tok_path))
    enc = lambda s: tk.encode(s, add_special_tokens=False).ids
    w1 = json.loads((rows_dir / "window1/rows.json").read_text())["rows"]
    tops = {}
    for r in sorted((r for r in w1 if r["arm"] == "jump" and not r.get("dropped")), key=lambda r: r["round"]):
        tops.setdefault(f"{r['suite']}/{r['id']}", r["tops"])
    suites = {"en": "tools/ref/clef/suite.jsonl", "ko": "tools/ref/clef/suite-ko.jsonl"}
    out = {}
    for suite, rel in suites.items():
        for line in subprocess.run(["git", "-C", str(SJCMP.parent), "show", f"{rev}:{rel}"], capture_output=True,
                                   text=True, check=True).stdout.splitlines():
            if not line.strip(): continue
            req = json.loads(line)
            key = f"{suite}/{req['id']}"
            if key not in tops: sys.exit(f"tokens.py: the rows have no jump answer for {key}")
            obj = {}
            for qid, q in req["questions"].items():
                t = tops[key][qid]
                obj[qid] = (t == "yes") if q["type"] == "noul" else t if q["type"] == "choice" else int(t)
            parts = sjcmp.merged(sjcmp.program_parts(req))
            ids = [("F", enc(str(b))) if k == "T" else ("P", [enc(str(o)) for o in b]) for k, b in parts]
            picks = sjcmp.picks_from_answer(req, obj)
            toks = sjcmp.stream(ids, picks)
            step_n, step_p = sjcmp.plan_counts(sjcmp.plan_step(toks))
            jump_calls = sjcmp.plan_jump(toks)
            jump_n, jump_p = sjcmp.plan_counts(jump_calls)
            # the pieces on screen walk the answer's own option: picks_from_answer indexes a noul's true as 1, the
            # program's options are ["true", "false"]; the counts are the same either way when both are one id
            shown = [(0 if obj[qid] else 1) if q["type"] == "noul" else p for (qid, q), p in zip(req["questions"].items(), picks)]
            stoks = sjcmp.stream(ids, shown)
            if sjcmp.plan_counts(sjcmp.plan_jump(stoks)) != (jump_n, jump_p) or len(stoks) != len(toks):
                sys.exit(f"tokens.py: {key}: the true and false paths make different calls")
            # each id's text (a piece that splits a character would carry the bytes it has; none here does)
            pieces = [[i, tk.decode([i]), d] for i, d in stoks]
            out[key] = {"parts": [[k, b] for k, b in parts], "picks": picks, "pieces": pieces,
                        "step": {"next_calls": step_n, "prefill_calls": step_p},
                        "jump": {"next_calls": jump_n, "prefill_calls": jump_p},
                        "jump_plan": jump_calls[1:]}
    doc = {"what": "the answer programs' ids from Qwen3.6's tokenizer and the engine calls sjcmp.py predicts (a derivation)",
           "tokenizer": {"file": "nvidia/Qwen3.6-35B-A3B-NVFP4 tokenizer.json (Qwen3.6-35B-A3B's tokenizer, copied from <box>)",
                         "sha256": hashlib.sha256(tok_path.read_bytes()).hexdigest()},
           "command": f"python tokens.py <tokenizer.json> {rows_dir.relative_to(HERE) if rows_dir.is_relative_to(HERE) else rows_dir}",
           "sjcmp": str(SJCMP.relative_to(SJCMP.parents[3])) + " @ " + rev,
           "convention": "next_calls are the steps after the prompt (the prompt's closing step left out), as check_counts predicts",
           "requests": out}
    (HERE / "sources/tokens-qwen36.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    for k, v in out.items():
        print(f"{k:22} ids {len(v['pieces']):3}  step {v['step']}  jump {v['jump']}")


if __name__ == "__main__":
    main()
