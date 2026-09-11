#!/usr/bin/env bash
# Launch pi against the workstation's local model, for recording.
#
# Tools, skills, extensions, project context and session storage are all off:
# an approval prompt mid-take would stall the recording. The system prompt is
# replaced too — pi's default one describes its tool protocol, and the model
# answers a plain coding question by trying to list the directory instead.
exec pi --provider freetoken --model DeepSeek-V4-Flash-0731 \
  -nt -ns -ne -np -nc --no-session \
  --system-prompt "You are a precise coding assistant. Answer directly with code and a short explanation. You have no tools available; never emit tool calls." \
  "$@"
