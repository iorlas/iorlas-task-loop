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

from taskloop.adapters import profile_at
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
from taskloop.contracts.bd_errors import BdCommandFailure
from taskloop.contracts.bead import Bead
from taskloop.contracts.beadsport import BdFailure, BeadQuery, Beads
from taskloop.contracts.config import EngineConfig, RepoProfile, SlotsConfig
from taskloop.contracts.gitport import Git
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ids import loop_key as repo_key
from taskloop.contracts.paths import TASK_EXCLUDE
from taskloop.contracts.procport import Spawner
from taskloop.contracts.slots import NotARepo, SlotFail, SlotGitError, SlotTable
from taskloop.contracts.slottable import WORKTREE, LiveSlot, SlotSource, build_slot_table
from taskloop.stores.real import real_stores


def profile(repo: str, base: str | None, git: Git) -> dict[str, Any]:
    """The repo's loop profile (.task-loop.json, parsed). With `base` (a ref such as origin/main), the copy committed there, so a pushed
    rule counts after a fetch even when nobody pulled the checkout; the working tree only when `base` does not resolve here (no remote).
    A file missing on the base is {}: committed wins."""
    return profile_source(repo, base, git)[0]


def profile_source(repo: str, base: str | None, git: Git) -> tuple[dict[str, Any], str]:
    """The profile and its exact commit, or an empty commit for the working-tree fallback."""
    try:
        commit = git.rev_parse(repo, base + "^{commit}") if base else ""
    except NotARepo:
        commit = ""  # a folder not yet initialized has only its local profile
    path = Path(repo) / profile_at.FILE
    if commit:
        try:
            return profile_at.raw_at(git, repo, commit) or {}, commit
        except (SlotGitError, ValueError) as err:
            raise config.ProfileReadError(str(path), commit, err) from err
    try:
        return profile_at.raw_in(repo) or {}, ""
    except (OSError, ValueError) as err:
        raise config.ProfileReadError(str(path), "", err) from err


def load_profile(data: Any) -> RepoProfile:
    """A parsed .task-loop.json as a RepoProfile; an unknown key or a wrong type exits, naming it. A retired key is said once."""
    try:
        return config.load(data, say_to=sys.stderr)
    except config.ConfigError as e:
        print(f"task-loop: {e}", file=sys.stderr)
        raise SystemExit(os.EX_CONFIG) from e


def cfg_source(repo: str, git: Git) -> tuple[RepoProfile, str, str]:
    """(the RepoProfile, the base hint, the pinned commit: empty for a local fallback). A bad .task-loop.json exits loudly."""
    try:
        local = profile(repo, None, git)
        engine = local.get("engine") if isinstance(local, dict) else None
        hint = engine.get("base") if isinstance(engine, dict) else None
        base = hint if isinstance(hint, str) else EngineConfig().base
        data, commit = profile_source(repo, base, git)
        return load_profile(data), base, commit
    except config.ConfigError as err:
        print(f"task-loop: {err}", file=sys.stderr)
        raise SystemExit(os.EX_CONFIG) from err


def load_cfg(repo: str, git: Git) -> EngineConfig:
    """The `engine` block of the repo's .task-loop.json as committed on the base branch, defaults for what it leaves out. The base is
    itself a key: the working tree names it, then the base's copy is read. A caller fetches first."""
    return cfg_source(repo, git)[0].engine


def profile_slots(repo: str, git: Git | None = None) -> SlotsConfig:
    """The `slots` block of the repo's loop profile. With `git`, as committed on the base ref (what the loops read, `cfg_source`: a stale
    checkout does not change the count); without, the working tree's copy (no git to ask; prefer passing one)."""
    if git is not None:
        return cfg_source(repo, git)[0].slots
    try:
        return load_profile(profile_at.raw_in(repo) or {}).slots
    except (OSError, ValueError):
        return SlotsConfig()


def slot_source(repo: str, git: Git) -> SlotSource:
    """The slot count the loops use (the profile on the base ref, as `cfg_source` reads it), this machine's host and the slot folders on
    disk. A bad profile exits (cfg_source says so); a caller that must not exit answers for it."""
    profile_, base, commit = cfg_source(repo, git)
    cfg = profile_.slots
    root = str(Path(slot_dir(repo, "x", cfg)).parent)
    return SlotSource(host=hostname(), count=cfg.count, source=base if commit else WORKTREE, sha=commit, dirs=slot_dirs(root), root=root)


def slot_dirs(root: str) -> frozenset[str]:
    """The names of the slot folders in `root` (no process: a directory listing)."""
    try:
        return frozenset(d.name for d in Path(root).iterdir() if d.is_dir())
    except OSError:
        return frozenset()


def slot_table(repo: str, who: Identity, git: Git, now: float, live: Mapping[str, LiveSlot] | None = None,
               store: Beads | None = None) -> SlotTable:
    """The one slot table of this repo on this machine (contracts/slottable): the config from the base ref, the slot beads of this host,
    `live` the runs the caller saw alive (slot name -> run)."""
    src = slot_source(repo, git)
    beads = slot_beads(repo, who, store)
    store = store or bd_store(who.actor, repo)
    open_ids: list[str] = []
    with contextlib.suppress(BdFailure):  # no bd answer: no claim is shown as starting work
        open_ids = [b.id for b in store.find(BeadQuery()) if b.status in ("open", "in_progress")]
    return build_slot_table(beads, src.count, live or {}, src.dirs, now, src.source, src.sha, open_ids)


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
        tickets=real_stores(who.config).tickets,
        cfgdir=who.config,
        actor=who.actor,
        host=hostname(),
        take_lock=lambda: os_lock(who.config.lock_file(f"slot-take-{repo_key(repo)}.lock"), f"pid {os.getpid()}"),
        busy=functools.partial(engine_busy, who.config), lock_pid=functools.partial(lock_pid, who.config),
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
        busy = functools.partial(engine_busy, who.config)
        return owned.clean(git, who.config, repo_key(repo), repo, slots_dir, cfg.base, cfg.count, busy)
    for r in owned.survey(git, who.config, repo_key(repo), repo, slots_dir):
        print("\t".join([r.state, r.path, r.branch or "-", r.note + (f" since {stamp(r.rec.created)}" if r.rec else "")]))
    return 0
