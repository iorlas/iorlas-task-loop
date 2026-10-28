"""The loop's composition root: builds the LoopEnv (app/loop) from tl, engine, delegate and the repo, and runs `tl next`,
`tl loop [status]` and `tl stop`. The loop itself is src/taskloop/app/loop; nothing here decides anything."""

import contextlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from taskloop.adapters import applog
from taskloop.domain.beads import matchers as beadlint
import engine
import loop_health as lh
import seams
import tl
from taskloop.adapters import delegate as dg
from taskloop.adapters import procs as sproc
from taskloop.adapters.locks import hold_path
from taskloop.app.doctor import profiles
from taskloop.app.loop.env import LoopEnv, ReloadNote, Storm
from taskloop.app.loop.files import LoopFiles
from taskloop.app.loop.loop import parse_handover
from taskloop.app.loop.queue import QueueRule, area_busy_text, has_areas  # noqa: F401 (engine reads has_areas here)
from taskloop.app.loop.versions import Installs
from taskloop.cli import loop as cli
from taskloop.contracts import paths
from taskloop.contracts.bead import Bead
from taskloop.contracts.config import RepoProfile
from taskloop.contracts.enums import LockWhat

STOP_GRACE_S = 300.0  # a stopped run-task is given this long to run its close step before stream-proc ends it
START_CWD = [""]  # the directory the loop was started in: where its argv's relative paths point


def cfgdir():
    return paths.ConfigDir(tl.config_dir())


def running(repo, store=None):
    """{bead: where} of the beads running now: a slot bead held for one (held_bead), or a live engine lock naming one, in a slot
    or any worktree of the repo."""
    out, slots = {}, tl.slot_beads(repo, store)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for b in slots:
        bid = b.metadata.get("held_bead")
        if bid and b.status == "in_progress" and not (b.lease_expires_at and b.lease_expires_at < stamp):
            out[bid] = b.title.split()[-1]
    for wt in tl.worktrees(repo, slots):
        lock = tl.read_engine_lock(wt)
        if lock.get("bead") and lock.get("pid") and tl.proc_alive(lock["pid"], lock.get("start") or ""):
            out.setdefault(lock["bead"], lock.get("slot") or Path(wt).name)
    return out


def area_lock(repo):
    return hold_path(cfgdir().lock_record(LockWhat.AREA.value, tl.repo_key(repo)), "pid %d" % os.getpid(), what=LockWhat.AREA)


def area_busy(repo, cfg, bead, store=None):
    """(area, "area A busy: B in S") for a bead whose area runs elsewhere, (area, "") when it is free, ("", "") for none (run-task's
    check before it takes the engine lock)."""
    store = store or tl.bd_store(repo)
    return area_busy_text(QueueRule(store, cfg, running(repo, store), lambda b: "", engine.say), bead)


def files_of(repo):
    return LoopFiles(cfgdir(), tl.repo_key(repo), tl.pid_alive, tl.now)


def live_loops(repo):
    return files_of(repo).live()


def delegate_route(repo):
    """The route.py of the delegate this repo's engine would use (its `delegate` config, the pin, the install), or None."""
    res = seams.resolve_delegate(engine.load_cfg(str(repo)).delegate)
    return res.route if isinstance(res, dg.Resolved) else None


def roles(repo):
    route = delegate_route(repo)
    if not route:
        return None
    return {role: v.get("usable") if isinstance((v or {}).get("usable"), bool) else None for role, v in dg.role_status(route).items()}


def make_probe(repo):
    route = delegate_route(repo)
    return dg.RouteProbe(route) if route else None


def storm(repo):
    rid = tl.git("remote", "get-url", "origin", cwd=repo) or str(repo)
    path = lh.storm_path(tl.config_dir(), rid)
    rec = lh.read_storm(path, tl.now())
    if not rec:
        return None
    banner = ("STOPPED: storm %s on %s; the beads stay open (look at their logs). Record %s expires %d min after it was written; "
              "delete it to start sooner" % (rec.get("fingerprint"), ",".join(rec.get("beads") or []), path,
                                             engine.oc.KNOBS["storm_window_s"] // 60))
    return Storm(rec.get("fingerprint") or "", banner)


def landed_on_base(repo, store, wt, bead_id):
    """True when the bead's land commit (titled `... (<id>)`) is the tip of its branch and already on the base."""
    if not os.path.isdir(wt):
        return False
    base = engine.load_cfg(repo).base
    branch = getattr(tl.peek(store, bead_id), "metadata", {}).get("branch") or "task/" + bead_id
    tl.fetch(wt)
    tip = tl.git("rev-parse", "--verify", "-q", "refs/heads/" + branch, cwd=wt)
    if not tip or not tl.git("log", "-1", "--format=%s", tip, cwd=wt).endswith("(%s)" % bead_id):
        return False
    return tl.run_git(wt, "merge-base", "--is-ancestor", tip, base, capture_output=True).returncode == 0


def reload_note(bead):
    rec = engine.read_reexec(bead)
    engine.drop_reexec(bead)
    if not rec:
        return None
    return ReloadNote(run=str(rec.get("run") or ""), to=str(rec.get("to") or ""), frm=str(rec.get("from") or ""),
                      from_dir=str(rec.get("from_dir") or ""), t=float(rec.get("t") or 0))


def fetch(repo):
    tl.fetch(repo)


def chores(repo):
    tl.sweep_asks(engine.say, engine.load_cfg(repo))  # asks of closed beads closed, unanswered ones parked, answers no run used flagged
    try:
        import reflect_digest
        reflect_digest.maybe_run()  # the run reflections into beads, once a day (tl-bl5)
    except Exception as e:
        engine.say("loop: reflect digest: %s" % e)


def claim(repo, bead, wt, slot):
    ok, why = engine.reclaim(bead, repo)  # a paused run leaves its bead open and still assigned: released here when that run is gone
    if not ok:
        return False, why
    return tl.cmd_claim(engine.Args(id=bead, worktree=wt, slot=slot)) == 0, "claimed by another session"


def spawn(cmd, log, extra):
    """run-task as a child in its own process group: Ctrl-C to the loop reaches it only as the loop's SIGTERM.
    -> (the child, the TermHold of its spawn): the caller replays the hold first inside the try that stops the child."""
    return sproc.popen_held(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                            env={**os.environ, **extra})


def stop_now(child: Any) -> None:
    sproc.stop_in_thread(child, STOP_GRACE_S)


def stop_tree(child: Any) -> None:
    sproc.stop_tree(child, grace=STOP_GRACE_S)


def exec_into(repo, d, argv, handover):
    os.environ["TL_LOOP_STATE"] = handover
    if START_CWD[0]:
        os.chdir(START_CWD[0])  # cmd_loop chdir'd into the repo; a relative --repo in argv means the start directory
    sys.stdout.flush()
    sys.stderr.flush()
    applog.close_all()
    try:
        os.execv(sys.executable, [sys.executable, str(d / "skills" / "task-loop" / "tl.py"), *argv])
    except OSError:
        os.environ.pop("TL_LOOP_STATE", None)
        with contextlib.suppress(OSError):
            os.chdir(repo)
        raise


def loop_lock(wt, slot, slot_bead, bead):
    if os.path.isdir(wt):
        tl.loop_lock(wt, slot, slot_bead, bead=bead)


def build(repo, store=None, session_actor=""):
    """The LoopEnv of `repo` on this install."""
    store = store or tl.bd_store(repo)
    cfg = cfgdir()

    def profile() -> RepoProfile:
        return engine.cfg_source(repo)[0]

    return LoopEnv(
        repo=repo, repo_key=tl.repo_key(repo), cfgdir=cfg, store=store, slot_env=lambda: tl.slot_env(repo, store, profile().slots),
        profile=profile, fetch=lambda: fetch(repo), lint=lambda b: beadlint.why(b, str(repo)), running=lambda: running(repo, store),
        area_lock=lambda: area_lock(repo),
        wt_lock=lambda key: hold_path(cfg.lock_record(LockWhat.WORKTREE.value, key), "pid %d" % os.getpid(), what=LockWhat.WORKTREE),
        start_worktree=lambda name: tl.start_worktree(repo, name), claim=lambda b, wt, slot: claim(repo, b, wt, slot),
        loop_lock=loop_lock, drop_engine_lock=lambda d: tl.drop_engine_lock(d, os.getpid()), spawn=spawn,
        stop_now=stop_now, stop_tree=stop_tree,
        run_task_argv=lambda bead, wt, slot, out, code: [sys.executable, str((code or tl.HERE) / "tl.py"), "run-task", bead, "--worktree", wt,
                                                         "--outcome-file", out] + (["--slot", slot] if slot else []),
        landed_on_base=lambda wt, bead: landed_on_base(repo, store, wt, bead), reload_note=reload_note, chores=lambda: chores(repo), ask_lines=lambda: tl.ask_sweeps.orphan_lines(tl.ask_store()),
        storm=lambda: storm(repo), probe=lambda: make_probe(repo), roles=lambda: roles(repo), has_delegate=lambda: bool(delegate_route(repo)),
        event=tl.event, pid_alive=tl.pid_alive, behind=tl.releases_behind, version=tl.HERE.parents[1].name, code_dir=str(tl.HERE),
        session_actor=session_actor, actor=tl.actor, exec_into=lambda d, argv, handover: exec_into(repo, d, argv, handover),
        take_handover=lambda: os.environ.pop("TL_LOOP_STATE", ""), say=engine.say, now=tl.now, pid=os.getpid())


def installs(cfg, tune=None):
    """The installs of task-loop on this machine; `tune` gives the loop constants (the repo's `loop` block), else the defaults."""
    kw = {"tune": tune} if tune else {}
    return Installs(cfg, tl.HERE.parents[1], lambda: tl.installed_version("task-loop"), lambda: tl.read_pin().get("task-loop") or "",
                    now=tl.now, **kw)


def vet_newer():
    """(version, dir, why) of the install the loop would move to (why: None when usable), or None: engine's step-boundary look."""
    t = installs(cfgdir()).vet()
    return (t.version, t.dir, t.why) if t else None


def cmd_next(a):
    repo = tl.repo_root(a.repo)
    return cli.cmd_next(build(repo), a)


def cmd_stop(a):
    repo = tl.repo_root(a.repo)
    return cli.cmd_stop(build(repo), files_of(repo), a)


def cmd_loop(a):
    repo = tl.repo_root(a.repo)
    if profiles.red_row(repo):
        print(profiles.red_row(repo))
        return 1
    env = build(repo)
    files = files_of(repo)
    if a.op == "status":
        for row in profiles.red_rows(profiles.registered(tl.config_dir() / "repos.json"), but=repo):
            print(row)  # another repo's bad profile: its red row here, nothing else changes
        return cli.cmd_status(env, files, installs(env.cfgdir, lambda: env.profile().loop), a)
    START_CWD[0] = os.getcwd()
    os.chdir(repo)  # every tl helper and bd call works on the current directory's repo
    inherited, _ = parse_handover(os.environ.get("TL_LOOP_STATE", ""))  # set when this process is the same loop, exec'd into a newer install
    if not tl.session_id():  # without a Claude session the actor would be per folder: two loops would share it
        os.environ["TASK_LOOP_SESSION"] = "loop-" + uuid.uuid4().hex[:12]
    # an actor of its own, never the session's: bd lets an actor re-claim its own bead, so two loops (or a loop and a hand run)
    # started from one session would both win one claim. run-task re-claims as this actor (one for both).
    os.environ.pop("TASK_LOOP_ACTOR", None)
    session = tl.actor()
    os.environ["TASK_LOOP_ACTOR"] = (inherited.actor if inherited else "") or "%s-%s" % (session, uuid.uuid4().hex[:6])
    env = build(repo, session_actor=session)
    return cli.cmd_loop(env, files, installs(env.cfgdir, lambda: env.profile().loop), a)
