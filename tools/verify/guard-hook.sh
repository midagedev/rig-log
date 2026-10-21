#!/bin/sh
# PreToolUse 훅 진입점. 가드는 python3 이 한다.
exec python3 "$(dirname "$0")/guard-hook.py" "$@"
