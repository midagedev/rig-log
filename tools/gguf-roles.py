# GGUF 텐서 인벤토리를 역할별로(순수 파이썬, numpy 없음). 크기는 샤드 안 오프셋 차이로 잰다(타입 표 불필요).
# 사용: python3 tools/gguf-roles.py '/models/<dir>/<name>-0000*-of-0000N.gguf'   (따옴표로 글롭을 넘긴다)
# 2026-09-30: 공개 DeepSeek-V4.1-Flash Q3_K_M의 VRAM 쪽 바이트를 셌다 — log/2026-09-30.md#offload-clip.
import struct, sys, glob, os, re, collections
def rd(f, fmt): return struct.unpack('<' + fmt, f.read(struct.calcsize('<' + fmt)))
def rstr(f): (n,) = rd(f, 'Q'); return f.read(n).decode('utf-8', 'replace')
SZ = {0: 'B', 1: 'b', 2: 'H', 3: 'h', 4: 'I', 5: 'i', 6: 'f', 7: '?', 10: 'Q', 11: 'q', 12: 'd'}
def skipval(f, t):
    if t == 8: rstr(f)
    elif t == 9:
        (et, n) = rd(f, 'IQ')
        if et == 8:
            for _ in range(n): rstr(f)
        else: f.seek(n * struct.calcsize(SZ[et]), 1)
    else: f.seek(struct.calcsize(SZ[t]), 1)
def shard(path):
    with open(path, 'rb') as f:
        assert f.read(4) == b'GGUF'
        (ver, nt, nkv) = rd(f, 'IQQ'); align = 32
        for _ in range(nkv):
            k = rstr(f); (t,) = rd(f, 'I')
            if k == 'general.alignment' and t == 4: (align,) = rd(f, 'I')
            else: skipval(f, t)
        ts = []
        for _ in range(nt):
            name = rstr(f); (nd,) = rd(f, 'I'); dims = rd(f, 'Q' * nd); (typ, off) = rd(f, 'IQ')
            ts.append([name, typ, dims, off])
        start = (f.tell() + align - 1) // align * align
    end = os.path.getsize(path) - start
    ts.sort(key=lambda x: x[3])
    for i, t in enumerate(ts): t.append((ts[i + 1][3] if i + 1 < len(ts) else end) - t[3])
    return ts
def role(n):
    if '_exps' in n: return 'routed experts'
    if 'engram_embd' in n: return 'engram table'
    if 'engram' in n: return 'engram dense'
    if 'shexp' in n: return 'shared expert'
    if 'ffn_gate_inp' in n or 'exp_probs_b' in n: return 'router'
    if 'ffn_norm' in n: return 'ffn_norm'
    if n.startswith('token_embd'): return 'token_embd'
    if n.startswith('output'): return 'head'
    if '.hc_' in n or n.startswith('hc_'): return 'hc'
    return 'attention+other'
tot = collections.Counter(); cnt = collections.Counter(); types = collections.defaultdict(collections.Counter)
per_layer_exps = collections.Counter(); blk_attn = collections.Counter()
for p in sorted(glob.glob(sys.argv[1])):
    for name, typ, dims, off, size in shard(p):
        r = role(name); tot[r] += size; cnt[r] += 1; types[r][typ] += 1
        m = re.match(r'blk\.(\d+)\.', name)
        if m and r == 'routed experts': per_layer_exps[int(m.group(1))] += size
        if m and r == 'attention+other': blk_attn[int(m.group(1))] += size
for r in sorted(tot, key=lambda r: -tot[r]): print(f"{r:18s} {cnt[r]:5d} {tot[r]:16,d}  types {dict(types[r])}")
print('total', f"{sum(tot.values()):,d}")
L = sorted(per_layer_exps); print('layers', len(L), 'exps/layer min/max', min(per_layer_exps.values()), max(per_layer_exps.values()))
print('attn/layer min/max', min(blk_attn.values()), max(blk_attn.values()))
