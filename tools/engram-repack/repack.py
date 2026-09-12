#!/usr/bin/env python3
"""Rebuild Q3_K_M shards 02 and 05 with the engram tensors taken from the
Q8_0 source shards, raw, no dequantization.

The converter writes engram from the fp8 original as Q8_0 unconditionally,
so the Q8_0 upload's engram tensors are what a fresh conversion would
produce. Everything except the four engram tensors per shard is copied
byte-identical from our Q3_K_M shard; KVs are copied verbatim.

Writes <shard>.tmp, verifies (tensor inventory + engram byte hashes +
whole-file sha256), then renames into place. Re-runnable: a verified output
is skipped, a stale .tmp is deleted and redone. One flock per output file:
two writers on one file destroyed 89 GB here on 2026-09-12.
"""
import argparse
import fcntl
import hashlib
import json
import os
import time

import numpy as np
from gguf import GGUFReader, GGUFWriter, GGUFValueType
from gguf.gguf_writer import WriterState

Q3_DIR = "/models/DeepSeek-V4.1-Flash-Q3_K_M"
SRC_DIR = "/models/DeepSeek-V4.1-Flash-Q8_0-engram-src"
DST_DIR = "/models/DeepSeek-V4.1-Flash-Q3_K_M-engramQ8"
Q3_NAME = "DeepSeek-V4.1-Flash-Q3_K_M-{:05d}-of-00009.gguf"
Q8_NAME = "DeepSeek-V4.1-Flash-Q8_0-{:05d}-of-00010.gguf"
PAUSE_FILE = "/tmp/rig-quiet"
CHUNK = 1 << 30  # slice size: never hold more than 1 GiB per copy step

# tensor name -> Q8_0 source shard number carrying it
SWAPS = {
    2: {
        "blk.1.engram_embd.weight": 8,
        "blk.1.engram_k.weight": 10,
        "blk.1.engram_q.weight": 10,
        "blk.1.engram_wkv.weight": 10,
    },
    5: {
        "blk.14.engram_embd.weight": 9,
        "blk.14.engram_k.weight": 10,
        "blk.14.engram_q.weight": 10,
        "blk.14.engram_wkv.weight": 10,
    },
}


def log(msg):
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}", flush=True)


def pause_gate(step):
    waits = 0
    while os.path.exists(PAUSE_FILE):
        if waits == 0:
            log(f"{step}: pause file {PAUSE_FILE} present, waiting")
        log(f"PAUSEWAIT {step}")
        time.sleep(60)
        waits += 1
    return waits


def raw_u8(tensor):
    """Flat uint8 byte view of a ReaderTensor's data (no copy of the bytes)."""
    a = tensor.data.reshape(-1)
    if a.dtype != np.uint8:
        a = a.view(np.uint8)
    assert a.nbytes == tensor.n_bytes, (a.nbytes, tensor.n_bytes)
    return a


def copy_kv(reader, writer):
    """Verbatim KV copy, after gguf-py's own gguf_new_metadata.py recipe:
    skip the virtual GGUF.* fields and the writer-managed architecture key."""
    for field in reader.fields.values():
        if field.name == "general.architecture" or field.name.startswith("GGUF."):
            continue
        val_type = field.types[0]
        sub_type = field.types[-1] if val_type == GGUFValueType.ARRAY else None
        writer.add_key_value(field.name, field.contents(), val_type, sub_type=sub_type)


def dontneed(fd):
    if fd is not None:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)


def stream_write_tensors(writer, plan, fadvise_fds=None):
    """GGUFWriter.write_tensor_data, but in <=1 GiB slices so this job does
    not evict the served model from the page cache. Mirrors the library's
    padding, tensor-info pop and state handling exactly; test_roundtrip.py
    byte-compares this path against the library path."""
    fout = writer.fout[0]
    ofd = fout.fileno()
    for name, raw, nbytes, fd_key in plan:
        first = next(iter(writer.tensors[0]))
        ti = writer.tensors[0].pop(first)
        assert first == name and ti.nbytes == nbytes, (first, name, ti.nbytes, nbytes)
        writer.write_padding(fout, fout.tell())
        off = 0
        while off < nbytes:
            buf = raw[off:off + CHUNK]
            fout.write(buf)
            off += buf.nbytes
            if fadvise_fds is not None:
                dontneed(fadvise_fds.get(fd_key))
                os.posix_fadvise(ofd, 0, 0, os.POSIX_FADV_DONTNEED)
        writer.write_padding(fout, nbytes)
        if writer.state != WriterState.WEIGHTS:
            writer.state = WriterState.WEIGHTS


def slice_hash(raw, fd=None):
    h = hashlib.sha256()
    off, n = 0, raw.nbytes
    while off < n:
        buf = raw[off:off + CHUNK]
        h.update(buf)
        off += buf.nbytes
        dontneed(fd)
    return h.hexdigest()


def file_sha256(path):
    h = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY)
    try:
        while True:
            buf = os.read(fd, CHUNK)
            if not buf:
                break
            h.update(buf)
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        return h.hexdigest()
    finally:
        os.close(fd)


def kv_signature(reader):
    """Comparable view of the real (non-virtual) KVs, in file order."""
    out = []
    for name, field in reader.fields.items():
        if name == "general.architecture" or name.startswith("GGUF."):
            continue
        out.append((name, tuple(t.name for t in field.types), repr(field.contents())))
    return out


def verify_shard(path, n, swaps_paths):
    """Re-open the candidate file and prove it is the shard we meant to
    build. Returns a summary dict; raises AssertionError on any mismatch."""
    r_our = GGUFReader(os.path.join(Q3_DIR, Q3_NAME.format(n)))
    src_readers = {p: GGUFReader(p) for p in sorted(set(swaps_paths.values()))}
    expect = {}
    for t in r_our.tensors:
        if t.name in swaps_paths:
            st = next(x for x in src_readers[swaps_paths[t.name]].tensors if x.name == t.name)
            expect[t.name] = (st.tensor_type, [int(d) for d in st.shape], st.n_bytes)
        else:
            expect[t.name] = (t.tensor_type, [int(d) for d in t.shape], t.n_bytes)

    rv = GGUFReader(path)
    assert [t.name for t in rv.tensors] == list(expect.keys()), "tensor name/order mismatch"
    by_name = {t.name: t for t in rv.tensors}
    for t in rv.tensors:
        et, eshape, enb = expect[t.name]
        assert t.tensor_type == et, (t.name, t.tensor_type, et)
        assert [int(d) for d in t.shape] == eshape, (t.name, t.shape, eshape)
        assert t.n_bytes == enb, (t.name, t.n_bytes, enb)
    assert kv_signature(rv) == kv_signature(r_our), "KV block not verbatim"

    summary = {"tensor_count": len(rv.tensors), "engram": {}}
    fds = {p: os.open(p, os.O_RDONLY) for p in src_readers}
    fd_new = os.open(path, os.O_RDONLY)
    try:
        for name, p in swaps_paths.items():
            st = next(x for x in src_readers[p].tensors if x.name == name)
            h_new = slice_hash(raw_u8(by_name[name]), fd_new)
            h_src = slice_hash(raw_u8(st), fds[p])
            assert h_new == h_src, (name, h_new, h_src)
            summary["engram"][name] = {
                "type": by_name[name].tensor_type.name,
                "shape": [int(d) for d in by_name[name].shape],
                "n_bytes": by_name[name].n_bytes,
                "sha256": h_new,
            }
            log(f"  engram {name}: {by_name[name].tensor_type.name} "
                f"shape={[int(d) for d in by_name[name].shape]} bytes={by_name[name].n_bytes} sha256=match")
    finally:
        for fd in list(fds.values()) + [fd_new]:
            os.close(fd)
    return summary


def write_marker(marker, out_path, summary, n, sha256=None):
    if sha256 is None:
        sha256 = file_sha256(out_path)
    data = {
        "shard": n,
        "file": os.path.basename(out_path),
        "size": os.path.getsize(out_path),
        "sha256": sha256,
        "tensor_count": summary["tensor_count"],
        "engram": summary["engram"],
    }
    tmp = marker + ".pending"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, marker)


def repack_shard(n):
    our_path = os.path.join(Q3_DIR, Q3_NAME.format(n))
    out_path = os.path.join(DST_DIR, Q3_NAME.format(n))
    tmp = out_path + ".tmp"
    marker = os.path.join(DST_DIR, "logs", f"done-{n:02d}.json")
    swaps_paths = {name: os.path.join(SRC_DIR, Q8_NAME.format(k)) for name, k in SWAPS[n].items()}

    if os.path.exists(out_path) and os.path.exists(marker):
        m = json.load(open(marker))
        if os.path.getsize(out_path) == m["size"]:
            log(f"shard {n:02d}: verified output already in place (sha {m['sha256'][:16]}...), skipping")
            return "skipped"

    lockf = open(os.path.join(DST_DIR, "." + os.path.basename(out_path) + ".lock"), "w")
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log(f"shard {n:02d}: lock held by another writer, skipping and not touching")
        return "locked"

    if os.path.exists(out_path) and not os.path.exists(marker):
        log(f"shard {n:02d}: final exists without marker, verifying in place")
        summary = verify_shard(out_path, n, swaps_paths)
        write_marker(marker, out_path, summary, n)
        log(f"shard {n:02d}: in-place verification passed, marker written")
        return "verified-existing"

    pause_gate(f"repack-{n:02d}")
    if os.path.exists(tmp):
        log(f"shard {n:02d}: stale {os.path.basename(tmp)} from an earlier run, deleting and redoing")
        os.remove(tmp)

    t0 = time.time()
    log(f"shard {n:02d}: reading headers")
    r_our = GGUFReader(our_path)
    src_readers = {p: GGUFReader(p) for p in sorted(set(swaps_paths.values()))}
    src_by_name = {p: {t.name: t for t in src_readers[p].tensors} for p in src_readers}
    by_name_our = {t.name: t for t in r_our.tensors}

    for name, p in swaps_paths.items():
        assert name in by_name_our, f"{name} not in our shard {n:02d}"
        assert name in src_by_name[p], f"{name} not in {os.path.basename(p)}"
        ot, st = by_name_our[name], src_by_name[p][name]
        log(f"  swap {name}: {ot.tensor_type.name} {[int(d) for d in ot.shape]} {ot.n_bytes} B"
            f"  ->  {st.tensor_type.name} {[int(d) for d in st.shape]} {st.n_bytes} B"
            f"  (from {os.path.basename(p)})")

    fds = {p: os.open(p, os.O_RDONLY) for p in list(src_readers) + [our_path]}

    arch_field = r_our.get_field("general.architecture")
    # Non-first split shards carry no arch key; the writer always adds one,
    # so remove it again to keep the KV block verbatim.
    w = GGUFWriter(tmp, arch=arch_field.contents() if arch_field else "deepseek41",
                   use_temp_file=False, endianess=r_our.endianess)
    if arch_field is None:
        w.remove_key("general.architecture")
    copy_kv(r_our, w)

    plan = []
    for t in r_our.tensors:
        if t.name in swaps_paths:
            p = swaps_paths[t.name]
            st = src_by_name[p][t.name]
            w.add_tensor_info(st.name, st.data.shape, st.data.dtype, st.data.nbytes,
                              raw_dtype=st.tensor_type)
            plan.append((st.name, raw_u8(st), st.n_bytes, p))
        else:
            w.add_tensor_info(t.name, t.data.shape, t.data.dtype, t.data.nbytes,
                              raw_dtype=t.tensor_type)
            plan.append((t.name, raw_u8(t), t.n_bytes, our_path))
    log(f"shard {n:02d}: {len(plan)} tensors registered ({len(swaps_paths)} swapped), writing")
    w.write_header_to_file()
    w.write_kv_data_to_file()
    w.write_ti_data_to_file()
    stream_write_tensors(w, plan, fds)
    w.flush()
    os.fsync(w.fout[0].fileno())
    w.close()
    for fd in fds.values():
        dontneed(fd)
        os.close(fd)

    t1 = time.time()
    size = os.path.getsize(tmp)
    log(f"shard {n:02d}: wrote {size} bytes in {t1 - t0:.0f}s "
        f"(old shard {os.path.getsize(our_path)}, delta {size - os.path.getsize(our_path):+d})")

    log(f"shard {n:02d}: verifying")
    summary = verify_shard(tmp, n, swaps_paths)
    whole = file_sha256(tmp)
    log(f"shard {n:02d}: verification passed in {time.time() - t1:.0f}s, sha256={whole}")

    os.rename(tmp, out_path)
    write_marker(marker, out_path, summary, n, sha256=whole)
    log(f"shard {n:02d}: renamed into place, marker written")
    return "done"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", required=True, help="2, 5, or all")
    args = ap.parse_args()
    shards = [2, 5] if args.shard == "all" else [int(args.shard)]
    for n in shards:
        repack_shard(n)


if __name__ == "__main__":
    main()
