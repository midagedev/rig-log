#!/usr/bin/env python3
"""Proves repack.py's writer path before it touches 104 GB files.

Part 1 writes the same synthetic GGUF twice, once through GGUFWriter's own
write_tensor_data and once through repack.stream_write_tensors, and
byte-compares the two files; then re-reads fields and tensors.
Part 2 copies the real shard-02 KV block verbatim plus one small real tensor
and compares the re-read KV signature and tensor bytes."""
import hashlib
import os
import sys

import numpy as np
from gguf import GGUFReader, GGUFWriter, GGMLQuantizationType

sys.path.insert(0, "/models/DeepSeek-V4.1-Flash-Q3_K_M-engramQ8")
from repack import (copy_kv, stream_write_tensors, raw_u8, kv_signature,
                    Q3_DIR, Q3_NAME)

TDIR = "/models/DeepSeek-V4.1-Flash-Q8_0-engram-src/test"
os.makedirs(TDIR, exist_ok=True)

rng = np.random.default_rng(7)
f32 = rng.standard_normal((7, 3)).astype(np.float32)   # asymmetric 2-D
q8 = rng.integers(0, 256, 68).astype(np.uint8)         # Q8_0 raw bytes
bf = rng.integers(0, 65536, 6).astype(np.uint16)       # BF16 raw bytes
tensors = [("t.f32", f32, GGMLQuantizationType.F32),
           ("t.q8", q8, GGMLQuantizationType.Q8_0),
           ("t.bf16", bf, GGMLQuantizationType.BF16)]


def add_kvs(w):
    w.add_uint32("test.u32", 1046)
    w.add_string("test.str", "no arch key on split shards")
    w.add_array("test.arr_str", ["a", "bb", "ccc"])
    w.add_array("test.arr_u32", [1, 2, 3, 4, 5])
    w.add_float32("test.f32", 1.5)
    w.add_bool("test.b", True)
    w.remove_key("general.architecture")


def add_infos(w):
    for name, arr, dt in tensors:
        w.add_tensor_info(name, arr.shape, arr.dtype, arr.nbytes, raw_dtype=dt)


a = os.path.join(TDIR, "lib.gguf")
w = GGUFWriter(a, arch="deepseek41", use_temp_file=False)
add_kvs(w); add_infos(w)
w.write_header_to_file(); w.write_kv_data_to_file(); w.write_ti_data_to_file()
for name, arr, dt in tensors:
    w.write_tensor_data(arr)
w.flush(); w.close()

b = os.path.join(TDIR, "stream.gguf")
w = GGUFWriter(b, arch="deepseek41", use_temp_file=False)
add_kvs(w); add_infos(w)
w.write_header_to_file(); w.write_kv_data_to_file(); w.write_ti_data_to_file()
plan = [(name, (arr.reshape(-1) if arr.dtype == np.uint8 else arr.reshape(-1).view(np.uint8)),
         arr.nbytes, None) for name, arr, dt in tensors]
stream_write_tensors(w, plan, fadvise_fds=None)
w.flush(); w.close()

da, db = open(a, "rb").read(), open(b, "rb").read()
assert da == db, f"stream path differs from library path: {len(da)} vs {len(db)} bytes"
print(f"part1: stream path byte-identical to write_tensor_data ({len(da)} bytes)")

r = GGUFReader(b)
assert "general.architecture" not in r.fields
kv = {name: fld.contents() for name, fld in r.fields.items() if not name.startswith("GGUF.")}
assert kv == {"test.u32": 1046, "test.str": "no arch key on split shards",
              "test.arr_str": ["a", "bb", "ccc"], "test.arr_u32": [1, 2, 3, 4, 5],
              "test.f32": 1.5, "test.b": True}, kv
got = {t.name: t for t in r.tensors}
assert got["t.f32"].tensor_type == GGMLQuantizationType.F32
# reader .shape is file dim order = reversed(numpy arg); data comes back
# in numpy order. Writer+reader reverse once each, so data round-trips.
assert [int(d) for d in got["t.f32"].shape] == [3, 7], got["t.f32"].shape
assert np.array_equal(got["t.f32"].data, f32)
assert got["t.q8"].tensor_type == GGMLQuantizationType.Q8_0 and got["t.q8"].n_bytes == 68
assert [int(d) for d in got["t.q8"].shape] == [64], got["t.q8"].shape
assert bytes(got["t.q8"].data) == bytes(q8)
assert got["t.bf16"].tensor_type == GGMLQuantizationType.BF16
assert [int(d) for d in got["t.bf16"].shape] == [6]
assert bytes(got["t.bf16"].data) == bytes(bf)
print("part1: KVs and tensors re-read correctly (asymmetric [7,3], raw Q8_0, raw BF16)")

src = os.path.join(Q3_DIR, Q3_NAME.format(2))
rs = GGUFReader(src)
out = os.path.join(TDIR, "kv.gguf")
w = GGUFWriter(out, arch="deepseek41", use_temp_file=False)
w.remove_key("general.architecture")
copy_kv(rs, w)
t = next(x for x in rs.tensors if x.name == "blk.1.engram_k.weight")
w.add_tensor_info(t.name, t.data.shape, t.data.dtype, t.data.nbytes, raw_dtype=t.tensor_type)
w.write_header_to_file(); w.write_kv_data_to_file(); w.write_ti_data_to_file()
stream_write_tensors(w, [(t.name, raw_u8(t), t.n_bytes, None)], fadvise_fds=None)
w.flush(); w.close()

ro = GGUFReader(out)
assert "general.architecture" not in ro.fields
assert kv_signature(ro) == kv_signature(rs), "real KV block not copied verbatim"
to = next(x for x in ro.tensors if x.name == t.name)
assert to.tensor_type == t.tensor_type and to.n_bytes == t.n_bytes
assert hashlib.sha256(raw_u8(to)).hexdigest() == hashlib.sha256(raw_u8(t)).hexdigest()
print("part2: real shard-02 KV block verbatim + tensor bytes identical")
print("TESTS PASS")
