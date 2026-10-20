#!/usr/bin/env python3
"""signalbox's resource ledger: the arithmetic of what the box has and what is promised.

Pure functions and small classes, no probe and no clock: daemon.py hands them one snapshot
(what /proc, the cgroups and nvidia-smi said this tick) and the holders (grants and queue
jobs that declared a need), and gets back the ledger, the admission verdicts and the
refusal lines. The config is configs/box-resources.json, read once at start by load_config.

One owner: signalbox. A holder's charge is max(declared, measured) of its resident bytes
(anon + file-hot + the locked and pinned pages that are subsets of them); a holder that
measures past its need is named `over`, never charged silently.

stdlib only, like daemon.py.
"""

import json
import re
from collections import namedtuple

GB = 10 ** 9   # decimal, as bloomery's plan prints and the design's numbers are

# The page classes of a RAM need. locked and pinned are disjoint from anon and file_hot as
# declared; churn is the residency churn pool, charged under the class charge_classes picks.
RAM_KEYS = ("locked", "pinned", "anon", "file_hot", "churn")
CHURN_HOSTING = ("hosted", "unhosted")
NVME_MODES = ("bulk", "lat")
NAME_RE = re.compile(r"[A-Za-z0-9._-]+")
UNIT_RE = re.compile(r"[A-Za-z0-9:_.@\\-]+\.(service|scope)")
# The user's order (2026-10-20): the timing sitting, then media and the release pass, then the
# toktape, the landing batch, the round batch, the static tier, the downloads.
REQUIRED_CLASSES = ("sitting", "media", "release", "tape", "lead", "round", "static", "fill")

Refusal = namedtuple("Refusal", "resource text holder")


class ConfigError(ValueError):
    pass


def gb(n):
    return "%.2f GB" % (n / GB)


def parse_cpus(value, what="cpus"):
    """A cpu list as the kernel prints it ("0-5,8-13") or a JSON list of ints: the sorted
    distinct cpu numbers. A bad list is a ValueError that names `what`."""
    if isinstance(value, str):
        out = []
        for part in value.split(","):
            m = re.fullmatch(r"(\d+)(?:-(\d+))?", part.strip())
            if not m:
                raise ValueError("%s: %r is not a cpu list like 0-5,8-13" % (what, value))
            lo = int(m.group(1))
            hi = int(m.group(2)) if m.group(2) is not None else lo
            if hi < lo:
                raise ValueError("%s: range %s runs backwards" % (what, part.strip()))
            out.extend(range(lo, hi + 1))
        return sorted(set(out))
    if isinstance(value, list) and value and all(
            isinstance(c, int) and not isinstance(c, bool) and c >= 0 for c in value):
        return sorted(set(value))
    raise ValueError("%s must be a cpu list string like 0-5,8-13 or a non-empty list of "
                     "cpu numbers, got %r" % (what, value))


def fmt_cpus(cpus):
    """The kernel's spelling of a cpu list: [0,1,2,8] -> "0-2,8"."""
    out, run = [], []
    for c in sorted(cpus):
        if run and c == run[-1] + 1:
            run.append(c)
            continue
        if run:
            out.append(run)
        run = [c]
    if run:
        out.append(run)
    return ",".join(str(r[0]) if len(r) == 1 else "%d-%d" % (r[0], r[-1]) for r in out)


# ---------------------------------------------------------------- config

def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _plain(d, where):
    """The keys of d that carry a value: `*_why` and `*_about` are the derivation comments."""
    if not isinstance(d, dict):
        raise ConfigError("%s must be an object" % where)
    return {k: v for k, v in d.items() if not (k.endswith("_why") or k.endswith("_about"))}


def _only(d, allowed, where):
    extra = sorted(set(d) - set(allowed))
    if extra:
        raise ConfigError("%s has keys the ledger does not read: %s" % (where, ", ".join(extra)))


def _need_key(d, key, where, lo, whole=True):
    """d[key] as a whole number (or a plain number when whole is False) >= lo."""
    v = d.get(key)
    ok = _is_int(v) if whole else (isinstance(v, (int, float)) and not isinstance(v, bool))
    if not ok:
        raise ConfigError("%s.%s must be %s, got %r" % (where, key, "a whole number" if whole
                                                         else "a number", v))
    if v < lo:
        raise ConfigError("%s.%s must be >= %s, got %r" % (where, key, lo, v))
    return v


class Config:
    """configs/box-resources.json, validated. Every number in it carries a `<name>_why`
    derivation beside it; the loader reads the numbers and ignores the comments."""

    def __init__(self, path, raw):
        self.path = path
        top = _plain(raw, "box-resources")
        _only(top, ("ram", "grants", "cpus", "nvme", "classes"), "box-resources")
        ram = _plain(top.get("ram"), "ram")
        _only(ram, ("os_other_bytes", "headroom_bytes", "memory_high_factor",
                    "memory_max_factor", "memory_max_add_bytes"), "ram")
        self.os_other = _need_key(ram, "os_other_bytes", "ram", 0)
        self.headroom = _need_key(ram, "headroom_bytes", "ram", 0)
        self.high_factor = float(_need_key(ram, "memory_high_factor", "ram", 1.0, whole=False))
        self.max_factor = float(_need_key(ram, "memory_max_factor", "ram", 1.0, whole=False))
        self.max_add = _need_key(ram, "memory_max_add_bytes", "ram", 0)
        if self.max_factor < self.high_factor:
            raise ConfigError("ram.memory_max_factor %s is below memory_high_factor %s: the "
                              "cap would sit under the throttle" % (self.max_factor, self.high_factor))
        grants = _plain(top.get("grants"), "grants")
        _only(grants, ("appear_s", "history"), "grants")
        self.appear_s = _need_key(grants, "appear_s", "grants", 1)
        self.history = _need_key(grants, "history", "grants", 1)
        cpus = _plain(top.get("cpus"), "cpus")
        _only(cpus, ("all",), "cpus")
        try:
            self.cpus = parse_cpus(cpus.get("all"), "cpus.all")
        except ValueError as e:
            raise ConfigError(str(e))
        self.nvme = {}
        for name, row in _plain(top.get("nvme"), "nvme").items():
            row = _plain(row, "nvme.%s" % name)
            _only(row, ("dev", "mount"), "nvme.%s" % name)
            if not NAME_RE.fullmatch(name) or not isinstance(row.get("dev"), str) \
                    or not NAME_RE.fullmatch(row["dev"]):
                raise ConfigError("nvme.%s needs a name and a dev like nvme0n1" % name)
            self.nvme[name] = row["dev"]
        classes = _plain(top.get("classes"), "classes")
        for name, rank in classes.items():
            if not NAME_RE.fullmatch(name) or not _is_int(rank) or not -1000 <= rank <= 1000:
                raise ConfigError("classes.%s must be an integer rank -1000..1000, got %r"
                                  % (name, rank))
        missing = [c for c in REQUIRED_CLASSES if c not in classes]
        if missing:
            raise ConfigError("classes lacks %s" % ", ".join(missing))
        c = classes
        order = (c["sitting"] > max(c["media"], c["release"])
                 and min(c["media"], c["release"]) > c["tape"] > c["lead"] > c["round"]
                 > c["static"] > c["fill"])
        if not order:
            raise ConfigError("classes break the order timing sitting > media and release > tape "
                              "> lead > round > static > fill: %s"
                              % ", ".join("%s %d" % (k, c[k]) for k in REQUIRED_CLASSES))
        self.class_priority = dict(classes)


def load_config(path):
    try:
        with open(path) as f:
            raw = json.load(f)
    except OSError as e:
        raise ConfigError("%s is unreadable (%s)" % (path, e.strerror))
    except ValueError as e:
        raise ConfigError("%s is not JSON (%s)" % (path, e))
    return Config(path, raw)


# ---------------------------------------------------------------- needs

def normalize_need(raw, kind):
    """The canonical need of a grant (kind "grant") or a queued job (kind "job"), or a
    ValueError that names the field. RAM bytes by page class; for a grant also the cards,
    the cpus as an explicit list and nvme drive modes; for a job the number of cpus it runs."""
    if not isinstance(raw, dict):
        raise ValueError("need must be an object")
    allowed = ("ram", "host_lock", "churn_hosting") + (
        ("cards", "cpus", "nvme") if kind == "grant" else ("cpus",))
    extra = sorted(set(raw) - set(allowed))
    if extra:
        raise ValueError("need has fields a %s does not take: %s (it takes %s)"
                         % (kind, ", ".join(extra), ", ".join(allowed)))
    need = {"ram": {}, "host_lock": False, "churn_hosting": "hosted"}
    ram = raw.get("ram", {})
    if not isinstance(ram, dict):
        raise ValueError("need.ram must be an object of bytes by page class")
    for key, value in ram.items():
        if key not in RAM_KEYS:
            raise ValueError("need.ram.%s is not a page class (%s)" % (key, ", ".join(RAM_KEYS)))
        if not _is_int(value) or value < 0:
            raise ValueError("need.ram.%s must be a whole number of bytes >= 0, got %r" % (key, value))
        need["ram"][key] = value
    if "host_lock" in raw:
        if not isinstance(raw["host_lock"], bool):
            raise ValueError("need.host_lock must be true or false")
        need["host_lock"] = raw["host_lock"]
    if "churn_hosting" in raw:
        if raw["churn_hosting"] not in CHURN_HOSTING:
            raise ValueError("need.churn_hosting must be one of %s" % (CHURN_HOSTING,))
        need["churn_hosting"] = raw["churn_hosting"]
    if kind == "grant":
        cards = raw.get("cards", [])
        if not isinstance(cards, list) or len(set(cards)) != len(cards):
            raise ValueError("need.cards must be a list of distinct card names")
        need["cards"] = list(cards)
        need["cpus"] = parse_cpus(raw["cpus"], "need.cpus") if "cpus" in raw else []
        nvme = raw.get("nvme", {})
        if not isinstance(nvme, dict) or any(m not in NVME_MODES for m in nvme.values()):
            raise ValueError("need.nvme must map a drive to %s" % (NVME_MODES,))
        need["nvme"] = dict(nvme)
    elif "cpus" in raw:
        if not _is_int(raw["cpus"]) or raw["cpus"] < 1:
            raise ValueError("a job's need.cpus is the number of cpus it runs, an integer >= 1")
        need["cpus"] = raw["cpus"]
    return need


def charge_classes(need):
    """Bytes by page class that a need charges. The churn pool is read in and locked with the
    plan's host segments under BLOOMERY_HOST_LOCK=1 when ChurnHosting is Hosted (the default):
    charged as locked. Hosted without the lock it is file-hot; Unhosted it is not read in and
    charges nothing (its victims are served from the file's mapping)."""
    ram = need["ram"]
    out = {"locked": ram.get("locked", 0), "pinned": ram.get("pinned", 0),
           "anon": ram.get("anon", 0), "file_hot": ram.get("file_hot", 0)}
    churn = ram.get("churn", 0)
    if need["churn_hosting"] == "hosted":
        out["locked" if need["host_lock"] else "file_hot"] += churn
    return out


def declared_total(need):
    return sum(charge_classes(need).values())


def limits_of(cfg, resident):
    """The cgroup caps a unit of `resident` bytes gets: a throttle at 1.1x, a stop at 1.5x + 2 GiB.
    They bind on the cgroup's charge, and a file page is charged to the cgroup that first read
    it: a model file read before the unit started is not throttled by a fresh slice."""
    if resident <= 0:
        return {}      # no RAM declared: nothing to cap
    return {"memory_high": int(resident * cfg.high_factor),
            "memory_max": int(resident * cfg.max_factor) + cfg.max_add}


# ---------------------------------------------------------------- the ledger

class Ledger:
    """The ledger of one snapshot. `rows` are the holders: dicts with id, kind (grant|job),
    holder, klass, owner, since, unit, need, state and `measured` (the resident bytes the
    snapshot read for it, or None when nothing could be read)."""

    def __init__(self, cfg, mem, mem_why, rows, held_back=0):
        self.cfg, self.mem, self.held_back = cfg, mem, held_back
        self.blind = None
        self.rows = [dict(r) for r in rows]
        for r in self.rows:
            r["declared"] = declared_total(r["need"])
            m = r.get("measured")
            r["measured_total"] = m["resident"] if m else None
            r["charge"] = max(r["declared"], r["measured_total"] or 0)
            r["over_by"] = max(0, (r["measured_total"] or 0) - r["declared"])
        self.charged = sum(r["charge"] for r in self.rows)
        self.measured = sum(r["measured_total"] or 0 for r in self.rows)
        self.exclusive_cpus = {r["id"]: r["need"]["cpus"] for r in self.rows
                               if r["kind"] == "grant" and r["need"].get("cpus")}
        self.cards_held = {c: r["id"] for r in self.rows if r["kind"] == "grant"
                           for c in r["need"].get("cards", [])}
        self.nvme_lat, self.nvme_bulk = {}, {}
        for r in self.rows:
            if r["kind"] != "grant":
                continue
            for drive, mode in r["need"].get("nvme", {}).items():
                if mode == "lat":
                    self.nvme_lat[drive] = r["id"]
                else:
                    self.nvme_bulk.setdefault(drive, []).append(r["id"])
        if mem is None:
            self.blind = "memory is unreadable (%s)" % (mem_why or "no reading this tick")
            self.mem_total = self.mem_avail = self.unowned = self.g = None
            self.free = None
            return
        self.mem_total, self.mem_avail = mem["MemTotal"], mem["MemAvailable"]
        # what the kernel says is used, less what the holders' own cgroups account for; it
        # cannot go below the OS's own share, which is measured once and carried in the config
        self.unowned = max(0, self.mem_total - self.mem_avail - self.measured)
        self.g = self.mem_total - max(cfg.os_other, self.unowned) - cfg.headroom
        self.free = self.g - self.charged - held_back

    def by_id(self, rid):
        return next((r for r in self.rows if r["id"] == rid), None)

    def holder_text(self, row):
        return "%s %s %s %s since %s" % (row["id"], row["klass"], row["holder"],
                                         row.get("unit") or "-", row.get("since") or "?")

    def cpu_free(self):
        taken = {c for cpus in self.exclusive_cpus.values() for c in cpus}
        return [c for c in self.cfg.cpus if c not in taken]

    def line(self, name, klass, refusal):
        """The one refusal line: who is refused, for what, held by whom, and the numbers that
        explain the unowned part of the box. A refusal with no holder in the ledger (a card lock,
        a hold) carries its own text for who."""
        tail = "; headroom %s" % gb(self.cfg.headroom)
        if self.unowned is not None:
            tail = "; unowned %s%s" % (gb(self.unowned), tail)
        row = self.by_id(refusal.holder)
        held = " — held by %s" % self.holder_text(row) if row else ""
        return "boxres: %s (class %s) refused rc 75: %s%s%s" % (name, klass, refusal.text, held, tail)

    def check(self, need, kind, skip_cards=()):
        """The refusals of this need beside the holders now: RAM against G less the charges,
        cpus against the exclusive sets, cards held by a grant, nvme bulk against lat. [] fits.
        `skip_cards` are cards the caller checks itself (a job's lane)."""
        out = []
        total = declared_total(need)
        if total and self.blind is None and total > self.free:
            top = max(self.rows, key=lambda r: r["charge"], default=None)
            out.append(Refusal("ram", "ram needs %s, free %s of cap %s"
                               % (gb(total), gb(max(0, self.free)), gb(self.g)),
                               top["id"] if top else None))
        elif total and self.blind is not None:
            out.append(Refusal("ram-blind", "ram: %s" % self.blind, None))
        for card in need.get("cards", []):
            if card in skip_cards:
                continue
            if card in self.cards_held:
                out.append(Refusal("card.%s" % card, "card.%s is held by a grant" % card,
                                   self.cards_held[card]))
        mine = set(need["cpus"]) if kind == "grant" and need.get("cpus") else set()
        for gid, cpus in self.exclusive_cpus.items():
            both = sorted(mine & set(cpus))
            if both:
                out.append(Refusal("cpu", "cpus %s are held by an exclusive set" % fmt_cpus(both), gid))
        for drive, mode in need.get("nvme", {}).items():
            if mode == "bulk" and drive in self.nvme_lat:
                out.append(Refusal("nvme.%s" % drive, "%s bulk is refused while a latency holder is up"
                                   % drive, self.nvme_lat[drive]))
            if mode == "lat" and self.nvme_bulk.get(drive):
                out.append(Refusal("nvme.%s" % drive, "%s latency is refused while bulk IO runs"
                                   % drive, self.nvme_bulk[drive][0]))
        return out

    def view(self):
        """The ledger as /ledger shows it (the daemon adds cards, holds and waiters)."""
        cfg = self.cfg
        ram = {"os_other": cfg.os_other, "headroom": cfg.headroom, "charged": self.charged,
               "measured": self.measured, "held_back": self.held_back}
        if self.blind:
            ram["blind"] = self.blind
        else:
            ram.update(mem_total=self.mem_total, mem_available=self.mem_avail,
                       unowned=self.unowned, g=self.g, free=self.free)
        return {
            "ram": ram,
            "cpu": {"all": fmt_cpus(cfg.cpus), "free": fmt_cpus(self.cpu_free()),
                    "exclusive": {gid: fmt_cpus(c) for gid, c in self.exclusive_cpus.items()}},
            "nvme": {d: {"lat": self.nvme_lat.get(d), "bulk": self.nvme_bulk.get(d, [])}
                     for d in cfg.nvme},
            "holders": [{
                "id": r["id"], "kind": r["kind"], "holder": r["holder"], "class": r["klass"],
                "owner": r.get("owner"), "unit": r.get("unit"), "since": r.get("since"),
                "state": r["state"], "need": r["need"], "declared": r["declared"],
                "measured": r["measured_total"], "charge": r["charge"],
                "over_by": r["over_by"], "over": r["over_by"] > 0,
                "text": r.get("text"),
            } for r in self.rows],
        }
