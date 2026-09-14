#!/usr/bin/env python
"""WKS-13: rebuild the served Q3_K_M shard set with every attention, shared-expert and indexer
projection taken from the uploader's Q8_0 build (shard 10 of that set, local), raw bytes, no
dequantization. Everything else is copied byte for byte; KVs verbatim (split.* included).
Shards with nothing to swap are hard-linked into the destination.

    graft-attn-q8.py [--dry-run] [--shard N]
"""
import argparse, fcntl, os, re, sys, time
sys.path.insert(0, "~/llama.cpp-v41/gguf-py")
from gguf import GGUFReader, GGUFWriter, GGUFValueType

SRC_DIR = "/models/DeepSeek-V4.1-Flash-Q3_K_M-engramQ8-tokembdBF16"
DST_DIR = "/models/DeepSeek-V4.1-Flash-Q3_K_M-engramQ8-tokembdBF16-attnQ8"
DONOR = "/models/DeepSeek-V4.1-Flash-Q8_0-engram-src/DeepSeek-V4.1-Flash-Q8_0-00010-of-00010.gguf"
NAME = "DeepSeek-V4.1-Flash-Q3_K_M-{:05d}-of-00009.gguf"
WANT = re.compile(r"^blk\.\d+\.(attn_(kv|q_a|q_b|output_a|output_b)\.weight|ffn_(gate|up|down)_shexp\.weight|indexer\.attn_q_b\.weight)$")

def log(m): print(time.strftime("%H:%M:%S"), m, flush=True)

def scalar(field, part):
    if field.types[-1] == GGUFValueType.STRING:
        return bytes(part).decode("utf-8")
    return part.tolist()[0]

def graft(n, donor_by_name, dry):
    src = os.path.join(SRC_DIR, NAME.format(n)); out = os.path.join(DST_DIR, NAME.format(n))
    if os.path.exists(out):
        log(f"shard {n:02d}: output exists, skipping"); return
    reader = GGUFReader(src)
    names = {t.name for t in reader.tensors if WANT.match(t.name)}
    if not names:
        log(f"shard {n:02d}: nothing to swap, hard-linking")
        if not dry: os.link(src, out)
        return
    missing = names - set(donor_by_name); assert not missing, sorted(missing)
    old = sum(t.n_bytes for t in reader.tensors if t.name in names); new = sum(donor_by_name[x].n_bytes for x in names)
    log(f"shard {n:02d}: {len(names)} tensors to swap, {old/1e9:.2f} GB -> {new/1e9:.2f} GB")
    for t in reader.tensors:
        if t.name in names:
            d = donor_by_name[t.name]
            assert [int(x) for x in t.shape] == [int(x) for x in d.shape], (t.name, t.shape, d.shape)
    if dry: return
    lock = open(out + ".lock", "w"); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    arch_f = reader.fields.get("general.architecture")
    arch = str(bytes(arch_f.parts[arch_f.data[0]]), encoding="utf-8") if arch_f else "deepseek41"
    writer = GGUFWriter(out + ".tmp", arch=arch, use_temp_file=False, endianess=reader.endianess)
    if arch_f is None:
        writer.remove_key("general.architecture")
    for field in reader.fields.values():
        if field.name in ("GGUF.version", "GGUF.tensor_count", "GGUF.kv_count", "general.architecture"):
            continue
        vt = field.types[0]; st = field.types[-1] if vt == GGUFValueType.ARRAY else None
        val = [scalar(field, field.parts[i]) for i in field.data] if vt == GGUFValueType.ARRAY else scalar(field, field.parts[-1])
        writer.add_key_value(field.name, val, vt, sub_type=st)
    plan = []
    for t in reader.tensors:
        s = donor_by_name[t.name] if t.name in names else t
        writer.add_tensor_info(t.name, s.data.shape, s.data.dtype, s.data.nbytes, s.tensor_type)
        plan.append(s)
    t0 = time.time()
    writer.write_header_to_file(); writer.write_kv_data_to_file(); writer.write_ti_data_to_file()
    for i, s in enumerate(plan):
        writer.write_tensor_data(s.data)
        if i % 40 == 0: log(f"  shard {n:02d} wrote {i+1}/{len(plan)}")
    writer.close()
    check = GGUFReader(out + ".tmp")
    got = {t.name: (t.tensor_type, t.n_bytes) for t in check.tensors}
    for t in reader.tensors:
        w = donor_by_name[t.name] if t.name in names else t
        assert got[t.name] == (w.tensor_type, w.n_bytes), (t.name, got[t.name], w.tensor_type, w.n_bytes)
    assert len(got) == len(reader.tensors)
    assert [t.name for t in check.tensors] == [t.name for t in reader.tensors], "order"
    del check
    os.rename(out + ".tmp", out)
    log(f"shard {n:02d}: verified {len(got)} tensors, {os.path.getsize(out)} bytes, {time.time()-t0:.0f}s")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--shard", type=int)
    a = ap.parse_args()
    os.makedirs(DST_DIR, exist_ok=True)
    donor = GGUFReader(DONOR); donor_by_name = {t.name: t for t in donor.tensors}
    for n in ([a.shard] if a.shard else range(1, 10)):
        graft(n, donor_by_name, a.dry_run)
    log("GRAFT_DONE")

if __name__ == "__main__":
    main()
