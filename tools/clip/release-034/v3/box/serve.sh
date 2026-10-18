#!/usr/bin/env bash
# The v3 film's server on the box, 127.0.0.1:8797, its pid in pids/http.pid (started once; a live one is kept).
R=/root/clip034-render/v3; cd "$R" || exit 1
mkdir -p pids logs
if [ -s pids/http.pid ] && kill -0 "$(cat pids/http.pid)" 2> /dev/null; then echo "http up: $(cat pids/http.pid)"; exit 0; fi
nohup nice -n 19 ../.venv/bin/python -m http.server 8797 --bind 127.0.0.1 > logs/http.log 2>&1 &
echo $! > pids/http.pid; sleep 1
curl -s -o /dev/null -w "http $(cat pids/http.pid): %{http_code}\n" http://127.0.0.1:8797/film.html
