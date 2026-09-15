#!/usr/bin/env python3
"""Replace the machine's hostname in a .tape with "workstation" before it is published.

A tape is gzipped JSON; the name appears in summary.server.host and
summary.host.hostname. Everything else is left byte-for-byte.

    tape-sanitize.py <in.tape> <out.tape> [hostname]
"""
import gzip, json, sys

src, dst = sys.argv[1], sys.argv[2]
name = sys.argv[3] if len(sys.argv) > 3 else None
d = json.loads(gzip.open(src, "rt").read())
s = d["summary"]
found = [s["server"].get("host"), s.get("host", {}).get("hostname")]
if name and any(h != name for h in found if h):
    sys.exit(f"hostname in the tape is {found}, not {name}")
s["server"]["host"] = "workstation"
if isinstance(s.get("host"), dict):
    s["host"]["hostname"] = "workstation"
with gzip.open(dst, "wt", compresslevel=9) as f:
    json.dump(d, f, separators=(",", ":"))
print(f"{found} -> workstation  {dst}")
