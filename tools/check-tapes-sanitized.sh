#!/bin/bash
# Fail if any tape or card under assets/ still names the machine. Run before committing a tape.
# The tape is gzipped JSON; the name sits in summary.server.host and summary.host.hostname
# and tools/tape-sanitize.py rewrites both to "workstation". Measured 2026-09-17: a tape copied
# straight from the box went into a commit with the real name and a peer session caught it.
set -u
cd "$(dirname "$0")/.." || exit 2
NAME=${1:-ws}
rc=0
for t in assets/*.tape; do
  hit=$(python3 -c '
import gzip, json, sys
s = json.load(gzip.open(sys.argv[1]))["summary"]
print(s["server"].get("host"), s.get("host", {}).get("hostname"))' "$t")
  case " $hit " in *" $NAME "*) echo "UNSANITIZED $t: $hit"; rc=1;; esac
done
if grep -l -- "· $NAME\$\|· $NAME \|^│ *$NAME *│" assets/*.card.txt 2>/dev/null; then echo "card text names the machine"; rc=1; fi
[ $rc -eq 0 ] && echo "tapes and cards clean ($(ls assets/*.tape | wc -l | tr -d ' ') tapes)"
exit $rc
