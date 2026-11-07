"""The machine-bound half of the slot code: the slot table, the slot environment, the slot beads of this machine, take and release, and
the worktrees of the repo. Everything a machine supplies (bd, git root, host name, os lock, events, tickets, clock, effects) comes in as
one `SlotsHost`; the composition root binds it."""
import contextlib
import functools
import os
import sys
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tlkernel import fence
from tlkernel.bd_errors import BdCommandFailure
from tlkernel.bead import Bead
from tlkernel.beadsport import BdFailure, BeadQuery, Beads
from tlkernel.config import SlotsConfig
from tlkernel.env import Env
from tlkernel.envvars import EnvVar
from tlkernel.fence import SLOT_GEN
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.ids import loop_key as repo_key
from tlkernel.paths import TASK_EXCLUDE
from tlkernel.procport import Spawner
from tlkernel.run import Reexec
from tlkernel.slots import NotARepo, SlotFail, SlotGitError, SlotTable
from tlkernel.slottable import LiveSlot, build_slot_table

from tlslots import line as slots_line
from tlslots import owned
from tlslots.config import exclude_local, prio_of, profile_slots, slot_dir, slot_excludes, slot_source
from tlslots.engine_lock import drop_engine_lock, engine_busy, lock_pid
from tlslots.env import DEFAULT_PRIO, SlotEnv, stamp
from tlslots.host import SlotsHost
from tlslots.pool import SlotPool, machine_slots


def slot_table(h: SlotsHost, repo: str, who: Identity, git: Git, now: float, live: Mapping[str, LiveSlot] | None = None,
               store: Beads | None = None) -> SlotTable:
    """The one slot table of this repo on this machine (contracts/slottable): the config from the base ref, the slot beads of this host,
    `live` the runs the caller saw alive (slot name -> run)."""
    src = slot_source(repo, git, fx=h.fx)
    beads = slot_beads(h, repo, who, store)
    store = store or h.bd(who.actor, repo)
    open_ids: list[str] = []
    with contextlib.suppress(BdFailure):  # no bd answer: no claim is shown as starting work
        open_ids = [b.id for b in store.find(BeadQuery()) if b.status in ("open", "in_progress")]
    return build_slot_table(beads, src.count, live or {}, src.dirs, now, src.source, src.sha, open_ids)


def slot_env(h: SlotsHost, repo: str, store: Beads | None = None, cfg: SlotsConfig | None = None, now: Callable[[], float] | None = None,
             *, spawner: Spawner, git: Git, who: Identity) -> SlotEnv:
    """The slot code's world (app/slots): this repo's bd, git, ticket line and take lock, and the effects it may cause."""
    return SlotEnv(
        repo=repo,
        repo_key=repo_key(repo),
        cfg=cfg or profile_slots(repo),
        store=store or h.bd(who.actor, repo),
        git=git,
        tickets=h.tickets(who.config),
        cfgdir=who.config,
        actor=who.actor,
        host=h.hostname(),
        take_lock=lambda: h.os_lock(who.config.lock_file(f"slot-take-{repo_key(repo)}.lock"), f"pid {os.getpid()}"),
        busy=functools.partial(engine_busy, who.config, fx=h.fx), lock_pid=functools.partial(lock_pid, who.config),
        drop_engine_lock=lambda wt, pid: drop_engine_lock(who.config, wt, pid) if pid is not None else None,
        event=functools.partial(h.event, who), say=print,
        warn=lambda m: print(m, file=sys.stderr), pid=os.getpid(),
        run_setup=lambda argv, d: spawner.run(argv, cwd=d, capture=False).exit,
        exclude_local=lambda r: exclude_local(git, r, *slot_excludes(r, cfg or profile_slots(r))), now=now or h.now)


def slot_beads(h: SlotsHost, repo: str, who: Identity, store: Beads | None = None) -> list[Bead]:
    """This machine's slot beads of `repo`."""
    return machine_slots(store or h.bd(who.actor, repo), h.hostname())


def slot_bead(h: SlotsHost, repo: str, name: str, who: Identity, store: Beads | None = None) -> Bead | None:
    return next((b for b in slot_beads(h, repo, who, store) if b.title.split()[-1] == name), None)


def slot_of(h: SlotsHost, repo: str, wt: str, who: Identity, store: Beads | None = None, *, strict: bool = False) -> str:
    """The slot whose worktree `wt` is, or ""."""
    here, cfg = Path(wt).resolve(), profile_slots(repo)
    record = owned.docs(who.config, repo_key(repo)).of(owned.key_of(wt)).get()
    if record is not None and record.kind == "slot":
        return here.name
    # Cleanup must fail closed when bd is unavailable, rather than remove a slot whose lease it could not read.
    beads = ([b for b in (store or h.bd(who.actor, repo)).find(BeadQuery(label="slot", include_closed=True))
              if b.status != "closed" and b.title.split()[1:2] == [h.hostname()]] if strict else slot_beads(h, repo, who, store))
    return next((n for n in (b.title.split()[-1] for b in beads) if Path(slot_dir(repo, n,
        cfg)).resolve() == here), "")


def waiting_line(h: SlotsHost, repo: str, who: Identity) -> list[Any]:
    """The live tickets (Ticket), first in line first; a dead waiter's ticket is removed."""
    return list(h.tickets(who.config).line(repo_key(repo)))


def wait_slot(h: SlotsHost, repo: str, cfg: SlotsConfig, why: str, bead: str = "", stop: Callable[[], bool] | None = None,
              sleep: Callable[[float], object] = time.sleep, poll: tuple[float, float] | None = None,
              on_wait: Callable[[int], None] | None = None, prio: int = DEFAULT_PRIO,
              store: Beads | None = None, *, spawner: Spawner, git: Git, who: Identity) -> tuple[str, str, BeadId] | None:
    """(name, dir, slot bead) once this waiter is first in line and a slot is free; None when stop() says so (see app/slots/line.py)."""
    env = slot_env(h, repo, store, cfg, spawner=spawner, git=git, who=who)
    return slots_line.wait_slot(env, why, bead, stop, sleep, poll, on_wait, prio)


def uninitialised(h: SlotsHost, repo: str, cfg: SlotsConfig, store: Beads | None = None, *,
                  spawner: Spawner, git: Git, who: Identity) -> str:
    """Why no slot can ever come free (the profile counts slots, this machine has no slot bead), or "": a waiter would queue for good."""
    if cfg.count < 1 or SlotPool(slot_env(h, repo, store, cfg, spawner=spawner, git=git, who=who)).slots():
        return ""
    return f"no slots on {h.hostname()}: run `tl slot init` ({cfg.count} in the profile)"


def take_named_slot(h: SlotsHost, repo: str, name: str, cfg: SlotsConfig, why: str, bead: str = "",
                    store: Beads | None = None, *, spawner: Spawner, git: Git, who: Identity) -> tuple[BeadId | None, str]:
    """(slot bead, "") when this session now holds slot `name`, or (None, why not)."""
    try:
        return SlotPool(slot_env(h, repo, store, cfg, spawner=spawner, git=git, who=who)).slot(name).take(why, bead), ""
    except SlotFail as e:
        return None, e.why


def release_slot(h: SlotsHost, repo: str, name: str, bead: str | None = None, mine: bool = False, force: bool = False,
                 store: Beads | None = None, gen: int | None = None, *, spawner: Spawner, git: Git, who: Identity) -> bool:
    """Frees slot `name` (see Slot.release); False when there is no such slot."""
    try:
        pool = SlotPool(slot_env(h, repo, store, spawner=spawner, git=git, who=who))
        return pool.slot(name).release(bead, mine=mine, force=force, gen=gen)
    except SlotFail:
        return False


def bead_priority(h: SlotsHost, repo: str, bead_id: BeadId, who: Identity, store: Beads | None = None) -> int:
    """The priority (0 = P0) of a bead, DEFAULT_PRIO when it cannot be read."""
    try:
        return prio_of(h.peek(store or h.bd(who.actor, repo), bead_id))
    except BdCommandFailure:  # no bd: it waits as a P2
        return DEFAULT_PRIO


def worktrees(h: SlotsHost, repo: str, git: Git, who: Identity, slots: list[Bead] | None = None) -> list[str]:
    """Every worktree of the repo (git worktree list) and every slot folder (`slots`: the slot beads, when the caller has them): where an
    engine lock may be."""
    try:
        found = [c.path for c in git.checkouts(repo)]
    except NotARepo:
        found: list[str] = []  # slot folders may exist before the repository does
    beads = slot_beads(h, repo, who) if slots is None else slots
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


def start_worktree(h: SlotsHost, repo: str, git: Git, who: Identity, name: str | None = None) -> str:
    """This session's loop worktree (`name`: the loop's pick, default this actor's), made once and reused."""
    d = owned.loop_path(repo, name or who.actor[3:])
    try:
        owned.create(git, who.config, repo_key(repo), repo, d, "origin/main", kind="loop", run=who.session or who.actor, bead="",
                     host=h.hostname(), now=h.now(), exclude=lambda: exclude_local(git, repo, ".worktrees/", TASK_EXCLUDE))
    except SlotGitError as e:
        sys.exit(e.tail)
    h.event(who, "worktree_start", "", worktree=d, repo=repo)
    return d


def live_actors(h: SlotsHost, repo: str, who: Identity, store: Beads | None = None) -> set[str]:
    """Actors holding a live lease on any bead: a session that heartbeats is alive."""
    try:
        beads = (store or h.bd(who.actor, repo)).find(BeadQuery(status="in_progress"))
    except BdFailure:
        return set()
    t = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    return {b.assignee for b in beads if b.lease_expires_at >= t}


def worktree(h: SlotsHost, git: Git, who: Identity, op: str, self_too: bool = False) -> int:
    """`tl worktree start|sunset`: one worktree per loop session when slots are off. Sunset removes the loop worktrees whose session is
    gone, never a dirty one."""
    repo = h.repo_root()
    if op == "start":
        print(start_worktree(h, repo, git, who))
        return 0
    if op != "sunset":
        return 2
    live, docs = live_actors(h, repo, who), owned.docs(who.config, repo_key(repo))
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
        h.event(who, "worktree_sunset", "", worktree=str(d), repo=repo)
        print("REMOVED " + str(d))
    git.prune_worktrees(repo)
    return 0


def owned_worktrees(h: SlotsHost, git: Git, who: Identity, op: str) -> int:
    """`tl worktrees [clean]`: list every worktree of this repo (owned, foreign, orphaned), or remove the owned ones that are merged
    and clean."""
    repo = h.repo_root()
    cfg = profile_slots(repo, git)
    slots_dir = str(Path(slot_dir(repo, "x", cfg)).parent)
    if op == "clean":
        busy = functools.partial(engine_busy, who.config, fx=h.fx)
        return owned.clean(git, who.config, repo_key(repo), repo, slots_dir, cfg.base, cfg.count, busy)
    for r in owned.survey(git, who.config, repo_key(repo), repo, slots_dir):
        print("\t".join([r.state, r.path, r.branch or "-", r.note + (f" since {stamp(r.rec.created)}" if r.rec else "")]))
    return 0


@dataclass(frozen=True)
class Taken:
    bead: BeadId | None = None
    refused: str = ""


@dataclass(frozen=True)
class Claim:
    slot: str
    worktree: str
    bead: BeadId
    gen: int | None


@dataclass(frozen=True)
class Refused:
    why: str


@dataclass(frozen=True)
class Stopped:
    pass


def handed_slot(slot: str, env: Env) -> bool:
    """Whether TL_REEXEC hands this run the slot its predecessor took."""
    handed = Reexec.parse(env.get(EnvVar.TL_REEXEC))
    return handed is not None and handed.owned == slot


def named(h: SlotsHost, repo: str, slot: str, sb: BeadId | None, named_in_env: bool, why: str,
          store: Beads | None, *, spawner: Spawner, git: Git, who: Identity, env: Env) -> Taken:
    if slot and sb and named_in_env and handed_slot(slot, env):
        return Taken(sb)
    if slot and not (sb and named_in_env):
        took, refused = take_named_slot(h, repo, slot, profile_slots(repo), why, store=store,
                               spawner=spawner, git=git, who=who)
        if not took:
            return Taken(refused=refused)
        return Taken(took)
    return Taken()


def any_slot(h: SlotsHost, repo: str, cfg_slots: SlotsConfig, bead_id: BeadId, wait: bool,
             halt: threading.Event, say: Callable[[str], None], store: Beads | None, *,
             spawner: Spawner, git: Git, who: Identity) -> Claim | Refused | Stopped:
    if why := uninitialised(h, repo, cfg_slots, store, spawner=spawner, git=git, who=who):
        return Refused(why)
    told: list[int] = []

    def waiting(ahead: int) -> None:
        if not told:
            say("no free slot{}; waiting in line".format(f" ({ahead} ahead)" if ahead else ""))
            told.append(1)

    got = wait_slot(h, repo, cfg_slots, "run-task " + bead_id, stop=lambda: not wait or halt.is_set(), sleep=halt.wait,
                    on_wait=waiting, prio=bead_priority(h, repo, bead_id, who, store), store=store,
                    spawner=spawner, git=git, who=who)
    if not got and halt.is_set():
        return Stopped()
    if not got:
        return Refused("no free slot (tl slot list); --wait waits in line for one")
    slot, worktree, sb = got
    gen = fence.gen_of(h.peek(store or h.bd(who.actor, repo), sb), SLOT_GEN)
    return Claim(slot, worktree, sb, gen)


def give_back(h: SlotsHost, repo: str, slot: str, bead_id: BeadId, gen: int | None, store: Beads | None, *,
              spawner: Spawner, git: Git, who: Identity, guard: Callable[[], AbstractContextManager[None]]) -> None:
    with guard():
        release_slot(h, repo, slot, bead=bead_id, mine=True, store=store, gen=gen, spawner=spawner, git=git, who=who)
