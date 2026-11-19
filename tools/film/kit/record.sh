#!/usr/bin/env bash
# record.sh BIN OUT [MODELS]: the film's "same task, two models" scene, recorded on the box (run as root, inside the
# lead's sitting window; one model on the card at a time). For each model (default "hy4 v41", in that order):
#   1. the card holds no compute process (else rc 75, naming it: one model at a time, and ComfyUI is the user's);
#   2. BIN (the shipped 0.3.15 tarball's bloomery-serve) starts with the model and its --mmproj at --ctx-size $CTX; the
#      kit waits for its `ready` event (stdout) and reads the served ctx from it;
#   3. a logging proxy (logproxy.mjs --effort-none) sits between dsh and the server: every request and answer is kept,
#      and a request with no top-level reasoning_effort gets "none" (thinking off, the same setting for both models);
#   4. a smoke task in the fence ("Create hello.txt containing the word hi, then read it back."): hello.txt must hold
#      hi and no answer may carry reasoning (thinking off), else rc 78 names what failed before the real task runs;
#   5. the task (prompt.txt) in the fence, capped at $TASK_CAP s: dsh headless as `user` under systemd-run with
#      NoNewPrivileges, /home and /root hidden (ProtectHome=tmpfs: no llama.cpp or any other engine of user's), /models
#      and /data/moved inaccessible, the system read only, network loopback only, CPUs $AGENT_CPUS at $AGENT_QUOTA,
#      memory $AGENT_MEM; a sampler records the fence's processes and the card's compute processes every 5 s;
#   6. the server and the proxy stop (their captured pids), the post-run checks run (the fence's process list holds no
#      engine or server; the card held only our server; `ps -u user` shows no process the run left), and the page is
#      captured in the same fence: page.png at t = 1 s and a 48-frame loop at 24 fps (shot.mjs, 1280x720, no network).
# Then summarize.mjs writes OUT/film.json, the file the film reads (promo0315v2: DSH_JSON=OUT/film.json ./refacts.sh;
# copy OUT to the Mac whole: film.json names its pages and frames relative to it).
#   BIN    the release tarball's bin/bloomery-serve        OUT  a new directory (refused if it exists); not under /tmp
#   MODELS hy4 | v41 | "hy4 v41" (default)
# Knobs (env): CTX=131072 (both models), TASK_CAP=2400 (s, a model's task), LOAD_CAP=1200 (s, a load), PORT=18081,
#   PPORT=18091 (the proxy), AGENT_CPUS=56-63 (on the box the SMT siblings of cores 24-31: pick CPUs the server's host
#   pool leaves alone if its plan pins those), AGENT_QUOTA=400%, AGENT_MEM=24G, NET=loopback|open (the fence's network),
#   NODE=/home/user/.local/bin/node (resolved; the fence binds its prefix only), DSH_JS (dsh's bin.js), PW
#   (playwright-core's dir, 1.62.1 on the box), PWB (its browsers).
# Predicted wall: per model a load (Hy4-flash 3.3 s warm in the 0.3.15 sitting's log; V4.1 bq3km up to a few minutes
# cold), the smoke (~1-4 min: Hy4-flash's prompt pass runs on the host CPU, 31.75 tok/s at P = 512 in the sitting), the
# task, the capture (~1 min). The task: T = (P0 + sum of each request's uncached tokens) / prompt rate + tokens out /
# decode rate. With P0 ~5-8k (dsh's system prompt and tools), ~15 requests of ~1-2k new tokens, ~12k out: Hy4-flash
# (31.75 / 31.71 tok/s) ~15-35 min, V4.1 (245.87 / 30.24) ~6-12 min; both models with loads ~25-55 min. The kit prints
# this prediction from the smoke's own first request before each task. Waits are on captured pids only.
# Exit: 0 film.json written; 64 usage; 65 summarize refused a run; 70 a server died or never got ready; 75 the card is
# busy; 78 the smoke failed (profile, fence or thinking-off).
set -euo pipefail
KIT=$(cd "$(dirname "$0")" && pwd)
BIN=${1:?usage: record.sh BIN OUT [MODELS]}; OUT=${2:?usage: record.sh BIN OUT [MODELS]}; MODELS=${3:-hy4 v41}
CTX=${CTX:-131072} TASK_CAP=${TASK_CAP:-2400} LOAD_CAP=${LOAD_CAP:-1200} PORT=${PORT:-18081} PPORT=${PPORT:-18091}
AGENT_CPUS=${AGENT_CPUS:-56-63} AGENT_QUOTA=${AGENT_QUOTA:-400%} AGENT_MEM=${AGENT_MEM:-24G} NET=${NET:-loopback}
NODE=$(readlink -f "${NODE:-/home/user/.local/bin/node}") DSH_JS=${DSH_JS:-/home/user/clipdsh/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js}
NODE_PREFIX=$(dirname "$(dirname "$NODE")") # the fence sees node's own prefix, not user's ~/.local/bin (it holds mistralrs)
PW=${PW:-/home/user/clipdsh/pw} PWB=${PWB:-/home/user/.cache/ms-playwright}
LOOP_FPS=24 LOOP_N=${LOOP_N:-120}
[ "$(id -u)" = 0 ] || { echo "record.sh: run as root (systemd-run's fence and the card)" >&2; exit 64; }
[ -x "$BIN" ] || { echo "record.sh: $BIN is not an executable" >&2; exit 64; }
case $OUT in /tmp/*|/var/tmp/*) echo "record.sh: OUT under /tmp or /var/tmp is hidden from the fence (PrivateTmp)" >&2; exit 64 ;; esac
[ -e "$OUT" ] && { echo "record.sh: $OUT exists; give a new directory" >&2; exit 64; }
for f in "$NODE" "$DSH_JS" "$PW/node_modules/playwright-core/package.json" "$KIT/prompt.txt" "$KIT/profile.yml.tmpl"; do
  [ -e "$f" ] || { echo "record.sh: $f is missing" >&2; exit 64; }
done
model() { # id -> NAME FILE MMPROJ MID
  case $1 in
    hy4) NAME=Hy4-flash FILE=/models/Hy4-flash-GGUF/Hy4-flash-Q4_K_M-00001-of-00002.gguf
         MMPROJ=/models/mmproj/AngelSlim--Hy4-flash-GGUF/mmproj-Hy4-flash-bf16.gguf MID=hy4-flash ;;
    v41) NAME=DeepSeek-V4.1-Flash FILE=/models/DeepSeek-V4.1-Flash-1017-bq3km/DeepSeek-V4.1-Flash-1017-bq3km-00001-of-00009.gguf
         MMPROJ=/models/DeepSeek-V4.1-Flash-fp8/mmproj/mmproj-DeepSeek-V4.1-Flash-BF16.gguf MID=deepseek-v4.1-flash ;;
    *) echo "record.sh: unknown model '$1' (hy4, v41)" >&2; exit 64 ;;
  esac
}
for m in $MODELS; do model "$m"; [ -f "$FILE" ] && [ -f "$MMPROJ" ] || { echo "record.sh: $m's files are missing ($FILE, $MMPROJ)" >&2; exit 64; }; done

mkdir -p "$OUT"; chown user:user "$OUT"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$OUT/record.log"; }
DSH_VER=$(sudo -u user "$NODE" "$DSH_JS" --version 2>/dev/null | head -1 || true)
BIN_SHA=$(sha256sum "$BIN" | cut -c1-16)
BIN_VER=$("$BIN" --version 2>/dev/null | head -1 || true)
CARD=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | head -1)
HOST="$(lscpu | sed -n 's/^Model name: *//p' | head -1), $(free -g | awk '/^Mem:/{print $2}') GiB RAM"
python3 - "$OUT/meta.json" "$KIT/prompt.txt" "$MODELS" "$DSH_VER" "$BIN" "$BIN_SHA" "$BIN_VER" "$CARD" "$HOST" "$CTX" "$AGENT_CPUS" "$AGENT_QUOTA" "$AGENT_MEM" "$NET" "$TASK_CAP" "$LOOP_FPS" "$LOOP_N" <<'PY'
import json, sys, time
(out, prompt, models, dsh, binp, sha, ver, card, host, ctx, cpus, quota, mem, net, cap, fps, n) = sys.argv[1:]
json.dump({'recorded': time.strftime('%Y-%m-%d %H:%M:%S %z'), 'prompt': open(prompt).read().strip(), 'models': models.split(),
           'dsh_version': dsh, 'bloomery': {'bin': binp, 'sha256_16': sha, 'version': ver}, 'card': card, 'host': host,
           'settings': {'ctx_size': int(ctx), 'thinking': 'off (enable_thinking=false; reasoning_effort "none" added by the proxy)',
                        'agent_cpus': cpus, 'agent_quota': quota, 'agent_mem': mem, 'net': net, 'task_cap_s': int(cap)},
           'loop': {'fps': int(fps), 'n': int(n)}}, open(out, 'w'), indent=1)
PY
log "kit $KIT; bin $BIN ($BIN_SHA, $BIN_VER); dsh $DSH_VER; card $CARD; models $MODELS"

# fence UNIT RUNDIR WORKDIR CAP NAME -- CMD...: CMD as `user` in the fence; its exit code lands in RUNDIR/NAME.rc (absent
# when the cap or a kill ended it), its output in RUNDIR/NAME.out / .err; the sampler writes RUNDIR/NAME.seen / .gpu.
fence() {
  local unit=$1 r=$2 w=$3 cap=$4 name=$5; shift 6
  local net=(-p IPAddressDeny=any -p IPAddressAllow=localhost)
  [ "$NET" = open ] && net=()
  ( for _ in $(seq 1 120); do systemctl is-active --quiet "$unit" && break; sleep 0.5; done
    while systemctl is-active --quiet "$unit"; do
      cg=$(systemctl show -p ControlGroup --value "$unit" 2> /dev/null || true)
      if [ -n "$cg" ] && [ -d "/sys/fs/cgroup$cg" ]; then
        pids=$(find "/sys/fs/cgroup$cg" -name cgroup.procs -exec cat {} + 2> /dev/null | sort -u | paste -sd, -)
        [ -n "$pids" ] && ps -o comm=,args= -p "$pids" 2> /dev/null | cut -c1-200 >> "$r/$name.seen"
      fi
      nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader >> "$r/$name.gpu" 2> /dev/null || true
      sleep 5
    done ) &
  local sp=$!
  systemd-run --quiet --wait --collect --unit "$unit" \
    -p User=user -p Group=user -p WorkingDirectory="$w" \
    -p Environment="HOME=$r/home" -p Environment="PATH=$KIT/bin:$NODE_PREFIX/bin:/usr/bin:/bin" \
    -p Environment="DSH_HOME=$r/dshhome" -p Environment=BLOOMERY_DSH_KEY=local -p Environment="NODE=$NODE" \
    -p Environment="PW=$PW" -p Environment="PLAYWRIGHT_BROWSERS_PATH=$PWB" \
    -p NoNewPrivileges=yes -p ProtectSystem=strict -p ProtectHome=tmpfs -p PrivateTmp=yes \
    -p BindPaths="$r" -p BindReadOnlyPaths="$KIT $NODE_PREFIX $(dirname "$(dirname "$(dirname "$(dirname "$DSH_JS")")")") $PW $PWB" \
    -p InaccessiblePaths=-/models -p InaccessiblePaths=-/data/moved "${net[@]}" \
    -p CPUQuota="$AGENT_QUOTA" -p AllowedCPUs="$AGENT_CPUS" -p MemoryMax="$AGENT_MEM" -p TasksMax=2048 \
    -p RuntimeMaxSec="$cap" -p StandardOutput="file:$r/$name.out" -p StandardError="file:$r/$name.err" \
    -- /bin/bash -c '"$@"; echo $? > "$0"' "$r/$name.rc" "$@" || true
  wait "$sp" || true
  [ -f "$r/$name.seen" ] && sort -u -o "$r/$name.seen" "$r/$name.seen"
  [ -f "$r/$name.gpu" ] && sort -u -o "$r/$name.gpu" "$r/$name.gpu"
  return 0
}
stop_pid() { # pid what: TERM, up to 60 s, then KILL; waits on that pid only
  local p=$1 i
  kill -0 "$p" 2> /dev/null || return 0
  kill -TERM "$p" 2> /dev/null || true
  for i in $(seq 1 120); do kill -0 "$p" 2> /dev/null || return 0; sleep 0.5; done
  log "$2 ($p) still up after 60 s: KILL"; kill -KILL "$p" 2> /dev/null || true; sleep 1
}

for m in $MODELS; do
  model "$m"
  R=$OUT/$m; mkdir -p "$R"/{home,dshhome/profiles/headless,work,smoke,loop}
  busy=$(nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader)
  [ -z "$busy" ] || { log "$m: the card has compute processes: $busy (one model at a time; ComfyUI is the user's): rc 75"; exit 75; }
  # 2. the server
  log "$m: starting $BIN -m $FILE --mmproj $MMPROJ --ctx-size $CTX --port $PORT"
  "$BIN" -m "$FILE" --mmproj "$MMPROJ" --ctx-size "$CTX" --port "$PORT" > "$R/serve.out" 2> "$R/serve.err" &
  SP=$!; echo "$SP" > "$R/serve.pid"
  t=0; until grep -q '"event":"ready"' "$R/serve.out" 2> /dev/null; do
    kill -0 "$SP" 2> /dev/null || { log "$m: the server died before ready; its stderr ends:"; tail -5 "$R/serve.err" | tee -a "$OUT/record.log"; exit 70; }
    [ "$t" -ge "$LOAD_CAP" ] && { log "$m: no ready event in $LOAD_CAP s"; stop_pid "$SP" server; exit 70; }
    sleep 2; t=$((t + 2))
  done
  SCTX=$(grep -m1 '"event":"ready"' "$R/serve.out" | python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["ctx"])')
  log "$m: ready after ~$t s, ctx $SCTX; plan: $(grep -m1 '^plan ' "$R/serve.err" | cut -c1-160 || true)"
  sed -e "s|@ID@|$MID|g" -e "s|@BASE@|http://127.0.0.1:$PPORT/v1|" -e "s|@CTX@|$SCTX|" -e "s|@MAXTOK@|$(( SCTX < 65536 ? SCTX / 2 : 32768 ))|" \
    "$KIT/profile.yml.tmpl" > "$R/dshhome/profiles/headless/cordis.patch.yml"
  chown -R user:user "$R"
  ps -u user -o pid= | sort -n > "$R/ps-user.before"
  # 4. the smoke, through its own proxy log
  "$NODE" "$KIT/logproxy.mjs" "$PPORT" "$PORT" "$R/smoke-proxy" --effort-none 2> "$R/smoke-proxy.log" &
  PP=$!; sleep 1
  log "$m: smoke"
  fence "dshfilm-$m-smoke" "$R" "$R/smoke" 300 smoke -- "$NODE" "$DSH_JS" headless "Create hello.txt containing the word hi, then read it back."
  stop_pid "$PP" proxy
  why=""
  grep -qi hi "$R/smoke/hello.txt" 2> /dev/null || why="hello.txt does not hold hi (rc $(cat "$R/smoke.rc" 2> /dev/null || echo none); see $R/smoke.err)"
  if [ -z "$why" ] && grep -q '"reasoning_chunks"' "$R/smoke-proxy/index.jsonl"; then why="an answer carried reasoning: thinking is not off"; fi
  if [ -n "$why" ]; then log "$m: smoke failed: $why: rc 78"; stop_pid "$SP" server; exit 78; fi
  # the task's predicted wall from the smoke's own requests: the first one's prompt (dsh's system prompt and tools,
  # uncached) over its time to first byte gives the prompt rate, the server's predicted_per_second the decode rate;
  # the task is ~15 requests, each adding ~1,500 uncached tokens (a tool result or a 1280x720 shot), ~12,000 out in all
  python3 - "$R/smoke-proxy/index.jsonl" "$TASK_CAP" <<'PY' | tee -a "$OUT/record.log"
import json, sys
rs = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
rs = [r for r in rs if r.get('usage') and r.get('t_first_byte')]
if not rs: print('  prediction: the smoke logged no usage'); sys.exit(0)
r0 = rs[0]; p0 = r0['usage']['prompt_tokens']; pp = p0 / max(0.001, (r0['t_first_byte'] - r0['t_start']) / 1000)
tg = max((r.get('timings') or {}).get('predicted_per_second') or 0 for r in rs) or 1
lo, hi = (p0 + 10 * 1000) / pp + 8000 / tg, (p0 + 20 * 2000) / pp + 16000 / tg
print(f'  prediction: first prompt {p0} tokens at {pp:.0f} tok/s prompt, {tg:.1f} tok/s decode -> the task {lo/60:.0f}-{hi/60:.0f} min'
      + (f' (over TASK_CAP {int(sys.argv[2])} s: raise it, or the run is capped and the film refuses it)' if hi > int(sys.argv[2]) else ''))
PY
  # 5. the task
  "$NODE" "$KIT/logproxy.mjs" "$PPORT" "$PORT" "$R/task-proxy" --effort-none 2> "$R/task-proxy.log" &
  PP=$!; sleep 1
  log "$m: task (cap $TASK_CAP s)"
  T0=$(date +%s%3N)
  fence "dshfilm-$m-task" "$R" "$R/work" "$TASK_CAP" task -- "$NODE" "$DSH_JS" headless "$(cat "$KIT/prompt.txt")"
  T1=$(date +%s%3N)
  stop_pid "$PP" proxy
  stop_pid "$SP" server
  log "$m: task ended after $(( (T1 - T0) / 1000 )) s, dsh rc $(cat "$R/task.rc" 2> /dev/null || echo 'none (capped)')"
  # 6. the checks
  ps -u user -o pid= | sort -n > "$R/ps-user.after"
  left=$(comm -13 "$R/ps-user.before" "$R/ps-user.after" | paste -sd, -)
  findings=()
  [ -n "$left" ] && findings+=("user processes left after the run: $(ps -o pid=,comm= -p "$left" | paste -sd ';' -)")
  # an engine by its command name, or by a path or binary name in its arguments (the prompt names none of these)
  bad=$(cat "$R/task.seen" "$R/smoke.seen" 2> /dev/null | grep -E -i '^(llama|ollama|vllm|sglang|exllama|mistral|bloomery)|llama-server|llama\.cpp|ollama|vllm|sglang|mistralrs|bloomery-serve' | head -5 | paste -sd ';' - || true)
  [ -n "$bad" ] && findings+=("an engine or server in the fence: $bad")
  other=$(cat "$R/task.gpu" "$R/smoke.gpu" 2> /dev/null | awk -F', ' -v p="$SP" '$1 != p' | sort -u | paste -sd ';' - || true)
  [ -n "$other" ] && findings+=("another compute process on the card: $other")
  # the page, in the same fence (no network)
  if [ -f "$R/work/index.html" ]; then
    fence "dshfilm-$m-shot" "$R" "$R/work" 300 shot -- "$NODE" "$KIT/shot.mjs" "$R/work/index.html" 1 "$R/page.png"
    fence "dshfilm-$m-loop" "$R" "$R/work" 600 loop -- "$NODE" "$KIT/shot.mjs" "$R/work/index.html" --loop "$LOOP_FPS" "$LOOP_N" "$R/loop"
  fi
  python3 - "$R/meta.json" "$NAME" "$FILE" "$MMPROJ" "$SCTX" "$T0" "$T1" "$R/task.rc" "$R/task.seen" "${findings[@]+"${findings[@]}"}" <<'PY'
import json, os, sys
out, name, f, mm, ctx, t0, t1, rcf, seen, *findings = sys.argv[1:]
rc = int(open(rcf).read().strip()) if os.path.exists(rcf) else None
procs = sorted({l.split()[0] for l in open(seen)} if os.path.exists(seen) else set())
json.dump({'name': name, 'file': os.path.basename(f), 'mmproj': os.path.basename(mm), 'ctx': int(ctx),
           't_task_start': int(t0), 't_task_end': int(t1), 'dsh_rc': rc, 'capped': rc is None,
           'fence': {'findings': findings, 'processes_seen': procs}}, open(out, 'w'), indent=1)
PY
  if [ ${#findings[@]} -eq 0 ]; then log "$m: fence findings: none"; else log "$m: fence findings: ${findings[*]}"; fi
  # the card is free before the next model
  for _ in $(seq 1 60); do [ -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)" ] && break; sleep 1; done
done
"$NODE" "$KIT/summarize.mjs" "$OUT" | tee -a "$OUT/record.log"
