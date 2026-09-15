# Verify a running exl3-serve against the lead's measured reference (2026-09-15, -gs 44,21 -mcs 185 -mct 32 -cs 32768 -mtp).
# usage: exl3serve-verify.py <base url> <out dir>. Exit 0 only when every check passes.
import sys, json, urllib.request, os
BASE, OUT = sys.argv[1], sys.argv[2]
fails = []
def check(name, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: got {got!r}" + ("" if ok else f" want {want!r}"))
    if not ok: fails.append(name)
props = json.load(urllib.request.urlopen(BASE + "/props", timeout=30))
json.dump(props, open(os.path.join(OUT, "props.json"), "w"), indent=2, ensure_ascii=False)
e = props.get("engine") or {}
m = e.get("model") or {}
print("## engine.model")
for k, v in {"format": "exl3", "arch": "Glm5NextForConditionalGeneration", "quant": "EXL3 4.05 bpw · head 6.0",
             "bytes": 165151541665, "files": 30, "params": 313326811966, "n_layers": 45, "n_experts": 288,
             "n_experts_used": 8, "ctx_train": 1048576, "active_bytes_per_token": 10979084996}.items():
    check(f"model.{k}", m.get(k), v)
check("name", e.get("name"), "exllamav3"); check("version", e.get("version"), "1.5.0")
print("  args:", e.get("args"))
print("## placement (reference: probe walk + MTP model + 185 CPU experts x 12 619 788 B per MoE layer)")
dev = {d.get("device"): d for d in (e.get("placement") or {}).get("devices", [])}
for name, want in {"GPU0": 42349887488 + 1603796992, "GPU1": 19178192896, "CPU": 1268829908 + 1272 + 185 * 12619788 * 42}.items():
    d = dev.get(name, {})
    check(f"{name}.bytes", d.get("bytes"), want)
    cl = d.get("classes") or {}
    check(f"{name}.bytes==sum(classes)", sum(cl.values()) if cl else None, d.get("bytes"))
    print(f"       classes {cl}")
check("vram_kv_bytes", (e.get("placement") or {}).get("vram_kv_bytes"), 419430400 + 157286400 + 52428800)
def zeros(o, path=""):
    if isinstance(o, dict): return [z for k, v in o.items() for z in zeros(v, f"{path}.{k}")]
    if isinstance(o, list): return [z for i, v in enumerate(o) for z in zeros(v, f"{path}[{i}]")]
    return [path] if (isinstance(o, (int, float)) and not isinstance(o, bool) and o == 0) else []
check("no numeric zero in engine", zeros(e), [])
print("## one streaming chat request")
body = {"messages": [{"role": "user", "content": "Write a Python function that parses ISO 8601 durations into timedelta, with two tests."}],
        "max_tokens": 400, "stream": True, "stream_options": {"include_usage": True}, "return_progress": True}
req = urllib.request.Request(BASE + "/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
raw, events = [], []
with urllib.request.urlopen(req, timeout=900) as r:
    for line in r:
        raw.append(line)
        s = line.decode("utf-8").strip()
        if s.startswith("data: ") and s != "data: [DONE]":
            events.append(json.loads(s[6:]))
open(os.path.join(OUT, "chat.sse.txt"), "wb").write(b"".join(raw))
text_deltas = 0; content = ""; reasoning = ""; progress = 0; final = None
for ev in events:
    if "prompt_progress" in ev: progress += 1
    for ch in ev.get("choices") or []:
        d = ch.get("delta") or {}
        c, rc = d.get("content") or "", d.get("reasoning_content") or ""
        if c or rc: text_deltas += 1
        content += c; reasoning += rc
        if ch.get("finish_reason"): final = ev
t = (final or {}).get("timings") or {}
print(f"  events {len(events)}, text deltas {text_deltas}, prompt_progress chunks {progress}, reasoning chars {len(reasoning)}, content chars {len(content)}")
print(f"  finish_reason {final and final['choices'][0]['finish_reason']}; timings {t}; usage {(final or {}).get('usage')}")
check("reasoning split non-empty", len(reasoning) > 0, True)
check("no </think> in any delta text", "</think>" in content or "</think>" in reasoning, False)
pn = t.get("predicted_n")
check("predicted_n - text deltas in {0,1} (tag tokens)", (pn - text_deltas) in (0, 1) if isinstance(pn, int) else None, True)
check("timings has draft_n", "draft_n" in t, True)
print("RESULT", "PASS" if not fails else "FAIL " + ", ".join(fails))
sys.exit(0 if not fails else 1)
