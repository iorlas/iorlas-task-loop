"""The validation of one commit in a reserved slot, under the slot's custody lock and inside the claim's keep-alive: the
checks step's flow (tl-8bh9.14.6 section 6, steps 4-12), pulled out of `check_entry` (tl-8bh9.14.8 slice L2) and
shared by a checks attempt's entry (X, `main` watched) and a land candidate's validation (S, no watch: `main` is None).

Order: the reconcile before any slot read or write (the latest setup run's unsettled command and every unsettled result
of the latest block, boot-aware: alive `unavailable checks:running`, unknown `checks:unknown`; gone, an unfinished result
becomes `interrupted`, so its block repeats whole); the deadline (`expired`); the profile at the commit on the slot's
pinned view (`profile:<reason>`); `main` read when watched (`main_moved`); a completed latest block is concluded as it
stands, never run again; the commit taken detached (`prepare.detach_at`); the slot reset to exactly it and set up at it
(`environment.prepare_for`, no probe; two failed setup runs conclude `setup:<conclusion>`); the block (`checks.Block`,
its results under the target's key through `CheckSink`: a candidate key passes `check_store.RESULT_HELD`); `main` read
again when watched; the conclusion from the latest block. A refusal the caller may conclude goes through `concluded`
(section 6.1's table). The caller writes the conclusion and releases the slot.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from git_porcelain import GitUnavailable, Repo

from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_types import AttemptKey, AttemptResult
from taskloop.check_store import Outcome, Required
from taskloop.checks import BlockTarget, CheckSink, check_env, completed, conclusion, main_seen
from taskloop.composition import Checking
from taskloop.environment import Renew, SetupFor
from taskloop.prepare import Prepared, detach_at, slot_listed
from taskloop.profile import PROFILE_PATH, Profile, Refused, read_profile

# Refusal words a relaunch may clear (counted, like every unavailable word): the slot's lock held or unopenable, a slot
# detached elsewhere with changes, and a store fence that moved under the entry.
RELAUNCHED: Final = frozenset({"slot_busy", "lock", "slot_dirty", "stale_reservation", "check_changed", "setup_changed"})


@dataclass(frozen=True)
class Verdict:
    """The validation's conclusion: `failed` has a reason; `seen` is `main` when found moved."""

    outcome: Outcome
    reason: str | None = None
    seen: str | None = None


type Ended = Verdict | AttemptResult


@dataclass(frozen=True)
class Target:
    """What one validation runs: under `key` (a checks attempt's or a land candidate's: its results, blocks and setup
    runs), in the held reservation's slot `slot_path` of `repo_id`, at `commit` (X or S), against the `required` names
    with their argv digests at the target, until `deadline`. `main` is the commit `main` was at when the required names
    were read, watched before and after the block (a checks attempt); None watches nothing (a land candidate, whose
    required names come from origin's immutable O). `profiled` writes the profile digest once, to the owner's row."""

    key: AttemptKey
    repo_id: str
    slot_path: str
    commit: str
    required: Required
    deadline: float
    main: str | None
    profiled: Callable[[str], None]


def concluded(result: AttemptResult) -> Verdict | None:
    """Section 6.1's table: a refusal concludes `failed` with its word (`slot_unborn` as `slot:unborn`), except those in
    `RELAUNCHED`; an unavailable word never concludes (None: relaunch and count)."""
    if result.status != "refused" or result.reason in RELAUNCHED:
        return None
    return Verdict("failed", "slot:unborn" if result.reason == "slot_unborn" else result.reason)


def validate(work: Checking, target: Target, renew: Renew) -> Ended:
    """The flow inside the keep-alive: a conclusion, or the refusal to relaunch or conclude."""
    try:
        return reconcile(work, target) or _expired(work, target) or _at(work, target, renew)
    except GitUnavailable:
        return AttemptResult("unavailable", "git")
    except StoreUnavailable:
        return AttemptResult("unavailable", "store")
    except StoreRefused as refused:
        return AttemptResult("refused", refused.reason)


def reconcile(work: Checking, target: Target) -> AttemptResult | None:
    """Before any slot read or write: every command that may still hold the slot, never signalled. Gone (or never
    registered), an unfinished result is concluded `interrupted`, so its block repeats whole."""
    key = target.key
    setup = work.setups.latest(key)
    rows = [row for row in work.store.results(key) if row.unsettled]
    processes = [process for process in (None if setup is None else setup.unsettled, *(row.process for row in rows)) if process]
    seen = {work.seen(process) for process in processes}
    if "alive" in seen or "unknown" in seen:
        return AttemptResult("unavailable", "checks:running" if "alive" in seen else "checks:unknown")
    for row in rows:
        if row.conclusion is None:
            work.store.finish(key, row.block, row.position, "interrupted", None, work.clock())
    return None


def _expired(work: Checking, target: Target) -> Verdict | None:
    """Past the deadline nothing of the validation runs (the reconcile proved it): it concludes."""
    return Verdict("failed", "expired") if work.clock() >= target.deadline else None


def _moved(view: Repo, main: str | None) -> Verdict | None:
    """`main` read now, against the commit the required names were read from (O1); nothing when not watched."""
    if main is None:
        return None
    seen = main_seen(view)
    return None if seen == main else Verdict("failed", "main_moved", seen)


def _profiled(work: Checking, target: Target) -> tuple[Profile, str, Path] | AttemptResult:
    """The profile at the commit and its digest, read on the slot's pinned view (its verified Git directory, returned)."""
    state = slot_listed(work.checkouts, work.slot_files, target.slot_path, target.repo_id)
    if isinstance(state, AttemptResult):
        return state
    files = work.profiles(Path(target.slot_path), state.gitdir)
    profile, blob = read_profile(files, target.commit), files.blob(target.commit, PROFILE_PATH)
    if isinstance(profile, Refused):
        return AttemptResult("refused", f"profile:{profile.reason}")
    if not isinstance(profile, Profile) or not isinstance(blob, bytes):
        return AttemptResult("unavailable", "git")
    return profile, hashlib.sha256(blob).hexdigest(), state.gitdir


def _at(work: Checking, target: Target, renew: Renew) -> Ended:
    """The profile at the commit, `main` when watched (also before a completed latest block is concluded as it stands: a
    candidate that moved it and then killed its entry never passes), then the commit taken detached."""
    read = _profiled(work, target)
    if isinstance(read, AttemptResult):
        return read
    profile, digest, gitdir = read
    results = work.store.results(target.key)
    moved = None if target.main is None else _moved(work.checkouts(Path(target.slot_path), git_dir=gitdir), target.main)
    if moved is None and completed(results, profile.checks, target.required):
        return Verdict(*conclusion(results, target.required))
    prepared = moved or detach_at(work.checkouts, work.slot_files, target.slot_path, target.repo_id, target.commit)
    if not isinstance(prepared, Prepared):
        return prepared
    return _environment(work, target, prepared, renew) or _block(work, target, profile, prepared, digest)


def _environment(work: Checking, target: Target, prepared: Prepared, renew: Renew) -> Ended | None:
    """The slot reset to exactly the commit and set up at it, no probe; two failed setup runs conclude
    `setup:<conclusion>` of the latest."""
    setup = SetupFor(target.key, Path(target.slot_path), target.commit, None, target.deadline, True)
    stopped = work.preparation.prepare_for(setup, prepared, renew, work.environ(), probe=None)
    if stopped is None or stopped != AttemptResult("refused", "environment:failed"):
        return stopped
    latest = work.setups.latest(target.key)
    return Verdict("failed", f"setup:{'failed' if latest is None or latest.conclusion is None else latest.conclusion}")


def _block(work: Checking, target: Target, profile: Profile, prepared: Prepared, digest: str) -> Ended:
    """The block, `main` again when watched, then the conclusion from the latest block."""
    key, path = target.key, Path(target.slot_path)
    number = work.store.block(key)
    target.profiled(digest)
    view = work.checkouts(path, git_dir=prepared.gitdir)
    block = BlockTarget(path, view, target.commit, target.required, target.deadline, check_env(work.environ(), path))
    stopped = work.block.run(block, CheckSink(work.store, key, work.files, work.clock), number, profile.checks)
    if stopped is not None:
        return stopped
    return _moved(view, target.main) or Verdict(*conclusion(work.store.results(key), target.required))
