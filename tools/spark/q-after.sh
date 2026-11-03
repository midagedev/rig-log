#!/bin/bash
# q-after.sh <command...> — wait until no row runner and no take.sh has run at three checks 30 s apart, then run the
# command. Queues a job that needs the machine to itself (an export, a probe set) behind the rows already started.
busy(){ pgrep -f "rows-(vllm-q38|gguf|q36|atlas|strata)\.sh|probes-lag\.sh|flare-prep\.sh|strata-setup\.sh" >/dev/null || pgrep -f "/root/health/take\.sh" >/dev/null; }
idle=0; while [ $idle -lt 3 ]; do sleep 30; if busy; then idle=0; else idle=$((idle+1)); fi; done
exec "$@"
