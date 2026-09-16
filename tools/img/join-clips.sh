#!/bin/bash
# join-clips.sh -o out.mp4 [--xfade N] <clip.mp4>... — cut a shot list into one film.
#
# Why this exists rather than a one-liner: LTX-2.5 generates video **and audio** in one pass,
# so every clip arrives with its own soundtrack. A plain concat therefore joins two things,
# and the audio is the one that misbehaves — each clip's music starts and stops, so a hard
# join clicks and the score restarts at every cut. Video wants the hard cut (that is what a
# cut is, and an action sequence is built from them); audio wants a short crossfade.
#
#   join-clips.sh -o duel.mp4 shot1/out.mp4 shot2/out.mp4 shot3/out.mp4 shot4/out.mp4
#   join-clips.sh -o duel.mp4 --xfade 0 <clips>      # hard cut on the audio too
#
# The reason a shot list exists at all is measured: asked for five beats in one clip, LTX
# rendered two and spent the rest of the frames on aftermath, because it was trained on
# captions of single coherent scenes under five seconds. Four clips of one beat each do not
# fight that. The cut carries what the model will not.
#
# Streams are re-encoded rather than concat-demuxed. Every clip here comes from the same
# pipeline at the same geometry, so a stream copy would usually work -- but "usually" fails
# silently into a file that plays for one shot and then stalls, and a 20-second render is not
# worth protecting with a gamble.
set -u
OUT=""; XFADE=0.25
CLIPS=()
while [ $# -gt 0 ]; do
  case "$1" in
    -o|--out) OUT=$2; shift 2 ;;
    --xfade)  XFADE=$2; shift 2 ;;
    -*) echo "join-clips.sh: unknown option $1" >&2; exit 64 ;;
    *)  CLIPS+=("$1"); shift ;;
  esac
done
[ -n "$OUT" ] || { echo "usage: join-clips.sh -o out.mp4 [--xfade SECONDS] <clip.mp4>..." >&2; exit 64; }
[ ${#CLIPS[@]} -ge 2 ] || { echo "join-clips.sh: need at least two clips" >&2; exit 64; }
for c in "${CLIPS[@]}"; do
  [ -f "$c" ] || { echo "join-clips.sh: no clip at $c" >&2; exit 1; }
done

# Report what is going in, because a shot in the wrong order is the mistake this makes easy
# and the mistake nothing downstream can catch.
echo "joining ${#CLIPS[@]} clips, audio crossfade ${XFADE}s:"
total=0
for i in "${!CLIPS[@]}"; do
  d=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "${CLIPS[$i]}")
  wh=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0:s=x "${CLIPS[$i]}")
  a=$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "${CLIPS[$i]}")
  printf "  %d. %-58s %6.2f s  %s  audio=%s\n" $((i+1)) "${CLIPS[$i]}" "$d" "$wh" "${a:-none}"
  total=$(python3 -c "print($total + $d)")
done

IN=(); for c in "${CLIPS[@]}"; do IN+=(-i "$c"); done
N=${#CLIPS[@]}

if [ "$(python3 -c "print(1 if float('$XFADE') > 0 else 0)")" = 1 ]; then
  # acrossfade takes two inputs at a time, so the audio chain is folded left to right; video
  # is a straight concat so the picture still cuts hard on the frame.
  V=""; for i in $(seq 0 $((N-1))); do V+="[$i:v]"; done
  F="${V}concat=n=$N:v=1:a=0[v]"
  prev="[0:a]"
  for i in $(seq 1 $((N-1))); do
    lbl="[a$i]"; [ "$i" -eq $((N-1)) ] && lbl="[a]"
    F+=";${prev}[$i:a]acrossfade=d=$XFADE:c1=tri:c2=tri$lbl"
    prev="$lbl"
  done
else
  V=""; for i in $(seq 0 $((N-1))); do V+="[$i:v][$i:a]"; done
  F="${V}concat=n=$N:v=1:a=1[v][a]"
fi

ffmpeg -hide_banner -v error -y "${IN[@]}" -filter_complex "$F" \
  -map "[v]" -map "[a]" -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -movflags +faststart "$OUT" || { echo "ffmpeg failed" >&2; exit 1; }

D=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT")
# a crossfade shortens the result by (N-1)*xfade; printing both is how a missing shot shows up
printf "%s  %.2f s from %.2f s of input (%d crossfades of %ss)  %s bytes\n" \
  "$OUT" "$D" "$total" $((N-1)) "$XFADE" "$(stat -f%z "$OUT" 2>/dev/null || stat -c%s "$OUT")"
