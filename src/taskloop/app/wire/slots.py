"""The slot code's world, built from this machine: the repo's profile, its bd, git and ticket line, the worktrees of the repo and the
loop's own worktree when slots are off. The composition root for `tl slot ...`, the loop and the engine."""
import contextlib
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from taskloop.adapters.beadtools import bd_store, peek
from taskloop.adapters.git import REAL, RealGit
from taskloop.adapters.gitrepo import repo_root
from taskloop.adapters.ident import actor, config_dir, hostname
from taskloop.adapters.landlock import os_lock
from taskloop.app.slots import line as slots_line
from taskloop.app.slots.engine_lock import drop_engine_lock, engine_busy, lock_pid
from taskloop.app.slots.env import DEFAULT_PRIO, SlotEnv
from taskloop.app.slots.pool import SlotPool
from taskloop.app.track import trail
from taskloop.app.track.trail import event
from taskloop.app.wire import real
from taskloop.contracts import config
from taskloop.contracts.bead import Bead
from taskloop.contracts.config import EngineConfig, RepoProfile, SlotsConfig
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ids import loop_key as repo_key
from taskloop.contracts.paths import TASK_EXCLUDE, ConfigDir
from taskloop.contracts.ports import BdFailure, BeadQuery, Beads, Git, Spawner
from taskloop.contracts.slots import SlotFail, SlotGitError
from taskloop.stores.files import FileTickets


def profile(repo: str, base: str | None = None, git: Git = REAL) -> dict[str, Any]:
    """The repo's loop profile (.task-loop.json, parsed). With `base` (a ref such as origin/main), the copy committed there, so a pushed
    rule counts after a fetch even when nobody pulled the checkout; the working tree only when `base` does not resolve here (no remote).
    A file missing on the base is {}: committed wins."""
    return profile_source(repo, base, git)[0]


def profile_source(repo: str, base: str | None = None, git: Git = REAL) -> tuple[dict[str, Any], str]:
    """The profile and its exact commit, or an empty commit for the working-tree fallback."""
    commit = git.rev_parse(repo, base + "^{commit}") if base else ""
    if commit:
        try:
            return json.loads(git.show(repo, commit, ".task-loop.json").strip() or "{}"), commit
        except (ValueError, SlotGitError):
            return {}, commit
    try:
        return json.loads((Path(repo) / ".task-loop.json").read_text(encoding="utf-8")), ""
    except (OSError, ValueError):
        return {}, ""


def load_profile(data: Any) -> RepoProfile:
    """A parsed .task-loop.json as a RepoProfile; an unknown key or a wrong type exits, naming it. A retired key is said once."""
    try:
        return config.load(data, say_to=sys.stderr)
    except config.ConfigError as e:
        sys.exit(f"task-loop: {e}")


def cfg_source(repo: str, git: Git = REAL) -> tuple[RepoProfile, str, str]:
    """(the RepoProfile, the base hint, the pinned commit: empty for a local fallback). A bad .task-loop.json exits loudly."""
    base = load_profile(profile(repo, None, git)).engine.base
    data, commit = profile_source(repo, base, git)
    return load_profile(data), base, commit


def load_cfg(repo: str) -> EngineConfig:
    """The `engine` block of the repo's .task-loop.json as committed on the base branch, defaults for what it leaves out. The base is
    itself a key: the working tree names it, then the base's copy is read. A caller fetches first."""
    return cfg_source(repo)[0].engine


def profile_slots(repo: str) -> SlotsConfig:
    """The `slots` block of the repo's loop profile (.task-loop.json in the working tree)."""
    try:
        return load_profile(json.loads((Path(repo) / ".task-loop.json").read_text(encoding="utf-8"))).slots
    except (OSError, ValueError):
        return SlotsConfig()


def slot_dir(repo: str, name: str, cfg: SlotsConfig) -> str:
    root = cfg.dir
    return str(Path(root if os.path.isabs(root) else os.path.join(repo, root)) / name)


def exclude_local(repo: str, *patterns: str) -> None:
    """Keep the loop's own folders out of `git add -A` in every repo, without touching its tracked .gitignore."""
    common = REAL.common_dir(repo)
    if not common:
        return
    f = Path(common) / "info" / "exclude"
    f.parent.mkdir(parents=True, exist_ok=True)
    have = f.read_text(encoding="utf-8") if f.exists() else ""
    add = [p for p in patterns if p not in have.split()]
    if add:
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(("\n" if have and not have.endswith("\n") else "") + "\n".join(add) + "\n")


def slot_env(repo: str, store: Beads | None = None, cfg: SlotsConfig | None = None, now: Callable[[], float] | None = None,
             spawner: Spawner | None = None) -> SlotEnv:
    """The slot code's world (app/slots): this repo's bd, git, ticket line and take lock, and the effects it may cause."""
    cdir = ConfigDir(config_dir())
    spawn = spawner or real.spawner()
    return SlotEnv(
        repo=repo, repo_key=repo_key(repo), cfg=cfg or profile_slots(repo), store=store or bd_store(repo), git=RealGit(),
        tickets=FileTickets(cdir), cfgdir=cdir, actor=actor(), host=hostname(),
        take_lock=lambda: os_lock(config_dir() / "locks" / f"slot-take-{repo_key(repo)}.lock", f"pid {os.getpid()}"),
        busy=engine_busy, lock_pid=lock_pid,
        drop_engine_lock=lambda wt, pid: drop_engine_lock(wt, pid) if pid is not None else None, event=event, say=print,
        warn=lambda m: print(m, file=sys.stderr), pid=os.getpid(),
        run_setup=lambda argv, d: spawn.run(argv, cwd=d, capture=False).exit,
        exclude_local=lambda r: exclude_local(r, ".slots/", TASK_EXCLUDE), now=now or trail.now)


def slot_beads(repo: str, store: Beads | None = None) -> list[Bead]:
    return SlotPool(slot_env(repo, store)).beads()


def slot_bead(repo: str, name: str, store: Beads | None = None) -> Bead | None:
    return SlotPool(slot_env(repo, store)).bead(name)


def slot_of(repo: str, wt: str, store: Beads | None = None) -> str:
    """The slot whose worktree `wt` is, or ""."""
    return SlotPool(slot_env(repo, store)).name_of(wt)


def waiting_line(repo: str) -> list[Any]:
    """The live tickets (Ticket), first in line first; a dead waiter's ticket is removed."""
    return list(FileTickets(ConfigDir(config_dir())).line(repo_key(repo)))


def wait_slot(repo: str, cfg: SlotsConfig, why: str, bead: str = "", stop: Callable[[], bool] | None = None,
              sleep: Callable[[float], object] = time.sleep, poll: tuple[float, float] | None = None,
              on_wait: Callable[[int], None] | None = None, prio: int = DEFAULT_PRIO,
              store: Beads | None = None) -> tuple[str, str, BeadId] | None:
    """(name, dir, slot bead) once this waiter is first in line and a slot is free; None when stop() says so (see app/slots/line.py)."""
    return slots_line.wait_slot(slot_env(repo, store, cfg), why, bead, stop, sleep, poll, on_wait, prio)


def take_named_slot(repo: str, name: str, cfg: SlotsConfig, why: str, bead: str = "",
                    store: Beads | None = None) -> tuple[BeadId | None, str]:
    """(slot bead, "") when this session now holds slot `name`, or (None, why not)."""
    try:
        return SlotPool(slot_env(repo, store, cfg)).slot(name).take(why, bead), ""
    except SlotFail as e:
        return None, e.why


def release_slot(repo: str, name: str, bead: str | None = None, mine: bool = False, force: bool = False,
                 store: Beads | None = None, gen: int | None = None) -> bool:
    """Frees slot `name` (see Slot.release); False when there is no such slot."""
    try:
        return SlotPool(slot_env(repo, store)).slot(name).release(bead, mine=mine, force=force, gen=gen)
    except SlotFail:
        return False


def prio_of(bead: Bead | None) -> int:
    """The priority number of a bead (0 = P0), DEFAULT_PRIO when it has none."""
    return bead.priority if bead and bead.priority is not None else DEFAULT_PRIO


def bead_priority(repo: str, bead_id: BeadId, store: Beads | None = None) -> int:
    """The priority (0 = P0) of a bead, DEFAULT_PRIO when it cannot be read."""
    try:
        return prio_of(peek(store or bd_store(repo), bead_id))
    except SystemExit:  # no bd: it waits as a P2
        return DEFAULT_PRIO


def worktrees(repo: str, slots: list[Bead] | None = None) -> list[str]:
    """Every worktree of the repo (git worktree list) and every slot folder (`slots`: the slot beads, when the caller has them): where an
    engine lock may be."""
    found = [c.path for c in REAL.checkouts(repo)]
    cfg = profile_slots(repo)
    found += [slot_dir(repo, b.title.split()[-1], cfg) for b in (slot_beads(repo) if slots is None else slots)]
    seen: set[str] = set()
    keep: list[str] = []
    for d in found:
        k = os.path.realpath(d)
        if k not in seen and os.path.realpath(repo) != k:
            seen.add(k)
            keep.append(d)
    return keep


def start_worktree(repo: str, name: str | None = None) -> str:
    """This session's loop worktree (`name`: the loop's pick, default this actor's), made once and reused."""
    exclude_local(repo, ".worktrees/", TASK_EXCLUDE)
    d = Path(repo) / ".worktrees" / ("loop-" + (name or actor()[3:]))
    if not d.exists():
        with contextlib.suppress(SlotGitError):
            REAL.fetch(repo)
        try:
            REAL.add_worktree(repo, str(d), "origin/main")
        except SlotGitError as e:
            sys.exit(e.tail)
    event("worktree-start", "", worktree=str(d), repo=repo)
    return str(d)


def live_actors(repo: str, store: Beads | None = None) -> set[str]:
    """Actors holding a live lease on any bead: a session that heartbeats is alive."""
    try:
        beads = (store or bd_store(repo)).find(BeadQuery(status="in_progress"))
    except BdFailure:
        return set()
    t = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    return {b.assignee for b in beads if b.lease_expires_at >= t}


def worktree(op: str, self_too: bool = False) -> int:
    """`tl worktree start|sunset`: one worktree per loop session when slots are off. Sunset removes the loop worktrees whose session is
    gone, never a dirty one."""
    repo = repo_root()
    if op == "start":
        print(start_worktree(repo))
        return 0
    if op != "sunset":
        return 2
    live = live_actors(repo)
    for d in sorted((Path(repo) / ".worktrees").glob("loop-*")):
        owner = "tl-" + d.name[5:]
        if owner == actor() and not self_too:
            continue
        if owner != actor() and any(w == owner or w.startswith(owner + "-") for w in live if w):
            continue  # a loop of that session claims as <owner>-<suffix>
        if REAL.dirty(str(d)):
            print("KEEP dirty " + str(d))
            continue
        REAL.remove_worktree(repo, str(d))
        event("worktree-sunset", "", worktree=str(d), repo=repo)
        print("REMOVED " + str(d))
    REAL.prune_worktrees(repo)
    return 0
