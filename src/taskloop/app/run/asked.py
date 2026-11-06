"""A worker answer's updates to the run's threads: computed from the answer, applied to the engine, kept with the done-memo."""
from typing import Any

from taskloop.app.run import done_memo
from taskloop.app.run.call import Call
from taskloop.app.run.worker_identity import PreparedCall
from taskloop.contracts import fence
from taskloop.contracts.asked import Fallback, SessionUpdate, Updates
from taskloop.contracts.checkpoint import Checkpoint
from taskloop.contracts.delegate import DelegateResult
from taskloop.domain.lanes.roles import READ_ONLY_NODES
from taskloop.stores.call_state import CallState


def thread_updates(c: Call, res: DelegateResult, fallback_lane: str, ctx: float | None, seen: list[str]) -> Updates:
    """The writer's thread after an answer that resumed it: delegate's ref, and the fallback it reported (every answer that picked a
    lane says it, a resumed one too). `fallback_lane` is the lane held now; `ctx` and `seen` are what the writer holds."""
    if not (c.resume_key and res.ref):
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


def apply(e: Any, u: Updates) -> None:
    """Assign `u` to the engine (its RunState holds the thread fields)."""
    if u.fallback is not None:
        e.writer_fallback, e.fallback_lane = u.fallback.on, u.fallback.lane
    if u.session is not None:
        e.writer.delegate, e.writer.ctx, e.writer.seen = u.session.ref, u.session.ctx, list(u.session.seen)
    if u.planner_ref:
        e.planner_ref = u.planner_ref


def settle(e: Any, c: Call, state: CallState, prepared: PreparedCall) -> None:
    """The memo of a consumed answer and the thread fields it left in RunState, in one transaction: a crash keeps both or neither.
    Only the thread fields of the stored record change (never its step, applied or ended). A run that lost its slot keeps the memo alone."""
    memo = done_memo.memo_in(e.run_dir, c.key, c.sha, state.answer_file, prepared.snapshot)
    s = e.state

    def amend(ck: Checkpoint) -> Checkpoint:
        return ck.replace(state=ck.state.replace(writer=s.writer, writer_fallback=s.writer_fallback, fallback_lane=s.fallback_lane,
                                                planner_ref=s.planner_ref))
    try:
        e.checkpoints.amend_with(amend, memo)
    except fence.Fenced:
        memo(None)
