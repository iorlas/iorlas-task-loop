"""Make a slot ready for a bead: a clean tree on the bead's branch, a dead session's work committed where it was (never
wiped), ignored setup output kept. All of git goes through the Git port; its typed errors become a SlotFail."""
import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from taskloop.app.slots.env import SlotEnv, stamp
from taskloop.contracts.slots import BranchPinned, DirtyTree, IndexLocked, RefRace, SlotFail, SlotGitError

if TYPE_CHECKING:
    from taskloop.app.slots.pool import Slot

T = TypeVar("T")
TRIES = 3  # a git lock (index.lock, a ref) held by another process is waited for this many times before the slot is broken


def retrying[T](env: SlotEnv, what: str, call: Callable[[], T]) -> T:
    """`call`, again while git reports a lock another process holds; BranchPinned is the bead's, anything else the slot's."""
    for i in range(TRIES):
        try:
            return call()
        except (IndexLocked, RefRace) as e:
            if i == TRIES - 1:
                raise SlotFail("slot_broken", f"{what}: git is locked: {e.tail}") from e
            env.sleep(0.2 * (i + 1))
        except BranchPinned as e:
            raise SlotFail("bead_pinned", e.tail) from e
        except DirtyTree as e:
            raise SlotFail("slot_broken", f"{what}: {e.tail}") from e
        except SlotGitError as e:
            raise SlotFail("slot_broken", f"{what}: {e.tail}") from e
    raise AssertionError("unreachable")


def ready_for(slot: Slot, bead: str, *, force: bool = False) -> None:
    env, d = slot.env, slot.dir
    holder = env.lock_pid(d)  # the lock judged busy below is the one dropped
    busy = env.busy(d)  # never commit or switch branches under a running engine (2026-10-21, lifesim-5ar.7)
    hold = slot.hold()
    if not busy and hold:
        busy = f"held by {hold.by} until {stamp(hold.until)}: {hold.why}"
    if busy and not force:
        raise SlotFail("busy", f"slot {slot.name}: {busy}; not reset (--force: reset anyway and drop the lock)")
    if busy:
        env.drop_engine_lock(d, holder)
        env.say(f"FORCED: slot {slot.name} reset over: {busy}")
    keep_work(slot)
    try:
        env.git.fetch(d)
    except SlotGitError as e:  # the tree is still clean and on a known base: the checkout below decides
        env.warn(f"tl: fetch in slot {slot.name} failed: {e.tail}")
    check_out(slot, bead)
    retrying(env, f"slot {slot.name}", lambda: env.git.clean(d, env.cfg.keep))
    setup(slot)


def keep_work(slot: Slot) -> None:
    """A dead session's work: committed where it was (on a wip branch when HEAD was detached), never wiped."""
    env, d = slot.env, slot.dir
    if retrying(env, f"slot {slot.name}", lambda: env.git.rebasing(d)):
        env.git.rebase_abort(d)
    if not retrying(env, f"slot {slot.name}", lambda: env.git.dirty(d)):
        return
    branch = env.git.branch(d) or f"wip/{slot.name}/{int(env.now())}"
    try:
        retrying(env, f"slot {slot.name}", lambda: env.git.commit_all(d, branch, f"wip: left in slot {slot.name}"))
    except SlotFail as e:
        raise SlotFail("slot_broken", f"could not commit the leftover work on {branch}: {e.why}") from e
    env.say("WIP committed on " + branch)


def check_out(slot: Slot, bead: str) -> None:
    env, d, base = slot.env, slot.dir, slot.env.cfg.base
    what = f"slot {slot.name}"
    if bead and env.git.has_branch(d, "task/" + bead):
        # the bead's branch holds its earlier runs' work: check it out as it is, never reset it to base (a forced reset
        # here wiped lifesim-r32's reviewed work on 2026-10-19; the engine rebases at land)
        held = free_branch(slot, "task/" + bead)
        if held:  # a live run has it: this bead is not for this slot now (never a failure)
            raise SlotFail("bead_pinned", held)
        retrying(env, what, lambda: env.git.checkout(d, "task/" + bead))
    elif bead:
        retrying(env, what, lambda: env.git.checkout_new(d, "task/" + bead, base))
    else:
        retrying(env, what, lambda: env.git.checkout_detached(d, base))


def free_branch(slot: Slot, branch: str) -> str:
    """Make `branch` free to check out in the slot. Another worktree holding it (a pre-slot worktree, a dead run's) is
    removed when clean, else detached where it stands: its files and commits stay (tl-bxk.10.26, lifesim 2026-10-22).
    "" when free, else why a live run keeps it (the repo's own checkout counts as live)."""
    env, d = slot.env, slot.dir
    held = [c for c in env.git.checkouts(d) if c.branch == branch and os.path.realpath(c.path) != os.path.realpath(d)]
    for c in held:
        busy = env.busy(c.path)
        if busy or c.main:
            return "branch {} is checked out in {}{}".format(branch, c.path, ": " + busy if busy else " (the repo's own checkout)")
    for c in held:
        if not env.git.dirty(c.path) and env.git.remove_worktree(env.repo, c.path):
            env.say(f"FREED: branch {branch}: removed the clean worktree {c.path}")
            continue
        try:
            env.git.checkout_detached(c.path, "HEAD")
        except SlotGitError as e:
            return f"branch {branch} is checked out in {c.path} and cannot be detached: {e.tail}"
        env.say(f"FREED: branch {branch}: detached HEAD in {c.path} (its files and commits stay)")
    return ""


def inputs_hash(d: str, patterns: list[str]) -> str:
    h = hashlib.sha256()
    for pat in patterns:
        for p in sorted(Path(d).glob(pat)):
            if p.is_file():
                h.update(str(p.relative_to(d)).encode())
                h.update(p.read_bytes())
    return h.hexdigest()


def setup(slot: Slot, force: bool = False) -> None:
    """Run the profile's setup only when its inputs changed since the last setup in this slot."""
    env, d, cfg = slot.env, slot.dir, slot.env.cfg
    if not cfg.setup:
        env.say("READY " + d)
        return
    digest = inputs_hash(d, cfg.setup_inputs)
    mark = env.cfgdir.slot_setup_mark(hashlib.sha1(d.encode()).hexdigest()[:12])
    mark.parent.mkdir(parents=True, exist_ok=True)
    if not force and cfg.setup_inputs and mark.exists() and mark.read_text() == digest:
        env.say("READY " + d + " (setup unchanged)")
        return
    t = env.now()
    rc = env.run_setup(cfg.setup, d)
    env.event("slot_setup", "", slot=slot.name, worktree=d, exit=rc, secs=round(env.now() - t), repo=env.repo)
    if rc != 0:
        raise SlotFail("slot_broken", f"setup exited {rc}")
    mark.write_text(digest)
    env.say("READY " + d)
