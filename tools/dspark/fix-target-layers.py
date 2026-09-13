#!/usr/bin/env python
"""Copy the V4.1 DSpark draft GGUF with dflash.target_layers rewritten from [38,39,40] to [37,38,39].

Why: ik_llama.cpp captures the OUTPUT of layer (id-1). DeepSeek V4 collects the target hidden after
the layer runs, so the V4 converter writes config+1 and that is right for V4. DeepSeek V4.1 collects
it BEFORE the layer runs (inference/model.py: "the MTP head reads the attention input of its target
layers, not their output"), i.e. the output of layer id-1 for config ids [37,38,39] -> outputs of
36,37,38 -> ik one-based ids [37,38,39]. The converter inherited the V4 class and wrote [38,39,40]:
off by one.
"""
import sys
sys.path.insert(0, "/home/user/llama.cpp-v41/gguf-py")
from gguf import GGUFReader, GGUFWriter, GGUFValueType

src, dst = sys.argv[1], sys.argv[2]
KEY = "dflash.target_layers"
NEW = [37, 38, 39]
reader = GGUFReader(src)
arch_f = reader.fields["general.architecture"]
arch = str(bytes(arch_f.parts[arch_f.data[0]]), encoding="utf-8")
writer = GGUFWriter(dst, arch=arch, endianess=reader.endianess)


def scalar(field, part):
    if field.types[-1] == GGUFValueType.STRING:
        return bytes(part).decode("utf-8")
    return part.tolist()[0]


for field in reader.fields.values():
    if field.name in ("GGUF.version", "GGUF.tensor_count", "GGUF.kv_count", "general.architecture"):
        continue
    val_type = field.types[0]
    sub_type = field.types[-1] if val_type == GGUFValueType.ARRAY else None
    if field.name == KEY:
        old = [int(field.parts[i][0]) for i in field.data]
        assert old == [38, 39, 40], old
        writer.add_array(KEY, NEW)
        print("rewrote", KEY, old, "->", NEW)
        continue
    if val_type == GGUFValueType.ARRAY:
        val = [scalar(field, field.parts[i]) for i in field.data]
    else:
        val = scalar(field, field.parts[-1])
    writer.add_key_value(field.name, val, val_type, sub_type=sub_type)
for t in reader.tensors:
    writer.add_tensor_info(t.name, t.data.shape, t.data.dtype, t.data.nbytes, t.tensor_type)
writer.write_header_to_file()
writer.write_kv_data_to_file()
writer.write_ti_data_to_file()
for t in reader.tensors:
    writer.write_tensor_data(t.data)
writer.close()
print("done", dst)
