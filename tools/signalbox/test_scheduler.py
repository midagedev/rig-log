#!/usr/bin/env python3
"""Scheduler policy tests with a fake clock and fake probes — no GPU, no box.
Run: python3 test_scheduler.py"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import daemon as D


class FakeProbes(D.Probes):
    def __init__(self, lease=None, locks=(), holds=(), vram=None):
        super().__init__(gpu_order="/nonexistent", lease="/nonexistent",
                         lock_glob="/nonexistent/*", hold_glob="/nonexistent/*")
        self.lease_state, self.lock_state = lease, dict(locks)
        self.hold_state, self.vram_state = list(holds), dict(vram or {})

    def uuids(self):
        return {"a6000": "GPU-fake-a6000", "3090": "GPU-fake-3090"}

    def vram_mib(self, card):
        return self.vram_state.get(card, 0)

    def gpu_lease(self):
        if not self.lease_state or not self.lease_state.get("tag"):
            return None
        d = dict(self.lease_state)
        pid = d.get("pid")
        live = False
        if pid:
            try:
                os.kill(pid, 0)
                live = True
            except PermissionError:
                live = True
            except OSError:
                live = False
        d["live"] = live
        return d

    def bloomery_locks(self):
        return dict(self.lock_state)

    def bloomery_holds(self):
        return list(self.hold_state)


def make_sched(lease=None, locks=(), holds=(), vram=None, windows=(), now=None,
               fake=True, cooldown=0):
    tmp = tempfile.mkdtemp(prefix="signalbox-test-")
    res_path = os.path.join(tmp, "reservations.json")
    with open(res_path, "w") as f:
        json.dump({"windows": list(windows), "cache_cooldown_s": cooldown}, f)
    clock = {"now": now or datetime(2026, 10, 3, 15, 0, 0)}
    s = D.Scheduler(probes=FakeProbes(lease, locks, holds, vram), home=tmp,
                    reservations=D.Reservations(res_path), fake=fake,
                    now_fn=lambda: clock["now"])
    return s, clock


PASS = FAIL = 0
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("ok   %s" % name)
    else:
        FAIL += 1
        print("FAIL %s %s" % (name, detail))


# ---------------------------------------------------------------- lanes
s, _ = make_sched()
a = s.submit({"kind": "fake", "name": "a", "owner": "t", "card": "a6000", "env": {"SLEEP": "30"}})
b = s.submit({"kind": "fake", "name": "b", "owner": "t", "card": "a6000", "env": {"SLEEP": "30"}})
c = s.submit({"kind": "fake", "name": "c", "owner": "t", "card": "3090", "env": {"SLEEP": "30"}})
s.tick()
check("lane: first a6000 job starts", a["status"] == "running", a["status"])
check("lane: second a6000 job waits", b["status"] == "queued" and "lanes busy" in (b["wait_reason"] or ""), b["wait_reason"])
check("lane: other card free", c["status"] == "running", c["status"])

# ---------------------------------------------------------------- class host/solo
s, _ = make_sched()
h = s.submit({"kind": "fake", "name": "h", "owner": "t", "job_class": "solo"})
o = s.submit({"kind": "fake", "name": "o", "owner": "t", "card": "3090"})
s.tick()
check("solo: starts alone", h["status"] == "running")
check("solo: blocks the other card too", o["status"] == "queued" and "solo" in (o["wait_reason"] or ""), o["wait_reason"])

# ---------------------------------------------------------------- cache groups
s, _ = make_sched(cooldown=60)
g1 = s.submit({"kind": "fake", "name": "g1", "owner": "t", "cache_group": "glm", "env": {"SLEEP": "1"}})
g2 = s.submit({"kind": "fake", "name": "g2", "owner": "t", "card": "3090", "cache_group": "qwen"})
s.tick()
check("cache: different groups never parallel", g2["status"] == "queued" and "cache group" in (g2["wait_reason"] or ""), g2["wait_reason"])
time.sleep(1.2)
s.tick()  # g1 done; cooldown now applies
check("cache: cooldown holds after finish", g2["status"] == "queued" and "cooldown" in (g2["wait_reason"] or ""), g2["wait_reason"])
s.cache_free["glm"] = s.now() - D.timedelta(seconds=120)
s.tick()
check("cache: cooldown expiry releases", g2["status"] == "running", g2["status"])

# media jobs get an implicit group
s, _ = make_sched(cooldown=0)
m1 = s.submit({"kind": "media-take", "script": "img", "name": "m1", "owner": "t"})
check("cache: media jobs default to a group", m1["cache_group"] == "media", m1["cache_group"])

# ---------------------------------------------------------------- lease law
dead = {"tag": "ltx-old", "pid": 99999999}
s, _ = make_sched(lease=dead, fake=False)
j = s.submit({"kind": "fake", "name": "j", "owner": "t"})
s.tick()
check("lease: dead pid is no lease (cleared, job runs)", j["status"] == "running", j["wait_reason"])
live = subprocess.Popen(["sleep", "60"])
s, _ = make_sched(lease={"tag": "img-x", "pid": live.pid}, fake=False)
j = s.submit({"kind": "fake", "name": "j", "owner": "t"})
s.tick()
check("lease: live pid blocks", j["status"] == "queued" and "gpu-lease" in (j["wait_reason"] or ""), j["wait_reason"])
live.terminate(); live.wait()

# ---------------------------------------------------------------- bloomery observation
s, _ = make_sched(locks={"bloomery-gate-a6000.lock": "held"}, fake=False)
j1 = s.submit({"kind": "fake", "name": "j1", "owner": "t", "card": "a6000"})
j2 = s.submit({"kind": "fake", "name": "j2", "owner": "t", "card": "3090"})
s.tick()
check("bloomery: card-specific lock blocks only its card",
      j1["status"] == "queued" and j2["status"] == "running",
      "%s / %s" % (j1["status"], j2["status"]))
s, _ = make_sched(locks={"bloomery-cpu.lock": "held"}, fake=False)
j = s.submit({"kind": "fake", "name": "j", "owner": "t"})
s.tick()
check("bloomery: box-wide lock blocks both", j["status"] == "queued")
s, _ = make_sched(holds=["bloomery-03-hold"], fake=False)
j = s.submit({"kind": "fake", "name": "j", "owner": "t"})
s.tick()
check("bloomery: a hold is occupancy", j["status"] == "queued")

# vram
s, _ = make_sched(vram={"a6000": 24000}, fake=False)
j = s.submit({"kind": "fake", "name": "j", "owner": "t", "card": "a6000"})
s.tick()
check("vram: busy card refuses", j["status"] == "queued" and "above" in (j["wait_reason"] or ""), j["wait_reason"])

# ---------------------------------------------------------------- reservations
train = {"name": "train-13", "days": list(range(7)), "start": "13:00", "minutes": 120,
         "cards": ["a6000", "3090"], "owner": "gate-batch"}
night = {"name": "webuta", "days": list(range(7)), "start": "23:30", "minutes": 480,
         "cards": ["a6000"], "owner": "webuta"}
s, clock = make_sched(windows=[train], now=datetime(2026, 10, 3, 13, 30), fake=False)
j = s.submit({"kind": "fake", "name": "j", "owner": "someone"})
own = s.submit({"kind": "fake", "name": "own", "owner": "gate-batch"})
s.tick()
check("res: active window blocks outsiders", j["status"] == "queued" and "reservation" in (j["wait_reason"] or ""), j["wait_reason"])
check("res: window owner passes", own["status"] == "running", own["status"])
# crossing: a 30-min media job at 12:45 would run past 13:00
s, clock = make_sched(windows=[train], now=datetime(2026, 10, 3, 12, 45), fake=False)
j = s.submit({"kind": "fake", "name": "j", "owner": "someone", "expected_min": 30})
s.tick()
check("res: job that cannot finish before the window holds",
      j["status"] == "queued" and "would cross" in (j["wait_reason"] or ""), j["wait_reason"])
s, clock = make_sched(windows=[train], now=datetime(2026, 10, 3, 12, 45), fake=False)
j = s.submit({"kind": "fake", "name": "j", "owner": "someone", "expected_min": 10})
s.tick()
check("res: short job before the window passes", j["status"] == "running", j["status"])
# night window only binds the a6000
s, clock = make_sched(windows=[night], now=datetime(2026, 10, 3, 23, 45), fake=False)
ja = s.submit({"kind": "fake", "name": "ja", "owner": "t", "card": "a6000"})
jt = s.submit({"kind": "fake", "name": "jt", "owner": "t", "card": "3090"})
s.tick()
check("res: night window binds a6000 only",
      ja["status"] == "queued" and jt["status"] == "running",
      "%s / %s" % (ja["status"], jt["status"]))

# ---------------------------------------------------------------- gen sugar + validation
s, _ = make_sched()
job = s.submit({"kind": "media-take", "script": "ltx", "name": "v1", "owner": "api",
                "env": {"PROMPT": "a watch movement", "FRAMES": "121"}})
check("gen: ltx env flows", job["env"]["PROMPT"] == "a watch movement" and job["script"] == "ltx")
D.Handler.sched = s
try:
    D.Handler.gen(D.Handler, "video", {})  # the sugar layer enforces the required knobs
    check("gen: missing PROMPT refused", False)
except ValueError:
    check("gen: missing PROMPT refused", True)
try:
    s.submit({"kind": "command", "argv": "true", "name": "c1", "owner": "t", "card": "gpu"})
    check("validation: bad card refused", False)
except ValueError:
    check("validation: bad card refused", True)
try:
    s.submit({"kind": "command", "argv": "true", "name": "bad name!", "owner": "t"})
    check("validation: bad name refused", False)
except ValueError:
    check("validation: bad name refused", True)

# ---------------------------------------------------------------- command job, real rc passthrough
s, _ = make_sched(fake=False)
ok = s.submit({"kind": "command", "argv": "exit 0", "name": "ok", "owner": "t", "card": "a6000"})
rc75 = s.submit({"kind": "command", "argv": "exit 75", "name": "r75", "owner": "t", "card": "3090"})
s.tick(); time.sleep(0.5); s.tick()
check("command: rc 0 is done", ok["status"] == "done", ok["status"])
check("command: rc 75 is failed, rc preserved", rc75["status"] == "failed" and rc75["rc"] == 75,
      "%s/%s" % (rc75["status"], rc75["rc"]))

# ---------------------------------------------------------------- calendar + state views
s, _ = make_sched()
s.submit({"kind": "fake", "name": "k1", "owner": "line1", "title": "GLM 깊이 6 재측정",
          "expected_min": 15, "env": {"SLEEP": "1"}})
s.tick()
md = s.calendar_md()
check("calendar: columns match the box-calendar shape",
      "| 요청 시각 | 세션 | 창 이름 | 모델 | 예상 분 | 결정하는 것 | 순서 | 끝 |" in md)
check("calendar: row carries owner and title", "line1" in md and "GLM 깊이 6 재측정" in md)
view = s.state_view()
check("state: cards carry reasons list", isinstance(view["cards"]["a6000"]["reasons"], list))

# ---------------------------------------------------------------- priority + eta
s, clock = make_sched(cooldown=0)
blocker = s.submit({"kind": "fake", "name": "blk", "owner": "t", "card": "a6000",
                    "expected_min": 10, "env": {"SLEEP": "30"}})
s.tick()
check("priority: blocker running", blocker["status"] == "running")
low = s.submit({"kind": "fake", "name": "low", "owner": "t", "card": "a6000",
                "priority": -5, "expected_min": 1, "env": {"SLEEP": "1"}})
high = s.submit({"kind": "fake", "name": "high", "owner": "t", "card": "a6000",
                 "priority": 5, "expected_min": 1, "env": {"SLEEP": "1"}})
eta = s.eta_seconds(low)
check("eta: blocker known -> finite", eta is not None and 500 <= eta <= 660, eta)
# unblock the lane; the higher priority takes it first
blocker["expected_min"] = 0
s.procs[blocker["id"]].terminate()
time.sleep(0.3)
s.tick()
check("priority: high jumps low", high["status"] == "running" and low["status"] == "queued",
      "%s / %s" % (high["status"], low["status"]))
s2, _ = make_sched(cooldown=0)
b2 = s2.submit({"kind": "fake", "name": "b2", "owner": "t", "card": "a6000",
                "expected_min": 0, "env": {"SLEEP": "30"}})
s2.tick()
q2 = s2.submit({"kind": "fake", "name": "q2", "owner": "t", "card": "a6000"})
check("eta: unbounded blocker -> honest unknown", s2.eta_seconds(q2) is None)
free = s2.submit({"kind": "fake", "name": "free", "owner": "t", "card": "3090"})
check("eta: startable lane -> 0", s2.eta_seconds(free) == 0)
s2.tick()
s2.procs[b2["id"]].terminate(); s2.procs[free["id"]].terminate()

# queued-ahead durations are in the estimate
s3, _ = make_sched(cooldown=0)
b3 = s3.submit({"kind": "fake", "name": "b3", "owner": "t", "card": "a6000",
                "expected_min": 5, "env": {"SLEEP": "30"}})
s3.tick()
s3.submit({"kind": "fake", "name": "mid", "owner": "t", "card": "a6000",
           "expected_min": 7})
last = s3.submit({"kind": "fake", "name": "last", "owner": "t", "card": "a6000"})
eta = s3.eta_seconds(last)
check("eta: queued-ahead included (5+7 min)", eta is not None and 660 <= eta <= 840, eta)
s3.procs[b3["id"]].terminate()

# priority adjust while queued
s4, _ = make_sched(cooldown=0)
b4 = s4.submit({"kind": "fake", "name": "b4", "owner": "t", "card": "a6000",
                "expected_min": 10, "env": {"SLEEP": "30"}})
s4.tick()
late = s4.submit({"kind": "fake", "name": "late", "owner": "t", "card": "a6000"})
s4.set_priority(late["id"], 50)
check("priority: adjustable while queued", late["priority"] == 50)
b4["expected_min"] = 0
s4.procs[b4["id"]].terminate(); time.sleep(0.3)
early = s4.submit({"kind": "fake", "name": "early", "owner": "t", "card": "a6000"})
s4.tick()
check("priority: bumped job dispatches ahead of newer same-priority",
      late["status"] == "running" and early["status"] == "queued",
      "%s / %s" % (late["status"], early["status"]))
s4.procs[late["id"]].terminate()

# ---------------------------------------------------------------- the tailnet door
import http.server

TOKEN = "door-test-token-0123456789"
tok_dir = tempfile.mkdtemp(prefix="signalbox-token-")
tok_path = os.path.join(tok_dir, "token")


def write_token(text, mode=0o600):
    with open(tok_path, "w") as f:
        f.write(text)
    os.chmod(tok_path, mode)


write_token(TOKEN + "\n")
sd, _ = make_sched()
D.Handler.sched, D.Handler.token_file = sd, tok_path
httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), D.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % httpd.server_address[1]
TAILNET = {"X-Forwarded-For": "203.0.113.7"}
AUTH = {"Authorization": "Bearer " + TOKEN}


def call(method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers=dict(headers or {}))
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


code, out = call("POST", "/jobs", {"kind": "fake", "name": "local1", "owner": "t", "wait": 0})
check("door: local POST /jobs kind=fake, no token, is unchanged (201)",
      code == 201 and out["kind"] == "fake", (code, out))

code, out = call("GET", "/health", headers=TAILNET)
check("door: tailnet GET /health without a token is 401", code == 401 and "rc" in out, (code, out))
code, out = call("GET", "/health", headers={**TAILNET, **AUTH})
check("door: tailnet GET /health with the token is 200", code == 200 and out == {"ok": True},
      (code, out))

code, _ = call("GET", "/health", headers={**TAILNET, "Authorization": "Bearer wrong-token"})
code_prefix, _ = call("GET", "/health",
                      headers={**TAILNET, "Authorization": "Bearer " + TOKEN[:-1]})
check("door: a wrong token and a prefix of the right one are both 401",
      code == 401 and code_prefix == 401, (code, code_prefix))

before = len(sd.jobs)
code, out = call("POST", "/jobs", {"kind": "command", "argv": "id", "wait": 0},
                 headers={**TAILNET, **AUTH})
check("door: tailnet POST /jobs kind=command is 403 and queues nothing",
      code == 403 and "tailnet" in out["error"] and "/jobs" in out["error"]
      and len(sd.jobs) == before, (code, out, len(sd.jobs) - before))

victim = sd.submit({"kind": "fake", "name": "victim", "owner": "t", "priority": 3})
code, out = call("POST", "/jobs/%s/priority" % victim["id"], {"priority": 900},
                 headers={**TAILNET, **AUTH})
check("door: tailnet POST /jobs/<id>/priority is 403 and the priority is unchanged",
      code == 403 and "not open to the tailnet" in out["error"] and victim["priority"] == 3,
      (code, out, victim["priority"]))

before = len(sd.jobs)
code, out = call("POST", "/gen/image", {"prompt": "a red kite", "wait": 0},
                 headers={**TAILNET, **AUTH})
check("door: tailnet POST /gen/image with the token is 201 and queues a media-take",
      code == 201 and out["kind"] == "media-take" and len(sd.jobs) == before + 1, (code, out))

before = len(sd.jobs)
code, out = call("POST", "/gen/image", {"prompt": "a red kite", "wait": 0, "priority": 50},
                 headers={**TAILNET, **AUTH})
check("door: tailnet /gen/image carrying priority is 403 and queues nothing",
      code == 403 and "priority" in out["error"] and len(sd.jobs) == before, (code, out))

code, out = call("GET", "/health", headers={"Tailscale-User-Login": "someone@example.com"})
check("door: Tailscale-* header alone marks a tailnet request (401 without a token)",
      code == 401, (code, out))

def refused(path, body, why_in_error):
    """True when a tailnet POST with the token is 403, names `why_in_error`, queues nothing."""
    before = len(sd.jobs)
    code, out = call("POST", path, dict(body, wait=0), headers={**TAILNET, **AUTH})
    return (code == 403 and why_in_error in out.get("error", "")
            and len(sd.jobs) == before), (code, out)


VIDEO = {"prompt": "a kite over a field", "frames": 49, "wh": "1024 576", "seed": 7}
ok, det = refused("/gen/video", dict(VIDEO, extra="x --output-path /tmp/y"), "extra")
check("knobs: tailnet extra is 403 by name and queues nothing", ok, det)
ok, det = refused("/gen/music", {"style": "lofi", "lyrics_file": "/etc/passwd"}, "lyrics_file")
check("knobs: tailnet lyrics_file is 403 by name", ok, det)
ok, det = refused("/gen/video", dict(VIDEO, plim=100), "plim")
check("knobs: tailnet plim is 403 by name", ok, det)
ok, det = refused("/gen/audio", {"mode": "encode", "cache": "cache/x"}, "tailnet")
check("knobs: tailnet /gen/audio is 403", ok, det)
ok, det = refused("/gen/video", dict(VIDEO, wh="1024 --x"), "wh")
check("knobs: tailnet wh \"1024 --x\" is 403 by name", ok, det)
ok, det = refused("/gen/video", dict(VIDEO, seed="42\n"), "seed")
check("knobs: a value with a trailing newline does not pass its format", ok, det)
ok, det = refused("/gen/image", {"prompt": "--output-path /x"}, "prompt")
check("knobs: tailnet text that starts with '-' is 403", ok, det)
ok, det = refused("/gen/video", dict(VIDEO, owner="bloomery"), "owner")
check("knobs: tailnet owner is 403 (it would pass a reservation window)", ok, det)

before = len(sd.jobs)
code, out = call("POST", "/gen/video", dict(VIDEO, wait=0), headers={**TAILNET, **AUTH})
check("knobs: tailnet /gen/video with prompt, frames, wh, seed is 201",
      code == 201 and out["kind"] == "media-take" and out["script"] == "ltx"
      and out["env"]["WH"] == "1024 576" and len(sd.jobs) == before + 1, (code, out))
code, out = call("POST", "/gen/music", {"style": "lofi", "lyrics": "la la", "seed": 3, "wait": 0},
                 headers={**TAILNET, **AUTH})
check("knobs: tailnet /gen/music with style, lyrics, seed is 201", code == 201, (code, out))
code, out = call("POST", "/gen/video", dict(VIDEO, extra="--skip-stage-2", wait=0))
check("knobs: local /gen/video with extra is unchanged (201)",
      code == 201 and out["env"]["EXTRA"] == "--skip-stage-2", (code, out))

# ---- v3: the tailnet owner, comfy session, own-job cancel, one media lane
T = {**TAILNET, **AUTH}
before = len(sd.jobs)
code, out = call("POST", "/comfy/session", {"minutes": 30, "tag": "win1", "wait": 0}, headers=T)
check("v3: tailnet /comfy/session minutes=30 is 201, kind comfy-session, owner hermes",
      code == 201 and out["kind"] == "comfy-session" and out["owner"] == "hermes"
      and out["card"] == "a6000" and out["env"]["MINUTES"] == "30" and out["env"]["TS_SERVE"] == "0"
      and len(sd.jobs) == before + 1, (code, out))
ok, det = refused("/comfy/session", {"minutes": 30, "ts_serve": 1}, "ts_serve")
check("v3: tailnet /comfy/session ts_serve is 403 by name and queues nothing", ok, det)
ok, det = refused("/comfy/session", {"minutes": 0}, "minutes")
check("v3: tailnet /comfy/session minutes=0 is 403", ok, det)
ok, det = refused("/comfy/session", {"minutes": 121}, "minutes")
check("v3: tailnet /comfy/session minutes=121 is 403", ok, det)
ok, det = refused("/comfy/session", {}, "minutes is required")
check("v3: tailnet /comfy/session without minutes (unbounded) is 403", ok, det)
ok, det = refused("/comfy/session", {"minutes": 30, "port": 22}, "port")
check("v3: tailnet /comfy/session port=22 is 403", ok, det)
ok, det = refused("/comfy/session", {"minutes": 30, "port": 8200}, "port")
check("v3: tailnet /comfy/session port=8200 is 403", ok, det)
ok, det = refused("/comfy/session", {"minutes": 30, "card": "3090"}, "card")
check("v3: tailnet /comfy/session card=3090 is 403", ok, det)
ok, det = refused("/comfy/session", {"minutes": 30, "owner": "bloomery"}, "owner")
check("v3: tailnet /comfy/session owner is 403", ok, det)
ok, det = refused("/comfy/session", {"minutes": 30, "tag": ".."}, "tag")
check("v3: tailnet /comfy/session tag \"..\" (a directory name) is 403", ok, det)
code, out = call("POST", "/comfy/session", {"minutes": 20, "port": 8190, "wait": 0}, headers=T)
check("v3: tailnet /comfy/session port=8190 is 201 with PORT in its env",
      code == 201 and out["env"].get("PORT") == "8190", (code, out))

code, out = call("POST", "/gen/image", {"prompt": "a blue kite", "wait": 0}, headers=T)
img = out
check("v3: tailnet /gen/image creates a job owned by hermes",
      code == 201 and out["owner"] == "hermes", (code, out))
code, out = call("POST", "/jobs/%s/cancel" % img["id"], headers=T)
check("v3: tailnet cancel of a hermes job is 200 and the job is cancelled",
      code == 200 and sd.by_id(img["id"])["status"] == "cancelled", (code, out))

local = sd.submit({"kind": "fake", "name": "local2", "owner": "t"})
code, out = call("POST", "/jobs/%s/cancel" % local["id"], headers=T)
check("v3: tailnet cancel of a locally submitted job is 403 by name and it stays queued",
      code == 403 and local["id"] in out["error"] and "not the tailnet's" in out["error"]
      and sd.by_id(local["id"])["status"] == "queued", (code, out))
code, out = call("POST", "/jobs/local2/cancel", headers=T)
check("v3: tailnet cancel by the name of a local job is 403 too",
      code == 403 and sd.by_id(local["id"])["status"] == "queued", (code, out))
code, out = call("POST", "/jobs/s9999/cancel", headers=T)
check("v3: tailnet cancel of a missing id is 404", code == 404, (code, out))
code, mine = call("POST", "/gen/image", {"prompt": "a green kite", "wait": 0}, headers=T)
code, out = call("POST", "/jobs/%s/cancel" % mine["id"], {"tag": "x"}, headers=T)
check("v3: tailnet cancel of its own job carrying a body key is 403 and the job stays queued",
      code == 403 and "tag" in out["error"] and sd.by_id(mine["id"])["status"] == "queued",
      (code, out))
code, out = call("POST", "/jobs/%s/cancel" % local["id"])
check("v3: local cancel of a local job is unchanged (200, cancelled)",
      code == 200 and sd.by_id(local["id"])["status"] == "cancelled", (code, out))

before = len(sd.jobs)
code_s, out_s = call("POST", "/comfy/stop", {}, headers=T)
code_b, out_b = call("POST", "/comfy/batch", {}, headers=T)
check("v3: tailnet /comfy/stop and /comfy/batch are 403 and queue nothing",
      code_s == 403 and code_b == 403 and len(sd.jobs) == before, (code_s, code_b))

before = len(sd.jobs)
code, out = call("POST", "/gen/music", {"style": "lofi", "card": "3090", "wait": 0})
check("v3: local /gen/music card=3090 is 400 by name (A6000 only) and queues nothing",
      code == 400 and "A6000 only" in out["error"] and len(sd.jobs) == before, (code, out))
code, out = call("POST", "/gen/music", {"style": "lofi", "card": "any", "wait": 0})
check("v3: local /gen/music card=any is 400 too", code == 400 and len(sd.jobs) == before, (code, out))
code, out = call("POST", "/gen/music", {"style": "lofi", "wait": 0})
check("v3: local /gen/music with no card is 201 on a6000, owner api (unchanged)",
      code == 201 and out["card"] == "a6000" and out["owner"] == "api"
      and len(sd.jobs) == before + 1, (code, out))
ok, det = refused("/gen/music", {"style": "lofi", "card": "3090"}, "card")
check("v3: tailnet /gen/music card=3090 is 403 by name", ok, det)
code, out = call("POST", "/comfy/session", {"minutes": 0, "ts_serve": 1, "owner": "x", "wait": 0})
check("v3: local /comfy/session keeps its rule (ts_serve, minutes=0, owner x pass)",
      code == 201 and out["owner"] == "x" and out["env"]["TS_SERVE"] == "1", (code, out))

os.remove(tok_path)
code_gone, out_gone = call("GET", "/health", headers={**TAILNET, **AUTH})
local_gone, _ = call("GET", "/health")
write_token(TOKEN + "\n", mode=0o644)
code_open, out_open = call("GET", "/health", headers={**TAILNET, **AUTH})
local_open, _ = call("GET", "/health")
check("door: a missing token file and a 0644 token file are both 503 naming the file; local works",
      code_gone == 503 and code_open == 503 and tok_path in out_gone["error"]
      and tok_path in out_open["error"] and local_gone == 200 and local_open == 200,
      (code_gone, code_open, local_gone, local_open))
httpd.shutdown()

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
