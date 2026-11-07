"""A worker answer's updates to the run's threads: computed from the answer, applied to the engine, kept with the done-memo."""
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from tlkernel import fence
from tlkernel.asked import SessionUpdate, Updates
from tlkernel.checkpoint import Checkpoint, RunState, WriterSession
from tlkernel.delegate import DelegateResult
from tlkernel.run import CallIdentity

from taskloop.app.workers import done_memo
from taskloop.app.workers.call import Call


class Threads(Protocol):
    """The engine's thread fields (RunState's, through StateField)."""

    writer: WriterSession
    planner_ref: str
    last_flag: str


class Amends(Protocol):
    def amend_with(self, fn: Callable[[Checkpoint], Checkpoint], also: Callable[[sqlite3.Connection | None], None]) -> bool: ...


class Settling(Protocol):
    run_dir: Path

    @property
    def checkpoints(self) -> Amends: ...


def thread_updates(c: Call, res: DelegateResult, seen: list[str]) -> Updates:
    """Keep only the prompt hashes the writer has seen."""
    if not (c.thread == "writer" and res.ref):
        return Updates()
    return Updates(session=SessionUpdate(tuple(seen)))


def done_updates(c: Call, res: DelegateResult, thread: Updates) -> Updates:
    """The updates of a call that ended: its prompt history, the planner's ref, and delegate's lane flag."""
    flag = res.flag or ""
    return Updates(thread.session, res.ref if c.node == "plan" and res.ref else "", flag)


def then(a: Updates, b: Updates) -> Updates:
    """`a`, and over it what `b` says."""
    return Updates(b.session or a.session, b.planner_ref or a.planner_ref, b.flag or a.flag)


def with_updates(state: RunState, u: Updates) -> RunState:
    """`state` with the thread fields of `u` set (only the ones `u` names)."""
    if u.session is not None:
        state = state.replace(writer=state.writer.replace(seen=list(u.session.seen)))
    if u.planner_ref:
        state = state.replace(planner_ref=u.planner_ref)
    return state


def apply(e: Threads, u: Updates) -> None:
    """Assign `u` to the engine (its RunState holds the thread fields); the flag is in memory only."""
    if u.session is not None:
        e.writer.seen = list(u.session.seen)
    if u.planner_ref:
        e.planner_ref = u.planner_ref
    e.last_flag = u.flag


def settle(e: Settling, c: Call, u: Updates, answer_file: str, identity: CallIdentity | None) -> None:
    """The memo of a consumed answer and the thread fields `u` names, in one transaction: a crash keeps both or neither.
    Only the thread fields of the stored record change (never its step, applied or ended). A run that lost its slot keeps the memo alone."""
    memo = done_memo.memo_in(e.run_dir, c.key, c.sha, answer_file, identity)

    def amend(ck: Checkpoint) -> Checkpoint:
        return ck.replace(state=with_updates(ck.state, u))
    try:
        e.checkpoints.amend_with(amend, memo)
    except fence.Fenced:
        memo(None)
