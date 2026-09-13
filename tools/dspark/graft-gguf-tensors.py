#!/usr/bin/env python
"""Copy a GGUF shard, replacing named tensors with the same-named tensors from another GGUF.

    graft-gguf-tensors.py DST_SHARD DONOR OUT tensor.name [tensor.name ...]

Metadata is copied verbatim (split.* included, so the result drops into the same shard set).
Every tensor not named is copied byte for byte; a named one takes the donor's type, shape and
bytes. No dequantization happens anywhere. The output is written under OUT.tmp, re-read to
check the inventory, then renamed; one flock per output.

Written to give the DSpark draft the bf16 token embedding and output head it was trained
against: the V4.1 draft file carries neither and borrows the target's, which in the Q3_K_M
upload are Q3_K and Q6_K. The uploader's Q8_0 set keeps both in BF16, so they can be grafted
from its last shard into shard 1 of a Q3_K_M variant without touching the 190 GB of experts.
"""
import fcntl, os, sys
sys.path.insert(0, "/home/user/llama.cpp-v41/gguf-py")
from gguf import GGUFReader, GGUFWriter, GGUFValueType

dst_shard, donor_path, out, names = sys.argv[1], sys.argv[2], sys.argv[3], set(sys.argv[4:])
assert names, "name at least one tensor"

lock = open(out + ".lock", "w")
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

reader = GGUFReader(dst_shard)
donor = GGUFReader(donor_path)
donor_by_name = {t.name: t for t in donor.tensors}
missing = names - set(donor_by_name)
assert not missing, f"donor lacks {sorted(missing)}"
present = names & {t.name for t in reader.tensors}
assert present == names, f"shard lacks {sorted(names - present)}"

arch_f = reader.fields["general.architecture"]
arch = str(bytes(arch_f.parts[arch_f.data[0]]), encoding="utf-8")
writer = GGUFWriter(out + ".tmp", arch=arch, endianess=reader.endianess)


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
    writer.add_key_value(field.name, val, val_type, sub_type=sub_type)

plan = []
for t in reader.tensors:
    src = donor_by_name[t.name] if t.name in names else t
    if t.name in names:
        print(f"graft {t.name}: {t.tensor_type.name} {t.n_bytes} B -> {src.tensor_type.name} {src.n_bytes} B", flush=True)
    writer.add_tensor_info(t.name, src.data.shape, src.data.dtype, src.data.nbytes, src.tensor_type)
    plan.append(src)
writer.write_header_to_file()
writer.write_kv_data_to_file()
writer.write_ti_data_to_file()
for i, src in enumerate(plan):
    writer.write_tensor_data(src.data)
    if i % 8 == 0:
        print(f"  wrote {i + 1}/{len(plan)}", flush=True)
writer.close()

check = GGUFReader(out + ".tmp")
got = {t.name: (t.tensor_type, t.n_bytes) for t in check.tensors}
for t in reader.tensors:
    want = donor_by_name[t.name] if t.name in names else t
    assert got[t.name] == (want.tensor_type, want.n_bytes), (t.name, got[t.name], want.tensor_type, want.n_bytes)
assert len(got) == len(reader.tensors)
del check
os.rename(out + ".tmp", out)
print("verified", out, len(got), "tensors", os.path.getsize(out), "bytes", flush=True)
