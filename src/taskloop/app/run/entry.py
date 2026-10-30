"""The run-task entry: the slot or worktree a run takes, the admission of its bead (a blocked one reopened), and the one outcome line."""
import contextlib
import fcntl
import json
import os
import signal
import stat
import sys
import threading
import time
import uuid
from collections.abc import Generator
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text

from taskloop.adapters import beadtools, childenv, gitrepo, ident
from taskloop.adapters import halt as halting
from taskloop.app.asks import intake
from taskloop.app.loop.queue import has_areas
from taskloop.app.reconcile import leases
from taskloop.app.run import console, running
from taskloop.app.run.engine import Blocked, Engine
from taskloop.app.slots import engine_lock
from taskloop.app.track import verbs
from taskloop.app.wire import slots as wslots
from taskloop.contracts import env as penv
from taskloop.contracts import fence, wire
from taskloop.contracts.bead import Bead
from taskloop.contracts.enums import AskStatus, Result
from taskloop.contracts.env import Env
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.fence import SLOT_GEN
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import BdFailure, BeadPatch, Spawner
from taskloop.contracts.run import Reexec, RunReport
from taskloop.contracts.stores import AskStore

say = console.say
engine_written = intake.engine_written  # what the engine (or a receipt of ours) wrote into a bead is never the owner's (tl-7y6.6.2)
TL_PY = Path(__file__).resolve().parents[4] / "skills" / "task-loop" / "tl.py"


class Args:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


def release_dead(repo: Any, store: Any = None) -> None:
    """The reconcile sweep's lease rules, before a run takes its bead: a dead run's claim (a crashed or paused one, a restarted session's
    old actor) is given back by the same rule `tl prune` and the loop's step use."""
    for line in leases.release_dead(repo, store or beadtools.bd_store(repo), running.running(repo, store), ident.hostname(), time.time()):
        say(line)


def _foreign_claim(b: Any, repo: Any, store: Any) -> str:
    """Why another actor's claim on the bead stops a run-task, "" when it does not: the sweep already gave back every dead one, so a claim
    that is left is live (a lease running, or a run on it). A blocked bead is the actor's still: it goes only when its engine is gone."""
    bead_id, who = b.id, b.assignee
    if not who.startswith("tl-"):
        return f"claimed by {who}"
    if b.status == "blocked" and bead_id not in running.running(repo, store):
        return ""
    logs = sorted((ident.config_dir() / "engine").glob(f"{bead_id}-*.jsonl"))
    return f"another run of {bead_id} is still running as {who} (a live claim)" + (f"; its engine log: {logs[-1]}" if logs else "")


def _blocked_by_engine(b: Any, store: Any) -> str:
    """Why a bead the engine blocked stays blocked ("" when a plain retry may reopen it)."""
    bead_id = b.id
    held = [d.id for d in b.dependencies if d.type == "blocks" and d.status != "closed"]
    if held:
        return "blocked by {}".format(", ".join(held))
    cs = store.comments(bead_id)
    blocks = [c for c in cs if c.text.startswith("Blocked:")]
    if not blocks:
        return "blocked by a person, not by the engine"
    after = [c for c in cs if c.created_at > blocks[-1].created_at and not engine_written(c.text)]
    ask = AskStore.at(ConfigDir(ident.config_dir())).get(bead_id)
    asking = ask is not None and ask.consumed is None and ask.status in (AskStatus.OPEN, AskStatus.PARKED, AskStatus.ANSWERED)
    if ask is not None and asking and ask.answer is not None:  # tl-gy4: an answer filed on the ask (dashboard, tl ask answer) is an answer
        after, asking = after[:0], False  # whether or not a comment followed the block; the run's check_ask consumes it
    if ask is not None and asking and not after:
        return f"waiting for the answer to ask {ask.id} ({ask.kind.value})"
    if after and not asking:
        return "{} commented after the engine blocked it; read that first".format(after[-1].author or "someone")
    return ""


def admit(bead_id: Any, repo: Any, store: Any = None, at: Any = None) -> Any:
    """(ok, why): whether run-task may take the bead, never taking what a person holds. A bead the engine blocked is reopened for a
    plain retry, or when a comment after the block answers the open ask; it stays blocked when a person commented after the block with
    no ask open (they may have parked it), while an ask waits unanswered, or while another bead blocks it. A claim by another actor
    that is still live stops it (dead ones are given back by `release_dead`, the reconcile lease rules, which runs first)."""
    store = store or beadtools.bd_store(repo)
    b = beadtools.peek(store, bead_id) or Bead(id=bead_id, title="", status="")
    who, me = b.assignee, ident.actor()
    if intake.held(b.metadata, at or time.time()):
        return False, f"held by the owner ({b.metadata[intake.HOLD]}): `tl hold {bead_id} --release` lets it go"
    if who and who != me:
        why = _foreign_claim(b, repo, store)
        if why:
            return False, why
    if b.status != "blocked":
        return True, ""
    why = _blocked_by_engine(b, store)
    if why:
        return False, why
    # tl-kwo: only if the claim is still the one just read (bd applies --if-assignee atomically): two loops looking at one freed bead
    # must not both reopen and then both claim
    guard = bool(who and who != me)
    try:
        store.update(bead_id, BeadPatch(status="open", if_assignee=who if guard else "", assignee=""))
    except BdFailure:
        if guard:
            return False, f"the claim of {bead_id} changed hands just now ({who} no longer holds it): not taken"
    return True, "reopened"


def append_output(stream: Any) -> Any:
    """Write a stream that is a file at the end of that file, wherever another writer left it: a second
    `run-task ... > log` on the same log truncates it, and a live run writing on at its old offset leaves a hole of NUL
    bytes (lifesim-gfr.31.1). A terminal, a pipe or a stream with no descriptor is left as it is."""
    try:
        fd = stream.fileno()
        regular = stat.S_ISREG(os.fstat(fd).st_mode)
    except (OSError, ValueError):  # no descriptor (a captured stream) or a closed one: nothing to keep in order
        return
    if regular:
        fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_APPEND)


def pause_line(rec: RunReport) -> Any:
    """A paused run's one line for whoever reran it by hand: the exact time the lane is back (tl-bxk.10.6)."""
    if rec.outcome is not Result.PAUSED:
        return ""
    due = rec.retry_after or 0.0
    if not due:
        return f"PAUSED {rec.bead}: no time the lane frees (login, network or setup); rerun when fixed: tl run-task {rec.bead}"
    return "PAUSED {}: the lane is back at {}; rerun then: tl run-task {}".format(
        rec.bead, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(due)), rec.bead)


def report(a: Any, rec: RunReport) -> Any:
    """The outcome as the run's last stdout line, and in --outcome-file when the loop names one."""
    line = json.dumps(wire.dump(rec), ensure_ascii=False)
    if getattr(a, "outcome_file", None):
        atomic_write_text(Path(a.outcome_file), line + "\n", fsync=False)
    say(line)


def main(a: Any, store: Any = None, *, env: Env, spawner: Spawner) -> Any:
    try:
        rc = run_main(a, store, env=env, spawner=spawner)
    except Blocked as b:  # a stop (SIGTERM) before the engine ran: the slot and the lock are already given back
        rc = RunReport(outcome=Result.FAILED, bead=a.id, why=b.why, kind=b.kind.value)
    if isinstance(rc, RunReport):  # stopped before the engine ran: nothing in the bead changed
        report(a, rc)
        return 1
    return rc


def run_main(a: Any, store: Any = None, *, env: Env, spawner: Spawner) -> Any:
    with halting.halt_on_sigterm():
        return run_main_stoppable(a, store, env=env, spawner=spawner)


def run_main_stoppable(a: Any, store: Any = None, *, env: Env, spawner: Spawner) -> Any:
    for f in (sys.stdout, sys.stderr):
        append_output(f)
    if not env.get(EnvVar.TASK_LOOP_SESSION) and not ident.session_id():
        penv.export(EnvVar.TASK_LOOP_SESSION, "engine-" + uuid.uuid4().hex[:12])
    repo = gitrepo.repo_root()
    cfg = wslots.load_cfg(repo)
    if a.slot == "any":
        return run_any_slot(a, repo, cfg, store, env=env, spawner=spawner)
    return run_in(a, repo, cfg, store, env=env, spawner=spawner)


def run_any_slot(a: Any, repo: Any, cfg: Any, store: Any = None, *, env: Env, spawner: Spawner) -> Any:
    """--slot any: the next free slot, taken in the repo's slot line (first come, first served; --wait: wait in it),
    run there as `--slot NAME`, given back at the end."""
    if a.dry_run:
        return RunReport(outcome=Result.FAILED, bead=a.id, why="failed: --slot any takes a slot; name one for --dry-run")
    wait = bool(getattr(a, "wait", False))
    told: list[int] = []

    def waiting(ahead: int) -> None:
        if not told:
            say("no free slot{}; waiting in line".format(f" ({ahead} ahead)" if ahead else ""))
            told.append(1)
    halt = halting.RUN_HALT["ev"] or threading.Event()
    got = wslots.wait_slot(repo, wslots.profile_slots(repo), "run-task " + a.id, stop=lambda: not wait or halt.is_set(), sleep=halt.wait,
                           on_wait=waiting, prio=wslots.bead_priority(repo, a.id, store), store=store, spawner=spawner)
    if not got and halt.is_set():
        raise Blocked("failed: stopped (SIGTERM)", kind=Kind.PAUSE_KILLED)  # run_bead's caller reports it; no slot was taken
    if not got:
        why = "no free slot (tl slot list); --wait waits in line for one"
        print(f"TAKEN: {why}")
        return RunReport(outcome=Result.TAKEN, bead=a.id, why=why)
    a.slot, a.worktree, sb = got
    a.slot_gen = fence.gen_of(beadtools.peek(store or beadtools.bd_store(repo), sb), SLOT_GEN)  # the lease this run took
    halting.RUN_SLOT["owned"] = a.slot  # a re-exec hands the slot on (TL_REEXEC) and its next run-task gives it back
    try:  # run_in sees the slot as taken (its Env names the slot's bead); the engine heartbeats it
        return run_in(a, repo, cfg, store, env=env.with_(EnvVar.TASK_LOOP_SLOT_BEAD, sb), spawner=spawner)
    finally:
        with _sigterm_ignored():
            wslots.release_slot(repo, a.slot, bead=a.id, mine=True, store=store, gen=a.slot_gen, spawner=spawner)


def take_area(a: Any, repo: Any, cfg: Any, lock: Any, sb: Any = "", store: Any = None) -> Any:
    """The engine lock, with the area check before it under the area lock (running.area_lock): "" when this run holds the
    worktree, else why not. A bead whose area runs elsewhere: a warning, or refused with --exclusive-area."""
    def mark() -> None:  # the slot says which bead runs in it (held_bead makes its area busy): only once the area is decided
        if sb:
            beadtools.attempt((store or beadtools.bd_store(repo)).update, sb, BeadPatch(set_metadata={"held_bead": a.id}))
    if not has_areas(cfg):
        why = lock.take()
        if not why:
            mark()
        return why
    with running.area_lock(repo):
        bead = beadtools.peek(store or beadtools.bd_store(repo), a.id) or Bead(id=a.id, title="", status="")
        _area, busy = running.area_busy(repo, cfg, bead)
        if busy and getattr(a, "exclusive_area", False):
            return busy + " (--exclusive-area)"
        if busy:
            say(f"⚠ {busy}: running anyway beside it; --exclusive-area refuses instead")
        why = lock.take()
        if not why:
            mark()
        return why


def _handed_slot(slot: Any, env: Env) -> Any:
    """True when TL_REEXEC (set by the run-task that exec'd into this one, not yet read by the Engine) says it took `slot` itself."""
    handed = Reexec.parse(env.get(EnvVar.TL_REEXEC))
    return handed is not None and handed.owned == slot


def _worktree_of(a: Any, repo: Any, spawner: Spawner, env: Env) -> tuple[str, Any]:
    """(worktree, failure): the directory the run works in (the slot's, the named one, or a new one), or the outcome that says why none."""
    wt = a.worktree
    if not wt and a.slot:  # the slot is the worktree
        wt = wslots.slot_dir(repo, a.slot, wslots.profile_slots(repo))
    if not wt:
        r = spawner.run([*childenv.script_argv(TL_PY, env), "worktree", "start"])
        wt = r.out.strip().splitlines()[-1] if r.exit == 0 and r.out.strip() else ""
        if not wt:
            print("tl: no worktree: " + r.err, file=sys.stderr)
            return "", RunReport(outcome=Result.FAILED, bead=a.id, why="failed: no worktree: " + r.err[-300:])
    wt = str(Path(wt).resolve())
    if (Path(wt) / ".git").is_dir():  # the main checkout holds the bead database and the config: never a worker's cwd
        print(f"tl: {wt} is the main checkout; run a task in a slot or a worktree (tl slot / tl worktree start)",
              file=sys.stderr)
        return "", RunReport(outcome=Result.FAILED, bead=a.id, why=f"failed: {wt} is the main checkout")
    return wt, None


def _slot_taken(a: Any, repo: Any, wt: str, slot: str, sb: BeadId | None, store: Any, env: Env,
                spawner: Spawner) -> tuple[BeadId | None, Any]:
    """(slot bead taken here, taken outcome): a hand run takes its slot's bead as the loop does; one the loop started has it already."""
    named = sb is not None and env.bead(EnvVar.TASK_LOOP_SLOT_BEAD) == sb
    if slot and sb and named and _handed_slot(slot, env):
        halting.RUN_SLOT["owned"] = slot
        return sb, None  # exec'd by the run-task that took this slot: it is still ours, and this process gives it back
    if slot and not (sb and named):
        took, why = wslots.take_named_slot(repo, slot, wslots.profile_slots(repo), "run-task " + a.id, store=store, spawner=spawner)
        if not took:
            print(f"TAKEN: {why}")
            return None, RunReport(outcome=Result.TAKEN, bead=a.id, why=why)
        halting.RUN_SLOT["owned"] = slot
        return took, None
    return None, None


@contextlib.contextmanager
def _sigterm_ignored() -> Generator[None]:
    """A give-back in a finally block is not cut short by a SIGTERM (only the main thread can set the handler)."""
    old = signal.signal(signal.SIGTERM, signal.SIG_IGN) if hasattr(signal, "SIGTERM") and \
        threading.current_thread() is threading.main_thread() else None
    try:
        yield
    finally:
        if old is not None:
            signal.signal(signal.SIGTERM, old)


def run_in(a: Any, repo: Any, cfg: Any, store: Any = None, *, env: Env, spawner: Spawner) -> Any:
    wt, failed = _worktree_of(a, repo, spawner, env)
    if failed:
        return failed
    if a.dry_run:
        return run_bead(a, repo, cfg, wt, store, env=env, spawner=spawner)
    took, slot = "", ""
    try:
        # a hand run takes its slot's bead as the loop does (a --worktree that is a slot too); one the loop started has
        # it already: TASK_LOOP_SLOT_BEAD names that very slot's bead
        slot = a.slot or wslots.slot_of(repo, wt, store)
        sb_row = wslots.slot_bead(repo, slot, store) if slot else None
        sb = sb_row.id if sb_row else None
        took, taken = _slot_taken(a, repo, wt, slot, sb, store, env, spawner)
        if taken:
            return taken
        if took:
            a.slot_gen = fence.gen_of(beadtools.peek(store or beadtools.bd_store(repo), took), SLOT_GEN)
        env = env.with_(EnvVar.TASK_LOOP_SLOT_BEAD, took) if took else env  # the engine's heartbeat keeps it
        lock = engine_lock.EngineLock(wt, a.id, slot, env)
        busy = take_area(a, repo, cfg, lock, took or sb if slot else "", store)
        if busy:
            why = busy if busy.startswith("area ") else f"worktree {wt}: {busy}"
            print(f"TAKEN: {why}")
            return RunReport(outcome=Result.TAKEN, bead=a.id, why=why)
        engine_lock.LOCK = lock
        return run_bead(a, repo, cfg, wt, store, env=env, spawner=spawner)
    finally:
        with _sigterm_ignored():
            if engine_lock.LOCK:
                engine_lock.LOCK.release()
                engine_lock.LOCK = None
            if took:
                wslots.release_slot(repo, slot, bead=a.id, mine=True, store=store, gen=getattr(a, "slot_gen", None), spawner=spawner)


defer_stop = halting.stop_deferred  # no state: also before an Engine exists


def run_bead(a: Any, repo: Any, cfg: Any, wt: Any, store: Any = None, *, env: Env, spawner: Spawner) -> Any:
    # a stop during the sweep, admit and claim waits for them, then the engine closes the run as stopped (trace, bead)
    with defer_stop(None) as stop:
        if not a.dry_run:
            release_dead(repo, store)
            ok, why = admit(a.id, repo, store)
            if not ok:
                print(f"TAKEN: {why}")
                return RunReport(outcome=Result.TAKEN, bead=a.id, why=why)
            if why:
                say(f"{a.id}: {why}")
        if not a.dry_run and verbs.claim(a.id, wt, a.slot, store=store) != 0:
            # bd lets this session re-claim its own bead (a reopened one); another session's claim stops here
            return RunReport(outcome=Result.TAKEN, bead=a.id, why="claimed by another session")
        claim = None if a.dry_run else fence.take(store or beadtools.bd_store(), a.id, ident.actor(),
                                                  env.bead(EnvVar.TASK_LOOP_SLOT_BEAD), getattr(a, "slot_gen", None))
        eng = Engine(a.id, wt, cfg, dry_run=a.dry_run, verbose=not getattr(a, "quiet", False),
                     fresh=bool(getattr(a, "fresh", False)), store=store, claim=claim, env=env, spawner=spawner)
        eng.stop_pending = bool(stop)
        say(f"engine log: {eng.log_path}")
    rc = eng.run()
    with defer_stop(None):  # the outcome line is what the loop reads: a stop waits for it
        rec = eng.result()
        if pause_line(rec):
            say(pause_line(rec))
        report(a, rec)
    return rc
