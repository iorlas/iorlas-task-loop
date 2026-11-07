"""A worker answer's updates to the run's threads: computed from the answer, applied to the engine, kept with the done-memo."""
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from tlkernel import fence
from tlkernel.asked import Fallback, SessionUpdate, Updates
from tlkernel.checkpoint import Checkpoint, RunState, WriterSession
from tlkernel.delegate import DelegateResult
from tlkernel.run import CallIdentity

from taskloop.app.workers import done_memo
from taskloop.app.workers.call import Call
from taskloop.domain.lanes.roles import READ_ONLY_NODES


class Threads(Protocol):
    """The engine's thread fields (RunState's, through StateField)."""

    writer: WriterSession
    writer_fallback: bool
    fallback_lane: str
    planner_ref: str
    last_flag: str


class Amends(Protocol):
    def amend_with(self, fn: Callable[[Checkpoint], Checkpoint], also: Callable[[sqlite3.Connection | None], None]) -> bool: ...


class Settling(Protocol):
    run_dir: Path

    @property
    def checkpoints(self) -> Amends: ...


def thread_updates(c: Call, res: DelegateResult, fallback_lane: str, ctx: float | None, seen: list[str]) -> Updates:
    """The writer's thread after an answer that resumed it: delegate's ref, and the fallback it reported (every answer that picked a
    lane says it, a resumed one too). `fallback_lane` is the lane held now; `ctx` and `seen` are what the writer holds."""
    if not (c.thread == "writer" and res.ref):
        return Updates()
    fallback = None
    if res.fallback is not None:
        fallback = Fallback(res.fallback, (res.first_lane or c.out_on or fallback_lane) if res.fallback else "")
    return Updates(session=SessionUpdate(res.ref, ctx, tuple(seen)), fallback=fallback)


def done_updates(c: Call, res: DelegateResult, thread: Updates) -> Updates:
    """The updates of a call that ended: its thread's, the planner's ref, and its lane flag (a read-only node that was routed past a
    dead lane to the writer's own family says so)."""
    flag = res.flag or ""
    if c.node in READ_ONLY_NODES and c.writer_family and res.family == c.writer_family and not flag:
        flag = "same_family"
    return Updates(thread.session, thread.fallback, res.ref if c.node == "plan" and res.ref else "", flag)


def then(a: Updates, b: Updates) -> Updates:
    """`a`, and over it what `b` says."""
    return Updates(b.session or a.session, b.fallback or a.fallback, b.planner_ref or a.planner_ref, b.flag or a.flag)


def with_updates(state: RunState, u: Updates) -> RunState:
    """`state` with the thread fields of `u` set (only the ones `u` names)."""
    if u.fallback is not None:
        state = state.replace(writer_fallback=u.fallback.on, fallback_lane=u.fallback.lane)
    if u.session is not None:
        state = state.replace(writer=state.writer.replace(delegate=u.session.ref, ctx=u.session.ctx, seen=list(u.session.seen)))
    if u.planner_ref:
        state = state.replace(planner_ref=u.planner_ref)
    return state


def apply(e: Threads, u: Updates) -> None:
    """Assign `u` to the engine (its RunState holds the thread fields); the flag is in memory only."""
    if u.fallback is not None:
        e.writer_fallback, e.fallback_lane = u.fallback.on, u.fallback.lane
    if u.session is not None:
        e.writer.delegate, e.writer.ctx, e.writer.seen = u.session.ref, u.session.ctx, list(u.session.seen)
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
