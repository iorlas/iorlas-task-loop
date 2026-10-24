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
import random
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import engine
import tl

POLL = 2               # seconds between looks at a running child (stop file, slot heartbeat)
HEARTBEAT = 60         # the slot bead's lease is kept alive this often while a bead runs
DRAINED_POLL = 300     # --wait-drained: how often an empty queue is looked at again
PAUSE_WAIT_MAX = 3600  # a lane back within this long is waited for; later, the next bead is tried
HELP_WAIT = 20         # a newer install must answer `tl.py --help` within this long to be moved to
PAUSE_RETRY = 900      # a pause with no time the lane frees (login, network), or a bead another session holds:
                       # try that bead again after this
SLOT_FAILS_TO_SET_ASIDE = 2  # instant failures in a row on one slot that set the slot aside (tl-g6a); not the loop's stop count
QUICK_FAIL_MIN = 1.5           # a failed run shorter than this, in minutes, is an instant failure
SLOT_FAILURE = re.compile(r"worktree \S+ has uncommitted work|did not give a clean tree|index\.lock|not a git repository|could not commit the leftover", re.I)  # the slot's own git state
SLOT_ASIDE_MIN = 720           # minutes a slot set aside stays held
FAILS_TO_STOP = 2      # failures in a row that stop the loop; parks and pauses never count, a landing ends the run
PAUSES_TO_REST = 3     # a bead paused this often in one loop run rests for REST while the loop takes others
REST = 3600
AREA_POLL = 60         # every ready bead waits for its area: look again this often
MARGIN = (30, 90)      # a paused bead wakes this many seconds (random) after its retry_after: the lane is surely back,
                       # and two loops paused on one lane do not knock in the same second (tl-bxk.10.6)

clock = time.time
STOP_NOW = threading.Event()  # SIGTERM or Ctrl-C to the loop itself: end the running bead as `tl stop --now` does


# ---- the queue rule -------------------------------------------------------------------------------------------------

def natural(bead_id):
    """fld.26.9 before fld.26.10: digit runs compare as numbers (split keeps text and numbers at the same places)."""
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", bead_id)]


def epics_of(bead, cache):
    """Every ancestor of a bead, nearest first; `parent` in bd's JSON is the direct one only."""
    out, pid = [], bead.get("parent")
    while pid and pid not in out:
        out.append(pid)
        if pid not in cache:
            cache[pid] = tl.show(pid).get("parent")
        pid = cache[pid]
    return out


# ---- areas (tl-bxk.11.4): two beads of one area never run at once ---------------------------------------------------

def has_areas(cfg):
    return bool(cfg.get("areas") or cfg.get("area_label_prefix"))


def area_of(b, cfg, cache):
    """The bead's area, "" for none (unrestricted). engine.areas {area: [epic id or label, ...]} first, in its order:
    the bead, any of its ancestors or one of its labels named; then the first label with engine.area_label_prefix
    (lane:live is area live). First match wins."""
    labels = b.get("labels") or []
    ups = None
    for name, members in (cfg.get("areas") or {}).items():
        if ups is None:
            ups = [b.get("id")] + epics_of(b, cache)
        if any(m in ups or m in labels for m in members or []):
            return name
    prefix = cfg.get("area_label_prefix") or ""
    if prefix:
        for x in labels:
            if x.startswith(prefix) and len(x) > len(prefix):
                return x[len(prefix):]
    return ""


def lapsed(b):
    t = b.get("lease_expires_at") or ""
    return bool(t) and t < time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def running(repo):
    """{bead: where} of the beads running now: a slot bead held for one (held_bead), or a live engine lock naming
    one, in a slot or any worktree of the repo."""
    out, slots = {}, tl.slot_beads(repo)
    for b in slots:
        bid = (b.get("metadata") or {}).get("held_bead")
        if bid and b.get("status") == "in_progress" and not lapsed(b):
            out[bid] = b["title"].split()[-1]
    for wt in tl.worktrees(repo, slots):
        lock = tl.read_engine_lock(wt)
        if lock.get("bead") and lock.get("pid") and tl.proc_alive(lock["pid"], lock.get("start") or ""):
            out.setdefault(lock["bead"], lock.get("slot") or Path(wt).name)
    return out


AREA_WAIT_SAY = 600  # seconds between the "still waiting on an area" lines

ANY_AREA = "*"  # busy_areas key for a running bead that could not be read


def busy_areas(repo, cfg, cache, but=""):
    """{area: (bead, where)} of the areas a running bead (other than `but`) works in."""
    out = {}
    for bid, where in sorted(running(repo).items()):
        if bid == but:
            continue
        held = tl.show(bid, cwd=repo)
        if not held:  # its area is unknown: it may be any, so every area waits (a slot hung on a bd error stays visible)
            say("running bead %s in %s is unreadable (bd show failed): every area counts as busy" % (bid, where))
            out.setdefault(ANY_AREA, (bid, where))
            continue
        a = area_of(held, cfg, cache)
        if a:
            out.setdefault(a, (bid, where))
    return out


def area_busy(repo, cfg, b, cache):
    """(area, "area A busy: B in S") for a bead whose area runs elsewhere, (area, "") when it is free, ("", "")."""
    a = area_of(b, cfg, cache)
    if not a:
        return "", ""
    busy = busy_areas(repo, cfg, cache, but=b.get("id", ""))
    hit = busy.get(a) or busy.get(ANY_AREA)
    return a, ("area %s busy: %s in %s" % (a, hit[0], hit[1]) if hit else "")


def area_lock(repo, cfg):
    """One area check and the mark that follows it at a time per repo (the loop's claim, run-task's engine lock): two
    takers never both see an area free. A no-op without areas."""
    if not has_areas(cfg):
        return contextlib.nullcontext()
    return tl.os_lock(tl.config_dir() / "locks" / ("area-%s.lock" % tl.repo_key(repo)), "pid %d" % os.getpid())


def queue(repo):
    """([(bead, reason)] in the order the loop takes them, [(id, why skipped)]). A reason names the rule that puts a
    bead before the next one. Fetches first: the rule is read from the base branch (engine.load_cfg). A bead whose
    area runs elsewhere is skipped (`area A busy: B in S`); the claim checks again under the area lock."""
    tl.fetch(repo)
    cfg = engine.load_cfg(repo)
    args = ["ready", "--json", "-n", "0"] + (["--label", cfg["pick_label"]] if cfg.get("pick_label") else [])
    try:
        ready = json.loads(tl.bd(*args, cwd=repo).stdout or "[]")
    except ValueError:
        ready = []
    order, skip = list(cfg.get("epic_order") or []), list(cfg.get("skip_labels") or [])
    keep, skipped, cache = [], [], {}
    for b in ready:
        labels = b.get("labels") or []
        hit = next((x for x in skip if x in labels), None)
        why = ("an epic" if b.get("issue_type") == "epic" else "a slot" if "slot" in labels
               else "label " + hit if hit else "")
        rank = len(order)
        if not why and order:
            ups = epics_of(b, cache)
            rank = min([order.index(e) for e in ups if e in order] or [len(order)])
            if rank == len(order) and cfg.get("epic_only"):
                why = "under no epic in epic_order (epic_only)"
        if why:
            skipped.append((b["id"], why))
        else:
            keep.append((int(b.get("priority") if b.get("priority") is not None else 2), rank, natural(b["id"]), b))
    keep.sort(key=lambda k: k[:3])
    if has_areas(cfg) and keep:
        busy, free = busy_areas(repo, cfg, cache), []
        for k in keep:
            hit = busy.get(area_of(k[3], cfg, cache)) or (busy.get(ANY_AREA) if area_of(k[3], cfg, cache) else None)
            if hit:
                skipped.append((k[3]["id"], "area %s busy: %s in %s" % (area_of(k[3], cfg, cache), hit[0], hit[1])))
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
        print(json.dumps({"pick": ranked[0][0] if ranked else None, "reason": ranked[0][1] if ranked else "",
                          "next": [{"id": b["id"], "priority": b.get("priority"), "reason": r} for b, r in ranked[1:6]],
                          "skipped": [{"id": i, "why": w} for i, w in skipped]}, ensure_ascii=False))
        return 0 if ranked else 1
    if not ranked:
        print("NONE: no ready bead in the queue")
    for n, (b, r) in enumerate(ranked[:6]):
        print("%s %s  P%s  %s  (%s)" % ("NEXT" if n == 0 else "then", b["id"], b.get("priority"), b.get("title", "")[:70], r))
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
    tmp.write_text(json.dumps(dict(st, repo=repo)), encoding="utf-8")
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
    for f in [d / (key + ".json")] + list(d.glob(key + ".*.json")):  # <key>.json: a loop of the code before tl-bxk.11.1
        try:
            st = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not pid_alive(st.get("pid")):
            with contextlib.suppress(OSError):
                f.unlink()
        elif st.get("pid") != but:
            out.append(st)
    return sorted(out, key=lambda st: st.get("started") or 0)


pid_alive = tl.pid_alive


SESSION_ACTOR = [""]  # the session's actor, without this loop's suffix: names the session's slots-off worktree
START_CWD = [""]  # the directory the loop was started in: where its argv's relative paths point
STARTED = [0.0]  # wall time this loop started: a stop file written before it was meant for the loops then running


def stop_mode(repo):
    """'now', 'after' (stop after the current bead) or '' (go on)."""
    if STOP_NOW.is_set():
        return "now"
    f = paths(repo)["stop"]
    try:
        if f.stat().st_mtime < STARTED[0]:
            return ""
        return f.read_text().strip() or "after"
    except OSError:
        return ""


def nap(secs, repo=None, until=0):
    """Sleep, waking early for a stop or the end time."""
    end = clock() + secs
    while clock() < end and not (repo and stop_mode(repo)) and not (until and clock() >= until):
        time.sleep(min(POLL, max(0.05, end - clock())))


def margin():
    return random.uniform(*MARGIN)


def say(text):
    engine.say("[%s] loop: %s" % (time.strftime("%H:%M:%S", time.localtime(clock())), text))


# ---- one bead -------------------------------------------------------------------------------------------------------

class Beat:
    """Keeps the slot bead's and the task bead's leases alive from the slot take to the release: a slow slot setup
    (lifesim: 5-12 min) outlasts a 5-minute lease. run-task heartbeats both too, so a SIGKILLed loop leaves no slot free
    under a live run."""

    def __init__(self, *ids):
        self.ids, self.every, self.ev = [i for i in ids if i], HEARTBEAT, threading.Event()
        self.th = threading.Thread(target=self.loop, daemon=True)
        self.th.start()

    def add(self, bead_id):
        self.ids.append(bead_id)

    def loop(self):
        while not self.ev.wait(self.every):
            for i in list(self.ids):
                tl.bd("heartbeat", i)

    def stop(self):
        self.ev.set()

def spawn(cmd, log):
    """run-task as a child in its own process group: Ctrl-C to the loop reaches it only as the loop's SIGTERM."""
    kw = {"stdin": subprocess.DEVNULL, "stdout": log, "stderr": subprocess.STDOUT}
    if os.name == "nt":
        kw["creationflags"] = 0x00000200  # CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    return subprocess.Popen(cmd, **kw)


def prepare(repo, slot, bead_id):
    """A slot gets a clean tree on the bead's branch (leftover work committed, never wiped); see tl slot reset.
    Returns (rc, why): why is git's error line when the reset failed."""
    a = engine.Args(op="reset", name=slot, bead=bead_id, n=None, force=False)
    rc = tl.cmd_slot(a)
    return rc, getattr(a, "error", "")


def landed_on_base(repo, wt, bead_id):
    """True when the bead's land commit (titled `... (<id>)`) is the tip of its branch and already on the base."""
    if not os.path.isdir(wt):
        return False
    base = engine.load_cfg(repo)["base"]
    branch = (tl.show(bead_id).get("metadata") or {}).get("branch") or "task/" + bead_id
    tl.fetch(wt)
    tip = tl.git("rev-parse", "--verify", "-q", "refs/heads/" + branch, cwd=wt)
    if not tip or not tl.git("log", "-1", "--format=%s", tip, cwd=wt).endswith("(%s)" % bead_id):
        return False
    return tl.run_git(wt, "merge-base", "--is-ancestor", tip, base, capture_output=True).returncode == 0


def run_bead(repo, b, slot, wt, slot_bead, started):
    """One bead through `tl run-task` as a child; returns its outcome record (failed when it gave none)."""
    runs = paths(repo)["runs"]
    runs.mkdir(exist_ok=True)
    stem = "%s-%s" % (b["id"], time.strftime("%Y%m%d-%H%M%S", time.localtime(clock())))
    out, log_path = runs / (stem + ".outcome.json"), runs / (stem + ".log")
    cmd = [sys.executable, str(tl.HERE / "tl.py"), "run-task", b["id"], "--worktree", wt, "--outcome-file", str(out)]
    cmd += ["--slot", slot] if slot else []
    t0 = clock()
    os.environ["TASK_LOOP_SLOT_BEAD"] = slot_bead or ""  # the engine heartbeats it too (see Beat)
    with open(log_path, "ab") as log:  # append: a rerun of the same stem never cuts a log another reader follows
        p = spawn(cmd, log)
        write_state(repo, pid=os.getpid(), started=started, bead=b["id"], slot=slot, since=t0, child=p.pid,
                    run_log=str(log_path), worktree=None if slot else wt)
        say("%s in %s (log %s)" % (b["id"], slot or wt, log_path))
        stopped = False
        try:
            while True:
                try:
                    rc = p.wait(timeout=POLL)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if not stopped and stop_mode(repo) == "now":
                    say("stop now: SIGTERM to %s (its close step still runs)" % b["id"])
                    p.terminate()  # SIGTERM on POSIX, which the engine traps; TerminateProcess on Windows
                    stopped = True
        except BaseException:  # the loop itself broke: the run ends (its close step runs) before the slot is freed
            p.terminate()
            p.wait()
            raise
    try:
        r = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        r = {"outcome": "failed", "why": "failed: no outcome from run-task (exit %s); see %s" % (rc, log_path)}
    if stopped and r.get("outcome") == "failed":  # a stop is no verdict on the bead: back to the queue, unclaimed,
        if landed_on_base(repo, wt, b["id"]):     # unless the stop came during a land that went through
            r["why"] = "%s; its land commit is on the base: not reopened, close it by hand" % (r.get("why") or "stopped")
        else:
            tl.bd("update", b["id"], "--status", "open", "--assignee", "", cwd=repo)
    r.setdefault("minutes", round((clock() - t0) / 60, 1))
    r["run_log"] = str(log_path)
    return r


def record(repo, bead_id, slot, r):
    line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(clock())), "bead": bead_id, "slot": slot,
            "outcome": r.get("outcome"), "minutes": r.get("minutes", 0), "rounds": r.get("rounds"),
            "tests_added": r.get("tests_added"), "asked": bool(r.get("asked")), "trace": r.get("run"),
            "engine_log": r.get("log"), "run_log": r.get("run_log"), "why": (r.get("why") or "")[:300]}
    with open(paths(repo)["log"], "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    say("%s %s%s" % (bead_id, line["outcome"], (": " + line["why"][:160]) if line["why"] else ""))


# ---- the loop -------------------------------------------------------------------------------------------------------

def version_key(name):
    """(1, 2, 3) for a version dir name like 0.23.6; None for anything else (a dev checkout, a cache scrap)."""
    return tuple(int(x) for x in name.split(".")) if re.fullmatch(r"\d+(\.\d+)*", name) else None


def newest_install(skip=()):
    """(version, dir) of the newest sibling version dir of this plugin root when it is newer than the running one, else
    None. A root that is no version dir (a dev checkout) never moves."""
    root = tl.HERE.parents[1]
    mine = version_key(root.name)
    if mine is None:
        return None
    best = None
    with contextlib.suppress(OSError):
        for d in root.parent.iterdir():
            k = version_key(d.name)
            if k and k > mine and d.name not in skip and d.is_dir() and (best is None or k > best[0]):
                best = (k, d)
    return (best[1].name, best[1]) if best else None


def complete(d):
    """None when the install in `d` looks usable, else why not: its plugin.json and tl.py, loop.py and engine.py exist
    and import (a half-copied file fails here, `--help` alone exits before loop and engine load), within HELP_WAIT s."""
    if not (d / ".claude-plugin" / "plugin.json").is_file():
        return "plugin.json is missing"
    here = d / "skills" / "task-loop"
    for f in ("tl.py", "loop.py", "engine.py"):
        if not (here / f).is_file():
            return "%s is missing" % f
    code = "import sys; sys.path.insert(0, sys.argv[1]); import tl, loop, engine"
    try:
        r = subprocess.run([sys.executable, "-I", "-c", code, str(here)], stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=HELP_WAIT)
    except subprocess.TimeoutExpired:
        return "importing tl, loop, engine did not finish in %d s" % HELP_WAIT
    except OSError as e:
        return "python did not start: %s" % e
    return None if r.returncode == 0 else "importing tl, loop, engine exited %d" % r.returncode


def maybe_move(a, repo, state):  # returns True when a stop arrived during the check: the caller looks at it first
    """Between beads: exec the newest complete install with the loop's own argv and `state` (TL_LOOP_STATE). The pid
    stays, so what is keyed by it (slot line, state file, stop file readers) carries over. A broken install is warned
    about once per version and never stops the loop."""
    if getattr(a, "pin", False) or not getattr(a, "argv", None):
        return
    try:
        found = newest_install(state["warned"])  # a version that failed is not looked at again
        if not found:
            return
        ver, d = found
        why = complete(d)
        if why:
            state["warned"].append(ver)
            say("warn: not moving to %s: %s; staying on %s" % (ver, why, tl.HERE.parents[1].name))
            return
        if STOP_NOW.is_set() or stop_mode(repo):  # the check took a while; a stop written meanwhile is read by this process
            return True
        say("moving to %s (was %s)" % (ver, tl.HERE.parents[1].name))
        os.environ["TL_LOOP_STATE"] = json.dumps(state)
        if START_CWD[0]:
            os.chdir(START_CWD[0])  # cmd_loop chdir'd into the repo; a relative --repo in argv means the start directory
        sys.stdout.flush()
        sys.stderr.flush()
        os.execv(sys.executable, [sys.executable, str(d / "skills" / "task-loop" / "tl.py"), *a.argv])
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
          "until": lambda v: v is None or num(v), "wt": lambda v: v is None or text(v),
          "actor": lambda v: v is None or text(v), "STARTED": num, "started": num}
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


def acquire(repo, cfg, wait_min, until):
    """(name, dir, slot bead) of a free slot, waiting in the repo's slot line (tl.wait_slot: first come, first served)
    with backoff while none is; None on a stop or the end time."""
    since, told = clock(), [0.0]

    def waiting(ahead):
        if not told[0] or clock() - told[0] >= wait_min * 60:
            say("no free slot%s%s; waiting" % (" for this loop: %d ahead in line" % ahead if ahead else "",
                                               "" if not told[0] else " for %d min" % ((clock() - since) // 60)))
            told[0] = clock()
    return tl.wait_slot(repo, cfg, "tl loop", stop=lambda: bool(stop_mode(repo) or (until and clock() >= until)),
                        sleep=lambda secs: nap(secs, repo, until), poll=(5, min(30, max(5, wait_min * 60))),
                        on_wait=waiting)


def reclaim(repo):
    """A dead loop's or session's beads and slots back to ready: only claims of tl- actors (bd's lease rule decides
    which are dead), never a person's hand claim."""
    try:
        held = json.loads(tl.bd("list", "--json", "--status", "in_progress", "-n", "0", cwd=repo).stdout or "[]")
    except ValueError:
        held = []
    who = sorted({b.get("assignee") for b in held if (b.get("assignee") or "").startswith("tl-")})
    if who:
        tl.bd("reclaim", "--older-than", "15m", *sum((["--assignee", w] for w in who), []), cwd=repo)


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
    STARTED[0] = st.get("STARTED") or time.time()
    if not st and not live_loops(repo, but=os.getpid()):  # a stop no loop read: never meant for this one
        with contextlib.suppress(OSError):
            p["stop"].unlink()
    started = st.get("started") or clock()
    write_state(repo, pid=os.getpid(), started=started)
    try:
        return passes(repo, a, started, st)
    finally:
        with contextlib.suppress(OSError):
            p["state"].unlink()
        if not live_loops(repo, but=os.getpid()):  # the other loops still read it
            with contextlib.suppress(OSError):
                p["stop"].unlink()
        for sig, h in old.items():
            signal.signal(getattr(signal, sig), h)


def worktree_name(repo):
    """Slots off: the session's worktree (loop-<session>), reused by each loop start; one another live loop of the
    repo works in gets this loop's own (loop-<session>-<suffix>): two loops in one tree reset it under each other."""
    name = SESSION_ACTOR[0][3:]
    taken = {st.get("worktree") for st in live_loops(repo, but=os.getpid())}
    if str(Path(repo) / ".worktrees" / ("loop-" + name)) in taken:
        return tl.actor()[3:]
    return name


def passes(repo, a, started, st=None):
    st = st or {}
    cfg, until = tl.profile_slots(repo), st.get("until") if "until" in st else end_time(a.until)
    slots = int(cfg.get("count") or 0) > 0
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
    while True:
        if stop_mode(repo):
            say("stopped on request after %d bead(s)" % ran)
            return 0
        if until and clock() >= until:
            say("%s reached after %d bead(s)" % (a.until, ran))
            return 0
        if a.max_beads and ran >= a.max_beads:
            say("%d bead(s) run (--max-beads)" % ran)
            return 0
        if maybe_move(a, repo, {"fails": fails, "ran": ran, "later": later, "pauses": pauses, "warned": warned, "until": until,
                             "wt": wt, "actor": os.environ.get("TASK_LOOP_ACTOR"), "STARTED": STARTED[0],
                             "started": started}):
            continue
        reclaim(repo)
        tl.close_stale_asks()  # asks of closed or missing beads (throttled)
        try:
            tl.renotify()  # an ask unanswered for 24 h pushed again; once a day, the looks that wait (throttled)
        except Exception as e:  # a push is never worth the loop
            say("re-push skipped: %s" % e)
        tl.park_stale_asks()  # asks unanswered past parks_at (3 days), throttled with the sweep above
        try:
            import digest
            digest.maybe_send()  # the morning digest, once a day, when a push channel is set
        except Exception as e:  # a digest never stops a loop
            say("digest: %s" % e)
        ranked, skipped = queue(repo)
        now = clock()
        for rested, due in read_rests(repo).items():  # another loop's pre-engine failure rests the bead here too
            later[rested] = max(later.get(rested, 0), due)
        cands = [b for b, _ in ranked if later.get(b["id"], 0) <= now]
        if cands:
            area_wait[0] = 0.0
        if not cands:
            if ranked:
                wake = min(later[b["id"]] for b, _ in ranked)
                say("every ready bead waits for a lane or another session: sleeping until %s"
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
                return 0
            nap(DRAINED_POLL, repo, until)
            continue
        got = acquire(repo, cfg, a.wait_slot_min, until) if slots else (None, wt, None)
        if got is None:
            continue
        name, d, slot_bead = got
        r, bid = None, ""
        beat = Beat(slot_bead)
        try:
            if os.path.isdir(d):  # from the take to run-task's own lock: no hand run gets in, the slot reset included
                tl.loop_lock(d, name, slot_bead)
            ecfg, cache = engine.load_cfg(repo), {}
            for b in cands:
                bid = b["id"]
                with area_lock(repo, ecfg):  # the area check, the claim and the mark that makes the area busy: as one
                    area, busy = area_busy(repo, ecfg, b, cache) if has_areas(ecfg) else ("", "")
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
                            tl.bd("update", slot_bead, "--set-metadata", "held_bead=" + bid, cwd=repo)
                beat.add(bid)
                rc, err = prepare(repo, name, b["id"]) if slots else (0, "")
                if rc != 0:
                    tl.bd("unclaim", b["id"], cwd=repo)
                    if rc == 5:  # a live run holds the bead's branch: not this loop's failure
                        r = {"outcome": "taken", "why": err}
                    else:  # before the engine: the bead rests for every loop, no failure of this loop's
                        r = {"outcome": "failed", "pre_engine": True, "why": "failed before the engine: %s" % (
                            "tl slot reset %s for %s found the slot busy (a live engine or a hold)" % (name, b["id"]) if rc == 4
                            else "tl slot reset %s for %s did not give a clean tree: %s" % (name, b["id"], err or "exit %d" % rc))}
                else:
                    r = run_bead(repo, b, name, d, slot_bead, started)
                record(repo, b["id"], name, r)
                if r.get("outcome") != "taken":
                    break
                later[bid] = clock() + PAUSE_RETRY
                beat.ids.remove(bid)
                r = None
                if slot_bead:  # the next candidate's area check must not see this one as running here
                    tl.bd("update", slot_bead, "--unset-metadata", "held_bead", cwd=repo)
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
        ran += 1
        out = r.get("outcome")
        if out == "landed":
            fails = []
        elif out == "failed":
            if not (slots and name and slot_quick.get(name)):  # a slot's own instant failure is the slot's (set aside after two)
                fails.append(bid)  # an infrastructure failure counts too: one config bug stops the loop after 2 beads
            if (r.get("why") or "").startswith("failed: infrastructure"):  # the bead is open again: others first, for every loop
                rest_bead(repo, bid, clock() + REST)
                later[bid] = clock() + REST
            if len(fails) >= FAILS_TO_STOP:
                print("STOPPED: %d failures in a row (%s); look at their logs (tl loop status) before starting again"
                      % (len(fails), ", ".join(fails)))
                return 2
        elif out == "paused":
            due = float(r.get("retry_after") or 0)
            pauses[bid] = pauses.get(bid, 0) + 1
            if pauses[bid] >= PAUSES_TO_REST:
                pauses[bid] = 0
                later[bid] = clock() + REST
                say("%s paused %d times: it rests an hour, the next bead first" % (bid, PAUSES_TO_REST))
            elif due and due - clock() <= PAUSE_WAIT_MAX:
                wake = due + margin()
                say("%s paused for a lane until %s: waiting for it, retry at %s" % (
                    bid, time.strftime("%H:%M:%S", time.localtime(due)), time.strftime("%H:%M:%S", time.localtime(wake))))
                nap(max(0, wake - clock()), repo, until)
            else:
                later[bid] = due + margin() if due else clock() + PAUSE_RETRY
                say("%s paused (%s): the next bead first" % (bid, (r.get("why") or "")[:120]))


def cmd_status(a):
    repo = tl.repo_root(a.repo)

    def t(x):
        return time.strftime("%m-%d %H:%M", time.localtime(x))
    loops = live_loops(repo)
    for st in loops:
        print("LOOP pid %s on %s since %s" % (st["pid"], repo, t(st.get("started") or 0)))
        if st.get("bead"):
            print("  now: %s in %s since %s; log %s" % (st["bead"], st.get("slot") or "its worktree", t(st["since"]),
                                                       st.get("run_log")))
    if loops and paths(repo)["stop"].exists():
        print("  stop requested: %s" % (paths(repo)["stop"].read_text().strip() or "after"))
    if not loops:
        print("no loop running on %s" % repo)
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
    loops = live_loops(repo)
    if not loops:
        print("no loop running on %s" % repo)
        return 1
    paths(repo)["stop"].write_text("now" if a.now else "after")
    for st in loops:
        print("STOP %s: loop pid %s%s" % ("NOW" if a.now else "after the current bead", st["pid"],
                                          (", running " + st["bead"]) if st.get("bead") else ""))
    return 0
