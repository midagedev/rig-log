#!/usr/bin/env bash
# run.sh: the whole box pass in one detached job: serve, check, full, post. Each step's rc in logs/run.log; stops at
# the first that fails. Start it with nohup and write its $! to pids/run.pid; wait on that pid.
R=/root/clip036-render; cd "$R" || exit 1
mkdir -p logs
log() { echo "$(date -u +%T) $*" >> logs/run.log; }
: > logs/run.log
bash serve.sh >> logs/run.log 2>&1 || { log "serve rc $?"; exit 1; }
bash drive.sh check 16 > logs/drive-check.log 2>&1; r=$?; log "check rc $r"; [ $r -eq 0 ] || exit 1
bash drive.sh full 16 > logs/drive-full.log 2>&1; r=$?; log "full rc $r"; [ $r -eq 0 ] || exit 1
bash post.sh > logs/post.log 2>&1; r=$?; log "post rc $r"; cat logs/post.log >> logs/run.log
exit $r
