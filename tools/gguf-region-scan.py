#!/usr/bin/env python3
"""Report tensors whose GGUF region is smaller than their type needs.

Reads only the tensor-info block, so a local path or an http(s) URL both work
and a remote file costs one range request rather than a download.  For a split
model the tensors start in shard 2; shard 1 is metadata only.

  ./gguf-region-scan.py model.gguf
  ./gguf-region-scan.py https://huggingface.co/<repo>/resolve/main/model.gguf
"""
import io, struct, sys, urllib.request

HEAD_BYTES = 6_000_000

# type id -> (name, bytes per block, per-row header bytes).  Block is 256
# elements for every type here; the header is what ggml_row_size() adds on top.
TYPES = {
    137: ("iq2_k",   76, 0), 138: ("iq3_k",  110, 0), 139: ("iq4_k",  144, 0),
    140: ("iq5_k",  176, 0), 141: ("iq6_k",  212, 0),
    144: ("iq4_ks", 136, 4), 145: ("iq2_ks",  70, 2), 146: ("iq4_kss", 128, 4),
    152: ("iq5_ks", 168, 4), 153: ("iq2_kt",  68, 4), 154: ("iq3_kt", 100, 4),
    155: ("iq4_kt", 128, 4), 156: ("iq3_ks", 102, 2), 157: ("iq2_kl",  86, 2),
    158: ("iq1_kt",  56, 4),
}
BLOCK = 256


def head(src):
    if src.startswith(("http://", "https://")):
        req = urllib.request.Request(src, headers={"Range": "bytes=0-%d" % (HEAD_BYTES - 1)})
        return urllib.request.urlopen(req, timeout=120).read()
    with open(src, "rb") as f:
        return f.read(HEAD_BYTES)


def tensors(src):
    f = io.BytesIO(head(src))
    magic, _ver, n_tensors, n_kv = struct.unpack("<IIQQ", f.read(24))
    if magic != 0x46554747:
        raise ValueError("not a GGUF file")
    scalar = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i",
              6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}

    def rd(fmt):
        return struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]

    def rstr():
        return f.read(rd("<Q")).decode("utf-8", "replace")

    def rval(t):
        if t == 8:
            return rstr()
        if t == 9:
            et, n = rd("<I"), rd("<Q")
            return [rval(et) for _ in range(n)]
        return rd(scalar[t])

    for _ in range(n_kv):
        rstr()
        rval(rd("<I"))
    out = []
    for _ in range(n_tensors):
        name = rstr()
        ne = [rd("<Q") for _ in range(rd("<I"))]
        out.append((name, ne, rd("<I"), rd("<Q")))
    return out


def scan(src):
    ts = sorted(tensors(src), key=lambda t: t[3])
    short, ok = {}, {}
    for (name, ne, tp, off), nxt in zip(ts, ts[1:]):
        if tp not in TYPES:
            continue                      # f32/f16/q8_0 and friends: not our concern
        tname, tsize, header = TYPES[tp]
        rows = 1
        for d in ne[1:]:
            rows *= d
        if rows == 0 or ne[0] % BLOCK:
            continue
        reserved = (nxt[3] - off) / rows
        needed = ne[0] // BLOCK * tsize + header
        bucket = short if reserved < needed else ok
        bucket.setdefault(tname, [0, set()])
        bucket[tname][0] += 1
        bucket[tname][1].add((reserved, needed))
    return len(ts), short, ok


for src in sys.argv[1:]:
    print("###", src.rsplit("/", 1)[-1])
    n, short, ok = scan(src)
    print("   %d tensors" % n)
    for name, (count, pairs) in sorted(short.items()):
        print("   SHORT %-8s x%-4d reserved/needed %s" % (name, count, sorted(pairs)))
    for name, (count, _) in sorted(ok.items()):
        print("   ok    %-8s x%d" % (name, count))
    if not short:
        print("   no short regions")
