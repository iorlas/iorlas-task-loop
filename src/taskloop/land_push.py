"""The land's remote side (tl-8bh9.14.8 section 7): the fetch of origin's `main`, the one delivery rule, the push of S
and `--withdraw`. Its Git writes are `fetch` (a remote-tracking ref, as the person's own `git fetch` writes it) and
`push` (never forced); both run on the person's checkout through the `remotes` view (hooks off, bounded transport, the
person's Git configuration and credentials).

**The delivery rule**, one for the first try and every resume. Delivery is recorded only from a `Pushed` answer for S, or
from origin's `main` as read by `ls_remote` or by the bounded fetch; never from the local remote-tracking ref without that
fetch, never from a log. `origin` is trusted as configured: how its fetch and push URLs are set is the person's choice
(section 27.1, decided 2026-11-12). With R the `ls_remote` answer for `main`: R is S is delivered (`already_pushed`); R
is O pushes S; anything else fetches, then S an ancestor of the fetched tip F is
delivered (`remote_head` F, which contains S), else the candidate is superseded `moved` and, at most once per invocation,
the caller makes candidate N+1 onto the moved `main` (`Again`); a second time is `target_moved`. A push answered
`remote_rejected` is read again by the same rule: origin's `main` no longer at O (the lost race for the ref: a lock held by the
other land, or its push won) is the race above, `remote_rejected` stays for a policy refusal with `main` unchanged
(tl-8bh9.14.35). The push names no
expected old tip: Git's fast-forward rule accepts it only while origin's `main` is an ancestor of S. An S no longer in
the repository (pruned) is superseded `gone` the same way.

`--withdraw` reads origin by the same rule and never pushes: delivered is recorded, else the candidate is superseded
`withdrawn` (so the task's abandon is possible again). No Git output, remote URL or credential is kept or printed.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from git_porcelain import GitUnavailable, HookRejected, MissingRevision, Pushed, RefRejected, Repo, Sha, Transient

from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.git_views import PUSH_TIMEOUT
from taskloop.land_store import LandRow, LandStore
from taskloop.operations import Failed

REMOTE: Final = "origin"
MAIN: Final = "refs/heads/main"
TRACKING: Final = "refs/remotes/origin/main"
FETCHED: Final = f"+{MAIN}:{TRACKING}"  # origin's `main` into its remote-tracking ref, never a local branch
ROUNDS: Final = 3  # delivery steps per invocation: a rejected push reads origin again; a third rejection is `target_moved`


@dataclass(frozen=True)
class Origin:
    """The person's checkout (`checkout`) and its remote-capable view (`repo`), whose `origin` was found to exist."""

    repo: Repo
    checkout: Path


@dataclass(frozen=True)
class Delivered:
    """The candidate delivered: `remote_head` is S, or origin's later tip containing it; `how` is `pushed` (this call's
    push) or `already_pushed` (origin was found to hold it); `no_change` when the new candidate made after a moved `main`
    found main already holding X's changes (delivered at insert, `remote_head` its O: nothing is pushed)."""

    row: LandRow
    remote_head: str
    how: Literal["pushed", "already_pushed", "no_change"]


@dataclass(frozen=True)
class Withdrawn:
    """The pushable candidate superseded `withdrawn`: S was not on origin's `main`."""

    row: LandRow


type Again = Callable[[], LandRow | Failed]  # candidate N+1 onto origin's moved `main`, validated when its tree differs
type Undelivered = Literal["at_origin", "moved"]
type _Seen = tuple[Literal["delivered", "at_origin", "moved"], str]


def remote_tips(repo: Repo, task_ref: str | None = None) -> tuple[str | None, str | None]:
    """One `ls_remote`: origin's `main` (R) and, when named, its task branch; GitUnavailable when origin cannot be read."""
    names = [MAIN] if task_ref is None else [MAIN, task_ref]
    found = {ref.name: ref.oid for ref in repo.ls_remote(REMOTE, names)}
    return found.get(MAIN), None if task_ref is None else found.get(task_ref)


def fetched(repo: Repo) -> str | None:
    """The bounded fetch of origin's `main` into its remote-tracking ref (PUSH_TIMEOUT, given explicitly: the view's
    `remote_timeout` bounds only pushes and `ls_remote`), then that ref: O, or F on a resume; None without one.
    GitUnavailable when the fetch fails."""
    repo.fetch(REMOTE, refspecs=[FETCHED], timeout=PUSH_TIMEOUT)
    return next((entry.sha for entry in repo.refs([TRACKING]) if entry.name == TRACKING), None)


def _seen(origin: Origin, row: LandRow) -> _Seen | Failed:
    """The delivery rule's read: R is S, R is O, or the fetched tip F containing S or not."""
    try:
        r, _task = remote_tips(origin.repo)
        if r in (row.commit, row.origin):
            return ("delivered" if r == row.commit else "at_origin"), row.commit
        f = None if r is None else fetched(origin.repo)
    except GitUnavailable as error:
        return Failed("unavailable", "remote", f"`{REMOTE}` could not be read ({type(error).__name__}): rerun. Nothing was pushed.")
    if f is None:
        return Failed("refused", "target", f"`{REMOTE}` has no branch `main`. Nothing was pushed.")
    try:
        contained = f == row.commit or origin.repo.is_ancestor(row.commit, f)
    except MissingRevision:  # S no longer here (pruned): origin's tip, known here after the fetch, cannot contain it
        contained = False
    except GitUnavailable as error:
        return Failed("unavailable", "git", f"Git could not compare S with origin's main ({type(error).__name__}): rerun.")
    return ("delivered" if contained else "moved"), f


def _recorded(lands: LandStore, now: float, row: LandRow, head: str, how: Literal["pushed", "already_pushed"]) -> Delivered | Failed:
    """The delivery, once, fenced (`land_store.record_delivery`); found delivered by a concurrent land is the same answer."""
    on_main = f"S ({row.commit}) is on origin's main"
    try:
        lands.record_delivery(row.key, head, now)
    except StoreRefused as refused:
        if refused.reason == "abandoned":
            return Failed("refused", "abandoned", f"{on_main}, but its checks attempt was abandoned: inspect the task.")
        again = lands.row(row.key)
        if again is not None and again.delivery is not None and again.remote_head is not None:
            return Delivered(again, again.remote_head, "already_pushed")
        return Failed("unavailable", "changed", f"{on_main}; the candidate changed meanwhile: rerun to record it.")
    except StoreUnavailable:
        return Failed("unavailable", "store", f"{on_main}; nothing was recorded: rerun to record it.")
    found = lands.row(row.key)
    return Delivered(row if found is None else found, head, how)


def _pushed(origin: Origin, s: str) -> Literal["pushed", "rejected"] | Failed:
    """One non-forced push of exactly S to origin's `main` from the person's checkout."""
    try:
        result = origin.repo.worktree(origin.checkout).push("main", remote=REMOTE, head=Sha(s))
    except GitUnavailable as error:
        return Failed("unavailable", "git", f"Git could not push ({type(error).__name__}): check `git push` works from this shell.")
    if isinstance(result, Pushed):
        return "pushed"
    return "rejected" if isinstance(result, RefRejected) else _refusal(result, s)


def _refusal(result: object, s: str) -> Failed:
    """A push neither made nor raced: unreachable, a hook (although hooks are off), or origin's own policy."""
    if isinstance(result, Transient):
        return Failed("unavailable", "remote", f"`{REMOTE}` could not be reached (network or credentials): rerun.")
    if isinstance(result, HookRejected):
        return Failed("unavailable", "git", "A hook refused the push although hooks are off: rerun.")
    return Failed("refused", "remote_rejected", f"`{REMOTE}` refused the push of S {s} to main by its own policy, not a race; "
                  "nothing was pushed and the candidate stays validated.")


def _step(lands: LandStore, clock: Callable[[], float], origin: Origin, row: LandRow) -> Delivered | Failed | str:
    """One pass of the rule: delivered, a refusal, `rejected` (read origin again), `moved` or `gone` (superseded). Origin
    is read first: an S pruned here after it reached origin is still delivered."""
    seen = _seen(origin, row)
    if isinstance(seen, Failed):
        return seen
    if seen[0] == "delivered":
        return _recorded(lands, clock(), row, seen[1], "already_pushed")
    try:
        gone = origin.repo.tree(f"{row.commit}^{{commit}}") is None
    except GitUnavailable as error:
        return Failed("unavailable", "git", f"Git could not read S ({type(error).__name__}): rerun.")
    if gone or seen[0] == "moved":
        return "gone" if gone else "moved"
    pushed = _pushed(origin, row.commit)
    if isinstance(pushed, Failed) and pushed.reason == "remote_rejected" and _raced(origin, row):
        return "rejected"  # a lost race for the ref (lock held, or main moved) answers as a policy refusal: it is the race
    return _recorded(lands, clock(), row, row.commit, "pushed") if pushed == "pushed" else pushed


def _raced(origin: Origin, row: LandRow) -> bool:
    """A remote-rejected push is the race when origin's `main` is no longer at O (read again by the rule); policy otherwise."""
    seen = _seen(origin, row)
    return not isinstance(seen, Failed) and seen[0] != "at_origin"


def deliver(lands: LandStore, clock: Callable[[], float], origin: Origin, row: LandRow, again: Again | None) -> Delivered | Failed:
    """The pushable candidate `row` delivered by the rule; `again` makes candidate N+1 (None: this invocation made one)."""
    for _ in range(ROUNDS):
        step = _step(lands, clock, origin, row)
        if isinstance(step, (Delivered, Failed)):
            return step
        if step == "rejected":
            continue
        lands.supersede(row.key, "gone" if step == "gone" else "moved", clock())
        if again is None:
            return _moved(row)
        made, again = again(), None
        if isinstance(made, Failed) or made.delivery == "no_change":  # main already holds X's changes: nothing to push
            return made if isinstance(made, Failed) else Delivered(made, made.origin, "no_change")
        row = made
    return _moved(row)


def _moved(row: LandRow) -> Failed:
    """The fact only; `land_guide`'s `target_moved` says what the rerun does."""
    return Failed("unavailable", "target_moved", f"origin's main moved off {row.origin} during this land (candidate {row.number}, "
                  f"S {row.commit}); nothing was pushed.")


def observed(lands: LandStore, clock: Callable[[], float], origin: Origin, row: LandRow) -> Delivered | Failed | Undelivered:
    """Origin read by the rule, never pushed: delivered is recorded; else `at_origin` (origin's `main` is still O) or
    `moved` (S not in origin's moved `main`)."""
    seen = _seen(origin, row)
    if isinstance(seen, Failed):
        return seen
    kind, head = seen
    if kind == "delivered":
        return _recorded(lands, clock(), row, head, "already_pushed")
    return kind


def withdraw(lands: LandStore, clock: Callable[[], float], origin: Origin, row: LandRow) -> Delivered | Withdrawn | Failed:
    """`--withdraw`: delivered is recorded (nothing to withdraw), else the candidate is superseded `withdrawn`."""
    found = observed(lands, clock, origin, row)
    if isinstance(found, (Delivered, Failed)):
        return found
    if not lands.supersede(row.key, "withdrawn", clock()):
        return Failed("unavailable", "changed", "The land candidate changed meanwhile: rerun.")
    again = lands.row(row.key)
    return Withdrawn(row if again is None else again)
