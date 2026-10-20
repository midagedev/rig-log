#!/usr/bin/env bash
# The 0.3.6 film's server on the box, 127.0.0.1:8799, its pid in pids/http.pid (started once; a live one is kept).
R=/root/clip036-render; cd "$R" || exit 1
mkdir -p pids logs
if [ -s pids/http.pid ] && kill -0 "$(cat pids/http.pid)" 2> /dev/null; then echo "http up: $(cat pids/http.pid)"; exit 0; fi
nohup nice -n 19 .venv/bin/python -m http.server 8799 --bind 127.0.0.1 > logs/http.log 2>&1 < /dev/null &
echo $! > pids/http.pid; sleep 1
curl -s -o /dev/null -w "http $(cat pids/http.pid): %{http_code}\n" http://127.0.0.1:8799/film.html
