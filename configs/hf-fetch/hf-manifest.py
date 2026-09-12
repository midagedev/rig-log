#!/usr/bin/env python3
"""Write a MANIFEST of every file in a HuggingFace repo: sha256, size, path.

The point is the sha256. A download that finishes is not a download that is
correct, and on this machine the difference was 89 GB of interleaved garbage
that had exactly the right file size. HF stores the sha256 of every LFS file
as its object id; paths-info hands it over without downloading anything.

usage: hf-manifest.py <user>/<repo> <destination-dir>
"""
import json, os, sys, urllib.request

API = "https://huggingface.co/api/models/%s"

def get(url, data=None):
    req = urllib.request.Request(url, data=data,
          headers={"Content-Type": "application/json"} if data else {})
    tok = os.environ.get("HF_TOKEN")
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def main():
    repo, dest = sys.argv[1], sys.argv[2]
    info = get(API % repo)
    if info.get("gated"):
        sys.exit("%s is gated; set HF_TOKEN and accept the terms first" % repo)
    paths = [s["rfilename"] for s in info["siblings"]]

    rows, CHUNK = [], 100          # paths-info caps the batch
    for i in range(0, len(paths), CHUNK):
        body = json.dumps({"paths": paths[i:i+CHUNK]}).encode()
        for f in get((API % repo) + "/paths-info/main", body):
            if f.get("type") != "file":
                continue
            lfs = f.get("lfs") or {}
            rows.append((lfs.get("oid", "-"), f.get("size", 0), f["path"]))

    rows.sort(key=lambda r: r[2])
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "MANIFEST"), "w") as out:
        out.write("# %s\n" % repo)
        for oid, size, path in rows:
            out.write("%s %d %s\n" % (oid, size, path))
    # sha256sum -c reads this directly; non-LFS files have no published hash.
    with open(os.path.join(dest, "SHA256SUMS"), "w") as out:
        for oid, size, path in rows:
            if oid != "-":
                out.write("%s  %s\n" % (oid, path))

    hashed = sum(1 for r in rows if r[0] != "-")
    print("%d files, %.1f GB, %d with a published sha256"
          % (len(rows), sum(r[1] for r in rows)/1e9, hashed))
    print("wrote %s/MANIFEST and %s/SHA256SUMS" % (dest, dest))

main()
