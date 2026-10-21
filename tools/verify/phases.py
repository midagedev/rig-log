"""phases.py — the S (static, collected) and B (box, collected) phases of the verify station.

A round writes code only; the station builds. The F phase (fast) is one request at a
time (tools/verify/verify). The S and B phases are *collected*: every pending request
of that phase is merged into one mix tree (the bloomery base + each request's patch, in
queue order), the phase runs once over the mix, and the reds are attributed back to the
requests that caused them.

  S (static)  the static tier runs once over the mix on the second Mac, through
              bloomery's own tools/mac-remote.sh --tree <mix> <base> (its internals are
              not copied here). Each red step is attributed by re-running only that step
              on the base + that one request; a red that the base alone also shows is
              'main's', named as such.
  B (box)     the union of the requests' gates runs as ONE tools/gate-batch.sh --tier
              fixture --round-ledger, from one station-owned box remote dir, on a mix
              tree as in S. Reds are attributed by re-running only that gate on the
              base + that one request.

The input-key skip (tools/recipes.py static-key, in the bloomery tree) is what makes an
unchanged request cost nothing: a request that touches none of the files a step's key
reads cannot have made that step red, so the step is not re-run for it.

The machine-specific code lives in rig-log (the user's rule); the bloomery tools are
called, never copied. Every path, host and user is read from the environment or the
bloomery tree and is scrubbed out of the output (rig-log is a public repository).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

HOME = os.path.expanduser("~")
SELF_DIR = os.path.dirname(os.path.abspath(__file__))
S_REMOTE = os.path.join(SELF_DIR, "s-remote.sh")
PRUNE_REMOTE = os.path.join(SELF_DIR, "prune-remote.sh")
SSH_OPTS = ["-o", "LogLevel=ERROR", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4"]
# The remote clones of the second Mac, one a track (bloomery's tools/mac-remote.sh).
MR_BASE = "repo/bloomery-mr"
# The GPU hold of another batch, on the box (bloomery's tools/gpu-gate.sh writes it).
BOX_GPU_HOLD = "/root/bloomery-batch.gpuhold"
# The station's own box remote dir: one dir, not one a track.
BOX_REMOTE = "~/repo/bloomery-station-b"
# The station's own clones on the second Mac; the prune never touches them.
STATION_TRACKS = ("station-f", "station-s", "station-b")


def say(msg):
    sys.stdout.write(str(msg) + "\n")


def run(argv, cwd=None, env=None, stdin=None, timeout=None):
    """Run a command and capture its output. A non-zero exit is a value, not an error.

    stdin 이 바이트면(역방향으로 보내는 tar) 출력은 디코딩해 문자열로 돌려준다.
    """
    binary = isinstance(stdin, (bytes, bytearray))
    try:
        p = subprocess.run(argv, cwd=cwd, env=env, input=stdin,
                           capture_output=True, text=not binary, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (255, "", "%s: %s" % (exc.__class__.__name__, exc))
    if binary:
        out = p.stdout.decode("utf-8", "replace")
        err = p.stderr.decode("utf-8", "replace")
        return (p.returncode, out, err)
    return (p.returncode, p.stdout, p.stderr)


def git(tree, *args):
    """Read-only git. --no-optional-locks keeps the index's mtime unchanged."""
    return subprocess.run(["git", "--no-optional-locks", "-C", tree] + list(args),
                          capture_output=True, text=True)


def shlex_quote(text):
    import shlex
    return shlex.quote(text)


def read_host(cfg):
    """The second Mac's user@host. Never printed."""
    if cfg.get("host"):
        return cfg["host"]
    path = os.path.join(HOME, ".config", "bloomery", "mac-remote")
    with open(path) as fh:
        line = fh.readline().strip()
    if not line or line.count("@") != 1:
        raise RuntimeError("no user@host line in %s" % path)
    return line


def make_scrub(host):
    """Take the second Mac's account's home, user and host out of every line."""
    user, _, h = host.partition("@")
    pairs = []
    if user and h:
        pairs.append(("%s@%s" % (user, h), "<user>@<host>"))
    if h:
        pairs.append((h, "<host>"))
    if user:
        pairs.append((user, "<user>"))

    def scrub(text):
        for s, r in pairs:
            if s:
                text = text.replace(s, r)
        return text
    return scrub


def ssh_argv(cfg, host, remote_cmd):
    """The ssh command line. VERIFY_SSH replaces the whole thing (the self-test)."""
    if cfg.get("ssh"):
        import shlex
        return shlex.split(cfg["ssh"]) + [host, remote_cmd]
    return ["ssh"] + SSH_OPTS + [host, remote_cmd]


def ssh_run(cfg, host, remote_cmd, stdin=None, timeout=None):
    """Run a command on the second Mac; its output comes back scrubbed."""
    rc, out, err = run(ssh_argv(cfg, host, remote_cmd), stdin=stdin, timeout=timeout)
    scrub = make_scrub(host)
    return (rc, scrub(out) + scrub(err))


def default_cfg(env=None):
    """Where everything is. Every path is a default the caller can override."""
    env = env if env is not None else os.environ
    root = env.get("VERIFY_ROOT") or os.path.join(HOME, ".cache", "bloomery", "verify")
    return {
        "root": root,
        "bloomery": env.get("VERIFY_BLOOMERY") or os.path.join(HOME, "repo", "bloomery"),
        "mix_root": env.get("VERIFY_MIX") or os.path.join(root, "mix"),
        "log_root": env.get("VERIFY_LOGS") or os.path.join(root, "logs"),
        "host": env.get("VERIFY_HOST") or "",
        "ssh": env.get("VERIFY_SSH") or "",
        "track": env.get("VERIFY_TRACK") or "station-f",
        "s_track": env.get("VERIFY_S_TRACK") or "station-s",
        "b_track": env.get("VERIFY_B_TRACK") or "station-b",
        "box_remote": env.get("VERIFY_BOX_REMOTE") or BOX_REMOTE,
        "prune_age": float(env.get("VERIFY_PRUNE_AGE") or 12),
        "prune": (env.get("VERIFY_PRUNE") or "on").lower() != "off",
        # 트랙을 빌려 쓸 때(따뜻한 트랙을 빌리는 경우) 그 트랙도 가지치기에서 지킨다.
        "keep_tracks": (env.get("VERIFY_KEEP_TRACKS") or "").split(),
        "hold_wait": float(env.get("VERIFY_HOLD_WAIT") or 3600),
        "hold_poll": float(env.get("VERIFY_HOLD_POLL") or 60),
    }


# --- the mix tree ------------------------------------------------------------

def mix_signature(base_sha, entries):
    """The mix's identity: its base and the requests' patches. The same mix is not run
    twice — a request whose patch does not apply waits for the next mix, and the tier
    must not burn a run on the same mix again."""
    import hashlib
    h = hashlib.sha256()
    h.update((base_sha or "").encode())
    for e in entries:
        h.update(("\n" + e["id"]).encode())
        try:
            with open(os.path.join(e["dir"], "patch.diff"), "rb") as fh:
                h.update(hashlib.sha256(fh.read()).digest())
        except OSError:
            h.update(b"no-patch")
    return h.hexdigest()


def last_run_path(cfg, kind):
    return os.path.join(cfg["log_root"], "%s-last.json" % kind)


def read_last_run(cfg, kind, signature):
    """The last run's results for the same mix, if there was one."""
    try:
        with open(last_run_path(cfg, kind)) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if data.get("signature") != signature:
        return None
    return data


def write_last_run(cfg, kind, signature, results, summary, **extra):
    """The last run's state: the mix's signature, its results, and (S 단계) 정적 단계가
    이미 돌았는지. 스테이션이 귀속 전에 죽어도 정적 단계는 다시 돌지 않는다."""
    path = last_run_path(cfg, kind)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data = {"signature": signature, "results": results, "summary": summary}
    data.update(extra)
    with open(path, "w") as fh:
        fh.write(json.dumps(data, indent=2) + "\n")


def request_base(entries):
    """The base every request of a phase is built on: the first request's base sha.

    Requests of one phase are based on the same revision; the first one in queue order
    names it. A request based on another revision has its patch applied to this base,
    and is deferred when the patch does not apply.
    """
    for e in entries:
        sha = (e.get("meta") or {}).get("base_sha")
        if sha:
            return sha
    return None


def mix_dir(cfg, name):
    return os.path.join(cfg["mix_root"], name)


def prepare_mix(cfg, name, base_sha, entries):
    """The mix tree: the bloomery base + each request's patch, in queue order.

    Returns (mixdir, applied, deferred). applied is the list of entries whose patch
    applied; deferred is a list of (entry, reason) — a request whose patch does not
    apply waits for the next mix.
    """
    d = mix_dir(cfg, name)
    if not os.path.isdir(os.path.join(d, ".git")):
        # A clone of the bloomery tree: the objects are shared (hard links), the
        # checkout is the base revision. The lead's own tree is never written to.
        rc, _, err = run(["git", "clone", "--local", "--no-checkout", cfg["bloomery"], d])
        if rc != 0:
            raise RuntimeError("clone of %s failed (%d): %s"
                               % (cfg["bloomery"], rc, err.strip()))
    rc, _, err = run(["git", "-C", d, "checkout", "-q", "--detach", base_sha])
    if rc != 0:
        raise RuntimeError("checkout of %s in the mix tree failed (%d): %s"
                           % (base_sha, rc, err.strip()))
    run(["git", "-C", d, "reset", "-q", "--hard"])
    run(["git", "-C", d, "clean", "-qfdx"])
    applied, deferred = [], []
    for e in entries:
        reason = apply_request(d, e)
        if reason:
            deferred.append((e, reason))
        else:
            applied.append(e)
    return (d, applied, deferred)


def apply_request(mixdir, entry):
    """One request's patch and its untracked files into a tree. "" on success."""
    qdir = entry["dir"]
    patch = os.path.join(qdir, "patch.diff")
    untar = os.path.join(qdir, "untracked.tar")
    if os.path.exists(patch) and os.path.getsize(patch) > 0:
        rc, _, err = run(["git", "-C", mixdir, "apply", "--whitespace=nowarn", patch])
        if rc != 0:
            last = (err.strip() or "git apply failed").splitlines()
            return "the patch does not apply (%s)" % (last[-1][:160] if last else "")
    if os.path.exists(untar) and os.path.getsize(untar) > 0:
        try:
            with tarfile.open(untar) as tf:
                tf.extractall(mixdir)
        except (OSError, tarfile.TarError) as exc:
            return "the untracked files do not unpack (%s)" % exc
    return ""


def patch_files(entry):
    """The files a request's patch touches."""
    files = set()
    patch = os.path.join(entry["dir"], "patch.diff")
    try:
        with open(patch, errors="replace") as fh:
            for line in fh:
                if line.startswith("diff --git "):
                    rest = line[len("diff --git "):].rstrip("\n")
                    if " b/" in rest:
                        files.add(rest.split(" b/", 1)[1])
                elif line.startswith("+++ "):
                    p = line[4:].rstrip("\n").split("\t")[0]
                    if p != "/dev/null":
                        files.add(p[2:] if p.startswith("b/") else p)
    except OSError:
        pass
    return files


# --- the second Mac: the static tier, one step, the jobs --------------------

def tier_run(cfg, mix, base_sha):
    """The static tier once over the mix, through bloomery's own tools/mac-remote.sh.

    The script is the mix tree's own (its version and the tree's content are one
    revision). Its output and its rc come back here.
    """
    script = os.path.join(mix, "tools", "mac-remote.sh")
    if not os.path.isfile(script):
        raise RuntimeError("the mix tree has no tools/mac-remote.sh")
    t0 = time.time()
    rc, out, err = run([script, "--tree", mix, base_sha], cwd=mix)
    return (rc, out + err, time.time() - t0)


RE_RESULTS = re.compile(r"^mac-static: results (\S+)", re.M)
RE_RED_STEP = re.compile(r"^mac-remote: red step (\S+) \(rc (\d+)\)", re.M)
RE_RED_STEPS = re.compile(r"^mac-static: red steps: (.+)$", re.M)


def parse_tier(out):
    """(the run's result directory, the red steps as (name, rc))."""
    m = RE_RESULTS.search(out)
    results = m.group(1) if m else ""
    reds = [(name, int(rc)) for name, rc in RE_RED_STEP.findall(out)]
    if not reds:
        m2 = RE_RED_STEPS.search(out)
        if m2:
            for item in m2.group(1).split():
                reds.append((item.split("(")[0], 0))
    return results, reds


def jobs_file_local(cfg, track, results):
    """The run's job file, fetched from the second Mac into the station's own area.

    bloomery's own mac-static.sh writes it (NAME⇥ATTRS⇥KEYSPEC⇥COMMAND a line), so the
    station re-runs a step with the command the tier itself used.
    """
    if not results:
        return None
    out_dir = os.path.join(cfg["log_root"], "jobs")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "%s-%s.tsv" % (track, os.path.basename(results)))
    if not os.path.exists(path):
        cmd = "cat \"$HOME/%s/%s/%s/jobs.tsv\" 2>/dev/null || true" % (MR_BASE, track, results)
        rc, out = ssh_run(cfg, read_host(cfg), cmd)
        if not out.strip():
            return None
        with open(path, "w") as fh:
            fh.write(out)
    return path


def step_command(jobs_path, name):
    """The command the tier itself ran for a step, from its job file."""
    if not jobs_path:
        return None
    try:
        with open(jobs_path, errors="replace") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) == 4 and parts[0] == name:
                    return parts[3]
    except OSError:
        pass
    return None


def key_files(tree, jobs_path, name):
    """The files a step's input key reads (tools/recipes.py static-key --files).

    None when the key is unknown: the tree's recipes.py cannot answer, or the step has
    no key at all (its key is "-" — "never skipped" — and its file list is empty). Then
    no request is skipped for that step: a step that is never skipped is always run.
    """
    script = os.path.join(tree, "tools", "recipes.py")
    if not os.path.isfile(script) or not os.path.isfile(jobs_path):
        return None
    rc, out, _ = run(["python3", script, "static-key", jobs_path, "--files", name], cwd=tree)
    if rc != 0:
        return None
    files = set(l.strip() for l in out.splitlines() if l.strip())
    return files or None


def run_step(cfg, track, base_sha, entry, command):
    """Run ONE command on the second Mac in a tree of the base + that one request.

    The tree is the station's own clone of the track: reset to the base, the request's
    patch applied, then the command. The result is (rc, output).
    """
    payload = tempfile.mkdtemp(prefix="verify-s-")
    try:
        with open(os.path.join(payload, "cmd"), "w") as fh:
            fh.write(command)
        if entry:
            for name in ("patch.diff", "untracked.tar"):
                src = os.path.join(entry["dir"], name)
                if os.path.exists(src):
                    shutil.copy(src, os.path.join(payload, name))
        shutil.copy(S_REMOTE, os.path.join(payload, "s-remote.sh"))
        tar_path = os.path.join(payload, "payload.tar")
        with tarfile.open(tar_path, "w") as tf:
            for name in ("cmd", "patch.diff", "untracked.tar", "s-remote.sh"):
                path = os.path.join(payload, name)
                if os.path.exists(path):
                    tf.add(path, arcname=name)
        with open(tar_path, "rb") as fh:
            data = fh.read()
        inner = ("T=$(mktemp -d) || exit 70; trap 'rm -rf \"$T\"' EXIT; "
                 "tar -xf - -C \"$T\" || exit 71; "
                 "bash \"$T/s-remote.sh\" %s %s \"$T\" \"$T/cmd\""
                 % (shlex_quote(track), shlex_quote(base_sha)))
        rc, out, err = run(ssh_argv(cfg, read_host(cfg), inner), stdin=data)
        scrub = make_scrub(read_host(cfg))
        return (rc, scrub(out) + scrub(err))
    finally:
        shutil.rmtree(payload, ignore_errors=True)


# --- the S phase -------------------------------------------------------------

def s_phase(cfg, entries, log_name="s.log"):
    """The S phase over the pending S requests.

    Per request: (rc, the red steps attributed to it, the path to the full log).
    A request whose patch does not apply gets rc None: it waits for the next mix.
    """
    base_sha = request_base(entries)
    if not base_sha:
        return ({}, "no request names a base revision")
    signature = mix_signature(base_sha, entries)
    last = read_last_run(cfg, "s", signature)
    log_path = os.path.join(cfg["log_root"], log_name)
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    if last and last.get("attributed"):
        # 같은 mix 의 귀속까지 끝났다: 정적 단계도 귀속도 다시 돌리지 않는다.
        return (last["results"], last["summary"] + "\ns: the same mix as the last run: "
                "the static tier is not run again")
    if last and last.get("tier_done"):
        # 같은 mix 의 정적 단계가 이미 돌았다(스테이션이 귀속 전에 죽었을 수 있다):
        # 정적 단계는 다시 돌리지 않고 귀속만 한다.
        mix = mix_dir(cfg, cfg["s_track"])
        applied = [e for e in entries if e["id"] in last.get("applied", [])]
        deferred = [(e, r) for e, r in zip([e for e in entries if e["id"] in last.get("deferred", [])],
                                          last.get("deferred", []))]
        reds = [tuple(r) for r in last.get("reds", [])]
        results = last.get("results_dir", "")
        out = last.get("tier_output", "")
        lines = [last.get("summary", "s: the static tier ran for this mix already")]
        lines.append("s: the static tier is not run again (the same mix)")
    else:
        mix, applied, deferred = prepare_mix(cfg, cfg["s_track"], base_sha, entries)
        lines = ["s: mix %s at %s, %d request(s)" % (mix, base_sha[:12], len(applied))]
        prc, pout = prune(cfg)
        lines.append("s: %s" % (pout.strip() or "prune: rc %d" % prc))
        for e, reason in deferred:
            lines.append("s: deferred %s: %s" % (e["id"], reason))
        rc, out, wall = tier_run(cfg, mix, base_sha)
        results, reds = parse_tier(out)
        lines.append("s: the static tier rc %d in %.1f s, %d red step(s)" % (rc, wall, len(reds)))
        for name, step_rc in reds:
            lines.append("s: red step %s (rc %d)" % (name, step_rc))
        # 정적 단계가 끝났다는 기록을 먼저 남긴다: 스테이션이 귀속 전에 죽어도 다음
        # 스테이션이 정적 단계를 다시 돌리지 않는다(정적 단계가 비싸다).
        write_last_run(cfg, "s", signature, {}, "\n".join(lines), tier_done=True,
                       reds=reds, applied=[e["id"] for e in applied],
                       deferred=[r for _, r in deferred], results_dir=results,
                       tier_output=out)
    # Attribution: each red step on the base + that one request, and on the base alone.
    jobs_path = jobs_file_local(cfg, cfg["s_track"], results)
    attributed = dict((e["id"], []) for e in applied)
    mains = []
    for name, step_rc in reds:
        command = step_command(jobs_path, name)
        if not command:
            lines.append("s: the red step %s has no command to re-run: it stays unattributed"
                         % name)
            continue
        files = key_files(mix, jobs_path, name) if jobs_path else None
        base_rc, _ = run_step(cfg, cfg["s_track"], base_sha, None, command)
        if base_rc != 0:
            mains.append(name)
            lines.append("s: the red step %s is main's: the base alone is red too (rc %d)"
                         % (name, base_rc))
        for e in applied:
            if files is not None and not (patch_files(e) & files):
                # The input-key skip: this request moved none of the files the step's
                # key reads, so the step cannot be its red and it is not re-run.
                continue
            one_rc, _ = run_step(cfg, cfg["s_track"], base_sha, e, command)
            if one_rc != 0:
                lines.append("s: the red step %s with %s alone: rc %d"
                             % (name, e["id"], one_rc))
                if base_rc == 0:
                    # main 이 되면 빨강이 아니다: 이 요청의 빨강이다.
                    attributed[e["id"]].append((name, one_rc))
                    lines.append("s: the red step %s is %s's (rc %d)"
                                 % (name, e["id"], one_rc))
            elif base_rc != 0:
                lines.append("s: the red step %s is green with %s alone"
                             % (name, e["id"]))
    out_by_id = {}
    for e in applied:
        reds_here = attributed[e["id"]]
        out_by_id[e["id"]] = {
            "rc": reds_here[0][1] if reds_here else 0,
            "reds": [r[0] for r in reds_here],
            "mains": mains,
            "log": log_path,
        }
    for e, reason in deferred:
        out_by_id[e["id"]] = {"rc": None, "reds": [], "mains": mains,
                              "log": log_path, "deferred": reason}
    with open(log_path, "w") as fh:
        fh.write("\n".join(lines) + "\n\n" + out)
    write_last_run(cfg, "s", signature, out_by_id, "\n".join(lines), attributed=True,
                   reds=reds, applied=[e["id"] for e in applied],
                   deferred=[r for _, r in deferred], results_dir=results, tier_output=out)
    return (out_by_id, "\n".join(lines))


# --- the B phase -------------------------------------------------------------

def affected_gates(tree, base):
    """The gate recipes `just affected BASE` names in a tree."""
    script = os.path.join(tree, "tools", "affected-gates.sh")
    if not os.path.isfile(script):
        return []
    rc, out, _ = run(["bash", script, base], cwd=tree)
    if rc != 0:
        return []
    gates = []
    for line in out.splitlines():
        if line.startswith("  gate-") or line.startswith("  weekly-"):
            name = line.split()[0]
            if name not in gates:
                gates.append(name)
    return gates


def request_gates(entry):
    """A request's gates: the ones it named, else the ones `just affected` names."""
    meta = entry.get("meta") or {}
    gates = list(meta.get("gates") or [])
    if gates:
        return gates
    base = meta.get("base") or "main"
    tree = meta.get("tree")
    if not tree or not os.path.isdir(tree):
        return []
    return affected_gates(tree, base)


def union_gates(entries):
    """The union of the requests' gates, in the order they first appear."""
    union = []
    for e in entries:
        for g in request_gates(e):
            if g not in union:
                union.append(g)
    return union


def box_prepare(cfg, tree):
    """The station's box remote dir must exist before the hold probe can read it.

    box.sh's readonly mode refuses a dir the box has not got (66), and the hold file
    lives outside the dir, so the probe needs the dir: a sync of the mix tree (the
    batch's own first step) makes it.
    """
    box = os.path.join(tree, "tools", "box.sh")
    if not os.path.isfile(box):
        return (0, "")
    env = dict(os.environ)
    env["BLOOMERY_REMOTE"] = cfg["box_remote"]
    rc, out, err = run(["bash", box, "true"], cwd=tree, env=env)
    return (rc, out + err)


def hold_up(cfg, tree):
    """True while another batch's GPU hold is up on the box.

    The hold is the batch's own (/root/bloomery-batch.gpuhold); gate-batch's --wait-hold
    covers the timing lease and the per-sitting holds, not this one, so the station waits
    for it itself.
    """
    box = os.path.join(tree, "tools", "box.sh")
    if not os.path.isfile(box):
        return False
    env = dict(os.environ)
    env["BLOOMERY_BOX_READONLY"] = "1"
    env["BLOOMERY_REMOTE"] = cfg["box_remote"]
    rc, out, err = run(["bash", box, "test -e %s" % BOX_GPU_HOLD], cwd=tree, env=env)
    return rc == 0


def wait_hold(cfg, tree):
    """Wait for the GPU hold to go down. A poll every 60 s, no event, no signal."""
    waited = 0.0
    while hold_up(cfg, tree):
        if waited >= cfg["hold_wait"]:
            return waited
        time.sleep(cfg["hold_poll"])
        waited += cfg["hold_poll"]
    return waited


def run_batch(cfg, mix, gates, list_path):
    """ONE gate-batch over the union of the gates, in the mix tree."""
    script = os.path.join(mix, "tools", "gate-batch.sh")
    if not os.path.isfile(script):
        raise RuntimeError("the mix tree has no tools/gate-batch.sh")
    with open(list_path, "w") as fh:
        fh.write("\n".join(gates) + "\n")
    env = dict(os.environ)
    env["BLOOMERY_REMOTE"] = cfg["box_remote"]
    t0 = time.time()
    rc, out, err = run([script, "--tier", "fixture", "--round-ledger", "--list", list_path],
                       cwd=mix, env=env)
    return (rc, out + err, time.time() - t0)


RE_RED_GATE = re.compile(r"^red: (\S+)\s+(\S+)", re.M)


def parse_batch(out):
    """The red gates of a batch: the recipe names."""
    reds = []
    for stem, _log in RE_RED_GATE.findall(out):
        name = re.sub(r"-\d+$", "", stem)
        if name not in reds:
            reds.append(name)
    return reds


def run_gate(tree, gate, box_remote, tier="fixture"):
    """One gate on the box, in a tree (the mix tree or the base + one request)."""
    env = dict(os.environ)
    env["BLOOMERY_REMOTE"] = box_remote
    env["BLOOMERY_TIER"] = tier
    rc, out, err = run(["just", gate], cwd=tree, env=env)
    return (rc, out + err)


def b_phase(cfg, entries, log_name="b.log"):
    """The B phase over the pending box requests.

    Per request: (rc, the red gates attributed to it, the path to the full log).
    """
    base_sha = request_base(entries)
    if not base_sha:
        return ({}, "no request names a base revision")
    signature = mix_signature(base_sha, entries)
    last = read_last_run(cfg, "b", signature)
    if last:
        return (last["results"], last["summary"] + "\nb: the same mix as the last run: "
                "the batch is not run again")
    mix, applied, deferred = prepare_mix(cfg, cfg["b_track"], base_sha, entries)
    lines = ["b: mix %s at %s, %d request(s)" % (mix, base_sha[:12], len(applied))]
    for e, reason in deferred:
        lines.append("b: deferred %s: %s" % (e["id"], reason))
    gates = union_gates(applied)
    lines.append("b: the union of the gates: %s" % (" ".join(gates) or "(none)"))
    log_path = os.path.join(cfg["log_root"], log_name)
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    if gates:
        prc, pout = box_prepare(cfg, mix)
        lines.append("b: the box dir %s: rc %d" % (cfg["box_remote"], prc))
        waited = wait_hold(cfg, mix)
        if waited:
            lines.append("b: waited %.0f s for another batch's GPU hold" % waited)
        list_path = os.path.join(cfg["log_root"], log_name.replace(".log", "-gates.txt"))
        rc, out, wall = run_batch(cfg, mix, gates, list_path)
    else:
        rc, out, wall = (0, "b: no gate to run\n", 0.0)
    reds = parse_batch(out)
    lines.append("b: the batch rc %d in %.1f s, %d red gate(s)" % (rc, wall, len(reds)))
    for name in reds:
        lines.append("b: red gate %s" % name)
    # Attribution: each red gate on the base + that one request.
    attributed = dict((e["id"], []) for e in applied)
    for name in reds:
        for e in applied:
            one, one_applied, _ = prepare_mix(cfg, cfg["b_track"] + "-one", base_sha, [e])
            if not one_applied:
                continue
            rrc, _ = run_gate(one, name, cfg["box_remote"])
            if rrc != 0:
                attributed[e["id"]].append(name)
                lines.append("b: the red gate %s is %s's (rc %d)" % (name, e["id"], rrc))
    out_by_id = {}
    for e in applied:
        reds_here = attributed[e["id"]]
        out_by_id[e["id"]] = {"rc": 1 if reds_here else 0, "reds": reds_here, "log": log_path}
    for e, reason in deferred:
        out_by_id[e["id"]] = {"rc": None, "reds": [], "log": log_path, "deferred": reason}
    with open(log_path, "w") as fh:
        fh.write("\n".join(lines) + "\n\n" + out)
    write_last_run(cfg, "b", signature, out_by_id, "\n".join(lines))
    return (out_by_id, "\n".join(lines))


# --- the second Mac's disk ---------------------------------------------------

def prune(cfg):
    """The station's prune of the second Mac's disk.

    Every track's target/ that no run has touched for the age and that no lock holds is
    removed; the station's own clones are never touched. One line: the tracks removed and
    the space free after.
    """
    if not cfg.get("prune", True):
        return (0, "prune: off\n")
    host = read_host(cfg)
    keep = " ".join(shlex_quote(k) for k in tuple(STATION_TRACKS) + tuple(cfg.get("keep_tracks") or ()))
    with open(PRUNE_REMOTE) as fh:
        script = fh.read()
    rc, out, err = run(ssh_argv(cfg, host, "bash -s -- %s %s" % (int(cfg["prune_age"]), keep)),
                       stdin=script)
    scrub = make_scrub(host)
    return (rc, scrub(out) + scrub(err))


# --- the self-test -----------------------------------------------------------

STUB_SSH = r'''#!/bin/sh
# VERIFY_SSH 스텁: ssh 의 마지막 인자(원격 명령 문자열)를 이 셸에서 돈다.
cmd=""
for a in "$@"; do cmd=$a; done
exec /bin/bash -c "$cmd"
'''

STUB_MAC_REMOTE = r'''#!/bin/sh
# The static tier's stub: the track's clone, a result directory, a job file, a red step.
TREE=$2
TRACK=$(basename "$TREE")
B="$HOME/repo/bloomery-mr/$TRACK"
if [ ! -d "$B/.git" ]; then
  mkdir -p "$(dirname "$B")"
  git clone --local "$TREE" "$B" >/dev/null 2>&1
fi
D="$B/target/mac-static/run.0001"
mkdir -p "$D"
printf 'check-demo\t-\ttree\tbash tools/check-demo.sh\n' > "$D/jobs.tsv"
printf 'check-main\t-\ttree\tbash tools/check-main.sh\n' >> "$D/jobs.tsv"
printf '0\n' > "$D/check-demo.rc"
printf '0\n' > "$D/check-main.rc"
echo "mac-static: results target/mac-static/run.0001"
echo "mac-static: check-demo rc 1 in 1 s"
echo "mac-static: check-main rc 1 in 1 s"
echo "mac-remote: red step check-demo (rc 1): the last 40 lines of the log on the remote"
echo "mac-remote: red step check-main (rc 1): the last 40 lines of the log on the remote"
exit 1
'''

STUB_CHECK_DEMO = r'''#!/bin/sh
# The step is red when the file says so.
grep -q '^red$' file.txt && exit 1
exit 0
'''

STUB_CHECK_MAIN = r'''#!/bin/sh
# The step is red on the base too: main's own red.
exit 1
'''

STUB_RECIPES = r'''#!/usr/bin/env python3
# recipes.py 스텁: static-key 는 이름과 키를, --files 는 그 단계의 입력 파일을 준다.
import sys
args = sys.argv[1:]
if args and args[0] == "static-key":
    jobs = args[1]
    names = []
    for line in open(jobs):
        f = line.rstrip("\n").split("\t")
        if len(f) == 4:
            names.append((f[0], f[2]))
    if "--files" in args:
        want = args[args.index("--files") + 1]
        for name, spec in names:
            if name == want:
                if spec == "tree":
                    print("file.txt")
                sys.exit(0)
        sys.exit(1)
    for name, spec in names:
        print("%s\t%s\t%s" % (name, "k-" + name, spec))
    sys.exit(0)
sys.exit(64)
'''

STUB_BOX = r'''#!/bin/sh
# The box's stub: the hold is up while $HOME/hold exists.
for a in "$@"; do cmd=$a; done
case "$cmd" in
  *"test -e /root/bloomery-batch.gpuhold"*)
    [ -f "$HOME/hold" ] && exit 0 || exit 1 ;;
esac
exit 0
'''

STUB_GATE_BATCH = r'''#!/bin/sh
# The batch's stub: it prints the red gate and its rc.
list=""
while [ $# -gt 0 ]; do
  case "$1" in --list) list=$2; shift 2;; *) shift;; esac
done
echo "gate-demo rc 1 3s try=1 lane=A tier=fixture"
echo "DONE total=1 red=1 tier=fixture"
echo "red: gate-demo  $list.gate-demo.log"
exit 1
'''


def make_entry(cfg, label, tree, base_sha, patch, phase="static", gates=None, name="file.txt",
               old="base"):
    """A queue entry with a patch, as the station's queue holds it."""
    qdir = os.path.join(cfg["root"], "queue", "20261021-%s-1" % label)
    os.makedirs(qdir, exist_ok=True)
    with open(os.path.join(qdir, "patch.diff"), "w") as fh:
        fh.write("diff --git a/%s b/%s\n--- a/%s\n+++ b/%s\n"
                 "@@ -1 +1 @@\n-%s\n+%s" % (name, name, name, name, old, patch))
    with open(os.path.join(qdir, "untracked.tar"), "wb") as fh:
        fh.write(b"")
    meta = {"id": "20261021-%s-1" % label, "tree": tree, "base": base_sha, "base_sha": base_sha,
            "phase": phase, "gates": gates or [], "label": label, "submitter": "selftest"}
    with open(os.path.join(qdir, "meta.json"), "w") as fh:
        fh.write(json.dumps(meta, indent=2) + "\n")
    return {"id": meta["id"], "dir": qdir, "meta": meta}


def selftest():
    """The S mix + attribution, the B union + attribution, the hold wait, the prune.

    Stubs only: a fake bloomery tree, a fake second Mac (the ssh is a local command),
    a fake box, a fake gate-batch. No real remote, no real box, no real gate.
    """
    bad = []
    tmp = tempfile.mkdtemp(prefix="verify-phases-selftest-")
    saved = {k: os.environ.get(k) for k in
             ("VERIFY_ROOT", "VERIFY_BLOOMERY", "VERIFY_MIX", "VERIFY_LOGS", "VERIFY_HOST",
              "VERIFY_SSH", "VERIFY_TRACK", "VERIFY_S_TRACK", "VERIFY_B_TRACK",
              "VERIFY_BOX_REMOTE", "VERIFY_PRUNE_AGE", "VERIFY_HOLD_WAIT", "VERIFY_HOLD_POLL",
              "HOME", "PATH")}
    try:
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        tree = os.path.join(tmp, "bloomery")
        os.makedirs(os.path.join(tree, "tools"))
        with open(os.path.join(tree, "file.txt"), "w") as fh:
            fh.write("base\n")
        with open(os.path.join(tree, "other.txt"), "w") as fh:
            fh.write("other\n")
        with open(os.path.join(tree, "justfile"), "w") as fh:
            fh.write("gate-demo:\n"
                     "\t@if grep -q '^red$' file.txt; then echo 'gate-demo: red'; exit 1; "
                     "else echo 'gate-demo ran'; fi\n"
                     "affected BASE='main':\n\t@echo '  gate-demo  file.txt  [why]'\n")
        for name, body in (("tools/mac-remote.sh", STUB_MAC_REMOTE),
                           ("tools/box.sh", STUB_BOX),
                           ("tools/gate-batch.sh", STUB_GATE_BATCH),
                           ("tools/check-demo.sh", STUB_CHECK_DEMO),
                           ("tools/check-main.sh", STUB_CHECK_MAIN),
                           ("tools/recipes.py", STUB_RECIPES)):
            path = os.path.join(tree, name)
            with open(path, "w") as fh:
                fh.write(body)
            os.chmod(path, 0o755)
        env = dict(os.environ)
        env.update({"GIT_AUTHOR_NAME": "selftest", "GIT_AUTHOR_EMAIL": "s@example.invalid",
                    "GIT_COMMITTER_NAME": "selftest", "GIT_COMMITTER_EMAIL": "s@example.invalid"})
        run(["git", "init", "-q", tree], env=env)
        run(["git", "-C", tree, "add", "-A"], env=env)
        run(["git", "-C", tree, "commit", "-q", "-m", "base"], env=env)
        base_sha = git(tree, "rev-parse", "HEAD").stdout.strip()

        # The fake second Mac: the ssh is a local command and HOME is the fake one.
        sshstub = os.path.join(tmp, "sshstub")
        with open(sshstub, "w") as fh:
            fh.write(STUB_SSH)
        os.chmod(sshstub, 0o755)
        os.environ.update({
            "VERIFY_ROOT": os.path.join(tmp, "root"),
            "VERIFY_BLOOMERY": tree,
            "VERIFY_MIX": os.path.join(tmp, "mix"),
            "VERIFY_LOGS": os.path.join(tmp, "logs"),
            "VERIFY_SSH": sshstub,
            "VERIFY_HOST": "selftest-host",
            "VERIFY_TRACK": "station-f",
            "VERIFY_S_TRACK": "station-s",
            "VERIFY_B_TRACK": "station-b",
            "VERIFY_BOX_REMOTE": "~/repo/bloomery-station-b",
            "VERIFY_HOLD_POLL": "0.05",
            "HOME": home,
        })
        cfg = default_cfg()
        os.makedirs(os.path.join(home, "repo", "bloomery-mr", "station-s"), exist_ok=True)

        # 1) the S phase: a red step, attributed to the request that caused it
        entries = [make_entry(cfg, "A", tree, base_sha, "red\n"),
                   make_entry(cfg, "B", tree, base_sha, "benign\n", name="other.txt",
                              old="other")]
        res, summary = s_phase(cfg, entries, "s.log")
        if res.get("20261021-A-1", {}).get("reds") != ["check-demo"]:
            bad.append("the red step is not attributed to the request that caused it: %s" % res)
        if res.get("20261021-B-1", {}).get("reds"):
            bad.append("a request that changed nothing is blamed: %s" % res)
        if not os.path.exists(os.path.join(cfg["log_root"], "s.log")):
            bad.append("the S phase wrote no full log")
        if res.get("20261021-A-1", {}).get("mains") != ["check-main"]:
            bad.append("a red the base alone shows is not named main's: %s" % res)
        if "is main's" not in summary:
            bad.append("the summary does not name the main's red: %s" % summary)

        # 1b) the same mix is not run twice (a deferred request must not burn a tier)
        runs_path = os.path.join(home, "tier-runs")
        first_runs = open(runs_path).read().strip() if os.path.exists(runs_path) else "0"
        res1b, summary1b = s_phase(cfg, entries, "s.log")
        again = open(runs_path).read().strip() if os.path.exists(runs_path) else "0"
        if again != first_runs:
            bad.append("the same mix ran the static tier again (%s -> %s)"
                       % (first_runs, again))
        if "the same mix as the last run" not in summary1b:
            bad.append("the same mix is not named as such: %s" % summary1b.splitlines()[-1])

        # 2) a request whose patch does not apply waits for the next mix
        bad_entry = make_entry(cfg, "C", tree, base_sha, "")
        with open(os.path.join(bad_entry["dir"], "patch.diff"), "w") as fh:
            fh.write("diff --git a/nope.txt b/nope.txt\n--- a/nope.txt\n+++ b/nope.txt\n"
                     "@@ -1 +1 @@\n-nothing\n+something\n")
        res2, summary2 = s_phase(cfg, [bad_entry], "s2.log")
        if "deferred 20261021-C-1" not in summary2:
            bad.append("a request whose patch does not apply is not named as deferred: %s" % summary2)
        if res2.get("20261021-C-1", {}).get("rc") is not None:
            bad.append("a deferred request has an rc: %s" % res2)

        # 2b) a step with no key (its key is "-") has no file list: nothing is skipped
        jobs_path = os.path.join(cfg["log_root"], "jobs", "unit.tsv")
        os.makedirs(os.path.dirname(jobs_path), exist_ok=True)
        with open(jobs_path, "w") as fh:
            fh.write("nokey\t-\t-\ttools/check-demo.sh\n")
        if key_files(tree, jobs_path, "nokey") is not None:
            bad.append("a step with no key is treated as if it had a file list")
        if key_files(tree, jobs_path, "nosuch") is not None:
            bad.append("an unknown step is treated as if it had a file list")

        # 3) the B phase: the union of the gates, and the red gate's attribution
        res3, summary3 = b_phase(cfg, [make_entry(cfg, "D", tree, base_sha, "red\n",
                                                   phase="box", gates=["gate-demo"])], "b.log")
        if "the union of the gates: gate-demo" not in summary3:
            bad.append("the B phase does not name the union of the gates: %s" % summary3)
        if res3.get("20261021-D-1", {}).get("reds") != ["gate-demo"]:
            bad.append("the red gate is not attributed to the request that caused it: %s" % res3)

        # 4) the union: two requests, one gate each, one in common
        u = union_gates([make_entry(cfg, "E", tree, base_sha, "", phase="box",
                                    gates=["gate-demo"]),
                         make_entry(cfg, "F", tree, base_sha, "", phase="box",
                                    gates=["gate-demo", "gate-other"])])
        if u != ["gate-demo", "gate-other"]:
            bad.append("the union of the gates is not the one gate both name: %s" % u)

        # 5) the hold wait: the hold is up, the wait ends when it goes down
        hold_file = os.path.join(home, "hold")
        with open(hold_file, "w") as fh:
            fh.write("up\n")
        if not hold_up(cfg, tree):
            bad.append("the GPU hold is not seen while it is up")
        os.unlink(hold_file)
        if hold_up(cfg, tree):
            bad.append("the GPU hold is seen after it went down")
        if wait_hold(cfg, tree) != 0:
            bad.append("the hold wait slept although the hold was down")

        # 6) the prune: an old track goes, a fresh one and a locked one stay
        base = os.path.join(home, "repo", "bloomery-mr")
        old = os.path.join(base, "old-track")
        fresh = os.path.join(base, "fresh-track")
        locked = os.path.join(base, "locked-track")
        mine = os.path.join(base, "station-b")
        for d in (old, fresh, locked, mine):
            os.makedirs(os.path.join(d, "target", "debug"), exist_ok=True)
        os.makedirs(os.path.join(base, "station-s", "target", "debug"), exist_ok=True)
        stamp = time.time() - 20 * 3600
        for d in (old, locked, mine):
            os.utime(os.path.join(d, "target"), (stamp, stamp))
            os.utime(os.path.join(d, "target", "debug"), (stamp, stamp))
        os.makedirs(os.path.join(base, ".lock-locked-track"), exist_ok=True)
        os.environ["VERIFY_PRUNE_AGE"] = "12"
        rc, out = prune(default_cfg())
        if os.path.exists(os.path.join(old, "target")):
            bad.append("the prune kept an old track's target: %r" % out)
        if not os.path.exists(os.path.join(fresh, "target")):
            bad.append("the prune removed a fresh track's target")
        if not os.path.exists(os.path.join(locked, "target")):
            bad.append("the prune removed a locked track's target")
        if not os.path.exists(os.path.join(mine, "target")):
            bad.append("the prune removed the station's own clone's target")
        if "tracks removed" not in out:
            bad.append("the prune printed no line: %r" % out)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)
    if bad:
        for line in bad:
            sys.stderr.write("verify phases self-test FAIL: %s\n" % line)
        sys.stderr.write("verify phases: self-test %d failed\n" % len(bad))
        return 1
    print("verify phases: self-test ok")
    return 0


if __name__ == "__main__":
    sys.exit(selftest())
