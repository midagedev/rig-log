#!/bin/bash
# kaiju4-chain.sh — orange cat, jaeger, catalogue-style sheet; gate on panel count; two IC-LoRA arms (ref strength 1.0 / 0.75)
set -u
until grep -qE "V41_3090_(DONE|FAILED)" /home/user/v41-3090-t1911.log 2>/dev/null; do sleep 15; done
until [ ! -f /home/user/gpu-lease ]; do sleep 5; done
MODEL=/models/Krea-2-Turbo PROMPT="$(cat /home/user/prompt-sheet-kaiju4.txt)" COUNT=4 SEED=23 WH="1536 896" bash /home/user/img-take.sh sheet-kaiju4 2>&1 | grep -E "refused|rc=|image|IMG_"
[ "$(ls /home/user/img-runs/sheet-kaiju4/k0*-*.png 2>/dev/null | wc -l)" -ge 4 ] || { echo "SHEET_FAILED"; exit 1; }
cd /home/user/imggen && /usr/local/bin/uv run python /home/user/contact-sheet.py /home/user/img-runs/sheet-kaiju4 -o /home/user/img-runs/sheet-kaiju4/contact.jpg | head -1
PICK=""
for f in /home/user/img-runs/sheet-kaiju4/k0*-*.png; do
  if /usr/local/bin/uv run python /home/user/ref-sheet-gate.py "$f" 2; then [ -z "$PICK" ] && PICK=$f; fi
done
echo "GATE_PICK ${PICK:-none}"
[ -n "$PICK" ] || { echo "GATE_FAILED all four sheets read as split screens"; exit 1; }
K=$(basename "$PICK" | cut -d- -f1)
ffmpeg -v error -y -loop 1 -framerate 24 -i "$PICK" -frames:v 121 -vf "scale=1536:896:flags=lanczos,format=yuv420p" -c:v libx264 -crf 12 -pix_fmt yuv420p /home/user/ref-sheet-kaiju4-$K.mp4
for S in 1.0 0.75; do
  until [ ! -f /home/user/gpu-lease ]; do sleep 5; done
  TAG=ingr-kaiju4-$K-s${S/./}
  PIPE=ic_lora WH="1536 896" FRAMES=121 SEED=23 OFFLOAD=disk \
    LORAS="/models/LTX-2.5/loras/ltx-2.5-22b-ic-lora-ingredients-0.9.safetensors 1.0" \
    VIDCOND="/home/user/ref-sheet-kaiju4-$K.mp4 $S" PROMPT="$(cat /home/user/prompt-ingr-kaiju4.txt)" \
    bash /home/user/ltx-take.sh $TAG 2>&1 | tee /home/user/ltx-runs/$TAG.take.log | grep -E "refused|rc=|output|LTX_|Error"
  grep -q LTX_DONE /home/user/ltx-runs/$TAG.take.log || exit 1
done
echo "CHAIN_DONE $K"
