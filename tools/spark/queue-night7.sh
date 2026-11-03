#!/bin/bash
# The seventh night queue, 2026-11-04: Atlas's nvfp4 recipe rows on Qwen3.6 (rows-atlas.sh atlas-nvfp4-rec / -nomtp),
# which need the avarok/atlas-gb10:dev image. The pull runs first, with no take beside it. Sentinel QUEUE_NIGHT7_DONE.
export HOME=/root
cd /root/health || exit 1
echo "$(date -u +%TZ) pull avarok/atlas-gb10:dev"
docker pull -q avarok/atlas-gb10:dev; echo "$(date -u +%TZ) pull rc=$?"
docker image inspect avarok/atlas-gb10:dev >/dev/null 2>&1 && ./rows-atlas.sh atlas-nvfp4-rec atlas-nvfp4-nomtp
echo QUEUE_NIGHT7_DONE
