"""Child processes: the env a child gets, running a delegate call, stopping its tree, the engine lock (moved unchanged from engine.py, E1 + E2)."""
import contextlib
import os
import re
import signal
import subprocess
import threading
import time

import tl

GIT_PIN_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")  # the engine's own git is pinned; no child inherits a pin


def child_env():
    """Workers never inherit the launcher's session (a leaked CLAUDE_* broke claude children in the factory)."""
    drop = ("CLAUDE_CODE_", "CLAUDECODE", "ANTHROPIC_", "DELEGATE_", "CODEX_COMPANION", "CLAUDE_PID",
            "CLAUDE_AGENT_SDK", "CLAUDE_PLUGIN", "TASK_LOOP_")
    env = {k: v for k, v in os.environ.items() if not k.startswith(drop) and k not in GIT_PIN_VARS}
    env["TASK_LOOP_WORKER"] = "1"
    env["DELEGATE_DEPTH"] = "1"  # a worker never delegates further
    return env


class TreeHashError(RuntimeError):
    """git could not say what the worktree would commit (read-tree, add or write-tree failed): no hash beats a hash of a half-built index."""


class TermHold:
    """Holds a SIGTERM that arrives while a child is being spawned, so the caller can stop that child first.
    Python runs its handler between bytecodes of the main thread, and the engine's handler raises: raised from inside
    Popen(), the exception leaves the constructor, the caller never gets the Popen object and the new child (and its tree)
    runs on unowned. A check that signals the engine at once (or a stop arriving right at a spawn) hits that window, more
    often when the machine is loaded. `with TermHold() as hold: p = Popen(...)`, then `hold.replay()` as the first line of the caller's
    try (the handler stays swapped until then), where the handler's raise finds p and the cleanup kills it. A no-op off the main thread or for a non-callable handler."""

    def __enter__(self):
        self.old, self.held = None, False
        if threading.current_thread() is threading.main_thread():
            old = signal.getsignal(signal.SIGTERM)
            if callable(old):
                self.old = old
                signal.signal(signal.SIGTERM, lambda *_: setattr(self, "held", True))
        return self

    def __exit__(self, kind, *_):
        if kind:  # a failed spawn has nothing to stop: the real handler is back at once
            self.release()
        return False

    def release(self):
        if self.old is not None:
            signal.signal(signal.SIGTERM, self.old)

    def replay(self):
        """The handler goes back and a held SIGTERM runs it now. Call it first thing inside the try that stops the child."""
        self.release()
        if self.held:
            self.held = False
            self.old(signal.SIGTERM, None)


def popen_held(*args, **kw):
    """(Popen(*args, **kw), the TermHold that kept a SIGTERM from unwinding the spawn); the caller calls hold.replay() inside its try."""
    with TermHold() as hold:
        return subprocess.Popen(*args, **kw), hold


WORKER_LINE = re.compile(r"delegate: worker pid=(\d+) pgid=(\d+)(?: run_id=(\S+))?")  # route.py 0.31.1+, on stderr when it starts one


VENDOR_ERROR_LINE = re.compile(r"\b(?:error|failed|failure|exception|timeout|timed out|refused|denied|"
                               r"rate.?limit|quota|out of credits|unavailable|crash(?:ed)?)\b", re.I)


def run_proc(cmd, cwd, timeout, log_path, on_line=None, env=None, idle=None, stop=None, obs=None):
    """Run a delegate call. timeout: the wall-clock limit; with `idle` (a write) it holds only while the worker's activity
    cannot be seen. A call stopped by a limit returns (None, secs) and, in `stop`, why and the pids of its worker that
    outlived the stop (prove_dead): the caller must not start another worker in the same tree while any lives.
    `obs` gets the process boundaries: started_t, ended_t, first_error_t, last_event_t, kill_t, why and alive. A missing
    boundary is None, never the completion time."""
    t = time.time()
    lines, worker = [], {}
    obs = {} if obs is None else obs
    obs.update(started_t=t, ended_t=None, first_error_t=None, last_event_t=None, kill_t=None, why="", alive=[])
    obs_lock, state = threading.Lock(), {"frozen": False}

    def note(ln):
        now = time.time()
        with obs_lock:  # the stop path freezes the last event and first error at the kill boundary
            if state["frozen"]:
                return
            obs["last_event_t"] = now
            if obs["first_error_t"] is None and VENDOR_ERROR_LINE.search(ln):
                obs["first_error_t"] = now
    with open(log_path, "ab") as log:
        p = subprocess.Popen(cmd, cwd=cwd, env=dict(child_env(), **(env or {})), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        if LOCK:
            LOCK.note(route_pid=p.pid)

        def read():
            for raw in p.stdout:
                ln = raw.decode("utf-8", "replace")
                note(ln)
                lines.append(ln)
                if idle:
                    idle.touch()
                if on_line:
                    try:
                        on_line(ln)
                    except Exception:
                        pass

        def read_err():  # route.py's stderr to the log; its worker line says which process group to stop
            for raw in p.stderr:
                text = raw.decode("utf-8", "replace")
                note(text)
                if idle:
                    idle.touch()
                try:
                    log.write(raw)
                    log.flush()
                except (ValueError, OSError):  # the call is over and its log closed
                    pass
                m = WORKER_LINE.search(text)
                if m:
                    pid = int(m.group(1))
                    worker.update(pid=pid, pgid=int(m.group(2)), start=tl.proc_start(pid), run_id=m.group(3) or "")
                    if LOCK:
                        LOCK.note(workers=[[pid, worker["start"]]])
        if idle:
            idle.begin()
        readers = [threading.Thread(target=f, daemon=True) for f in (read, read_err)]
        for r in readers:
            r.start()
        stopped = False
        try:
            try:
                why = idle.wait(p, worker, timeout) if idle else wait_wall(p, timeout)
            except BaseException:  # stopped: never leave the worker running
                stopped = True
                with obs_lock:
                    state["frozen"] = True
                    obs.update(kill_t=time.time(), why="interrupted")
                obs["alive"] = stop_and_prove(p, log, worker)
                obs["ended_t"] = time.time()
                if stop is not None:
                    stop.update(obs)
                raise
            if why:
                stopped = True
                with obs_lock:
                    state["frozen"] = True
                    obs.update(kill_t=time.time(), why=why)
                obs["alive"] = stop_and_prove(p, log, worker)
                obs["ended_t"] = time.time()
                if stop is not None:
                    stop.update(obs)
                for r in readers:
                    r.join(2)
                return None, time.time() - t
        finally:
            if LOCK:
                LOCK.note(route_pid=None, **({} if stopped else {"workers": []}))
        for r in readers:
            r.join(10)
        obs["ended_t"] = time.time()
    return (p.returncode, "".join(lines)), time.time() - t


def wait_wall(p, timeout):
    """"" when the call ended within `timeout` seconds, else why it is stopped."""
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return "timeout %d min" % (timeout // 60)
    return ""


STOP_GRACE = 10  # seconds route.py gets to stop its worker after a SIGTERM, before everything is SIGKILLed


PROOF_TERM, PROOF_KILL = 5, 10  # seconds a worker that outlived the stop gets after a SIGTERM, then after a SIGKILL
REAP_WAIT, EXIT_WAIT = 5, 2  # seconds to reap the killed delegate process, then to see the worker's pid gone (tests shrink both)


def own_ids():
    """Pids and group ids this process must never signal: itself, its group, its parent and the parent's group."""
    ids = {os.getpid(), os.getpgrp(), os.getppid()}
    with contextlib.suppress(OSError):
        ids.add(os.getpgid(os.getppid()))
    return ids


def send_group(pgid, sig, pid=None, start=""):
    """killpg that never signals the caller's own group (or its parent's): a recorded or parsed group id is only a claim.
    pid (+ start): the member that names the group; it must still be that process and still sit in that group."""
    if not pgid or pgid <= 1 or pgid in own_ids():
        raise RuntimeError("refusing to signal process group %s: it is ours or our parent's" % pgid)
    if pid is not None:
        if not tl.proc_alive(pid, start):
            return False
        try:
            if os.getpgid(pid) != pgid:
                return False
        except OSError:
            return False
    try:
        os.killpg(pgid, sig)
    except OSError:
        return False
    return True


def send_pid(pid, sig, start=""):
    """kill that never signals the caller itself or its parent, and only the process that started at `start`."""
    if not pid or pid <= 1 or pid in own_ids():
        raise RuntimeError("refusing to signal pid %s: it is ours or our parent's" % pid)
    if start and not tl.proc_alive(pid, start):
        return False
    try:
        os.kill(pid, sig)
    except OSError:
        return False
    return True


def signal_child(p, sig):
    """Signal a child's whole group when it leads a group of its own, else the child alone: a child that shares our
    group (no new session) is never reached through the group id, which is ours."""
    try:
        led = os.getpgid(p.pid) == p.pid
    except OSError:
        led = True  # gone or mocked: its pid is the group id it would have led
    try:
        if led:
            return send_group(p.pid, sig)
        return send_pid(p.pid, sig)
    except RuntimeError:
        return False


def stop_tree(p, log=None, worker=None):
    """Stop a delegate call and its worker. route.py runs the worker in a process group of its own and stops it on
    SIGTERM, never on SIGKILL: a SIGKILL to route.py's group alone orphaned the lifesim-5ar.7 writer, which kept editing
    the slot after its engine stopped (2026-10-21). So: note the whole tree, SIGTERM route.py, give it STOP_GRACE, look
    again, then SIGKILL what is still the same process (same pid, group and start time in both looks: a pid reused in
    between is never hit). A survivor is written to the log and kept in the engine lock, so the slot stays busy while
    it lives. route.py 0.31.1+ names its worker (`delegate: worker pid=N pgid=N` on stderr): then SIGTERM to route.py
    is the stop (it SIGKILLs the worker's group), and only a route.py still alive after STOP_GRACE is SIGKILLed with the
    worker's group. The ps tree walk is for a route.py that named no worker."""
    if worker and worker.get("pgid"):
        return stop_named(p, log, worker)
    before = tl.proc_table()
    tree = descendants(p.pid, before)
    signal_child(p, signal.SIGTERM)
    try:
        p.wait(timeout=STOP_GRACE)
    except subprocess.TimeoutExpired:
        pass
    if p.returncode is None:  # unreaped, its pid and group id cannot have been reused
        signal_child(p, 9)
    after = tl.proc_table()
    same = [(pid, pgid, st) for pid, pgid, st in tree if after.get(pid, (None, None, None))[1:] == (pgid, st)]
    for pid, pgid, st in same:
        with contextlib.suppress(RuntimeError):
            send_group(pgid, 9)  # a group with a member still in it keeps its id; never our own or our parent's
        with contextlib.suppress(RuntimeError):
            send_pid(pid, 9)
    with contextlib.suppress(Exception):
        p.wait(timeout=REAP_WAIT)
    end, left = time.time() + EXIT_WAIT, same
    while left and time.time() < end:
        left = [x for x in left if tl.proc_alive(x[0], x[2])]
        if left:
            time.sleep(0.05)
    if left:
        if log:
            log.write(("\u26a0 worker pid %s outlived the stop of its delegate call\n" % [x[0] for x in left]).encode())
        if LOCK:
            LOCK.note(workers=[[x[0], x[2]] for x in left])
    return [x[0] for x in left]


def stop_and_prove(p, log, worker):
    """stop_tree, then the proof that nothing of the call is left (prove_dead). -> pids still alive."""
    tree = descendants(p.pid, tl.proc_table())  # looked at before the stop: a child in a session of its own is reparented to init by it
    alive = stop_tree(p, log, worker)
    alive = prove_dead(alive, worker, log, tree)
    if LOCK:
        LOCK.note(workers=[[pid, tl.proc_start(pid)] for pid in alive])  # a survivor keeps the slot busy; none: free
    return alive


def lingering(pids, worker, tree=()):
    """[(pid, start)] of the stopped call's processes still alive: `pids`, `tree` (what ran under route.py before the stop,
    as descendants() lists it: still the same process when the start time matches), the worker route.py named with
    everything under it, and the members of its group while the worker leads it. Never ours, our group's or our parent's."""
    table = tl.proc_table()
    ours = own_ids()
    want = set(pids) | {pid for pid, _, start in tree if tl.proc_alive(pid, start)}
    if worker.get("pid") and tl.proc_alive(worker["pid"], worker.get("start") or ""):
        want.add(worker["pid"])
    for pid in list(want):
        want.update(k[0] for k in descendants(pid, table))
    pgid = worker.get("pgid")
    if pgid and pgid > 1 and pgid not in ours and tl.proc_alive(worker.get("pid"), worker.get("start") or ""):
        # only while the leader is the process route.py named: a dead worker's group id may be an unrelated group's now
        want.update(pid for pid, (_, pg, _) in table.items() if pg == pgid)
    return [(pid, table[pid][2]) for pid in sorted(want - ours) if pid in table and tl.proc_alive(pid, table[pid][2])]


def group_empty(pgid):
    """No process is left in group `pgid` (a signal 0 finds nobody). False for our own group and when unsure."""
    if not pgid or pgid <= 1 or pgid in own_ids():
        return False
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def prove_dead(pids, worker, log=None, tree=()):
    """After a delegate call was stopped: look until its worker's whole tree is gone, SIGTERM then SIGKILL to what is not.
    A group id named by route.py is only a claim (the worker may sit in another group: lifesim-fld.27.10's Claude writer
    survived the stop and wrote on under the retry), so every survivor is also signalled by pid. -> pids still alive:
    the caller does not start another worker in this tree."""
    worker = worker or {}
    if not pids and not any(tl.proc_alive(pid, start) for pid, _, start in tree):
        if not worker.get("pid") or group_empty(worker.get("pgid")):
            return []  # nothing of the tree lives, and the named worker's group is empty: no process-table walk needed
    left = lingering(pids, worker, tree)
    for sig, secs in ((signal.SIGTERM, PROOF_TERM), (signal.SIGKILL, PROOF_KILL)):
        if not left:
            break
        for pid, start in left:
            with contextlib.suppress(RuntimeError, OSError):  # its own group too: Claude's background shells sit in one
                send_group(os.getpgid(pid), sig, pid=pid, start=start)
            with contextlib.suppress(RuntimeError):
                send_pid(pid, sig, start)
        end = time.time() + secs
        while left and time.time() < end:
            left = [x for x in left if tl.proc_alive(*x)]
            if left:
                time.sleep(0.05)
        left = lingering([x[0] for x in left], worker, tree)
    if left and log:
        log.write(("\u26a0 worker pid %s outlived SIGTERM and SIGKILL after the stop of its delegate call\n"
                   % [x[0] for x in left]).encode())
    return [x[0] for x in left]


def stop_named(p, log, w):
    signal_child(p, signal.SIGTERM)
    try:
        p.wait(timeout=STOP_GRACE)
    except subprocess.TimeoutExpired:
        signal_child(p, 9)
    with contextlib.suppress(RuntimeError):  # the worker route.py named: still that process, still in that group, never ours
        send_group(w["pgid"], 9, pid=w["pid"], start=w.get("start") or "")
    with contextlib.suppress(Exception):
        p.wait(timeout=REAP_WAIT)
    end = time.time() + EXIT_WAIT
    while time.time() < end and tl.proc_alive(w["pid"], w.get("start") or ""):
        time.sleep(0.05)
    if not tl.proc_alive(w["pid"], w.get("start") or ""):
        return []
    if log:
        log.write(("\u26a0 worker pid %s outlived the stop of its delegate call\n" % w["pid"]).encode())
    if LOCK:
        LOCK.note(workers=[[w["pid"], w.get("start") or ""]])
    return [w["pid"]]


def descendants(pid, table):
    """[(pid, pgid, start)] of every process under `pid` in a tl.proc_table()."""
    kids = {}
    for k, (ppid, pgid, st) in table.items():
        kids.setdefault(ppid, []).append((k, pgid, st))
    found, todo = [], [pid]
    while todo:
        for k in kids.get(todo.pop(), []):
            if k not in found:
                found.append(k)
                todo.append(k[0])
    return found


class EngineLock:
    """<worktree>/.task/engine.lock while run-task runs there (see tl.engine_busy). A worker that outlived its stop keeps
    the lock (pid 0) until it is gone."""

    def __init__(self, wt, bead, slot=""):
        self.wt = wt
        self.path = tl.engine_lock_path(wt)
        self.data = {"pid": os.getpid(), "start": tl.proc_start(os.getpid()), "bead": bead, "slot": slot or "",
                     "slot_bead": os.environ.get("TASK_LOOP_SLOT_BEAD", ""), "by": "run-task", "started": time.time(),
                     "route": None, "workers": []}

    def take(self):
        """"" when this run holds the worktree now, else what holds it. A run the loop started takes over the loop's
        lock for its slot."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handoff = True  # engine_busy lets it take over only its parent loop's lock for the same slot bead
        for _ in range(3):
            busy = tl.engine_busy(self.wt, handoff=handoff)
            if busy:
                return busy
            try:  # created only if absent: two runs starting at once cannot both win
                os.close(os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            except FileExistsError:
                with contextlib.suppress(OSError):  # a dead run's lock or the parent loop's (engine_busy said so)
                    if not tl.engine_busy(self.wt, handoff=handoff):
                        self.path.unlink()
                continue
            self.write()
            return ""
        return "another run took the engine lock at the same time"

    def write(self):
        tl.write_engine_lock(self.wt, self.data)

    def note(self, route_pid=False, **kw):
        if route_pid is not False:
            kw["route"] = [route_pid, tl.proc_start(route_pid)] if route_pid else None
        self.data.update(kw)
        with contextlib.suppress(OSError):
            self.write()

    def release(self):
        left = [w for w in self.data.get("workers") or [] if tl.proc_alive(w[0], w[1])]
        with contextlib.suppress(OSError):
            if left:
                self.data.update(pid=0, route=None, workers=left)
                self.write()
            else:
                self.path.unlink()


LOCK = None  # this process's EngineLock while run-task runs


def kill_tree(p):
    try:
        if p.pid in own_ids() or (p.returncode is None and os.getpgid(p.pid) in own_ids()):
            raise RuntimeError("kill_tree: child %s is in our own process group; refusing to kill it" % p.pid)
        try:  # a descendant that called setsid left the group: note it now, before it is reparented
            away = [(k, st) for k, g, st in descendants(p.pid, tl.proc_table()) if g != p.pid]
        except Exception:
            away = []
        send_group(p.pid, signal.SIGTERM)  # Unity removes Temp/UnityLockfile on SIGTERM
        end = time.time() + 10
        while time.time() < end and tl.proc_alive(p.pid):  # not p.wait(): a reaped leader frees its pid, and its
            time.sleep(0.1)                                # group id with it, for any new process to take
        if p.returncode is None:
            send_group(p.pid, signal.SIGKILL)  # stragglers; p is still unreaped, so the group id is still its own
        for sig in (signal.SIGTERM, signal.SIGKILL):  # setsid'd descendants: the same pid and start time only
            for k, st in away:
                try:
                    send_pid(k, sig, st)
                except RuntimeError:
                    pass
            if sig == signal.SIGTERM and away:
                time.sleep(1)
    except OSError:
        pass
    p.wait()
