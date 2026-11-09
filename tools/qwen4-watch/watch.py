#!/usr/bin/env python3
"""Watch Hugging Face for Qwen4 weights and start their download the moment they appear (the box, one run a tick).

Run by qwen4-watch.timer every 2 h. A repo counts when its id is Qwen4… or Qwhen4… (either spelling, a hyphen allowed) under Qwen, Qwhen or unsloth (the official weights and
the GGUF quants that usually follow within hours). For each repo not seen before it writes a MANIFEST through
configs/hf-fetch/hf-manifest.py into /models/<repo name>, keeps the rows this box should fetch (below), and starts
hf-worker.sh under ionice/nice in the background (its log and pid beside the MANIFEST). FOUND lists every repo seen,
for the lead's session to read.

What is fetched:
  - unsloth GGUF repos: the UD-Q4_K_XL files only (the quant the Qwen3.8 rows are served at), plus every *.json/*.md;
  - official repos: everything when the repo is BF16/full precision and its size fits (FREE_RESERVE below), since our
    own quantizer reads the checkpoint folder; an -FP8/-AWQ/-GPTQ/-GGUF/-MLX repo and a repo that does not fit get
    the metadata only (config, tokenizer, index, chat template): enough to read the architecture.
Nothing is fetched twice: a repo in the state file is skipped, and hf-worker resumes a file it already has.
"""
import json, os, re, shutil, subprocess, sys, time, urllib.request

HOME = os.environ.get("QWEN4_WATCH_HOME", "/root/qwen4-watch")
FETCH = os.environ.get("QWEN4_HF_FETCH", "/root/qwen4-watch/hf-fetch")
MODELS = os.environ.get("QWEN4_MODELS", "/models")
FREE_RESERVE = 400 * 10**9   # bytes /models keeps free after every fetch this watcher starts
ID = re.compile(os.environ.get("QWEN4_ID_RE", r"^(Qwen|Qwhen|unsloth)/(Qwen|Qwhen)-?4([-.]|$)"), re.I)
SEARCH = os.environ.get("QWEN4_SEARCH", "Qwen4,Qwhen")
AUTHORS = ("Qwen", "Qwhen", "unsloth")
NO_FETCH = os.environ.get("QWEN4_NO_FETCH") == "1"   # the self-test: the MANIFEST and its cut, no download
META = re.compile(r"(\.json|\.md|\.txt|\.py|\.jinja|tokenizer\.model|\.tiktoken)$")
QUANT_SUFFIX = re.compile(r"-(FP8|AWQ|GPTQ|GGUF|MLX|Int4|Int8|NVFP4|MXFP4)", re.I)

def log(*a):
    print(time.strftime("%Y-%m-%dT%H:%M:%S"), *a, flush=True)

def get(url):
    req = urllib.request.Request(url)
    tok = os.environ.get("HF_TOKEN")
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def candidates():
    out = set()
    for author in AUTHORS:
        for term in SEARCH.split(","):
            for m in get(f"https://huggingface.co/api/models?author={author}&search={term}&limit=200"):
                if ID.match(m["id"]):
                    out.add(m["id"])
    return sorted(out)

def keep(repo, path, size, total, free):
    if META.search(path):
        return True
    if repo.startswith("unsloth/"):
        return "UD-Q4_K_XL" in path
    if QUANT_SUFFIX.search(repo.split("/", 1)[1]):
        return False
    return total + FREE_RESERVE <= free

def start(repo):
    name = repo.split("/", 1)[1]
    dest = os.path.join(MODELS, name)
    os.makedirs(dest, exist_ok=True)
    subprocess.run([sys.executable, os.path.join(FETCH, "hf-manifest.py"), repo, dest], check=True)
    man = os.path.join(dest, "MANIFEST")
    rows = [l.rstrip("\n").split(" ", 2) for l in open(man) if l.strip() and not l.startswith("#")]
    head = [l for l in open(man) if l.startswith("#")]
    # MANIFEST rows: "sha256 size path", one space each (hf-manifest.py; a path may hold spaces)
    total = sum(int(r[1]) for r in rows)
    free = shutil.disk_usage(MODELS).free
    kept = [r for r in rows if keep(repo, r[2], int(r[1]), total, free)]
    shutil.copy(man, man + ".all")
    with open(man, "w") as f:
        f.writelines(head)
        f.writelines(" ".join(r) + "\n" for r in kept)
    want = sum(int(r[1]) for r in kept)
    log(f"{repo}: {len(rows)} files {total/1e9:.1f} GB in the repo; fetching {len(kept)} files {want/1e9:.1f} GB "
        f"into {dest} (free {free/1e9:.0f} GB)")
    if want == 0 or NO_FETCH:
        return dest, want
    lg = open(os.path.join(dest, "fetch.log"), "a")
    p = subprocess.Popen(["ionice", "-c3", "nice", "-n", "19", "bash", os.path.join(FETCH, "hf-worker.sh"), repo, dest],
                         stdout=lg, stderr=subprocess.STDOUT, start_new_session=True)
    open(os.path.join(dest, "fetch.pid"), "w").write(f"{p.pid}\n")
    return dest, want

def main():
    os.makedirs(HOME, exist_ok=True)
    tf = os.path.expanduser("~/.cache/huggingface/token")
    if "HF_TOKEN" not in os.environ and os.path.exists(tf):
        os.environ["HF_TOKEN"] = open(tf).read().strip()
    state_f = os.path.join(HOME, "state.json")
    state = json.load(open(state_f)) if os.path.exists(state_f) else {"seen": {}}
    found = candidates()
    log(f"tick: {len(found)} matching repos ({', '.join(found) or 'none'})")
    for repo in found:
        if repo in state["seen"]:
            continue
        try:
            dest, want = start(repo)
            state["seen"][repo] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "dir": dest, "bytes": want}
        except Exception as e:   # a failed repo is retried next tick, named here
            log(f"{repo}: not started: {e!r}")
    json.dump(state, open(state_f + ".tmp", "w"), indent=1)
    os.replace(state_f + ".tmp", state_f)
    with open(os.path.join(HOME, "FOUND"), "w") as f:
        for repo, s in sorted(state["seen"].items()):
            f.write(f"{repo}\t{s['at']}\t{s['dir']}\t{s['bytes']}\n")

if __name__ == "__main__":
    main()
