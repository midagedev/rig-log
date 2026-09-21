#!/bin/bash
# bench-agent-shape.sh <port> <outdir> <corpus> [rows...] — agent-shaped throughput against a
# running llama-server: decode at several prompt depths, one cold 30k prefill, and the
# prompt-cache reuse pattern an agent actually produces (same prefix again; same prefix plus
# new tail; same prefix with an edit in the middle).
#
# Written for round WORKER (2026-09-21). Three things make this different from llama-bench:
# the prompt is real text from this repository rather than lorem, the reuse rows are what a
# coding agent does to a KV cache between turns, and every row carries its own quietness
# witnesses so a suspect row says so instead of needing a timeline reconstructed afterwards
# (docs/quiet-machine.md).
#
# The lease is taken here, not by the caller: a delegated round given the rule in prose
# writes its own gate and gets it wrong — that incident is why this is a script at all.
# Witnesses per row: both cards, loadavg, /proc/pressure/io some avg10, llm.service.
#
# Rows are n = 3 by default (REPS); anything below that is SMOKE and the caller must label
# it so. Output: <outdir>/rows.jsonl (one object per repetition) and a summary on stdout.
set -u
PORT=${1:?usage: bench-agent-shape.sh <port> <outdir> <corpus> [rows...]}
OUT=${2:?outdir}
CORPUS=${3:?corpus file}
shift 3
ROWS=${*:-depth0 depth8k depth32k prefill30k reuse}
REPS=${REPS:-3}
LEASE=${LEASE:-/root/bloomery-cpu.lock}
mkdir -p "$OUT"

exec 9>"$LEASE"
flock -w 1800 9 || { echo "lease $LEASE not acquired in 1800 s"; exit 1; }
echo "lease $LEASE held by $$"

PORT=$PORT OUT=$OUT CORPUS=$CORPUS ROWS=$ROWS REPS=$REPS python3 - <<'PY'
import json, os, subprocess, time, urllib.request, urllib.error

port, out, corpus = os.environ["PORT"], os.environ["OUT"], os.environ["CORPUS"]
rows, reps = os.environ["ROWS"].split(), int(os.environ["REPS"])
url = f"http://127.0.0.1:{port}/v1/chat/completions"
text = open(corpus, encoding="utf-8").read()


def witness():
    g = subprocess.run(["nvidia-smi", "--query-gpu=index,memory.used,utilization.gpu",
                        "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout
    io = [l for l in open("/proc/pressure/io") if l.startswith("some")][0].split()[1]
    llm = subprocess.run(["systemctl", "is-active", "llm.service"],
                         capture_output=True, text=True).stdout.strip()
    apps = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory",
                           "--format=csv,noheader"], capture_output=True, text=True).stdout.split("\n")
    return {"gpus": g.strip().replace("\n", " | "), "loadavg": open("/proc/loadavg").read().split()[0],
            "io_some_avg10": io, "llm_service": llm,
            "compute_apps": [a for a in apps if a.strip()]}


def ask(messages, max_tokens, cache_prompt=True, label=""):
    body = {"model": "local", "messages": messages, "max_tokens": max_tokens,
            "temperature": 0.0, "stream": False, "cache_prompt": cache_prompt}
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    w0 = witness(); t0 = time.time()
    try:
        d = json.load(urllib.request.urlopen(req, timeout=1800))
    except urllib.error.HTTPError as e:
        return {"label": label, "error": f"HTTP {e.code}", "body": e.read()[:400].decode(errors="replace"),
                "witness_before": w0, "witness_after": witness()}
    wall = time.time() - t0
    t = (d.get("__verbose") or {}).get("timings") or d.get("timings") or {}
    return {"label": label, "wall_s": round(wall, 3),
            "prompt_n": t.get("prompt_n"), "cache_n": t.get("cache_n"),
            "predicted_n": t.get("predicted_n"),
            "prompt_ms": t.get("prompt_ms"), "predicted_ms": t.get("predicted_ms"),
            "prefill_tok_s": t.get("prompt_per_second"),
            "decode_tok_s": t.get("predicted_per_second"),
            "ttft_s": round((t.get("prompt_ms") or 0) / 1000.0, 3),
            "cached_tokens": ((d.get("usage") or {}).get("prompt_tokens_details") or {}).get("cached_tokens"),
            "usage": d.get("usage"), "finish": d["choices"][0]["finish_reason"],
            "witness_before": w0, "witness_after": witness()}


# Chars per token is not guessable for this corpus. A first attempt used 3 chars/token and
# asked for 30k tokens; the server answered 400 with n_prompt_tokens=56012, because this
# repository's logs are Korean-heavy and run about 1.6 chars per token. So the ratio is
# measured against the server's own tokenizer once, and then checked: the row still records
# prompt_n, which is the fact, while the label is only the target.
def _tokenize(s):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/tokenize",
                                 json.dumps({"content": s}).encode(),
                                 {"Content-Type": "application/json"})
    return len(json.load(urllib.request.urlopen(req, timeout=300))["tokens"])


_probe_chars = 40000
_cpt = _probe_chars / _tokenize(text[:_probe_chars])
print(f"# calibration: {_cpt:.3f} chars/token over {_probe_chars} chars of the corpus")


def filler(tokens):
    if not tokens:
        return ""
    s = text[: int(tokens * _cpt)]
    # one correction pass — the ratio drifts across the corpus
    n = _tokenize(s)
    if n:
        s = text[: int(len(s) * tokens / n)]
    return s


sink = open(f"{out}/rows.jsonl", "a")


def emit(r):
    sink.write(json.dumps(r, ensure_ascii=False) + "\n"); sink.flush()
    print(json.dumps({k: v for k, v in r.items() if k not in ("witness_before", "witness_after", "usage")},
                     ensure_ascii=False))


Q = "\n\nIn one sentence, what is the subject of the text above?"

for row in rows:
    for i in range(reps):
        if row.startswith("depth"):
            d = row[5:]
            ntok = {"0": 0, "8k": 8000, "32k": 32000, "24k": 24000, "48k": 48000}[d]
            msgs = [{"role": "user", "content": (filler(ntok) + Q) if ntok else
                     "Count from 1 to 40, separated by spaces."}]
            emit(dict(row=row, rep=i, **ask(msgs, 160, True, f"{row}#{i}")))
        elif row == "prefill30k":
            msgs = [{"role": "user", "content": filler(30000) + Q}]
            # cache_prompt False => cold prefill, otherwise the second repetition is a cache hit
            emit(dict(row=row, rep=i, **ask(msgs, 8, False, f"{row}#{i}")))
        elif row == "agentloop":
            # The shape that actually decides this model's fitness as a delegate: a long
            # system prefix plus a tools array, then turns that grow by an assistant message
            # carrying tool_calls and a tool message carrying the result. Appending is only
            # cache-preserving if the template re-renders the earlier turns byte-identically,
            # and a tool_call round-trip is where that is most likely to break (a dropped id,
            # a reasoning block stripped on re-render). Measured here rather than assumed.
            tools = [{"type": "function", "function": {
                "name": "read_file", "description": "Read a file from disk.",
                "parameters": {"type": "object",
                               "properties": {"path": {"type": "string"}}, "required": ["path"]}}}]
            sysmsg = {"role": "system", "content": "You are a code assistant.\n\n" + filler(20000)}
            msgs = [sysmsg, {"role": "user", "content": "Read /tmp/worker-marker.txt with the tool."}]
            for step in range(4):
                body = {"model": "local", "messages": msgs, "tools": tools,
                        "max_tokens": 128, "temperature": 0.0, "stream": False, "cache_prompt": True}
                req = urllib.request.Request(url, json.dumps(body).encode(),
                                             {"Content-Type": "application/json"})
                w0 = witness(); t0 = time.time()
                try:
                    d = json.load(urllib.request.urlopen(req, timeout=1800))
                except urllib.error.HTTPError as e:
                    emit({"row": "agentloop", "rep": i, "step": step, "error": f"HTTP {e.code}",
                          "body": e.read()[:400].decode(errors="replace"),
                          "witness_before": w0, "witness_after": witness()})
                    break
                wall = time.time() - t0
                t = (d.get("__verbose") or {}).get("timings") or d.get("timings") or {}
                m = d["choices"][0]["message"]
                tc = m.get("tool_calls") or []
                emit({"row": "agentloop", "rep": i, "step": step,
                      "prompt_n": t.get("prompt_n"), "cache_n": t.get("cache_n"),
                      "ttft_s": round((t.get("prompt_ms") or 0) / 1000.0, 3),
                      "wall_s": round(wall, 3), "predicted_n": t.get("predicted_n"),
                      "decode_tok_s": t.get("predicted_per_second"),
                      "tool_calls": len(tc),
                      "tool_name": tc[0]["function"]["name"] if tc else None,
                      "finish": d["choices"][0]["finish_reason"],
                      "witness_before": w0, "witness_after": witness()})
                msgs = msgs + [{"role": "assistant", "content": m.get("content") or "",
                                **({"tool_calls": tc} if tc else {})}]
                if tc:
                    msgs.append({"role": "tool", "tool_call_id": tc[0].get("id", "call_0"),
                                 "name": tc[0]["function"]["name"],
                                 "content": "WORKER-MARKER-7391"})
                    msgs.append({"role": "user", "content": f"Good. Now read it again (attempt {step + 2})."})
                else:
                    msgs.append({"role": "user", "content": f"Read it again (attempt {step + 2}) with the tool."})
        elif row == "reuseseq":
            # The reuse rows the round publishes. A reuse table is only readable if each row
            # says what was in the slot BEFORE the request, because llama-server keeps exactly
            # one cached prompt per slot: the previous request's. Measured 2026-09-21, a table
            # that did not record this read as "the cache is flaky" when it was in fact
            # deterministic — every cache_n=0 row followed a request whose prompt diverged.
            pre = filler(30000)
            tail1 = filler(500)
            cut = int(len(pre) * 0.6)
            edited = pre[:cut] + "\n[EDITED LINE INSERTED BY THE AGENT AT 60% DEPTH]\n" + pre[cut:]
            cut9 = int(len(pre) * 0.9)
            edit90 = pre[:cut9] + "\n[EDITED LINE INSERTED BY THE AGENT AT 90% DEPTH]\n" + pre[cut9:]
            seq = [
                ("t0-cold-prefix",      [{"role": "user", "content": pre + Q}],              "unrelated/cold"),
                ("t1-same-prefix",      [{"role": "user", "content": pre + Q}],              "the same prefix"),
                ("t2-append-500",       [{"role": "user", "content": pre + Q},
                                         {"role": "assistant", "content": "A build log."},
                                         {"role": "user", "content": tail1 + "\nSame question."}], "the t1 prefix"),
                ("t3-append-again",     [{"role": "user", "content": pre + Q},
                                         {"role": "assistant", "content": "A build log."},
                                         {"role": "user", "content": tail1 + "\nSame question."},
                                         {"role": "assistant", "content": "Still a build log."},
                                         {"role": "user", "content": tail1 + "\nAnd again."}], "the t2 prompt"),
                ("t4-edit-at-90pct",    [{"role": "user", "content": edit90 + Q}],           "the t3 prompt"),
                ("t5-edit-at-60pct",    [{"role": "user", "content": edited + Q}],           "the t4 prompt"),
                ("t6-back-to-prefix",   [{"role": "user", "content": pre + Q}],              "the t5 prompt"),
            ]
            for name, msgs, slot_had in seq:
                r = ask(msgs, 8, True, f"{name}#{i}")
                emit(dict(row=name, rep=i, slot_held_before=slot_had, **r))
        elif row == "reuse":
            pre = filler(30000)
            a = ask([{"role": "user", "content": pre + Q}], 8, True, f"reuse-1st#{i}")
            emit(dict(row="reuse-1st-prefix", rep=i, **a))
            b = ask([{"role": "user", "content": pre + Q},
                     {"role": "assistant", "content": "A build log."},
                     {"role": "user", "content": filler(500)[:1500] + "\nSame question again."}],
                    8, True, f"reuse-append#{i}")
            emit(dict(row="reuse-append-500", rep=i, **b))
            cut = int(len(pre) * 0.6)
            edited = pre[:cut] + "\n[EDITED LINE INSERTED BY THE AGENT AT 60% DEPTH]\n" + pre[cut:]
            c = ask([{"role": "user", "content": edited + Q}], 8, True, f"reuse-edit60#{i}")
            emit(dict(row="reuse-edit-at-60pct", rep=i, **c))
        else:
            print(f"unknown row {row}")
sink.close()
PY
rc=$?
echo "bench rc=$rc"
exit $rc
