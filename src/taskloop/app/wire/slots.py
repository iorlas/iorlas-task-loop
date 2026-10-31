"""The slot code's world, built from this machine: the repo's profile, its bd, git and ticket line, the worktrees of the repo and the
loop's own worktree when slots are off. The composition root for `tl slot ...`, the loop and the engine."""
import functools
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from taskloop.adapters.beadtools import bd_store, peek
from taskloop.adapters.gitrepo import repo_root
from taskloop.adapters.ident import hostname
from taskloop.adapters.landlock import os_lock
from taskloop.app.slots import line as slots_line
from taskloop.app.slots import owned
from taskloop.app.slots.engine_lock import drop_engine_lock, engine_busy, lock_pid
from taskloop.app.slots.env import DEFAULT_PRIO, SlotEnv, stamp
from taskloop.app.slots.pool import SlotPool, machine_slots
from taskloop.app.track import trail
from taskloop.app.track.trail import event
from taskloop.contracts import config
from taskloop.contracts.bead import Bead
from taskloop.contracts.config import EngineConfig, RepoProfile, SlotsConfig
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ids import loop_key as repo_key
from taskloop.contracts.paths import TASK_EXCLUDE
from taskloop.contracts.ports import BdFailure, BeadQuery, Beads, Git, Spawner
from taskloop.contracts.slots import SlotFail, SlotGitError
from taskloop.stores.files import FileTickets


def profile(repo: str, base: str | None, git: Git) -> dict[str, Any]:
    """The repo's loop profile (.task-loop.json, parsed). With `base` (a ref such as origin/main), the copy committed there, so a pushed
    rule counts after a fetch even when nobody pulled the checkout; the working tree only when `base` does not resolve here (no remote).
    A file missing on the base is {}: committed wins."""
    return profile_source(repo, base, git)[0]


def profile_source(repo: str, base: str | None, git: Git) -> tuple[dict[str, Any], str]:
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


def cfg_source(repo: str, git: Git) -> tuple[RepoProfile, str, str]:
    """(the RepoProfile, the base hint, the pinned commit: empty for a local fallback). A bad .task-loop.json exits loudly."""
    base = load_profile(profile(repo, None, git)).engine.base
    data, commit = profile_source(repo, base, git)
    return load_profile(data), base, commit


def load_cfg(repo: str, git: Git) -> EngineConfig:
    """The `engine` block of the repo's .task-loop.json as committed on the base branch, defaults for what it leaves out. The base is
    itself a key: the working tree names it, then the base's copy is read. A caller fetches first."""
    return cfg_source(repo, git)[0].engine


def profile_slots(repo: str) -> SlotsConfig:
    """The `slots` block of the repo's loop profile (.task-loop.json in the working tree)."""
    try:
        return load_profile(json.loads((Path(repo) / ".task-loop.json").read_text(encoding="utf-8"))).slots
    except (OSError, ValueError):
        return SlotsConfig()


def slot_dir(repo: str, name: str, cfg: SlotsConfig) -> str:
    root = cfg.dir
    return str(Path(root if os.path.isabs(root) else os.path.join(repo, root)) / name)


def slot_excludes(repo: str, cfg: SlotsConfig) -> tuple[str, ...]:
    """The exclude lines for the slot folder (a path under the repo; one outside it needs none) and the scratch folder."""
    d = Path(slot_dir(repo, "x", cfg)).parent
    return (str(d.relative_to(repo)) + "/", TASK_EXCLUDE) if d.is_relative_to(repo) else (TASK_EXCLUDE,)


def exclude_local(git: Git, repo: str, *patterns: str) -> None:
    """Keep the loop's own folders out of `git add -A` in every repo, without touching its tracked .gitignore."""
    common = git.common_dir(repo)
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
             *, spawner: Spawner, git: Git, who: Identity) -> SlotEnv:
    """The slot code's world (app/slots): this repo's bd, git, ticket line and take lock, and the effects it may cause."""
    return SlotEnv(
        repo=repo,
        repo_key=repo_key(repo),
        cfg=cfg or profile_slots(repo),
        store=store or bd_store(who.actor, repo),
        git=git,
        tickets=FileTickets(who.config),
        cfgdir=who.config,
        actor=who.actor,
        host=hostname(),
        take_lock=lambda: os_lock(who.config.root / "locks" / f"slot-take-{repo_key(repo)}.lock", f"pid {os.getpid()}"),
        busy=engine_busy, lock_pid=lock_pid,
        drop_engine_lock=lambda wt, pid: drop_engine_lock(wt, pid) if pid is not None else None, event=functools.partial(event,
            who), say=print,
        warn=lambda m: print(m, file=sys.stderr), pid=os.getpid(),
        run_setup=lambda argv, d: spawner.run(argv, cwd=d, capture=False).exit,
        exclude_local=lambda r: exclude_local(git, r, *slot_excludes(r, cfg or profile_slots(r))), now=now or trail.now)


def slot_beads(repo: str, who: Identity, store: Beads | None = None) -> list[Bead]:
    """This machine's slot beads of `repo`."""
    return machine_slots(store or bd_store(who.actor, repo), hostname())


def slot_bead(repo: str, name: str, who: Identity, store: Beads | None = None) -> Bead | None:
    return next((b for b in slot_beads(repo, who, store) if b.title.split()[-1] == name), None)


def slot_of(repo: str, wt: str, who: Identity, store: Beads | None = None) -> str:
    """The slot whose worktree `wt` is, or ""."""
    here, cfg = Path(wt).resolve(), profile_slots(repo)
    return next((n for n in (b.title.split()[-1] for b in slot_beads(repo, who, store)) if Path(slot_dir(repo, n,
        cfg)).resolve() == here), "")


def waiting_line(repo: str, who: Identity) -> list[Any]:
    """The live tickets (Ticket), first in line first; a dead waiter's ticket is removed."""
    return list(FileTickets(who.config).line(repo_key(repo)))


def wait_slot(repo: str, cfg: SlotsConfig, why: str, bead: str = "", stop: Callable[[], bool] | None = None,
              sleep: Callable[[float], object] = time.sleep, poll: tuple[float, float] | None = None,
              on_wait: Callable[[int], None] | None = None, prio: int = DEFAULT_PRIO,
              store: Beads | None = None, *, spawner: Spawner, git: Git, who: Identity) -> tuple[str, str, BeadId] | None:
    """(name, dir, slot bead) once this waiter is first in line and a slot is free; None when stop() says so (see app/slots/line.py)."""
    return slots_line.wait_slot(slot_env(repo, store, cfg, spawner=spawner, git=git, who=who), why, bead, stop, sleep, poll, on_wait, prio)


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


def prio_of(bead: Bead | None) -> int:
    """The priority number of a bead (0 = P0), DEFAULT_PRIO when it has none."""
    return bead.priority if bead and bead.priority is not None else DEFAULT_PRIO


def bead_priority(repo: str, bead_id: BeadId, who: Identity, store: Beads | None = None) -> int:
    """The priority (0 = P0) of a bead, DEFAULT_PRIO when it cannot be read."""
    try:
        return prio_of(peek(store or bd_store(who.actor, repo), bead_id))
    except SystemExit:  # no bd: it waits as a P2
        return DEFAULT_PRIO


def worktrees(repo: str, git: Git, who: Identity, slots: list[Bead] | None = None) -> list[str]:
    """Every worktree of the repo (git worktree list) and every slot folder (`slots`: the slot beads, when the caller has them): where an
    engine lock may be."""
    found = [c.path for c in git.checkouts(repo)]
    beads = slot_beads(repo, who) if slots is None else slots
    if beads:  # no slot beads, no profile read: a repo whose profile is bad still lists its worktrees
        cfg = profile_slots(repo)
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
        if lost := owned.losses(git, str(d), profile_slots(repo).base):
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
    cfg = profile_slots(repo)
    slots_dir = str(Path(slot_dir(repo, "x", cfg)).parent)
    if op == "clean":
        return owned.clean(git, who.config, repo_key(repo), repo, slots_dir, cfg.base, cfg.count, engine_busy)
    for r in owned.survey(git, who.config, repo_key(repo), repo, slots_dir):
        print("\t".join([r.state, r.path, r.branch or "-", r.note + (f" since {stamp(r.rec.created)}" if r.rec else "")]))
    return 0
