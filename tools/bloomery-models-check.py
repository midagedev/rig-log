#!/usr/bin/env python3
"""bloomery-models-check.py — the box's model map keeps every gate input on NVMe.

    tools/bloomery-models-check.py [MAP]      check configs/bloomery/models.tsv (or MAP); rc 0 ok, 1 a row on the HDD
    tools/bloomery-models-check.py --self-test

A row whose path is under /data (the HDD, sda) is refused unless the map names it in a `# hdd-ok KEY: reason` line.
A gate that reads a model from the HDD is not red, it is slow: its engine children page the file at HDD speed and
end at the gate bound (gate-gpu-qwen4exp-iqleg, 2026-11-09: rc 124 after 900 s on the copy under /data/moved). So
the failure this blocks is a timeout read as a hang. Run it before installing the map as /root/bloomery-models.tsv.
"""
import re
import sys
from pathlib import Path

HDD = ("/data/",)
DEFAULT = Path(__file__).resolve().parent.parent / "configs" / "bloomery" / "models.tsv"
ALLOW = re.compile(r"^#\s*hdd-ok\s+(\S+)\s*:\s*(\S.*)$")


def check(text):
    """The problems of one map's text, as lines; empty when every row is on NVMe or allowed."""
    allowed, rows, problems = {}, [], []
    for n, line in enumerate(text.splitlines(), 1):
        m = ALLOW.match(line.strip())
        if m:
            allowed[m.group(1)] = m.group(2)
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 2 or not parts[1].startswith("/"):
            problems.append(f"line {n}: not `key<TAB>absolute path`: {line!r}")
            continue
        rows.append((n, parts[0], parts[1]))
    keys = {k for _, k, _ in rows}
    for n, key, path in rows:
        if path.startswith(HDD) and key not in allowed:
            problems.append(f"line {n}: {key} is on the HDD ({path}); copy it to /models or add `# hdd-ok {key}: <reason>`")
    for key in sorted(set(allowed) - keys):
        problems.append(f"hdd-ok {key}: names no row")
    for key in sorted(k for k in allowed if k in keys and not any(p.startswith(HDD) for _, kk, p in rows if kk == k)):
        problems.append(f"hdd-ok {key}: its row is not on the HDD any more; drop the line")
    return problems


def self_test():
    ok = "a\t/models/a.gguf\nb\t/mirror/b.gguf\n"
    assert check(ok) == [], check(ok)
    hdd = "a\t/data/moved/models/a.gguf\n"
    assert any("a is on the HDD" in p for p in check(hdd)), "an HDD row is refused"
    allowed = "# hdd-ok a: monthly rotation only\na\t/data/moved/models/a.gguf\n"
    assert check(allowed) == [], check(allowed)
    stale = "# hdd-ok a: old\na\t/models/a.gguf\n"
    assert any("not on the HDD any more" in p for p in check(stale)), "a stale allowance is named"
    two = "# hdd-ok a: rotation\n# hdd-ok b: rotation\na\t/data/a.gguf\nb\t/data/b.gguf\nc\t/models/c.gguf\n"
    assert check(two) == [], check(two)
    orphan = "# hdd-ok z: gone\na\t/models/a.gguf\n"
    assert any("names no row" in p for p in check(orphan)), "an allowance with no row is named"
    bad = "a /models/a.gguf\n"
    assert any("not `key<TAB>" in p for p in check(bad)), "a malformed row is named"
    print("bloomery-models-check: self-test ok")
    return 0


def main(argv):
    if argv[1:] == ["--self-test"]:
        return self_test()
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT
    problems = check(path.read_text())
    for p in problems:
        print(f"bloomery-models-check: {p}", file=sys.stderr)
    if not problems:
        print(f"bloomery-models-check: ok ({path})")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
