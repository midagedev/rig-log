#!/usr/bin/env python
"""Copy a GGUF, overriding or adding metadata keys; tensors are copied byte for byte.

    set-gguf-keys.py SRC DST key=JSON [key=JSON ...]

JSON picks the type: true/false -> bool, [ints] -> int array, int -> uint32, float -> float32,
"str" -> string. An existing key is replaced in place; a missing key is appended.

Written for the V4.1 DSpark draft, whose converted file carries no `dflash.attention.causal`, so
ik_llama.cpp falls back to causal_attn = true and masks the 5-token proposal block causally. The
reference (inference/model.py, get_dspark_topk_idxs) lets every block position see the whole block.
"""
import json, sys
sys.path.insert(0, "/home/user/llama.cpp-v41/gguf-py")
from gguf import GGUFReader, GGUFWriter, GGUFValueType

src, dst, pairs = sys.argv[1], sys.argv[2], sys.argv[3:]
overrides = {}
for p in pairs:
    k, v = p.split("=", 1)
    overrides[k] = json.loads(v)

reader = GGUFReader(src)
arch_f = reader.fields["general.architecture"]
arch = str(bytes(arch_f.parts[arch_f.data[0]]), encoding="utf-8")
writer = GGUFWriter(dst, arch=arch, endianess=reader.endianess)


def put(key, val):
    if isinstance(val, bool):
        writer.add_bool(key, val)
    elif isinstance(val, list):
        writer.add_array(key, val)
    elif isinstance(val, int):
        writer.add_uint32(key, val)
    elif isinstance(val, float):
        writer.add_float32(key, val)
    else:
        writer.add_string(key, val)


def scalar(field, part):
    if field.types[-1] == GGUFValueType.STRING:
        return bytes(part).decode("utf-8")
    return part.tolist()[0]


for field in reader.fields.values():
    if field.name in ("GGUF.version", "GGUF.tensor_count", "GGUF.kv_count", "general.architecture"):
        continue
    val_type = field.types[0]
    sub_type = field.types[-1] if val_type == GGUFValueType.ARRAY else None
    if val_type == GGUFValueType.ARRAY:
        val = [scalar(field, field.parts[i]) for i in field.data]
    else:
        val = scalar(field, field.parts[-1])
    if field.name in overrides:
        new = overrides.pop(field.name)
        print("replaced", field.name, (val if not isinstance(val, list) or len(val) < 8 else "[...]"), "->", new)
        put(field.name, new)
        continue
    writer.add_key_value(field.name, val, val_type, sub_type=sub_type)
for k, v in overrides.items():
    print("added", k, "=", v)
    put(k, v)
for t in reader.tensors:
    writer.add_tensor_info(t.name, t.data.shape, t.data.dtype, t.data.nbytes, t.tensor_type)
writer.write_header_to_file()
writer.write_kv_data_to_file()
writer.write_ti_data_to_file()
for t in reader.tensors:
    writer.write_tensor_data(t.data)
writer.close()
print("done", dst)
