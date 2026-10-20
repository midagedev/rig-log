#!/usr/bin/env bash
# The clip036 render env, all of it under /root/clip036-render: copied from /root/clip034-render (read only there): its
# venv on the system python 3.12 (playwright 1.63.0, numpy, fonttools, pillow) and its ms-playwright (chromium 1243 and
# its headless shell). No network. Starts only while the timing lease and every hold are down (rc 75 otherwise); the
# copy runs under nice 19 and ionice idle.
set -euo pipefail
R=/root/clip036-render; S=/root/clip034-render
mkdir -p "$R"/pids "$R"/logs "$R"/music
cd "$R"
. ./lease-probe.sh
if ! lease_free || [ -n "$(lease_holds_up)" ]; then echo "setup: the lease or a hold is up; not copying"; exit 75; fi
for d in .venv ms-playwright; do
  [ -e "$R/$d" ] && { echo "$d: there"; continue; }
  rm -rf "$R/$d.part"; nice -n 19 ionice -c 3 cp -a "$S/$d" "$R/$d.part" && mv "$R/$d.part" "$R/$d"; echo "$d: copied"
done
.venv/bin/python -c 'import playwright, numpy, fontTools, PIL; print("venv ok")'
ls ms-playwright
