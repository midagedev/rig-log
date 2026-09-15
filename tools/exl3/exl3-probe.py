# exl3-serve round-2 premises probe: storage info vs quantization_config, per-device bytes by class
# (module walk, deduped by storage), split slice and CPU expert bytes, MTP placement, cache bytes,
# and what Generator.iterate() hands back per step under -mtp depth 1. Sentinel PROBE_DONE / PROBE_FAILED.
import sys, os, json, time, inspect, traceback, collections
sys.path.insert(0, os.path.expanduser("~/exllamav3-src/examples"))
import torch
import exllamav3
from exllamav3 import model_init, Generator, Job, GreedySampler
import argparse
p = argparse.ArgumentParser()
model_init.add_args(p, cache = True, add_draft_model_args = True, default_cache_size = 32768)
args = p.parse_args()

def section(name, fn):
    print(f"\n## {name}", flush = True)
    try: fn()
    except Exception: traceback.print_exc(); sys.stdout.flush()

def klass(key):
    if "embed_tokens" in key: return "embeddings"
    if "lm_head" in key or "shared_head" in key: return "output"
    if ".mlp.experts" in key: return "experts"
    if ".mlp.gate" in key: return "ffn"
    if ".mlp." in key or key.endswith(".mlp"): return "ffn"
    if ".self_attn" in key: return "attention"
    return "other"

def tensors_of(m):
    try: t = m.get_tensors()
    except Exception: return []
    if isinstance(t, dict): return list(t.values())
    return list(t or [])

def walk(root, seen):
    stack = [root]
    while stack:
        m = stack.pop()
        if id(m) in seen: continue
        seen.add(id(m)); yield m
        stack.extend(getattr(m, "modules", []) or [])

def main():
    print("argv:", sys.argv[1:], "CUDA_DEVICE_ORDER:", os.environ.get("CUDA_DEVICE_ORDER"))
    from exllamav3.version import __version__ as exl3_version
    print("version:", exl3_version)
    t0 = time.time()
    r = model_init.init(args, progress = False, quiet = True)
    model, config, cache, tokenizer = r[:4]
    extra = r[4:]
    print(f"loaded in {time.time()-t0:.0f} s; init returned {len(r)} items: {[type(x).__name__ for x in r]}")
    draft_model, draft_cache = (extra[0], extra[2]) if len(extra) >= 3 else (None, None)

    def storage():
        print("get_storage_info (mean bpw, head bpw, vram_bits):", model.get_storage_info())
        q = json.load(open(os.path.join(args.model_dir, "quantization_config.json")))
        print("quantization_config.json:", {k: q.get(k) for k in ("bits", "head_bits", "codebook")})
    section("storage info", storage)

    def placement():
        for name, root in (("model", model), ("draft_model", draft_model)):
            if root is None: print(name, "None"); continue
            seen, stor = set(), set()
            by = collections.defaultdict(lambda: collections.defaultdict(int))
            devs_of_layer45 = set()
            tops = list(root)
            for top in tops:
                for m in walk(top, seen):
                    key = getattr(m, "key", "") or ""
                    for t in tensors_of(m):
                        if not isinstance(t, torch.Tensor): continue
                        sid = (t.untyped_storage().data_ptr(), str(t.device))
                        if sid in stor: continue
                        stor.add(sid)
                        by[str(t.device)][klass(key)] += t.untyped_storage().nbytes()
                        if ".layers.45." in key: devs_of_layer45.add(str(t.device))
            for d, c in sorted(by.items()):
                print(f"{name} {d}: total {sum(c.values())} {dict(c)}")
            print(f"{name} layer-45 tensor devices: {sorted(devs_of_layer45)}; top modules {len(tops)}: {[getattr(x,'key','?') for x in tops[:3]]} ... {[getattr(x,'key','?') for x in tops[-3:]]}")
        for i in range(torch.cuda.device_count()):
            print(f"cuda:{i} memory_allocated {torch.cuda.memory_allocated(i)} reserved {torch.cuda.memory_reserved(i)}")
    section("placement by device and class (get_tensors, deduped by storage)", placement)

    def split():
        seen = set(); n = 0; cpu_bytes = 0; sizes = set()
        for top in model:
            for m in walk(top, seen):
                if not (hasattr(m, "num_experts") and hasattr(m, "ups")): continue
                E = m.num_experts; gpu = len(m.ups); k = E - gpu
                per = [sum(config.stc.get_tensor_sizes(f"{m.key}.experts.{e}")) for e in (0, E - 1)]
                sizes.update(per); cpu_bytes += k * per[0]
                if n < 2 or n == 41:
                    print(f"{m.key}: E={E} len(ups)={gpu} split_k={k} cpu_split_first={getattr(m,'cpu_split_first',None)} dynamic={getattr(m,'_split_dynamic',None)} expert bytes e0/eLast={per} top_k={getattr(m,'num_experts_per_tok',None)}")
                n += 1
        print(f"moe modules {n}; distinct expert byte sizes {sorted(sizes)}; CPU expert bytes (split_k x size) {cpu_bytes}")
    section("split slice and CPU expert bytes", split)

    def caches():
        for name, c in (("cache", cache), ("draft_cache", draft_cache)):
            if c is None: print(name, "None"); continue
            print(name, type(c).__name__, [a for a in dir(c) if not a.startswith("__")][:40])
            for attr in ("layers", "cache_layers", "caches"):
                L = getattr(c, attr, None)
                if L is None: continue
                items = L.values() if isinstance(L, dict) else L
                by = collections.defaultdict(int); ss = 0; stor = set()
                for layer in items:
                    try: ss += int(layer.storage_size())
                    except Exception: pass
                    for t in tensors_of(layer):
                        if isinstance(t, torch.Tensor):
                            sid = (t.untyped_storage().data_ptr(), str(t.device))
                            if sid in stor: continue
                            stor.add(sid); by[str(t.device)] += t.untyped_storage().nbytes()
                print(f"{name}.{attr}: storage_size sum {ss}; tensor bytes by device {dict(by)}")
    section("cache bytes", caches)

    def stream():
        print("Job.__init__", inspect.signature(Job.__init__))
        print("Generator.__init__", inspect.signature(Generator.__init__))
        kw = dict(model = model, cache = cache, tokenizer = tokenizer, draft_model = draft_model, draft_cache = draft_cache, max_batch_size = 1)
        try: gen = Generator(num_draft_tokens = 1, **kw)
        except TypeError as e: print("no num_draft_tokens:", e); gen = Generator(**kw)
        ids = tokenizer.encode("Write one sentence about rivers, then the word 日本語.", encode_special_tokens = True)
        job = Job(input_ids = ids, max_new_tokens = 30, sampler = GreedySampler(), stop_conditions = [tokenizer.eos_token_id])
        gen.enqueue(job); step = 0
        while gen.num_remaining_jobs():
            for res in gen.iterate():
                ti = res.get("token_ids")
                print(f"step {step}: keys {sorted(res.keys())} token_ids {None if ti is None else tuple(ti.shape)} {None if ti is None else ti.flatten().tolist()} text {res.get('text')!r} eos {res.get('eos')}")
                if res.get("eos"):
                    print("eos result:", {k: v for k, v in res.items() if k not in ('job', 'token_ids', 'text')})
                step += 1
    section("iterate() per step under -mtp", stream)
    print("PROBE_DONE", flush = True)

if __name__ == "__main__":
    try: main()
    except Exception: traceback.print_exc(); print("PROBE_FAILED", flush = True)
