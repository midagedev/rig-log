# exllamav3 bench v6 = v5 + --patch_defer (monkeypatch of the candidate fix for the static-placement bug). v5 = v4 + --dump_stats <json>: per-layer router selection counts (the runtime's _split_hist) for EXL3_MOE_CPU_SPLIT_STATS. alternates prompts run to run (essay / coding / explanation) so the dynamic placement is measured on a mixed stream, not one text's routing histogram. Greedy 400-token decode x N + one 11k-token prefill, timings from the Job results.
# usage: python exl3-bench.py -m <dir> [-gs 44,20] [-mcl N | -mcs N] [-mct T] [-cs 32768] [-mtp] [--no_prefill]
import sys, os, time, json, argparse
sys.path.insert(0, os.path.expanduser("~/exllamav3-src/examples"))
from exllamav3 import model_init, Generator, Job, GreedySampler
import jinja2
p = argparse.ArgumentParser()
model_init.add_args(p, cache = True, add_draft_model_args = True, default_cache_size = 32768)
p.add_argument("--no_prefill", action = "store_true"); p.add_argument("--runs", type = int, default = 3)
p.add_argument("--effort", type = str, default = "high")
p.add_argument("--dump_stats", type = str, default = None); p.add_argument("--patch_defer", action = "store_true"); p.add_argument("--draft_n", type = int, default = None); p.add_argument("--dyn_draft", action = "store_true")
args = p.parse_args()

def main():
    if args.patch_defer:
        # Candidate fix under test: the deferred-load guard must also see the CLI split (infer_params.moe_cpu_split), not only the env var
        from exllamav3.modules import block_sparse_mlp_cpu as bsc
        _orig = bsc.BlockSparseMLP_CPU.can_defer_load
        def can_defer_load(self):
            if os.environ.get("EXL3_MOE_CPU_SPLIT_STATS") and (int(os.environ.get("EXL3_MOE_CPU_SPLIT", 0)) > 0 or getattr(self.config.infer_params, "moe_cpu_split", 0)):
                return False
            return _orig(self)
        bsc.BlockSparseMLP_CPU.can_defer_load = can_defer_load
        print("patched can_defer_load", flush = True)
    t0 = time.time()
    r = model_init.init(args, progress = False, quiet = True)
    model, config, cache, tokenizer = r[:4]; draft_model, draft_config, draft_cache = (r[4:7] if len(r) > 4 else (None, None, None))
    print(f"loaded in {time.time()-t0:.0f} s", flush = True)
    os.system("nvidia-smi --query-gpu=memory.used --format=csv,noheader | tr '\\n' ' '; echo")
    gen = Generator(model = model, cache = cache, tokenizer = tokenizer, draft_model = draft_model, draft_cache = draft_cache, max_batch_size = 1, num_draft_tokens = args.draft_n, dynamic_draft_tokens = args.dyn_draft)
    print(f"num_draft_tokens {gen.num_draft_tokens} dynamic {gen.dynamic_draft}", flush = True)
    tpl = jinja2.Environment(extensions=["jinja2.ext.loopcontrols"]).from_string(open(os.path.join(args.model_dir, "chat_template.jinja")).read())
    def prompt(msg):
        return tpl.render(messages = [{"role": "user", "content": msg}], add_generation_prompt = True, reasoning_effort = args.effort, tools = None)
    def run(msg, n):
        ids = tokenizer.encode(prompt(msg), encode_special_tokens = True)
        job = Job(input_ids = ids, max_new_tokens = n, sampler = GreedySampler(), stop_conditions = [tokenizer.eos_token_id])
        gen.enqueue(job); text = ""; meta = None
        while gen.num_remaining_jobs():
            for res in gen.iterate():
                text += res.get("text", "")
                if res.get("eos"): meta = res
        return text, meta
    prompts = ["Write a 600-word essay about rivers. take 1",
               "Write a Python function that parses ISO-8601 durations like P3DT4H5M into a timedelta, with tests.",
               "Explain to a first-year student why memory bandwidth, not compute, bounds decoding speed for mixture-of-experts models on consumer hardware.",
               "Write a short story about a lighthouse keeper who receives a letter from the future.",
               "Write a Rust function that merges two sorted iterators into one, with doc comments."]
    for i in range(args.runs):
        text, m = run(prompts[i % len(prompts)], 400)
        n = m.get("new_tokens"); tg = m.get("time_generate"); tp = m.get("time_prefill")
        print(f"    decode {n/tg:.1f} tok/s ({n} tok) p{i % len(prompts)}  prompt {m.get('prompt_tokens')} tok  TTFT {tp:.2f}s  acc {m.get('accepted_draft_tokens')}/{m.get('rejected_draft_tokens')}", flush = True)
        open(os.path.expanduser("~/exl3-ans2.txt"), "a").write(f"p{i % len(prompts)} " + text[:200].replace("\n", " ") + "\n")
    if not args.no_prefill:
        doc = open(os.path.expanduser("~/eval/wiki.test.raw")).read()[:50000]
        text, m = run(doc + "\n\nSummarize the above in three sentences.", 64)
        n = m.get("prompt_tokens"); tp = m.get("time_prefill"); ng = m.get("new_tokens"); tg = m.get("time_generate")
        print(f"    prefill {n} tok @ {n/tp:.1f} tok/s  TTFT {tp:.1f}s  decode {ng/tg:.1f}", flush = True)
    os.system("nvidia-smi --query-gpu=memory.used --format=csv,noheader | tr '\\n' ' '; echo")
    if args.dump_stats:
        stats = {}
        def walk(m):
            h = getattr(m, "_split_hist", None)
            if h is not None: stats[m.key] = [float(x) for x in h.cpu().tolist()]
            for c in getattr(m, "modules", []) or []: walk(c)
        walk(model)
        json.dump(stats, open(args.dump_stats, "w"))
        tot = sum(sum(v) for v in stats.values())
        print(f"stats dumped: {len(stats)} layers, {tot:.0f} selections -> {args.dump_stats}", flush = True)
    print("EXL3_BENCH_OK")

if __name__ == "__main__":
    main()
