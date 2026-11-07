"""The slot code's world, built from this machine: the repo's profile, its bd, git and ticket line, the worktrees of the repo and the
loop's own worktree when slots are off. The composition root for `tl slot ...`, the loop and the engine."""
import contextlib
import functools
import os
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from tlkernel.bd_errors import BdCommandFailure
from tlkernel.bead import Bead
from tlkernel.beadsport import BdFailure, BeadQuery, Beads
from tlkernel.config import SlotsConfig
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.ids import loop_key as repo_key
from tlkernel.paths import TASK_EXCLUDE
from tlkernel.procport import Spawner
from tlkernel.slots import NotARepo, SlotFail, SlotGitError, SlotTable
from tlkernel.slottable import LiveSlot, build_slot_table
from tlslots import line as slots_line
from tlslots import owned
from tlslots.config import exclude_local, prio_of, profile_slots, slot_dir, slot_excludes, slot_source
from tlslots.engine_lock import drop_engine_lock, engine_busy, lock_pid
from tlslots.env import DEFAULT_PRIO, SlotEnv, stamp
from tlslots.pool import SlotPool, machine_slots

from taskloop.adapters.beadtools import bd_store, peek
from taskloop.adapters.gitrepo import repo_root
from taskloop.adapters.ident import hostname
from taskloop.adapters.landlock import os_lock
from taskloop.app.track import trail
from taskloop.app.track.trail import event
from taskloop.app.wire import slotfx
from taskloop.stores.real import real_stores


def slot_table(repo: str, who: Identity, git: Git, now: float, live: Mapping[str, LiveSlot] | None = None,
               store: Beads | None = None) -> SlotTable:
    """The one slot table of this repo on this machine (contracts/slottable): the config from the base ref, the slot beads of this host,
    `live` the runs the caller saw alive (slot name -> run)."""
    src = slot_source(repo, git, fx=slotfx.FX)
    beads = slot_beads(repo, who, store)
    store = store or bd_store(who.actor, repo)
    open_ids: list[str] = []
    with contextlib.suppress(BdFailure):  # no bd answer: no claim is shown as starting work
        open_ids = [b.id for b in store.find(BeadQuery()) if b.status in ("open", "in_progress")]
    return build_slot_table(beads, src.count, live or {}, src.dirs, now, src.source, src.sha, open_ids)


def slot_env(repo: str, store: Beads | None = None, cfg: SlotsConfig | None = None, now: Callable[[], float] | None = None,
             *, spawner: Spawner, git: Git, who: Identity) -> SlotEnv:
    """The slot code's world (app/slots): this repo's bd, git, ticket line and take lock, and the effects it may cause."""
    return SlotEnv(
        repo=repo,
        repo_key=repo_key(repo),
        cfg=cfg or profile_slots(repo),
        store=store or bd_store(who.actor, repo),
        git=git,
        tickets=real_stores(who.config).tickets,
        cfgdir=who.config,
        actor=who.actor,
        host=hostname(),
        take_lock=lambda: os_lock(who.config.lock_file(f"slot-take-{repo_key(repo)}.lock"), f"pid {os.getpid()}"),
        busy=functools.partial(engine_busy, who.config, fx=slotfx.FX), lock_pid=functools.partial(lock_pid, who.config),
        drop_engine_lock=lambda wt, pid: drop_engine_lock(who.config, wt, pid) if pid is not None else None, event=functools.partial(event,
            who), say=print,
        warn=lambda m: print(m, file=sys.stderr), pid=os.getpid(),
        run_setup=lambda argv, d: spawner.run(argv, cwd=d, capture=False).exit,
        exclude_local=lambda r: exclude_local(git, r, *slot_excludes(r, cfg or profile_slots(r))), now=now or trail.now)


def slot_beads(repo: str, who: Identity, store: Beads | None = None) -> list[Bead]:
    """This machine's slot beads of `repo`."""
    return machine_slots(store or bd_store(who.actor, repo), hostname())


def slot_bead(repo: str, name: str, who: Identity, store: Beads | None = None) -> Bead | None:
    return next((b for b in slot_beads(repo, who, store) if b.title.split()[-1] == name), None)


def slot_of(repo: str, wt: str, who: Identity, store: Beads | None = None, *, strict: bool = False) -> str:
    """The slot whose worktree `wt` is, or ""."""
    here, cfg = Path(wt).resolve(), profile_slots(repo)
    record = owned.docs(who.config, repo_key(repo)).of(owned.key_of(wt)).get()
    if record is not None and record.kind == "slot":
        return here.name
    # Cleanup must fail closed when bd is unavailable, rather than remove a slot whose lease it could not read.
    beads = ([b for b in (store or bd_store(who.actor, repo)).find(BeadQuery(label="slot", include_closed=True))
              if b.status != "closed" and b.title.split()[1:2] == [hostname()]] if strict else slot_beads(repo, who, store))
    return next((n for n in (b.title.split()[-1] for b in beads) if Path(slot_dir(repo, n,
        cfg)).resolve() == here), "")


def waiting_line(repo: str, who: Identity) -> list[Any]:
    """The live tickets (Ticket), first in line first; a dead waiter's ticket is removed."""
    return list(real_stores(who.config).tickets.line(repo_key(repo)))


def wait_slot(repo: str, cfg: SlotsConfig, why: str, bead: str = "", stop: Callable[[], bool] | None = None,
              sleep: Callable[[float], object] = time.sleep, poll: tuple[float, float] | None = None,
              on_wait: Callable[[int], None] | None = None, prio: int = DEFAULT_PRIO,
              store: Beads | None = None, *, spawner: Spawner, git: Git, who: Identity) -> tuple[str, str, BeadId] | None:
    """(name, dir, slot bead) once this waiter is first in line and a slot is free; None when stop() says so (see app/slots/line.py)."""
    return slots_line.wait_slot(slot_env(repo, store, cfg, spawner=spawner, git=git, who=who), why, bead, stop, sleep, poll, on_wait, prio)


def uninitialised(repo: str, cfg: SlotsConfig, store: Beads | None = None, *, spawner: Spawner, git: Git, who: Identity) -> str:
    """Why no slot can ever come free (the profile counts slots, this machine has no slot bead), or "": a waiter would queue for good."""
    if cfg.count < 1 or SlotPool(slot_env(repo, store, cfg, spawner=spawner, git=git, who=who)).slots():
        return ""
    return f"no slots on {hostname()}: run `tl slot init` ({cfg.count} in the profile)"


def take_named_slot(repo: str, name: str, cfg: SlotsConfig, why: str, bead: str = "",
                    store: Beads | None = None, *, spawner: Spawner, git: Git, who: Identity) -> tuple[BeadId | None, str]:
    """(slot bead, "") when this session now holds slot `name`, or (None, why not)."""
    try:
        return SlotPool(slot_env(repo, store, cfg, spawner=spawner, git=git, who=who)).slot(name).take(why, bead), ""
    except SlotFail as e:
        return None, e.why


def release_slot(repo: str, name: str, bead: str | None = None, mine: bool = False, force: bool = False,
                 store: Beads | None = None, gen: int | None = None, *, spawner: Spawner, git: Git, who: Identity) -> bool:
    """Frees slot `name` (see Slot.release); False when there is no such slot."""
    try:
        return SlotPool(slot_env(repo, store, spawner=spawner, git=git, who=who)).slot(name).release(bead, mine=mine, force=force, gen=gen)
    except SlotFail:
        return False


def bead_priority(repo: str, bead_id: BeadId, who: Identity, store: Beads | None = None) -> int:
    """The priority (0 = P0) of a bead, DEFAULT_PRIO when it cannot be read."""
    try:
        return prio_of(peek(store or bd_store(who.actor, repo), bead_id))
    except BdCommandFailure:  # no bd: it waits as a P2
        return DEFAULT_PRIO


def worktrees(repo: str, git: Git, who: Identity, slots: list[Bead] | None = None) -> list[str]:
    """Every worktree of the repo (git worktree list) and every slot folder (`slots`: the slot beads, when the caller has them): where an
    engine lock may be."""
    try:
        found = [c.path for c in git.checkouts(repo)]
    except NotARepo:
        found: list[str] = []  # slot folders may exist before the repository does
    beads = slot_beads(repo, who) if slots is None else slots
    if beads:  # no slot beads, no profile read: a repo whose profile is bad still lists its worktrees
        cfg = profile_slots(repo, git)
        found += [slot_dir(repo, b.title.split()[-1], cfg) for b in beads]
    seen: set[str] = set()
    keep: list[str] = []
    for d in found:
        k = os.path.realpath(d)
        if k not in seen and os.path.realpath(repo) != k:
            seen.add(k)
            keep.append(d)
    return keep


def start_worktree(repo: str, git: Git, who: Identity, name: str | None = None) -> str:
    """This session's loop worktree (`name`: the loop's pick, default this actor's), made once and reused."""
    d = owned.loop_path(repo, name or who.actor[3:])
    try:
        owned.create(git, who.config, repo_key(repo), repo, d, "origin/main", kind="loop", run=who.session or who.actor, bead="",
                     host=hostname(), now=trail.now(), exclude=lambda: exclude_local(git, repo, ".worktrees/", TASK_EXCLUDE))
    except SlotGitError as e:
        sys.exit(e.tail)
    event(who, "worktree_start", "", worktree=d, repo=repo)
    return d


def live_actors(repo: str, who: Identity, store: Beads | None = None) -> set[str]:
    """Actors holding a live lease on any bead: a session that heartbeats is alive."""
    try:
        beads = (store or bd_store(who.actor, repo)).find(BeadQuery(status="in_progress"))
    except BdFailure:
        return set()
    t = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    return {b.assignee for b in beads if b.lease_expires_at >= t}


def worktree(git: Git, who: Identity, op: str, self_too: bool = False) -> int:
    """`tl worktree start|sunset`: one worktree per loop session when slots are off. Sunset removes the loop worktrees whose session is
    gone, never a dirty one."""
    repo = repo_root()
    if op == "start":
        print(start_worktree(repo, git, who))
        return 0
    if op != "sunset":
        return 2
    live, docs = live_actors(repo, who), owned.docs(who.config, repo_key(repo))
    for d in sorted((Path(repo) / ".worktrees").glob("loop-*")):
        owner = "tl-" + d.name[5:]
        if owner == who.actor and not self_too:
            continue
        if owner != who.actor and any(w == owner or w.startswith(owner + "-") for w in live if w):
            continue  # a loop of that session claims as <owner>-<suffix>
        if lost := owned.losses(git, str(d), profile_slots(repo, git).base):
            print("KEEP " + str(d) + ": removing it would lose\n" + "\n".join("  " + x for x in lost[: owned.SHOWN]))
            continue
        git.remove_worktree(repo, str(d))
        docs.of(owned.key_of(str(d))).delete()
        event(who, "worktree_sunset", "", worktree=str(d), repo=repo)
        print("REMOVED " + str(d))
    git.prune_worktrees(repo)
    return 0


def owned_worktrees(git: Git, who: Identity, op: str) -> int:
    """`tl worktrees [clean]`: list every worktree of this repo (owned, foreign, orphaned), or remove the owned ones that are merged
    and clean."""
    repo = repo_root()
    cfg = profile_slots(repo, git)
    slots_dir = str(Path(slot_dir(repo, "x", cfg)).parent)
    if op == "clean":
        busy = functools.partial(engine_busy, who.config, fx=slotfx.FX)
        return owned.clean(git, who.config, repo_key(repo), repo, slots_dir, cfg.base, cfg.count, busy)
    for r in owned.survey(git, who.config, repo_key(repo), repo, slots_dir):
        print("\t".join([r.state, r.path, r.branch or "-", r.note + (f" since {stamp(r.rec.created)}" if r.rec else "")]))
    return 0
