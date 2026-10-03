#!/usr/bin/env python3
"""Scheduler policy tests with a fake clock and fake probes — no GPU, no box.
Run: python3 test_scheduler.py"""
import json
import os
import subprocess
import sys
import tempfile
import time
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

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
