"""The loop: one process runs ready beads one after another, each through `tl run-task` in any free slot.

    tl.py next [--repo DIR] [--json]          what the loop would take next, and why (claims nothing)
    tl.py loop [--repo DIR] [--max-beads N] [--until HH:MM] [--wait-slot-min M] [--wait-drained]
    tl.py loop status [--repo DIR] [--last N] what runs now and the last beads
    tl.py stop [--repo DIR] [--now]           every loop on the repo stops after its bead, or now (close runs)

The queue rule lives in the repo's .task-loop.json (engine.pick_label, skip_labels, epic_order, epic_only, areas,
area_label_prefix): ready beads with the pick label, minus skip labels, epics, slots and beads whose area runs elsewhere;
then priority, epic order, lowest id. Python 3.8+, standard library only.
"""

import contextlib
import datetime
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import applog
import beadlint
import delegate_link as dl
import engine
import seams
import loop_health
import netgate
import outcome as oc
import tl
from taskloop.contracts.ports import BeadPatch, BeadQuery

POLL = 2               # seconds between looks at a running child (stop file, slot heartbeat)
HEARTBEAT = 60         # the slot bead's lease is kept alive this often while a bead runs
DRAINED_POLL = 300     # --wait-drained: how often an empty queue is looked at again
SELFTEST_WAIT = 30     # a newer install must pass `tl.py selftest` (a few seconds of work) within this long
HELP_WAIT = 20         # a newer install must answer `tl.py --help` within this long to be moved to
PAUSE_RETRY = 900      # a bead another session holds, or a pause with no delegate to ask about its role: try it again after this.
                       # A network pause is not here: it is probed every NET_PROBE s (tl-kyy); a lane pause waits on its role (GateRole)
GATE_CACHE_S = 30      # delegate's role view is looked at no more often than this
GATE_UNKNOWN_S = 900   # a role whose usability delegate cannot say (unknown) is tried again after this long: unknown fails open
NET_PROBE = netgate.PROBE_EVERY  # while the network is down the loop claims nothing and looks every this many seconds
BEAT_EVERY = 60        # the loop's state file carries a beat, refreshed at most this often (tl-7y6.2.12)
LOGS_KEPT = 5          # loop-<pid>.log files kept per repo
SLOT_FAILS_TO_SET_ASIDE = 2  # instant failures in a row on one slot that set the slot aside (tl-g6a); not the loop's stop count
QUICK_FAIL_MIN = 1.5           # a failed run shorter than this, in minutes, is an instant failure
SLOT_FAILURE = re.compile(r"worktree \S+ has uncommitted work|did not give a clean tree|index\.lock|not a git repository|could not commit the leftover", re.I)  # the slot's own git state
SLOT_ASIDE_MIN = 720           # minutes a slot set aside stays held
FAILS_TO_STOP = 2      # runs in a row that gave no verdict (run-task died with no outcome) that stop the loop. A run that gave a Kind
                       # is the storm detector's (a FAULT_* cools its bead, the same fingerprint on two beads stops every loop);
                       # parks and pauses never count, a landing ends the run
PAUSES_TO_REST = 3     # a bead paused this often in one loop run rests for REST while the loop takes others: a role that is usable
                       # and still pauses the bead is not a lane to wait for
REST = 3600
AREA_POLL = 60         # every ready bead waits for its area: look again this often

clock = time.time
STOP_NOW = threading.Event()  # SIGTERM or Ctrl-C to the loop itself: end the running bead as `tl stop --now` does


# ---- the queue rule -------------------------------------------------------------------------------------------------

def natural(bead_id):
    """fld.26.9 before fld.26.10: digit runs compare as numbers (split keeps text and numbers at the same places)."""
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", bead_id)]


def epics_of(bead, cache, store=None):
    """Every ancestor of a bead, nearest first; `parent` in bd's JSON is the direct one only."""
    out, pid = [], bead.parent
    while pid and pid not in out:
        out.append(pid)
        if pid not in cache:
            cache[pid] = getattr(tl.peek(store or tl.bd_store(), pid), "parent", None)
        pid = cache[pid]
    return out


# ---- areas (tl-bxk.11.4): two beads of one area never run at once ---------------------------------------------------

def has_areas(cfg):
    return bool(cfg.areas or cfg.area_label_prefix)


def area_of(b, cfg, cache, store=None):
    """The bead's area, "" for none (unrestricted). engine.areas {area: [epic id or label, ...]} first, in its order:
    the bead, any of its ancestors or one of its labels named; then the first label with engine.area_label_prefix
    (lane:live is area live). First match wins."""
    labels = b.labels
    ups = None
    for name, members in cfg.areas.items():
        if ups is None:
            ups = [b.id] + epics_of(b, cache, store)
        if any(m in ups or m in labels for m in members or []):
            return name
    prefix = cfg.area_label_prefix
    if prefix:
        for x in labels:
            if x.startswith(prefix) and len(x) > len(prefix):
                return x[len(prefix):]
    return ""


def lapsed(b):
    t = b.lease_expires_at
    return bool(t) and t < time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def running(repo, store=None):
    """{bead: where} of the beads running now: a slot bead held for one (held_bead), or a live engine lock naming
    one, in a slot or any worktree of the repo."""
    out, slots = {}, tl.slot_beads(repo, store)
    for b in slots:
        bid = b.metadata.get("held_bead")
        if bid and b.status == "in_progress" and not lapsed(b):
            out[bid] = b.title.split()[-1]
    for wt in tl.worktrees(repo, slots):
        lock = tl.read_engine_lock(wt)
        if lock.get("bead") and lock.get("pid") and tl.proc_alive(lock["pid"], lock.get("start") or ""):
            out.setdefault(lock["bead"], lock.get("slot") or Path(wt).name)
    return out


AREA_WAIT_SAY = 600  # seconds between the "still waiting on an area" lines

ANY_AREA = "*"  # busy_areas key for a running bead that could not be read


def busy_areas(repo, cfg, cache, but="", store=None):
    """{area: (bead, where)} of the areas a running bead (other than `but`) works in."""
    out = {}
    for bid, where in sorted(running(repo, store).items()):
        if bid == but:
            continue
        held = tl.peek(store or tl.bd_store(repo), bid)
        if not held:  # its area is unknown: it may be any, so every area waits (a slot hung on a bd error stays visible)
            say("running bead %s in %s is unreadable (bd show failed): every area counts as busy" % (bid, where))
            out.setdefault(ANY_AREA, (bid, where))
            continue
        a = area_of(held, cfg, cache, store)
        if a:
            out.setdefault(a, (bid, where))
    return out


def area_busy(repo, cfg, b, cache, store=None):
    """(area, "area A busy: B in S") for a bead whose area runs elsewhere, (area, "") when it is free, ("", "")."""
    a = area_of(b, cfg, cache, store)
    if not a:
        return "", ""
    busy = busy_areas(repo, cfg, cache, but=b.id, store=store)
    hit = busy.get(a) or busy.get(ANY_AREA)
    return a, ("area %s busy: %s in %s" % (a, hit[0], hit[1]) if hit else "")


def area_lock(repo, cfg):
    """One area check and the mark that follows it at a time per repo (the loop's claim, run-task's engine lock): two
    takers never both see an area free. A no-op without areas."""
    if not has_areas(cfg):
        return contextlib.nullcontext()
    return tl.os_lock(tl.config_dir() / "locks" / ("area-%s.lock" % tl.repo_key(repo)), "pid %d" % os.getpid())


def queue(repo, store=None):
    """([(bead, reason)] in the order the loop takes them, [(id, why skipped)]). A reason names the rule that puts a
    bead before the next one. Fetches first: the rule is read from the base branch (engine.load_cfg). A bead whose
    area runs elsewhere is skipped (`area A busy: B in S`); the claim checks again under the area lock."""
    tl.fetch(repo)
    cfg = engine.load_cfg(repo)
    store = store or tl.bd_store(repo)
    ready = tl.listed(store.ready, cfg.pick_label)
    order, skip = list(cfg.epic_order), list(cfg.skip_labels)
    keep, skipped, cache = [], [], {}
    for b in ready:
        labels = b.labels
        hit = next((x for x in skip if x in labels), None)
        why = ("an epic" if b.issue_type == "epic" else "a slot" if "slot" in labels
               else "label " + hit if hit else "")
        rank = len(order)
        if not why and order:
            ups = epics_of(b, cache, store)
            rank = min([order.index(e) for e in ups if e in order] or [len(order)])
            if rank == len(order) and cfg.epic_only:
                why = "under no epic in epic_order (epic_only)"
        if not why:
            why = beadlint.why(b, str(repo))
        if why:
            skipped.append((b.id, why))
        else:
            keep.append((b.priority if b.priority is not None else 2, rank, natural(b.id), b))
    keep.sort(key=lambda k: k[:3])
    if has_areas(cfg) and keep:
        busy, free = busy_areas(repo, cfg, cache, store=store), []
        for k in keep:
            hit = busy.get(area_of(k[3], cfg, cache, store)) or (busy.get(ANY_AREA) if area_of(k[3], cfg, cache, store) else None)
            if hit:
                skipped.append((k[3].id, "area %s busy: %s in %s" % (area_of(k[3], cfg, cache, store), hit[0], hit[1])))
            else:
                free.append(k)
        keep = free
    ranked = []
    for i, k in enumerate(keep):
        if i + 1 == len(keep):
            reason = "only candidate" if i == 0 else "last"
        elif k[0] != keep[i + 1][0]:
            reason = "priority P%d before P%d" % (k[0], keep[i + 1][0])
        elif k[1] != keep[i + 1][1]:
            reason = "epic %s (%s in epic_order)" % (order[k[1]], ordinal(k[1] + 1))
        else:
            reason = "lowest id"
        ranked.append((k[3], reason))
    return ranked, skipped


def ordinal(n):
    return "%d%s" % (n, "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def cmd_next(a):
    repo = tl.repo_root(a.repo)
    ranked, skipped = queue(repo)
    if a.json:
        print(json.dumps({"pick": engine.dataclasses.asdict(ranked[0][0]) if ranked else None, "reason": ranked[0][1] if ranked else "",
                          "next": [{"id": b.id, "priority": b.priority, "reason": r} for b, r in ranked[1:6]],
                          "skipped": [{"id": i, "why": w} for i, w in skipped]}, ensure_ascii=False))
        return 0 if ranked else 1
    if not ranked:
        print("NONE: no ready bead in the queue")
    for n, (b, r) in enumerate(ranked[:6]):
        print("%s %s  P%s  %s  (%s)" % ("NEXT" if n == 0 else "then", b.id, b.priority, b.title[:70], r))
    for i, w in skipped:
        print("skip %s: %s" % (i, w))
    return 0 if ranked else 1


# ---- state: per loop, under the config dir; several loops may run on one repo (tl-bxk.11.1) --------------------------

def paths(repo):
    """The repo's files: one stop file, one log and one rest file for all its loops; `state` is this process's own.
    (`rest` is not <key>.*.json: live_loops reads those as loop states.)"""
    d = tl.config_dir() / "loop"
    d.mkdir(exist_ok=True)
    key = "%s-%s" % (Path(repo).name, hashlib.sha1(repo.encode()).hexdigest()[:8])
    return {"state": d / ("%s.%d.json" % (key, os.getpid())), "states": (d, key),
            "stop": d / (key + ".stop"), "rest": d / (key + "-rest.json"), "log": d / (key + ".jsonl"), "runs": d / key}


def read_state(repo):
    try:
        return json.loads(paths(repo)["state"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(repo, **st):
    d, key = paths(repo)["states"]
    f = d / ("%s.%d.json" % (key, st.get("pid") or os.getpid()))
    tmp = f.with_suffix(".tmp")
    st = dict({"beat": clock(), "log": str(LOG[0] or "")}, **st)  # every write is a sign of life; the log path outlives the session
    tmp.write_text(json.dumps(dict(st, repo=repo, version=tl.HERE.parents[1].name, code_dir=str(tl.HERE))), encoding="utf-8")
    os.replace(tmp, f)


def read_rests(repo):
    """{bead: when it may run again} for the beads that failed before their engine started, shared by every loop on the repo."""
    try:
        rests = json.loads(paths(repo)["rest"].read_text(encoding="utf-8"))
        return {b: float(t) for b, t in rests.items() if float(t) > clock()}
    except (OSError, ValueError, AttributeError):
        return {}


def rest_bead(repo, bead_id, until):
    f = paths(repo)["rest"]
    with tl.os_lock(f.with_name(f.name + ".lock"), "pid %d" % os.getpid()):
        rests = read_rests(repo)
        rests[bead_id] = until
        tmp = f.with_name(f.name + ".%d.tmp" % os.getpid())
        tmp.write_text(json.dumps(rests), encoding="utf-8")
        os.replace(tmp, f)


def live_loops(repo, but=None):
    """The states of the repo's live loops (`but`: leave this pid out), oldest first; a dead loop's file is removed."""
    d, key = paths(repo)["states"]
    out = []
    for f in d.glob(key + ".*.json"):
        try:
            st = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not pid_alive(st.get("pid")):
            with contextlib.suppress(OSError):  # a loop that died with no exit line leaves its state as evidence (a SIGKILL, a reboot)
                paths(repo)["runs"].mkdir(exist_ok=True)
                os.replace(f, paths(repo)["runs"] / ("died-%s.json" % st.get("pid")))
        elif st.get("pid") != but:
            out.append(st)
    return sorted(out, key=lambda st: st.get("started") or 0)


pid_alive = tl.pid_alive


SESSION_ACTOR = [""]  # the session's actor, without this loop's suffix: names the session's slots-off worktree
START_CWD = [""]  # the directory the loop was started in: where its argv's relative paths point


@contextlib.contextmanager
def stop_lock(repo):
    """Serialize stop capture with loop registration, removal and request cleanup."""
    f = paths(repo)["stop"]
    with tl.os_lock(f.with_name(f.name + ".lock"), "pid %d" % os.getpid()):
        yield


def read_stop(repo):
    """The targeted stop request ({mode: after|now, targets: [pids], time}), or {} when none is filed or it is unreadable."""
    try:
        request = json.loads(paths(repo)["stop"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if (isinstance(request, dict) and request.get("mode") in ("after", "now") and isinstance(request.get("targets"), list)
            and isinstance(request.get("time"), (int, float))):
        return request
    return {}


def stop_for(request, pid):
    """The mode of a stop request that names this loop's pid, else ''."""
    return request["mode"] if request and pid in request["targets"] else ""


def clean_stop(repo, loops):
    """Caller holds stop_lock. Keep requests still needed by any live target."""
    request = read_stop(repo)
    if not request:
        return
    if not any(st["pid"] in request["targets"] for st in loops):
        with contextlib.suppress(FileNotFoundError):
            paths(repo)["stop"].unlink()


def stop_mode(repo):
    """'now', 'after' (stop after the current bead) or '' (go on)."""
    if STOP_NOW.is_set():
        return "now"
    return stop_for(read_stop(repo), os.getpid())


def nap(secs, repo=None, until=0):
    """Sleep, waking early for a stop or the end time."""
    end = clock() + secs
    while clock() < end and not (repo and stop_mode(repo)) and not (until and clock() >= until):
        if repo:
            touch_beat(repo)
        time.sleep(min(POLL, max(0.05, end - clock())))


def touch_beat(repo):
    """The loop is alive: stamp `beat` in its state file, at most every BEAT_EVERY s. Liveness itself is the pid; the beat is
    how long ago a loop last looked, for the absent-loop line."""
    st = read_state(repo)
    if st and clock() - float(st.get("beat") or 0) >= BEAT_EVERY:
        write_state(repo, **dict({k: v for k, v in st.items() if k not in ("repo", "version", "code_dir")}, beat=clock()))


class GateRole:
    """What a paused bead waits for (tl-7y6.2.8): its role, not a clock. delegate's `route.py status --json` roles[role].usable says
    True (wake), False (keep waiting) or None (unknown: wake once the bead has waited GATE_UNKNOWN_S). The bead's own retry_after is
    a hint and never blocks. The view is cached GATE_CACHE_S. Loop-local: nothing is written to a bead, a label or a file by this
    class, and the held beads travel only in the loop's own state across a move to a newer install."""

    def __init__(self, route_fn, now=None):
        self.route_fn, self.now = route_fn, now or (lambda: clock())
        self.held = {}              # bead -> [role, since]
        self.seen = (None, {})      # (when the view was read, roles)

    def hold(self, bead, role):
        self.held[bead] = [role, self.now()]

    def view(self):
        t = self.now()
        if self.seen[0] is None or t - self.seen[0] >= GATE_CACHE_S:
            route = self.route_fn()
            self.seen = (t, dl.role_status(route) if route else {})
        return self.seen[1]

    def usable(self, role):
        """True, False or None (delegate does not say)."""
        v = (self.view().get(role) or {}).get("usable")
        return v if isinstance(v, bool) else None

    def ready(self, bead):
        """True when `bead` is not held, or its role is usable now, or its role has been unknown long enough."""
        if bead not in self.held:
            return True
        role, since = self.held[bead]
        u = self.usable(role)
        if u is True or (u is None and self.now() - since >= GATE_UNKNOWN_S):
            del self.held[bead]
            return True
        return False

    def next_look(self, bead):
        """When `bead` is worth asking about again (epoch)."""
        role, since = self.held[bead]
        t = (self.seen[0] or self.now()) + GATE_CACHE_S
        return min(t, since + GATE_UNKNOWN_S) if self.usable(role) is None else t


LOG = [None]  # this loop's own log file: what say() prints is kept after the session that started the loop is gone


def say(text):
    line = "[%s] loop: %s" % (time.strftime("%H:%M:%S", time.localtime(clock())), text)
    engine.say(line)
    if LOG[0]:
        with contextlib.suppress(OSError):
            applog.append(LOG[0], line + "\n")


def open_log(repo):
    """loop-<pid>.log under the repo's runs dir (the newest LOGS_KEPT stay); its path is shown by `tl loop status`."""
    d = paths(repo)["runs"]
    d.mkdir(exist_ok=True)
    LOG[0] = d / ("loop-%d.log" % os.getpid())
    old = sorted((f for f in d.glob("loop-*.log") if f != LOG[0]), key=lambda f: f.stat().st_mtime)
    for f in old[:max(0, len(old) - (LOGS_KEPT - 1))]:
        with contextlib.suppress(OSError):
            f.unlink()
    return LOG[0]


# ---- one bead -------------------------------------------------------------------------------------------------------

class Beat:
    """Keeps the slot bead's and the task bead's leases alive from the slot take to the release: a slow slot setup
    (lifesim: 5-12 min) outlasts a 5-minute lease. run-task heartbeats both too, so a SIGKILLed loop leaves no slot free
    under a live run."""

    def __init__(self, store, *ids):
        self.store = store
        self.ids, self.every, self.ev = [i for i in ids if i], HEARTBEAT, threading.Event()
        self.th = threading.Thread(target=self.loop, daemon=True)
        self.th.start()

    def add(self, bead_id):
        self.ids.append(bead_id)

    def loop(self):
        while not self.ev.wait(self.every):
            for i in list(self.ids):
                tl.attempt(self.store.heartbeat, i)

    def stop(self):
        self.ev.set()

def spawn(cmd, log):
    """run-task as a child in its own process group: Ctrl-C to the loop reaches it only as the loop's SIGTERM."""
    kw = {"stdin": subprocess.DEVNULL, "stdout": log, "stderr": subprocess.STDOUT}
    kw["start_new_session"] = True
    return subprocess.Popen(cmd, **kw)


def prepare(repo, slot, bead_id):
    """A slot gets a clean tree on the bead's branch (leftover work committed, never wiped); see tl slot reset.
    Returns (rc, why): why is git's error line when the reset failed."""
    a = engine.Args(op="reset", name=slot, bead=bead_id, n=None, force=False)
    rc = tl.cmd_slot(a)
    return rc, getattr(a, "error", "")


def landed_on_base(repo, wt, bead_id, store=None):
    """True when the bead's land commit (titled `... (<id>)`) is the tip of its branch and already on the base."""
    if not os.path.isdir(wt):
        return False
    base = engine.load_cfg(repo).base
    branch = getattr(tl.peek(store or tl.bd_store(repo), bead_id), "metadata", {}).get("branch") or "task/" + bead_id
    tl.fetch(wt)
    tip = tl.git("rev-parse", "--verify", "-q", "refs/heads/" + branch, cwd=wt)
    if not tip or not tl.git("log", "-1", "--format=%s", tip, cwd=wt).endswith("(%s)" % bead_id):
        return False
    return tl.run_git(wt, "merge-base", "--is-ancestor", tip, base, capture_output=True).returncode == 0


def run_bead(repo, b, slot, wt, slot_bead, started, code=None):
    """One bead through `tl run-task` as a child; returns its outcome record (failed when it gave none). code: the
    task-loop dir to run from (the fallback after a crash-after-exec; default this loop's own)."""
    runs = paths(repo)["runs"]
    runs.mkdir(exist_ok=True)
    stem = "%s-%s" % (b.id, time.strftime("%Y%m%d-%H%M%S", time.localtime(clock())))
    out, log_path = runs / (stem + ".outcome.json"), runs / (stem + ".log")
    cmd = [sys.executable, str((code or tl.HERE) / "tl.py"), "run-task", b.id, "--worktree", wt, "--outcome-file", str(out)]
    cmd += ["--slot", slot] if slot else []
    t0 = clock()
    os.environ["TASK_LOOP_SLOT_BEAD"] = slot_bead or ""  # the engine heartbeats it too (see Beat)
    with open(log_path, "ab") as log:  # append: a rerun of the same stem never cuts a log another reader follows
        p = spawn(cmd, log)
        write_state(repo, pid=os.getpid(), started=started, bead=b.id, slot=slot, since=t0, child=p.pid,
                    run_log=str(log_path), worktree=None if slot else wt)
        say("%s in %s (log %s)" % (b.id, slot or wt, log_path))
        stopped = False
        try:
            while True:
                try:
                    rc = p.wait(timeout=POLL)
                    break
                except subprocess.TimeoutExpired:
                    pass
                touch_beat(repo)
                if not stopped and stop_mode(repo) == "now":
                    say("stop now: SIGTERM to %s (its close step still runs)" % b.id)
                    p.terminate()  # SIGTERM on POSIX, which the engine traps; TerminateProcess on Windows
                    stopped = True
        except BaseException:  # the loop itself broke: the run ends (its close step runs) before the slot is freed
            p.terminate()
            p.wait()
            raise
    try:
        r = json.loads(out.read_text(encoding="utf-8"))
        gave = True
    except (OSError, ValueError):
        r = {"outcome": "failed", "why": "failed: no outcome from run-task (exit %s); see %s" % (rc, log_path)}
        gave = False
    moved = engine.read_reexec(b.id)  # the engine exec'd into a newer install and left this note; a clean end removes it
    engine.drop_reexec(b.id)
    if moved and not gave and not stopped and rc not in (0, None) and code is None and time.time() - float(moved.get("t") or 0) < engine.RELOAD_FALLBACK_S:
        back = Path(moved.get("from_dir") or "")
        if (back / "tl.py").is_file():  # died within RELOAD_FALLBACK_S of the exec: that version is refused, once more on the old one
            why = "run-task died (exit %s) %d s after the exec into it" % (rc, time.time() - float(moved.get("t") or 0))
            record_bad_version(str(moved.get("to")), why)
            tl.event("reload_fallback", b.id, who="loop", old=moved.get("to"), new=moved.get("from"), why=why, run=moved.get("run"))
            say("RED: %s died after the move to task-loop %s; %s goes on from its checkpoint on %s" % (b.id, moved.get("to"), b.id, moved.get("from")))
            os.environ["TL_REEXEC"] = json.dumps({"run": moved.get("run"), "bead": b.id, "from": moved.get("to"), "owned": "", "fallback": True})
            try:
                return run_bead(repo, b, slot, wt, slot_bead, started, code=back)
            finally:
                os.environ.pop("TL_REEXEC", None)  # the fallback run took it; no later run-task of this loop may inherit it
    if stopped and r.get("outcome") == "failed":  # a stop is no verdict on the bead: back to the queue, unclaimed,
        if landed_on_base(repo, wt, b.id):     # unless the stop came during a land that went through
            r["why"] = "%s; its land commit is on the base: not reopened, close it by hand" % (r.get("why") or "stopped")
        else:
            tl.attempt(tl.bd_store(repo).update, b.id, BeadPatch(status="open", assignee=""))
    r.setdefault("minutes", round((clock() - t0) / 60, 1))
    r["run_log"] = str(log_path)
    return r


def record(repo, bead_id, slot, r):
    line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(clock())), "bead": bead_id, "slot": slot,
            "outcome": r.get("outcome"), "minutes": r.get("minutes", 0), "rounds": r.get("rounds"),
            "tests_added": r.get("tests_added"), "asked": bool(r.get("asked")), "trace": r.get("run"),
            "engine_log": r.get("log"), "run_log": r.get("run_log"), "why": (r.get("why") or "")[:300]}
    applog.append(paths(repo)["log"], json.dumps(line, ensure_ascii=False) + "\n")
    say("%s %s%s" % (bead_id, line["outcome"], (": " + line["why"][:160]) if line["why"] else ""))


# ---- the loop -------------------------------------------------------------------------------------------------------

def version_key(name):
    """(1, 2, 3) for a version dir name like 0.23.6; None for anything else (a dev checkout, a cache scrap)."""
    return tuple(int(x) for x in name.split(".")) if re.fullmatch(r"\d+(\.\d+)*", name) else None


def newest_install(skip=()):
    """(version, dir) of the pinned sibling version dir (pinned.json) when it is not the running one; without a pin the
    newest sibling version dir of this plugin root when it is newer than the running one, else None. A root that is no version dir (a dev checkout) never moves."""
    root = tl.HERE.parents[1]
    mine = version_key(root.name)
    if mine is None:
        return None
    pinned = tl.read_pin().get("task-loop")  # the owner's pin (tl pin): that version, newer or older; never a newer one
    if pinned:
        d = root.parent / str(pinned)
        k = version_key(str(pinned))
        return (d.name, d) if k and k != mine and d.is_dir() and d.name not in skip else None
    best = None
    with contextlib.suppress(OSError):
        for d in root.parent.iterdir():
            k = version_key(d.name)
            if k and k > mine and d.name not in skip and d.is_dir() and (best is None or k > best[0]):
                best = (k, d)
    return (best[1].name, best[1]) if best else None


def complete(d):
    """None when the install in `d` looks usable, else why not: its plugin.json and tl.py, loop.py and engine.py exist
    and import (a half-copied file fails here, `--help` alone exits before loop and engine load), within HELP_WAIT s,
    and `tl.py selftest` passes (an install that imports but cannot plan a bead is refused and recorded)."""
    if not (d / ".claude-plugin" / "plugin.json").is_file():
        return "plugin.json is missing"
    here = d / "skills" / "task-loop"
    for f in ("tl.py", "loop.py", "engine.py"):
        if not (here / f).is_file():
            return "%s is missing" % f
    code = "import sys; sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2]); import tl, loop, engine"
    try:
        r = subprocess.run([sys.executable, "-I", "-c", code, str(here), str(d / "src")], stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=HELP_WAIT)
    except subprocess.TimeoutExpired:
        return "importing tl, loop, engine did not finish in %d s" % HELP_WAIT
    except OSError as e:
        return "python did not start: %s" % e
    if r.returncode != 0:
        why = "importing tl, loop, engine exited %d" % r.returncode
        record_bad_version(d.name, why)
        return why
    why = selftest_of(here)
    if why:
        why = "selftest failed: " + why
        record_bad_version(d.name, why)
    return why


def selftest_of(here):
    """None when `tl.py selftest` of the install at `here` passes, else the tail of what it said."""
    try:
        r = subprocess.run([sys.executable, str(here / "tl.py"), "selftest"], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=SELFTEST_WAIT, cwd=here)
    except subprocess.TimeoutExpired:
        return "did not finish in %d s" % SELFTEST_WAIT
    except OSError as e:
        return "python did not start: %s" % e
    if r.returncode == 0:
        return None
    return "exit %d: %s" % (r.returncode, ((r.stderr or "") + (r.stdout or "")).strip()[-300:])


def record_bad_version(version, why):
    """bad-versions.json in the config dir: {version: {"why", "at", "seen_by"}}, the installs a loop refused."""
    f = tl.config_dir() / "bad-versions.json"
    try:
        bad = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        bad = {}
    if not isinstance(bad, dict):
        bad = {}
    bad[version] = {"why": why[:400], "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                    "seen_by": tl.HERE.parents[1].name, "key": install_key(tl.HERE.parents[1].parent / version)}
    tmp = f.with_name(f.name + ".%d.tmp" % os.getpid())
    try:
        tmp.write_text(json.dumps(bad, indent=1), encoding="utf-8")
        os.replace(tmp, f)
    except OSError:
        pass  # the refusal stands; only its record is lost


def install_key(d):
    """Size and mtime of the install's tl.py, loop.py and engine.py: a version re-installed under the same number differs."""
    out = []
    for f in ("tl.py", "loop.py", "engine.py"):
        try:
            st = (d / "skills" / "task-loop" / f).stat()
        except OSError:
            return ""
        out.append("%d:%d" % (st.st_size, st.st_mtime_ns))
    return ",".join(out)


def bad_versions():
    """The version names bad-versions.json refuses: an entry holds while the install's key is the one recorded (an entry
    without a key holds for good). A refused version is not tested again at every step boundary."""
    try:
        bad = json.loads((tl.config_dir() / "bad-versions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    root = tl.HERE.parents[1].parent
    return {v for v, rec in (bad.items() if isinstance(bad, dict) else ())
            if not isinstance(rec, dict) or not rec.get("key") or rec["key"] == install_key(root / v)}


def vet_newer(skip=()):
    """(version, dir, why) for the newest install above the running one that is not refused: why is None when it is usable
    (complete() passed, selftest included), else what failed (and the version is now in bad-versions.json). None when
    there is nothing newer to look at. One test per call; the caller is a step boundary."""
    found = newest_install(set(skip) | bad_versions())
    if not found:
        return None
    return found[0], found[1], complete(found[1])


def pin_aware(d):
    """True when the install in `d` reads pinned.json when it picks its version (loop.py names read_pin)."""
    try:
        return "read_pin" in (d / "skills" / "task-loop" / "loop.py").read_text(encoding="utf-8")
    except OSError:
        return False


def maybe_move(a, repo, state):  # returns True when a stop arrived during the check: the caller looks at it first
    """Between beads: exec the newest complete install with the loop's own argv and `state` (TL_LOOP_STATE). The pid
    stays, so what is keyed by it (slot line, state file, stop file readers) carries over. A broken install is warned
    about once per version and never stops the loop."""
    if getattr(a, "pin", False) or not getattr(a, "argv", None):
        return
    try:
        found = vet_newer(state["warned"])  # a version that failed is not looked at again (bad-versions.json)
        if not found:
            return
        ver, d, why = found
        if why:
            state["warned"].append(ver)
            say("warn: not moving to %s: %s; staying on %s" % (ver, why, tl.HERE.parents[1].name))
            tl.event("reload_refused", "", who="loop", version=ver, why=why[:300], running=tl.HERE.parents[1].name)
            return
        if STOP_NOW.is_set() or stop_mode(repo):  # the check took a while; a stop written meanwhile is read by this process
            return True
        say("moving to %s (was %s)" % (ver, tl.HERE.parents[1].name))
        tl.event("reload", "", who="loop", old=tl.HERE.parents[1].name, new=ver, code_dir=str(d))
        os.environ["TL_LOOP_STATE"] = json.dumps(state)
        if START_CWD[0]:
            os.chdir(START_CWD[0])  # cmd_loop chdir'd into the repo; a relative --repo in argv means the start directory
        sys.stdout.flush()
        sys.stderr.flush()
        argv = list(a.argv)
        if tl.read_pin().get("task-loop") and "--pin" not in argv and not pin_aware(d):
            argv.append("--pin")  # an install from before pins would move straight back to the newest one
        applog.close_all()
        os.execv(sys.executable, [sys.executable, str(d / "skills" / "task-loop" / "tl.py"), *argv])
    except OSError as e:  # execv itself failed: the loop goes on where it is
        os.environ.pop("TL_LOOP_STATE", None)
        with contextlib.suppress(OSError):
            os.chdir(repo)
        say("warn: could not move: %s" % e)


def inherited():
    """The state an older version of this loop handed over through TL_LOOP_STATE ({} on a fresh start); a field of the
    wrong type is dropped with a warning, never trusted."""
    raw = os.environ.pop("TL_LOOP_STATE", "")
    try:
        st = json.loads(raw) if raw else {}
    except ValueError:
        st = None
    if raw and not isinstance(st, dict):
        say("warn: TL_LOOP_STATE is not a JSON object: ignored")
        return {}
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)  # noqa: E731
    text = lambda v: isinstance(v, str)  # noqa: E731
    ok = {"fails": lambda v: isinstance(v, list) and all(map(text, v)),
          "warned": lambda v: isinstance(v, list) and all(map(text, v)),
          "ran": lambda v: isinstance(v, int) and not isinstance(v, bool),
          "later": lambda v: isinstance(v, dict) and all(text(k) and num(x) for k, x in v.items()),
          "pauses": lambda v: isinstance(v, dict) and all(text(k) and isinstance(x, int) for k, x in v.items()),
          "gated": lambda v: isinstance(v, dict) and all(text(k) and isinstance(x, list) and len(x) == 2 and text(x[0]) and num(x[1])
                                                         for k, x in v.items()),
          "until": lambda v: v is None or num(v), "wt": lambda v: v is None or text(v),
          "actor": lambda v: v is None or text(v), "started": num}
    out = {}
    for k, v in st.items():
        if k in ok and ok[k](v):
            out[k] = v
        else:
            say("warn: TL_LOOP_STATE field %r has a bad value: dropped" % k)
    return out


def end_time(hhmm):
    """--until HH:MM: the next time it is that o'clock (tomorrow when it has passed today)."""
    if not hhmm:
        return 0
    h, m = (int(x) for x in hhmm.split(":"))
    now = datetime.datetime.fromtimestamp(clock())
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return (t if t > now else t + datetime.timedelta(days=1)).timestamp()


def acquire(repo, cfg, wait_min, until, prio=tl.DEFAULT_PRIO):
    """(name, dir, slot bead) of a free slot, waiting in the repo's slot line (tl.wait_slot: lowest priority number first, then first come)
    with backoff while none is; None on a stop or the end time."""
    since, told = clock(), [0.0]

    def waiting(ahead):
        if not told[0] or clock() - told[0] >= wait_min * 60:
            say("no free slot%s%s; waiting" % (" for this loop: %d ahead in line" % ahead if ahead else "",
                                               "" if not told[0] else " for %d min" % ((clock() - since) // 60)))
            told[0] = clock()
    return tl.wait_slot(repo, cfg, "tl loop", stop=lambda: bool(stop_mode(repo) or (until and clock() >= until)),
                        sleep=lambda secs: nap(secs, repo, until), poll=(5, min(30, max(5, wait_min * 60))),
                        on_wait=waiting, prio=prio)


def reclaim(repo, store=None):
    """A dead loop's or session's beads and slots back to ready: only claims of tl- actors (bd's lease rule decides
    which are dead), never a person's hand claim."""
    store = store or tl.bd_store(repo)
    held = tl.listed(store.find, BeadQuery(status="in_progress"))
    who = sorted({b.assignee for b in held if b.assignee.startswith("tl-")})
    if who:
        tl.attempt(store.reclaim, "15m", who)


def cmd_loop(a):
    if a.op == "status":
        return cmd_status(a)
    START_CWD[0] = os.getcwd()
    repo = tl.repo_root(a.repo)
    os.chdir(repo)  # every tl helper and bd call works on the current directory's repo
    st = inherited()  # set when this process is the same loop, exec'd into a newer install
    if not tl.session_id():  # without a Claude session the actor would be per folder: two loops would share it
        os.environ["TASK_LOOP_SESSION"] = "loop-" + uuid.uuid4().hex[:12]
    # an actor of its own, never the session's: bd lets an actor re-claim its own bead, so two loops (or a loop and a
    # hand run) started from one session would both win one claim. run-task re-claims as this actor (one for both).
    os.environ.pop("TASK_LOOP_ACTOR", None)
    SESSION_ACTOR[0] = tl.actor()
    os.environ["TASK_LOOP_ACTOR"] = st.get("actor") or "%s-%s" % (SESSION_ACTOR[0], uuid.uuid4().hex[:6])
    old = {}
    if threading.current_thread() is threading.main_thread():
        for sig in ("SIGTERM", "SIGINT"):
            if hasattr(signal, sig):
                old[sig] = signal.signal(getattr(signal, sig), lambda *_: STOP_NOW.set())
    STOP_NOW.clear()
    p = paths(repo)
    started = st.get("started", clock())
    open_log(repo)
    with stop_lock(repo):
        write_state(repo, pid=os.getpid(), started=started)
        clean_stop(repo, live_loops(repo))
    EXIT.clear()
    try:
        return passes(repo, a, started, st)
    finally:
        write_exit(repo, started)
        applog.close_all()  # tl-64i: the loop's log handles end with the loop
        with stop_lock(repo):
            with contextlib.suppress(FileNotFoundError):
                p["state"].unlink()
            clean_stop(repo, live_loops(repo))
        for sig, h in old.items():
            signal.signal(getattr(signal, sig), h)


EXIT = {}  # why passes() returned: {"reason": ..., "detail": ...}; empty when it did not (an exception, a signal)


def left(reason, detail=""):
    EXIT.update(reason=reason, detail=detail)


def write_exit(repo, started):
    """A loop that exits writes its reason (drained, until, max_beads, stop_request, signal, storm, crash) to the repo's
    exits file and its event log; `tl loop status` shows the last one. A loop that cannot (SIGKILL) leaves died-<pid>.json."""
    reason = EXIT.get("reason") or ("signal" if STOP_NOW.is_set() else "crash")
    rec = {"v": 1, "pid": os.getpid(), "repo": repo, "t": clock(), "started": started, "reason": reason,
           "detail": EXIT.get("detail", ""), "log_path": str(LOG[0] or "")}
    with contextlib.suppress(OSError):
        d = paths(repo)["runs"]
        d.mkdir(exist_ok=True)
        with open(d / "exits.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    with contextlib.suppress(Exception):
        tl.event("loop_exit", who="loop", repo=repo, pid=os.getpid(), reason=reason, detail=rec["detail"][:200])


def repo_id(repo):
    """The key the engine files a storm record under (engine.repo_id: the origin url, else the worktree)."""
    return tl.git("remote", "get-url", "origin", cwd=repo) or str(repo)


def live_storm(repo):
    return loop_health.read_storm(loop_health.storm_path(tl.config_dir(), repo_id(repo)), clock())


def storm_banner(rec, repo):
    return ("STOPPED: storm %s on %s; the beads stay open (look at their logs). Record %s expires %d min after it was written; "
            "delete it to start sooner" % (rec.get("fingerprint"), ",".join(rec.get("beads") or []),
                                           loop_health.storm_path(tl.config_dir(), repo_id(repo)), oc.KNOBS["storm_window_s"] // 60))


def delegate_route(repo):
    """The route.py of the delegate this repo's engine would use (its `delegate` config, the pin, the install), or None."""
    res = dl.resolve(engine.load_cfg(str(repo)).delegate)
    return res.route if isinstance(res, dl.Resolved) else None


def make_probe(repo):
    """delegate's `route.py net` as a NetProbe, or None when no delegate is installed (the old PAUSE_RETRY rest then)."""
    route = delegate_route(repo)
    return netgate.RouteProbe(route) if route else None


def worktree_name(repo):
    """Slots off: the session's worktree (loop-<session>), reused by each loop start; one another live loop of the
    repo works in gets this loop's own (loop-<session>-<suffix>): two loops in one tree reset it under each other."""
    name = SESSION_ACTOR[0][3:]
    taken = {st.get("worktree") for st in live_loops(repo, but=os.getpid())}
    if str(Path(repo) / ".worktrees" / ("loop-" + name)) in taken:
        return tl.actor()[3:]
    return name


def passes(repo, a, started, st=None, store=None):
    st, store = st or {}, store or tl.bd_store(repo)
    cfg, until = tl.profile_slots(repo), st.get("until") if "until" in st else end_time(a.until)
    slots = cfg.count > 0
    wt = st.get("wt")
    if not slots and wt:
        write_state(repo, pid=os.getpid(), started=started, worktree=wt)
    elif not slots:  # the pick and the state that names it, under a lock: two loops starting at once never pick one tree
        with tl.os_lock(tl.config_dir() / "locks" / ("worktree-%s.lock" % paths(repo)["states"][1]), "pid %d" % os.getpid()):
            wt = tl.start_worktree(repo, worktree_name(repo))
            write_state(repo, pid=os.getpid(), started=started, worktree=wt)
    area_wait = [0.0, 0.0]  # when every ready bead began waiting for an area, and when that was last said
    slot_quick = {}  # slot -> the beads that failed in an instant there, in a row
    fails, ran, later, pauses = [], 0, {}, {}  # later: a paused or taken bead -> when to try it again
    fails, ran = list(st.get("fails") or []), int(st.get("ran") or 0)  # kept across a move to a newer install
    later, pauses = dict(st.get("later") or {}), dict(st.get("pauses") or {})
    warned = list(st.get("warned") or [])
    net, net_first, net_down_t, probe = netgate.NetState(), [], [0.0], None  # tl-kyy: the network pause; probe made at the first one
    gate = GateRole(lambda: delegate_route(repo))  # a lane pause waits for its role to be usable, not for a clock
    gate.held = {k: list(v) for k, v in (st.get("gated") or {}).items()}
    while True:
        if stop_mode(repo):
            say("stopped on request after %d bead(s)" % ran)
            left("stop_request")
            return 0
        if until and clock() >= until:
            say("%s reached after %d bead(s)" % (a.until, ran))
            left("until")
            return 0
        if a.max_beads and ran >= a.max_beads:
            say("%d bead(s) run (--max-beads)" % ran)
            left("max_beads")
            return 0
        storm = live_storm(repo)  # another run (any loop) tripped the storm detector: nothing is claimed until it expires
        if storm:
            print(storm_banner(storm, repo))
            left("storm", storm.get("fingerprint") or "")
            return 2
        if net.down:  # tl-kyy: the network is down. No claim; a probe every NET_PROBE s; the same bead first when it is back
            if net.poll(probe, clock()) is None:
                nap(max(1.0, net.next_probe - clock()), repo, until)
                continue
            down_s = round(clock() - net_down_t[0])
            say("network is back after %d s: %s first" % (down_s, ", ".join(net_first) or "the queue"))
            tl.event("net_up", ",".join(net_first), who="loop", repo=repo, down_s=down_s)
        if maybe_move(a, repo, {"fails": fails, "ran": ran, "later": later, "pauses": pauses, "gated": gate.held, "warned": warned, "until": until,
                             "wt": wt, "actor": os.environ.get("TASK_LOOP_ACTOR"),
                             "started": started}):
            continue
        reclaim(repo, store)
        tl.close_stale_asks()  # asks of closed or missing beads (throttled)
        tl.park_stale_asks()  # asks unanswered past parks_at (3 days), throttled with the sweep above
        try:
            import reflect_digest
            reflect_digest.maybe_run()  # the run reflections into beads, once a day (tl-bl5)
        except Exception as e:
            say("reflect digest: %s" % e)
        ranked, skipped = queue(repo, store)
        now = clock()
        for rested, due in read_rests(repo).items():  # another loop's pre-engine failure rests the bead here too
            later[rested] = max(later.get(rested, 0), due)
        cands = [b for b, _ in ranked if later.get(b.id, 0) <= now and gate.ready(b.id)]
        cands.sort(key=lambda b: b.id not in net_first)  # a bead the network paused goes first, the same one (stable sort)
        net_first = [] if cands and cands[0].id not in net_first else net_first
        if cands:
            area_wait[0] = 0.0
        if not cands:
            if ranked:
                wake = min(gate.next_look(b.id) if b.id in gate.held and later.get(b.id, 0) <= now else later[b.id]
                           for b, _ in ranked)
                say("every ready bead waits for a lane or another session: looking again at %s"
                    % time.strftime("%H:%M:%S", time.localtime(wake)))
                nap(wake - now, repo, until)
                continue
            areas = [w for _, w in skipped if w.startswith("area ")]
            if areas:  # not drained: those beads run once their area frees; --until still ends the loop
                t = clock()
                if not area_wait[0]:
                    area_wait[0] = area_wait[1] = t
                    say("every ready bead waits for its area (%s): looking again in %d s" % ("; ".join(areas[:3]), AREA_POLL))
                elif t - area_wait[1] >= AREA_WAIT_SAY:  # a hung but live holder never frees it: say how long
                    area_wait[1] = t
                    m = re.match(r"area (\S+) busy: (\S+) in (\S+)", areas[0])
                    say("waiting %d min on area %s held by %s in %s" % ((t - area_wait[0]) // 60, *(m.groups() if m else (areas[0], "?", "?"))))
                nap(AREA_POLL, repo, until)
                continue
            area_wait[0] = 0.0
            if not a.wait_drained:
                print("DRAINED: no ready bead after %d bead(s)" % ran)
                left("drained")
                return 0
            nap(DRAINED_POLL, repo, until)
            continue
        prio = min(tl.prio_of(b) for b in cands)  # the best bead this loop would run
        got = acquire(repo, cfg, a.wait_slot_min, until, prio) if slots else (None, wt, None)
        if got is None:
            continue
        name, d, slot_bead = got
        r, bid = None, ""
        beat = Beat(store, slot_bead)
        try:
            if os.path.isdir(d):  # from the take to run-task's own lock: no hand run gets in, the slot reset included
                tl.loop_lock(d, name, slot_bead)
            ecfg, cache = engine.load_cfg(repo), {}
            for b in cands:
                bid = b.id
                with area_lock(repo, ecfg):  # the area check, the claim and the mark that makes the area busy: as one
                    area, busy = area_busy(repo, ecfg, b, cache, store) if has_areas(ecfg) else ("", "")
                    if busy:  # another run took the area since the queue was read
                        say("%s: %s; the next bead" % (bid, busy))
                        continue
                    # a paused run leaves its bead open and still assigned: released here when that run is gone, as
                    # run-task does
                    ok, why = engine.reclaim(bid, repo)
                    if not ok or tl.cmd_claim(engine.Args(id=bid, worktree=d, slot=name)) != 0:
                        record(repo, bid, name, {"outcome": "taken", "why": why if not ok else "claimed by another session"})
                        later[bid] = clock() + PAUSE_RETRY
                        continue
                    if area:
                        if os.path.isdir(d):
                            tl.loop_lock(d, name, slot_bead, bead=bid)
                        if slot_bead:
                            tl.attempt(store.update, slot_bead, BeadPatch(set_metadata={"held_bead": bid}))
                beat.add(bid)
                rc, err = prepare(repo, name, b.id) if slots else (0, "")
                if rc != 0:
                    store.unclaim(b.id)
                    if rc == 5:  # a live run holds the bead's branch: not this loop's failure
                        r = {"outcome": "taken", "why": err}
                    else:  # before the engine: the bead rests for every loop, no failure of this loop's
                        r = {"outcome": "failed", "pre_engine": True, "why": "failed before the engine: %s" % (
                            "tl slot reset %s for %s found the slot busy (a live engine or a hold)" % (name, b.id) if rc == 4
                            else "tl slot reset %s for %s did not give a clean tree: %s" % (name, b.id, err or "exit %d" % rc))}
                else:
                    r = run_bead(repo, b, name, d, slot_bead, started)
                record(repo, b.id, name, r)
                if r.get("outcome") != "taken":
                    break
                later[bid] = clock() + PAUSE_RETRY
                beat.ids.remove(bid)
                r = None
                if slot_bead:  # the next candidate's area check must not see this one as running here
                    tl.attempt(store.update, slot_bead, BeadPatch(unset_metadata=["held_bead"]))
                if os.path.isdir(d):
                    tl.loop_lock(d, name, slot_bead)
        finally:
            beat.stop()
            tl.drop_engine_lock(d, os.getpid())
            if slots:
                tl.release_slot(repo, name, mine=True)
            write_state(repo, pid=os.getpid(), started=started, worktree=wt)
        if r is None:  # every candidate is held by another session: the next pass sleeps until one is due
            continue
        if slots and name and r is not None:
            out0 = r.get("outcome")
            quick = (out0 == "failed" and SLOT_FAILURE.search(r.get("why") or "") is not None
                     and "already used by worktree" not in (r.get("why") or "") and (  # that one is the bead's branch, held elsewhere
                r.get("pre_engine") or (r.get("minutes") is not None and float(r["minutes"]) < QUICK_FAIL_MIN)))  # the slot's, and instant
            slot_quick[name] = (slot_quick.get(name, []) + [bid]) if quick else []
            if len(slot_quick[name]) >= SLOT_FAILS_TO_SET_ASIDE:  # (the failures before it were counted toward the stop: see `fails` below)
                # tl-g6a: a broken slot must not eat the queue (7 beads failed in under a minute each on s4): it is held, the
                # failures are the slot's, not the beads' or the loop's, and the dashboard and the loop log say so
                why = "%d runs failed within %g min each (%s): last: %s" % (
                    len(slot_quick[name]), QUICK_FAIL_MIN, ", ".join(slot_quick[name]), (r.get("why") or "")[:160])
                try:
                    held = tl.cmd_slot(engine.Args(op="hold", name=name, why="set aside by tl loop: " + why, for_min=SLOT_ASIDE_MIN,
                                                   n=None, bead=None, force=False))
                except SystemExit:  # no such slot bead: nothing to hold
                    held = 1
                say("SLOT %s %s: %s" % (name, ("SET ASIDE for %d h" % (SLOT_ASIDE_MIN // 60)) if held == 0 else
                                        "could not be set aside (another loop has it)", why))
                tl.event("slot-aside", bid, slot=name, why=why, held=(held == 0), repo=repo)
                if held == 0:
                    fails = [f for f in fails if f not in slot_quick[name]]
                    slot_quick[name] = []
                    continue
                slot_quick[name] = slot_quick[name][-1:]  # still failing: asked again after the next one
        if r.get("pre_engine"):  # the engine never started: no verdict on the run, so no failure toward the stop
            rest_bead(repo, bid, clock() + REST)
            later[bid] = clock() + REST
            say("%s failed before its engine started: it rests an hour for every loop on the repo, the next bead first" % bid)
            continue
        kind = r.get("kind") or ""
        if r.get("outcome") == "paused" and kind == oc.Kind.PAUSE_NETWORK.value:
            # tl-kyy: the machine is offline. It is no run, no failure and no pause of the bead's: no label is touched, no
            # counter moves (ran, pauses, fails), and the bead is not rested. The loop probes and resumes the same bead.
            if probe is None:
                probe = make_probe(repo)
            if probe is None:
                later[bid] = clock() + PAUSE_RETRY
                say("%s paused for the network and no delegate is installed to probe it: the next bead first" % bid)
                continue
            if net.mark_down(clock()):
                net_down_t[0] = clock()
                say("NETWORK DOWN: %s paused; no bead is claimed until the probe passes (every %d s)" % (bid, NET_PROBE))
                tl.event("net_down", bid, who="loop", repo=repo, why=(r.get("why") or "")[:200])
            if bid not in net_first:
                net_first.append(bid)
            continue
        ran += 1
        out = r.get("outcome")
        if r.get("storm"):  # this run's close tripped the storm detector (the engine wrote the record and the banner)
            print(r["storm"])
            left("storm", r["storm"][:200])
            return 2
        if out == "landed":
            fails = []
        elif out == "failed":
            if kind.startswith("fault_"):  # a fault of the machine or the engine: the bead is open, labelled, cooled; the storm is the stop
                rest_bead(repo, bid, clock() + oc.KNOBS["fault_cooldown_s"])
                later[bid] = clock() + oc.KNOBS["fault_cooldown_s"]
            elif not (slots and name and slot_quick.get(name)):  # no verdict at all (run-task died); a slot's own instant failure is the slot's
                fails.append(bid)
            if len(fails) >= FAILS_TO_STOP:
                print("STOPPED: %d failures in a row (%s); look at their logs (tl loop status) before starting again"
                      % (len(fails), ", ".join(fails)))
                left("storm", "%d runs gave no outcome" % len(fails))
                return 2
        elif out == "paused":
            due = float(r.get("retry_after") or 0)
            pauses[bid] = pauses.get(bid, 0) + 1
            if pauses[bid] >= PAUSES_TO_REST:
                pauses[bid] = 0
                later[bid] = clock() + REST
                say("%s paused %d times: it rests an hour, the next bead first" % (bid, PAUSES_TO_REST))
            elif r.get("role") and delegate_route(repo):
                gate.hold(bid, r["role"])  # the lane's own time (due) is a hint: the bead wakes when delegate says the role is usable
                say("%s paused for the %s role%s: it wakes when delegate says the role is usable, the next bead first" % (
                    bid, r["role"], (" (a time hint: " + time.strftime("%H:%M:%S", time.localtime(due)) + ")") if due else ""))
            else:
                later[bid] = clock() + PAUSE_RETRY
                say("%s paused (%s): the next bead first" % (bid, (r.get("why") or "")[:120]))


def last_exit(repo):
    """The repo's newest exit line ({} when none)."""
    try:
        lines = (paths(repo)["runs"] / "exits.jsonl").read_text(encoding="utf-8").splitlines()
        return json.loads(lines[-1])
    except (OSError, ValueError, IndexError):
        return {}


def health(repo, loops):
    """loop_health for the repo: loops alive, ready beads (one bd call, here only), the newest beat of any loop, live or dead."""
    beats = [float(st.get("beat") or st.get("started") or 0) for st in loops]
    if not beats:
        for f in paths(repo)["runs"].glob("died-*.json"):
            with contextlib.suppress(OSError, ValueError):
                st = json.loads(f.read_text(encoding="utf-8"))
                beats.append(float(st.get("beat") or st.get("started") or 0))
        beats.append(float(last_exit(repo).get("t") or 0))
    try:
        ready = len(queue(repo)[0])
    except Exception as e:  # a status line never fails on a bd error
        say("health: ready beads unreadable: %s" % e)
        ready = 0
    return loop_health.loop_health(len(loops), ready, max(beats) if beats else 0.0, clock())


def health_lines(repo, loops):
    """Lines under the loop list: how long since the last beat, the last exit reason, and one RED line for an absent loop."""
    h, out, ex = health(repo, loops), [], last_exit(repo)
    ago = lambda t: "%d min ago" % ((clock() - t) // 60)  # noqa: E731
    if h.last_beat:
        out.append("last beat %s" % ago(h.last_beat))
    if ex:
        out.append("last exit: %s%s (%s)" % (ex.get("reason"), ": " + ex["detail"] if ex.get("detail") else "", ago(float(ex.get("t") or 0))))
    if h.verdict == "absent":
        out.append("RED: %s has %d ready bead(s) and no loop alive (last beat %s): start one with `tl loop --repo %s`" % (
            repo, h.ready, ago(h.last_beat) if h.last_beat else "never", repo))
    return out


def cmd_status(a):
    repo = tl.repo_root(a.repo)

    def t(x):
        return time.strftime("%m-%d %H:%M", time.localtime(x))
    loops = live_loops(repo)
    request = read_stop(repo)
    for st in loops:
        print("LOOP pid %s on %s since %s" % (st["pid"], repo, t(st.get("started") or 0)))
        if st.get("version"):
            lag = tl.releases_behind(st["version"])
            print("  running task-loop %s from %s%s" % (st["version"], st.get("code_dir") or "?", "; lags %d release(s)" % lag if lag else ""))
        if st.get("bead"):
            print("  now: %s in %s since %s; log %s" % (st["bead"], st.get("slot") or "its worktree", t(st["since"]),
                                                       st.get("run_log")))
        mode = stop_for(request, st["pid"])
        if mode:
            print("  stop requested: %s" % mode)
        if st.get("log"):
            print("  log %s" % st["log"])
    if not loops:
        print("no loop running on %s" % repo)
    for line in health_lines(repo, loops):
        print(line)
    try:
        refused = json.loads((tl.config_dir() / "bad-versions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        refused = {}
    for v in sorted(bad_versions()):  # a refused install that is still in the cache (a red line until a fixed release replaces it)
        print("RED: task-loop %s refused: %s" % (v, (refused.get(v) or {}).get("why", "")[:160]))
    f = paths(repo)["log"]
    lines = f.read_text(encoding="utf-8").splitlines()[-a.last:] if f.exists() else []
    if lines:
        print("%-16s  %-14s %-4s %-7s %5s %6s %5s %-3s  %s" % ("when", "bead", "slot", "outcome", "min", "rounds", "tests",
                                                                "ask", "trace / why"))
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        print("%-16s  %-14s %-4s %-7s %5s %6s %5s %-3s  %s" % (
            (r.get("ts") or "").replace("T", " ")[:16], r.get("bead"), r.get("slot") or "-", r.get("outcome"),
            r.get("minutes"), "-" if r.get("rounds") is None else r["rounds"],
            "-" if r.get("tests_added") is None else r["tests_added"], "yes" if r.get("asked") else "no",
            r.get("trace") or (r.get("why") or "")[:60]))
    return 0


def cmd_stop(a):
    """Every loop running on the repo stops (a loop started later does not read this stop)."""
    repo = tl.repo_root(a.repo)
    with stop_lock(repo):
        loops = live_loops(repo)
        if not loops:
            print("no loop running on %s" % repo)
            return 1
        request = {"mode": "now" if a.now else "after", "targets": [st["pid"] for st in loops], "time": clock()}
        f = paths(repo)["stop"]
        tmp = f.with_name(f.name + ".%d.tmp" % os.getpid())
        tmp.write_text(json.dumps(request), encoding="utf-8")
        os.replace(tmp, f)
    for st in loops:
        print("STOP %s: loop pid %s%s" % ("NOW" if a.now else "after the current bead", st["pid"],
                                          (", running " + st["bead"]) if st.get("bead") else ""))
    return 0


# ---- selftest -------------------------------------------------------------------------------------------------------

def selftest():
    """One bead through Engine.run (plan, write, review, land) with a scripted lane in a temp repo and a temp config dir,
    on this install's code. None when it lands and closes the bead, else why not. Nothing real is touched: no bd, no
    delegate, no network, no model."""
    import tempfile
    from unittest import mock

    from taskloop.adapters.fake_beads import FakeBeads

    py = '"%s"' % sys.executable
    check = py + " -c \"import os,sys; sys.exit(0 if os.path.exists('f.txt') else 1)\""
    plan = {"summary": "do it", "stages": [{"goal": "add f", "files": ["f.txt"], "checks": [check], "hard": False}],
            "risks": [], "question": "", "options": [], "decided": "", "cases": [], "leftovers": []}
    write = {"summary": "wrote f", "checks_run": [{"cmd": check, "exit": 0}], "question": "", "options": [], "decided": "",
             "bad_checks": [], "new_cases": [], "unchecked": [], "logic_only": ""}
    review = {"findings": [], "unmet": [], "question": "", "options": [], "decided": "", "leftovers": [], "unchecked": [],
              "look": ""}
    bead = engine.Bead(id="t-1", title="Add f", status="open", acceptance_criteria="f.txt exists")
    closed, blocked = [], []

    def lane(cmd, **kw):  # fake route.py run: one contract 3 answer on stdout
        schema = json.loads(Path(cmd[cmd.index("--schema") + 1]).read_text(encoding="utf-8"))
        props, cwd = schema.get("properties", {}), cmd[cmd.index("--cwd") + 1]
        if "stages" in props:
            data, node = plan, "plan"
        elif "checks_run" in props:
            data, node = write, "write"
            Path(cwd, "f.txt").write_text("f\n", encoding="utf-8")
        else:
            data, node = review, "review"
        tokens = {"in": 1, "cached": 0, "out": 1}
        j = {"contract": dl.CONTRACT, "data": data, "text": "ok", "say": "", "ref": "ref-" + node, "lane": "L", "model": "m", "effort": "e",
             "family": "openai" if node == "write" else "claude", "flag": None, "fallback": False, "first_lane": "L", "rung": 0,
             "tokens": tokens, "cost": 0.0, "secs": 1, "run_id": "selftest", "call_id": "selftest", "denied": [], "git_violation": [],
             "warnings": [], "usage": {"tokens": tokens, "cost": 0.0, "secs": 1, "turns": 1, "ref": "ref-" + node}, "stop": None,
             "resumed": False}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(j), "")

    class Runner:  # the engine's process seam for the fake lane
        stop, obs, secs = {}, {}, 0.0

        def __call__(self, cmd, **kw):
            self.stop, self.obs = {}, {}
            return lane(cmd, **kw)

    with tempfile.TemporaryDirectory(prefix="tl-selftest-") as tmp:
        home = Path(os.path.realpath(tmp))
        env = {"XDG_CONFIG_HOME": str(home / "cfg"), "APPDATA": str(home / "cfg"), "HOME": str(home), "USERPROFILE": str(home),
               "CLAUDE_CODE_SESSION_ID": "selftest-0", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        origin, wt = home / "o.git", home / "wt"
        with mock.patch.dict(os.environ, env):
            for cmd in (["init", "-q", "--bare", "-b", "main", str(origin)], ["clone", "-q", str(origin), str(wt)]):
                r = subprocess.run(["git"] + cmd, cwd=home, capture_output=True, text=True)
                if r.returncode:
                    return "git %s: %s" % (cmd[0], r.stderr.strip()[-200:])
            (wt / "a.txt").write_text("a\n", encoding="utf-8")
            for cmd in (["add", "-A"], ["commit", "-qm", "init"], ["push", "-q", "origin", "HEAD:main"]):
                r = subprocess.run(["git"] + cmd, cwd=wt, capture_output=True, text=True)
                if r.returncode:
                    return "git %s: %s" % (cmd[0], r.stderr.strip()[-200:])
            cfg = engine.load_cfg(str(wt))
            res = dl.resolve(cfg.delegate)  # the configured delegate's own contract when there is one; else a bare one
            contract = res.contract if isinstance(res, dl.Resolved) else {"contract": dl.CONTRACT, "reasons": {}, "run_args": []}
            resolved = dl.Resolved(Path("/selftest"), "/selftest/route.py", contract, "explicit")
            store = FakeBeads()
            store.beads["t-1"] = bead
            with mock.patch.object(tl, "cmd_close", side_effect=lambda a: closed.append(a.reason) or 0), \
                    mock.patch.object(tl, "cmd_block", side_effect=lambda a: blocked.append(a.why) or 0), \
                    mock.patch.object(tl, "cmd_land", return_value=0), \
                    mock.patch.object(engine.time, "sleep"):
                cfg = engine.dataclasses.replace(cfg, reflect=False)
                os.chdir(wt)  # the engine reads cwd
                try:
                    rc = engine.Engine("t-1", str(wt), cfg, route=seams.FixedRoute(resolved, Runner()), store=store).run()
                finally:
                    os.chdir(home.parent)  # out of the directory that is removed next
    if rc != 0 or not closed:
        return "the engine ended %s without closing the bead%s" % (rc, (" (blocked: %s)" % blocked[0][:200]) if blocked else "")
    return None


def cmd_selftest(a):
    started = time.monotonic()
    try:
        why = selftest()
    except Exception as e:  # any raise is a failure; the traceback tail says where
        import traceback
        why = "%s: %s\n%s" % (type(e).__name__, e, "".join(traceback.format_exc().splitlines(True)[-6:]))
    secs = time.monotonic() - started
    if why:
        print("selftest FAILED in %.1f s: %s" % (secs, why), file=sys.stderr)
        return 1
    print("selftest ok in %.1f s" % secs)
    return 0
