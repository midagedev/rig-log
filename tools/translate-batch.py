#!/usr/bin/env python3
"""translate-batch.py — every markdown file in the repo, through one loaded model.

Fifty-one files and 134 000 words. Loading DeepSeek-V4.1-Flash takes 172 s, so doing this a
file at a time would spend 2.4 hours on loads alone; this stands one server up and walks the
whole tree past it.

It deliberately does **not** reuse `translate-md.py`'s request path. That path produced every
row in `log/2026-09-18-c` and those rows say "the whole document in one request"; keeping it
untouched is what keeps them reproducible. What is shared is what has to be identical -- the
system prompt with its glossary, the section splitter, and the fence masking -- all imported
from that file so the two tools can never drift apart.

    translate-batch.py --url http://127.0.0.1:8011/v1/chat/completions \\
        --out /home/user/translate/repo --files README.md docs/*.md log/*.md

A part is a request. A file larger than --max-chunk-words is cut at its top-level headings,
and a section still too large is cut again at a blank line or a table row. **Parts are a
compromise and the row records how many were used**: a term the model settles in part three
cannot reach part one, and after that only the glossary check holds them together.
"""

import argparse
import importlib.util
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("tmd", os.path.join(HERE, "translate-md.py"))
TMD = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(TMD)


def ask(url, model, system, text, temp, max_tokens, timeout, extra=None):
    body = {"model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": text}],
            "temperature": temp, "max_tokens": max_tokens, "stream": False}
    # Some templates gate their reasoning channel on a kwarg rather than on a flag, and the
    # server merges whatever lands here into the request. Solar Open 2 needs
    # `{"chat_template_kwargs": {"reasoning_effort": "minimal"}}`: without it the template
    # defaults to "high", the whole generation goes to the reasoning channel, and the answer
    # comes back empty -- measured twice on 2026-09-18, 13 450 tokens for a 1-byte file.
    # llama-server ignores chat_template_kwargs unless it was started with --jinja.
    if extra:
        body.update(extra)
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.load(r)
    wall = time.time() - t0
    choice = payload["choices"][0]
    out = choice["message"]["content"]
    notes = []
    if choice.get("finish_reason") not in (None, "stop"):
        notes.append(f"finish_reason={choice.get('finish_reason')}")
    m = re.match(r"\s*<think(?:ing)?>.*?</think(?:ing)?>\s*", out, re.S)
    if m:
        notes.append("a reasoning block was removed")
        out = out[m.end():]
    elif re.match(r"\s*<think", out):
        raise RuntimeError("the reply opens a reasoning block that never closes")
    m = re.match(r"\s*```[a-zA-Z]*\n(.*)\n```\s*\Z", out, re.S)
    if m:
        notes.append("the part came back wrapped in a code fence; stripped")
        out = m.group(1)
    # An empty part is the failure this file could not see. translate-round.sh grew a byte
    # count after a model answered nothing and the round reported rc=0 over a 1-byte file; the
    # batch had the same hole, and worse, because it writes the file from the parts it got and
    # a silently missing part is a silently truncated document. A part that came back with
    # almost nothing raises, the file is marked FAILED, and --resume will do it again.
    reasoning = (choice.get("message") or {}).get("reasoning_content") or ""
    if len(out.strip()) < 40 <= len(text.strip()):
        raise RuntimeError(
            f"the part came back with {len(out.strip())} characters for {len(text.split())} "
            f"words in" + (f", and {len(reasoning)} characters of reasoning_content -- the "
            f"answer went to the reasoning channel" if reasoning else ""))
    if reasoning:
        notes.append(f"reasoning_content: {len(reasoning)} chars")
    t = payload.get("timings") or {}
    return out, t, wall, notes


def dst_for(rel):
    """Where a source path's translation is written, in one place.

    The translation keeps the source's own relative path -- `docs/foo.md` under --out -- so the
    output directory is a mirror of the tree and `diff -r` lines the two up. The resume check
    and the write used to compute this separately, which is how they come to disagree."""
    return rel


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8011/v1/chat/completions")
    p.add_argument("--model", default="local")
    p.add_argument("--out", required=True, help="directory for the translations and the rows")
    p.add_argument("--root", default=".", help="paths in --files are relative to this")
    p.add_argument("--files", nargs="+", required=True)
    p.add_argument("--max-chunk-words", type=int, default=3000)
    p.add_argument("--max-tokens", type=int, default=12288)
    p.add_argument("--temp", type=float, default=0.0)
    p.add_argument("--timeout", type=float, default=1800.0)
    p.add_argument("--extra-json", default=None,
                   help='merged into every request body, e.g. \'{"chat_template_kwargs": '
                        '{"reasoning_effort": "minimal"}}\'')
    p.add_argument("--resume", action="store_true",
                   help="skip a file whose translation already exists. Four hours of decode is "
                        "long enough that the run will be interrupted at least once")
    a = p.parse_args()
    extra = json.loads(a.extra_json) if a.extra_json else None

    os.makedirs(a.out, exist_ok=True)
    rows_path = os.path.join(a.out, "rows.jsonl")
    # "Done" used to mean "there is a row for it", and a row is written for a failure too.
    # Measured 2026-09-18: a batch was interrupted, every one of its fifty rows said
    # `ok: false`, and the next run skipped all fifty, wrote nothing, and reported success.
    # A ledger that cannot tell a success from a failure is worse than no ledger, because it
    # is trusted. Done means the row says ok **and** the file it claims to have written is on
    # disk -- the second half costs one stat and catches an output directory that was cleared
    # under a ledger that was not.
    done = set()
    if a.resume and os.path.exists(rows_path):
        for line in open(rows_path, encoding="utf-8"):
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("ok") and os.path.exists(os.path.join(a.out, dst_for(row["file"]))):
                done.add(row["file"])

    started = time.time()
    for i, rel in enumerate(a.files, 1):
        if rel in done:
            print(f"[{i}/{len(a.files)}] {rel}: already done, skipping", flush=True)
            continue
        src = open(os.path.join(a.root, rel), encoding="utf-8").read()
        parts = TMD.split_sections(src, a.max_chunk_words)
        pieces, notes, pn, dn, pms, dms, wall = [], [], 0, 0, 0.0, 0.0, 0.0
        t_file = time.time()
        try:
            for k, part in enumerate(parts, 1):
                sent, held = TMD.mask_fences(part)
                out, t, w, nn = ask(a.url, a.model, TMD.SYSTEM, sent, a.temp,
                                    a.max_tokens, a.timeout, extra)
                out, missing = TMD.restore_fences(out, held)
                if missing:
                    nn.append(f"part {k}: {missing} held block(s) had nowhere to go back to")
                pieces.append(out.rstrip())
                notes += [f"part {k}: {x}" for x in nn]
                pn += t.get("prompt_n") or 0
                dn += t.get("predicted_n") or 0
                pms += t.get("prompt_ms") or 0.0
                dms += t.get("predicted_ms") or 0.0
                wall += w
        except Exception as e:                      # one bad file must not end the run
            row = {"file": rel, "ok": False, "error": f"{type(e).__name__}: {e}",
                   "parts": len(parts), "wall_s": round(time.time() - t_file, 2)}
            with open(rows_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"[{i}/{len(a.files)}] {rel}: FAILED — {row['error']}", flush=True)
            continue

        dst = os.path.join(a.out, dst_for(rel))
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        open(dst, "w", encoding="utf-8").write("\n\n".join(pieces).rstrip() + "\n")
        row = {"file": rel, "ok": True, "parts": len(parts),
               "source_words": len(src.split()), "prompt_tokens": pn, "predicted_tokens": dn,
               "prefill_tok_s": round(pn / (pms / 1000), 1) if pn and pms else None,
               "decode_tok_s": round(dn / (dms / 1000), 1) if dn and dms else None,
               "out_in_ratio": round(dn / pn, 3) if pn and dn else None,
               "wall_s": round(wall, 2), "notes": notes}
        with open(rows_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        el = time.time() - started
        print(f"[{i}/{len(a.files)}] {rel}: {row['source_words']}w in {len(parts)} part(s), "
              f"{row['wall_s']:.0f}s, {row['decode_tok_s']} tok/s"
              f"{'  ' + '; '.join(notes) if notes else ''}   [elapsed {el/60:.0f}m]", flush=True)
    # The exit status is the batch's own verdict on itself. Without this the caller sees the
    # status of `print`, which is always zero, and a run that translated nothing looks like a
    # run that translated everything -- which is exactly what happened on 2026-09-18.
    rows = []
    if os.path.exists(rows_path):
        for line in open(rows_path, encoding="utf-8"):
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    last = {}
    for r in rows:
        last[r["file"]] = r
    bad = [f for f in a.files if not (last.get(f) or {}).get("ok")]
    print(f"BATCH_DONE  {len(a.files) - len(bad)}/{len(a.files)} ok", flush=True)
    if bad:
        print("FAILED: " + ", ".join(bad[:12]) + ("…" if len(bad) > 12 else ""), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
