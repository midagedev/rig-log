#!/bin/bash
# Strata rows of the DGX Spark comparison, 2026-11-03: the server Strata's setup wrote for a model (strata-setup.sh),
# started the way its run script starts it (serve/server.py --engine strata --config <run config>), only on our port
# and without --open. The run config keeps what setup chose for the model on this machine (11-03, Qwen3.6 UD-Q4_K_XL:
# --native <gguf> --max-context 65536 --prefill auto --mtp 2), so this is the default row and the recommended row at once.
#   strata-nomtp   the same config with --mtp <draft> taken out of its args (a copy beside the take; the original stays)
# usage: rows-strata.sh <tag prefix> <run script, e.g. <checkout>/run-qwen36-ud-q4_k_xl.sh> [row ...]   rows: strata-default strata-nomtp
set -u
PFX=${1:?tag prefix}; RUN=${2:?run script}; shift 2; P=18736
cmd=$(sed -n 's/^exec //p' "$RUN" | sed 's/"--port" "[0-9]*"/"--port" "'$P'"/; s/ "--open"//')
dir=$(sed -n 's/^cd "\(.*\)"$/\1/p' "$RUN")
cfg=$(echo "$cmd" | grep -o '"--config" "[^"]*"' | cut -d'"' -f4)
[ -n "$cmd" ] && [ -n "$dir" ] && [ -f "$cfg" ] || { echo "cannot read $RUN"; exit 1; }
ver=$(git -C "$dir" describe --tags 2>/dev/null || echo "?")
for row in "${@:-strata-default strata-nomtp}"; do
  case $row in
    strata-default) S="cd \"$dir\" && $cmd";;
    strata-nomtp)
      c2=/root/takes/.strata-nomtp-$(basename "$cfg")
      python3 - "$cfg" "$c2" <<'PY' || exit 1
import json, sys
c = json.load(open(sys.argv[1])); a = c["args"]
if "--mtp" in a: i = a.index("--mtp"); del a[i:i + 2]
a[:] = [x for j, x in enumerate(a) if not (x.startswith("--mtp-") or (j and a[j - 1].startswith("--mtp-")))]
json.dump(c, open(sys.argv[2], "w"), indent=1)
PY
      S="cd \"$dir\" && ${cmd/\"$cfg\"/\"$c2\"}";;
    *) echo "unknown row $row"; continue;;
  esac
  SERVE="$S" PORT=$P ENGINE="Strata $ver" /root/health/take.sh "$PFX-$row"
done
