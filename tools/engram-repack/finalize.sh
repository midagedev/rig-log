#!/bin/bash
# Completes the engramQ8 dir: hardlink the untouched shards, assemble
# SHA256SUMS (hardlinks reuse the source dir's verified sums), verify all 9.
set -euo pipefail
Q=/models/DeepSeek-V4.1-Flash-Q3_K_M
D=/models/DeepSeek-V4.1-Flash-Q3_K_M-engramQ8
cd "$D"
while [ -e /tmp/rig-quiet ]; do echo "$(date -Is) PAUSEWAIT finalize"; sleep 60; done

for i in 01 03 04 06 07 08 09; do
  f=DeepSeek-V4.1-Flash-Q3_K_M-000$i-of-00009.gguf
  if [ ! -e "$f" ]; then ln "$Q/$f" "$f"; echo "hardlinked $f"; fi
done

~/.venv-gguf/bin/python - <<'PY'
import json, os
D = "/models/DeepSeek-V4.1-Flash-Q3_K_M-engramQ8"
Q = "/models/DeepSeek-V4.1-Flash-Q3_K_M"
lines = []
for i in ("01", "03", "04", "06", "07", "08", "09"):
    name = f"DeepSeek-V4.1-Flash-Q3_K_M-000{i}-of-00009.gguf"
    for line in open(os.path.join(Q, "SHA256SUMS")):
        if line.split()[1] == name:
            lines.append(line.strip())
            break
    else:
        raise SystemExit(f"{name} missing from source SHA256SUMS")
for i in (2, 5):
    m = json.load(open(os.path.join(D, "logs", f"done-{i:02d}.json")))
    lines.append(f"{m['sha256']}  {m['file']}")
open(os.path.join(D, "SHA256SUMS"), "w").write("\n".join(lines) + "\n")
print(f"wrote SHA256SUMS with {len(lines)} entries")
PY

nice -n 19 ionice -c3 sha256sum -c SHA256SUMS 2>&1 | tee logs/final-verify.log
echo "=== $(date -Is) finalize: dir complete and verified"
