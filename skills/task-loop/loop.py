"""The loop: one process runs ready beads one after another, each through `tl run-task` in any free slot.

    tl.py next [--repo DIR] [--json]          what the loop would take next, and why (claims nothing)
    tl.py loop [--repo DIR] [--max-beads N] [--until HH:MM] [--wait-slot-min M] [--wait-drained]
    tl.py loop status [--repo DIR] [--last N] what runs now and the last beads
    tl.py stop [--repo DIR] [--now]           every loop on the repo stops after its bead, or now (close runs)

The queue rule lives in the repo's .task-loop.json (engine.pick_label, skip_labels, epic_order, epic_only): ready
beads with the pick label, minus skip labels, epics and slots; then priority, epic order, lowest id. Python 3.8+,
standard library only.
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
PAUSE_RETRY = 900      # a pause with no time the lane frees (login, network), or a bead another session holds:
                       # try that bead again after this
FAILS_TO_STOP = 2      # failures in a row that stop the loop; parks and pauses never count, a landing ends the run
PAUSES_TO_REST = 3     # a bead paused this often in one loop run rests for REST while the loop takes others
REST = 3600
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


def queue(repo):
    """([(bead, reason)] in the order the loop takes them, [(id, why skipped)]). A reason names the rule that puts a
    bead before the next one. Fetches first: the rule is read from the base branch (engine.load_cfg)."""
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
    """The repo's files: one stop file and one log for all its loops; `state` is this process's own."""
    d = tl.config_dir() / "loop"
    d.mkdir(exist_ok=True)
    key = "%s-%s" % (Path(repo).name, hashlib.sha1(repo.encode()).hexdigest()[:8])
    return {"state": d / ("%s.%d.json" % (key, os.getpid())), "states": (d, key),
            "stop": d / (key + ".stop"), "log": d / (key + ".jsonl"), "runs": d / key}


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
    """A slot gets a clean tree on the bead's branch (leftover work committed, never wiped); see tl slot reset."""
    return tl.cmd_slot(engine.Args(op="reset", name=slot, bead=bead_id, n=None, force=False))


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

def end_time(hhmm):
    """--until HH:MM: the next time it is that o'clock (tomorrow when it has passed today)."""
    if not hhmm:
        return 0
    h, m = (int(x) for x in hhmm.split(":"))
    now = datetime.datetime.fromtimestamp(clock())
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return (t if t > now else t + datetime.timedelta(days=1)).timestamp()


def acquire(repo, cfg, wait_min, until):
    """(name, dir, slot bead) of a free slot, waiting with backoff while none is; None on a stop or the end time."""
    delay, told = 15, clock()
    say_wait = True
    while True:
        got = tl.take_slot(repo, cfg)
        if got:
            return got
        if stop_mode(repo) or (until and clock() >= until):
            return None
        if say_wait or clock() - told >= wait_min * 60:
            say("no free slot%s; waiting" % ("" if say_wait else " for %d min" % ((clock() - told) // 60)))
            say_wait, told = False, clock()
        nap(delay, repo, until)
        delay = min(delay * 2, 300, max(15, wait_min * 60))


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
    repo = tl.repo_root(a.repo)
    os.chdir(repo)  # every tl helper and bd call works on the current directory's repo
    if not tl.session_id():  # without a Claude session the actor would be per folder: two loops would share it
        os.environ["TASK_LOOP_SESSION"] = "loop-" + uuid.uuid4().hex[:12]
    # an actor of its own, never the session's: bd lets an actor re-claim its own bead, so two loops (or a loop and a
    # hand run) started from one session would both win one claim. run-task re-claims as this actor (one for both).
    os.environ.pop("TASK_LOOP_ACTOR", None)
    SESSION_ACTOR[0] = tl.actor()
    os.environ["TASK_LOOP_ACTOR"] = "%s-%s" % (SESSION_ACTOR[0], uuid.uuid4().hex[:6])
    old = {}
    if threading.current_thread() is threading.main_thread():
        for sig in ("SIGTERM", "SIGINT"):
            if hasattr(signal, sig):
                old[sig] = signal.signal(getattr(signal, sig), lambda *_: STOP_NOW.set())
    STOP_NOW.clear()
    p = paths(repo)
    STARTED[0] = time.time()
    if not live_loops(repo, but=os.getpid()):  # a stop no loop read: never meant for this one
        with contextlib.suppress(OSError):
            p["stop"].unlink()
    started = clock()
    write_state(repo, pid=os.getpid(), started=started)
    try:
        return passes(repo, a, started)
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


def passes(repo, a, started):
    cfg, until = tl.profile_slots(repo), end_time(a.until)
    slots = int(cfg.get("count") or 0) > 0
    wt = None
    if not slots:  # the pick and the state that names it, under a lock: two loops starting at once never pick one tree
        with tl.os_lock(tl.config_dir() / "locks" / ("worktree-%s.lock" % paths(repo)["states"][1]), "pid %d" % os.getpid()):
            wt = tl.start_worktree(repo, worktree_name(repo))
            write_state(repo, pid=os.getpid(), started=started, worktree=wt)
    fails, ran, later, pauses = [], 0, {}, {}  # later: a paused or taken bead -> when to try it again
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
        reclaim(repo)
        ranked, _ = queue(repo)
        now = clock()
        cands = [b for b, _ in ranked if later.get(b["id"], 0) <= now]
        if not cands:
            if ranked:
                wake = min(later[b["id"]] for b, _ in ranked)
                say("every ready bead waits for a lane or another session: sleeping until %s"
                    % time.strftime("%H:%M:%S", time.localtime(wake)))
                nap(wake - now, repo, until)
                continue
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
            for b in cands:
                bid = b["id"]
                # a paused run leaves its bead open and still assigned: released here when that run is gone, as run-task does
                ok, why = engine.reclaim(bid, repo)
                if not ok or tl.cmd_claim(engine.Args(id=bid, worktree=d, slot=name)) != 0:
                    record(repo, bid, name, {"outcome": "taken", "why": why if not ok else "claimed by another session"})
                    later[bid] = clock() + PAUSE_RETRY
                    continue
                beat.add(bid)
                rc = prepare(repo, name, b["id"]) if slots else 0
                if rc != 0:
                    tl.bd("unclaim", b["id"], cwd=repo)
                    r = {"outcome": "failed", "why": "failed: tl slot reset %s %s" % (
                        name, "found the slot busy (a live engine or a hold)" if rc == 4 else "did not give a clean tree")}
                else:
                    r = run_bead(repo, b, name, d, slot_bead, started)
                record(repo, b["id"], name, r)
                if r.get("outcome") != "taken":
                    break
                later[bid] = clock() + PAUSE_RETRY
                beat.ids.remove(bid)
                r = None
        finally:
            beat.stop()
            tl.drop_engine_lock(d, os.getpid())
            if slots:
                tl.release_slot(repo, name)
            write_state(repo, pid=os.getpid(), started=started, worktree=wt)
        if r is None:  # every candidate is held by another session: the next pass sleeps until one is due
            continue
        ran += 1
        out = r.get("outcome")
        if out == "landed":
            fails = []
        elif out == "failed":
            fails.append(bid)
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
