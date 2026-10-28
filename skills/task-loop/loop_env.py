"""The loop's composition root: builds the LoopEnv (app/loop) from tl, engine, delegate and the repo, and runs `tl next`,
`tl loop [status]` and `tl stop`. The loop itself is src/taskloop/app/loop; nothing here decides anything."""

import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from taskloop.adapters import applog, beadtools, gitrepo, ident, pidcheck
from taskloop.domain.beads import matchers as beadlint
import outcome as oc
from taskloop.app.run import entry
from taskloop.app.run.running import area_busy, area_lock, running
from taskloop.app.run import console
import loop_health as lh
import seams
from taskloop.app.release import catalog, reexec
from taskloop.app.slots import engine_lock
from taskloop.app.release import pins
from taskloop.app.track import trail
from taskloop.app.wire import asks as wasks
from taskloop.app.wire import lanes as wlanes
from taskloop.app.wire import slots as wslots
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
from taskloop.adapters.gitenv import run_git
from taskloop.app.track import verbs
from taskloop.app.asks import sweeps as ask_sweeps

STOP_GRACE_S = 300.0  # a stopped run-task is given this long to run its close step before stream-proc ends it
HERE = Path(__file__).resolve().parent  # the install this code runs from; tl.main takes it as a parameter for a test
START_CWD = [""]  # the directory the loop was started in: where its argv's relative paths point


def cfgdir():
    return paths.ConfigDir(ident.config_dir())



def files_of(repo, now=trail.now):
    return LoopFiles(cfgdir(), wslots.repo_key(repo), pidcheck.pid_alive, now)


def live_loops(repo):
    return files_of(repo).live()


def delegate_route(repo):
    """The route.py of the delegate this repo's engine would use (its `delegate` config, the pin, the install), or None."""
    res = seams.resolve_delegate(wslots.load_cfg(str(repo)).delegate)
    return res.route if isinstance(res, dg.Resolved) else None


def roles(repo):
    route = delegate_route(repo)
    if not route:
        return None
    return {role: v.get("usable") if isinstance((v or {}).get("usable"), bool) else None for role, v in dg.role_status(route).items()}


def make_probe(repo):
    route = delegate_route(repo)
    return dg.RouteProbe(route) if route else None


def storm(repo, now=trail.now):
    rid = gitrepo.git("remote", "get-url", "origin", cwd=repo) or str(repo)
    path = lh.storm_path(ident.config_dir(), rid)
    rec = lh.read_storm(path, now())
    if not rec:
        return None
    banner = ("STOPPED: storm %s on %s; the beads stay open (look at their logs). Record %s expires %d min after it was written; "
              "delete it to start sooner" % (rec.get("fingerprint"), ",".join(rec.get("beads") or []), path,
                                             oc.KNOBS["storm_window_s"] // 60))
    return Storm(rec.get("fingerprint") or "", banner)


def landed_on_base(repo, store, wt, bead_id):
    """True when the bead's land commit (titled `... (<id>)`) is the tip of its branch and already on the base."""
    if not os.path.isdir(wt):
        return False
    base = wslots.load_cfg(repo).base
    branch = getattr(beadtools.peek(store, bead_id), "metadata", {}).get("branch") or "task/" + bead_id
    gitrepo.fetch(wt)
    tip = gitrepo.git("rev-parse", "--verify", "-q", "refs/heads/" + branch, cwd=wt)
    if not tip or not gitrepo.git("log", "-1", "--format=%s", tip, cwd=wt).endswith("(%s)" % bead_id):
        return False
    return run_git(wt, "merge-base", "--is-ancestor", tip, base, capture_output=True).returncode == 0


def reload_note(bead):
    rec = reexec.read_reexec(bead)
    reexec.drop_reexec(bead)
    if not rec:
        return None
    return ReloadNote(run=str(rec.get("run") or ""), to=str(rec.get("to") or ""), frm=str(rec.get("from") or ""),
                      from_dir=str(rec.get("from_dir") or ""), t=float(rec.get("t") or 0))


def fetch(repo):
    gitrepo.fetch(repo)


def chores(repo):
    wlanes.chore(console.say)  # delegate's lane status filed again when the snapshot is 20 min old (the dash reads the file)
    wasks.sweep_asks(console.say, wslots.load_cfg(repo))  # asks of closed beads closed, unanswered ones parked, answers no run used flagged
    try:
        import reflect_digest
        reflect_digest.maybe_run()  # the run reflections into beads, once a day (tl-bl5)
    except Exception as e:
        console.say("loop: reflect digest: %s" % e)


def claim(repo, store, bead, wt, slot, now=trail.now):
    ok, why = entry.reclaim(bead, repo, store, now())  # a paused run leaves its bead open and still assigned: released here when that run is gone
    if not ok:
        return False, why
    return verbs.claim(bead, wt, slot, store=store) == 0, "claimed by another session"


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
        engine_lock.loop_lock(wt, slot, slot_bead, bead=bead)


def build(repo, store=None, session_actor="", here=HERE, now=trail.now):
    """The LoopEnv of `repo` on this install."""
    store = store or beadtools.bd_store(repo)
    cfg = cfgdir()

    def profile() -> RepoProfile:
        return wslots.cfg_source(repo)[0]

    return LoopEnv(
        repo=repo, repo_key=wslots.repo_key(repo), cfgdir=cfg, store=store, slot_env=lambda: wslots.slot_env(repo, store, profile().slots, now),
        profile=profile, fetch=lambda: fetch(repo), lint=lambda b: beadlint.why(b, str(repo)), running=lambda: running(repo, store),
        area_lock=lambda: area_lock(repo),
        wt_lock=lambda key: hold_path(cfg.lock_record(LockWhat.WORKTREE.value, key), "pid %d" % os.getpid(), what=LockWhat.WORKTREE),
        start_worktree=lambda name: wslots.start_worktree(repo, name), claim=lambda b, wt, slot: claim(repo, store, b, wt, slot, now),
        loop_lock=loop_lock, drop_engine_lock=lambda d: engine_lock.drop_engine_lock(d, os.getpid()), spawn=spawn,
        stop_now=stop_now, stop_tree=stop_tree,
        run_task_argv=lambda bead, wt, slot, out, code: [sys.executable, str((code or here) / "tl.py"), "run-task", bead, "--worktree", wt,
                                                         "--outcome-file", out] + (["--slot", slot] if slot else []),
        landed_on_base=lambda wt, bead: landed_on_base(repo, store, wt, bead), reload_note=reload_note, chores=lambda: chores(repo), ask_lines=lambda: ask_sweeps.orphan_lines(wasks.store()),
        storm=lambda: storm(repo, now), probe=lambda: make_probe(repo), roles=lambda: roles(repo), has_delegate=lambda: bool(delegate_route(repo)),
        event=trail.event, pid_alive=pidcheck.pid_alive, behind=catalog.releases_behind, version=here.parents[1].name, code_dir=str(here),
        session_actor=session_actor, actor=ident.actor, exec_into=lambda d, argv, handover: exec_into(repo, d, argv, handover),
        take_handover=lambda: os.environ.pop("TL_LOOP_STATE", ""), say=console.say, now=now, pid=os.getpid())


def installs(cfg, tune=None, here=HERE, now=trail.now):
    """The installs of task-loop on this machine; `tune` gives the loop constants (the repo's `loop` block), else the defaults."""
    kw = {"tune": tune} if tune else {}
    return Installs(cfg, here.parents[1], lambda: catalog.installed_version("task-loop"), lambda: pins.read_pin().get("task-loop") or "",
                    now=now, **kw)


def vet_newer(here=HERE):
    """(version, dir, why) of the install the loop would move to (why: None when usable), or None: engine's step-boundary look."""
    t = installs(cfgdir(), here=here).vet()
    return (t.version, t.dir, t.why) if t else None


def cmd_next(a, here=HERE, now=trail.now):
    repo = gitrepo.repo_root(a.repo)
    return cli.cmd_next(build(repo, here=here, now=now), a)


def cmd_stop(a, here=HERE, now=trail.now):
    repo = gitrepo.repo_root(a.repo)
    return cli.cmd_stop(build(repo, here=here, now=now), files_of(repo, now), a)


def cmd_loop(a, here=HERE, now=trail.now):
    repo = gitrepo.repo_root(a.repo)
    if profiles.red_row(repo):
        print(profiles.red_row(repo))
        return 1
    env = build(repo, here=here, now=now)
    files = files_of(repo, now)
    if a.op == "status":
        for row in profiles.red_rows(profiles.registered(ident.config_dir() / "repos.json"), but=repo):
            print(row)  # another repo's bad profile: its red row here, nothing else changes
        return cli.cmd_status(env, files, installs(env.cfgdir, lambda: env.profile().loop, here, now), a)
    START_CWD[0] = os.getcwd()
    os.chdir(repo)  # every tl helper and bd call works on the current directory's repo
    inherited, _ = parse_handover(os.environ.get("TL_LOOP_STATE", ""))  # set when this process is the same loop, exec'd into a newer install
    if not ident.session_id():  # without a Claude session the actor would be per folder: two loops would share it
        os.environ["TASK_LOOP_SESSION"] = "loop-" + uuid.uuid4().hex[:12]
    # an actor of its own, never the session's: bd lets an actor re-claim its own bead, so two loops (or a loop and a hand run)
    # started from one session would both win one claim. run-task re-claims as this actor (one for both).
    os.environ.pop("TASK_LOOP_ACTOR", None)
    session = ident.actor()
    os.environ["TASK_LOOP_ACTOR"] = (inherited.actor if inherited else "") or "%s-%s" % (session, uuid.uuid4().hex[:6])
    env = build(repo, session_actor=session, here=here, now=now)
    return cli.cmd_loop(env, files, installs(env.cfgdir, lambda: env.profile().loop, here, now), a)


def live_work():
    """What runs on this machine: ("loop"|"run", text) for every live loop and every busy engine lock of the registered repos."""
    try:
        repos = [r for r in json.loads(paths.ConfigDir(ident.config_dir()).repos().read_text(encoding="utf-8")) if os.path.isdir(r)]
    except (OSError, ValueError):
        repos = []
    out = []
    for r in repos:
        for st in live_loops(r):
            out.append(("loop", "loop pid %s on %s%s" % (st.pid, r, (" running " + st.bead) if st.bead else "")))
        for wt in [r] + wslots.worktrees(r, slots=None if shutil.which("bd") else []):  # slot dirs need bd
            busy = engine_lock.engine_busy(wt)
            if busy:
                out.append(("run", "run in %s: %s" % (wt, busy)))
    return out


def cmd_cutover(a):
    live = live_work()
    if a.json:
        print(json.dumps({"live": [{"kind": k, "what": w} for k, w in live]}))
    elif live:
        print("\n".join("LIVE %s" % w for _, w in live))
    else:
        print("CLEAR: no live loop or run")
    return 1 if live else 0
