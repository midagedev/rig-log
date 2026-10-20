#!/usr/bin/env bash
# After drive.sh full: encode (tmix + x264 at CRF 18 + the track), then the pop, sync and flash scans, each logged
# with its rc.
R=/root/clip036-render; cd "$R" || exit 1
for step in encode pops sync flash; do
  CRF=18 nice -n 19 .venv/bin/python render.py $step > "logs/$step.log" 2>&1; r=$?
  echo "$step rc $r"; [ "$step" = encode ] && [ "$r" -ne 0 ] && exit 1
done
ls -l out/
