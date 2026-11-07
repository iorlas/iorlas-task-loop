"""Prepare semantic call identities and judge persisted work before adopting it."""

from dataclasses import dataclass, replace
from pathlib import Path

from tlkernel.gitport import Git

from taskloop.app.workers import done_memo, worker_identity
from taskloop.app.workers.worker_identity import ExecutionContext, NodeInput, PreparedCall, context
from taskloop.stores import call_state

# Bump when answer interpretation changes incompatibly, even if the JSON schema does not.
PRODUCER = "worker-run:4;answers:1"


def prepare_call(input: NodeInput, context: ExecutionContext) -> PreparedCall:
    return worker_identity.prepare_call(input, context, PRODUCER)


@dataclass(frozen=True)
class Fresh:
    reason: str = ""


@dataclass(frozen=True)
class Resuming:
    ref: str
    text: str


@dataclass(frozen=True)
class Returned:
    raw: dict[str, object]
    state: call_state.CallState | None = None


@dataclass(frozen=True)
class CallJournal:
    run_dir: Path
    call_dir: Path
    bead: str
    key: tuple[object, ...]


def recover(call: PreparedCall, journal: CallJournal) -> Fresh | Resuming | Returned:
    done = done_memo.recall(journal.run_dir, journal.key, call.execution_id, call.snapshot)
    if done is not None:
        return Returned(done)
    st = call_state.load_for(journal.call_dir, journal.bead, journal.key)
    if st is None:
        return Fresh()
    return _recover_state(call, st)


def _recover_state(call: PreparedCall, st: call_state.CallState) -> Fresh | Resuming | Returned:
    if not st.execution_id:
        return Fresh("call has no verified execution identity (legacy or unobserved effects); execute again")
    if st.execution_id != call.execution_id:
        return Fresh("execution context/policy/schema/producer changed; execute again")
    what = call_state.reattach(st)
    if what and what[0] == "answer":
        return Returned(what[1], st)
    if what:
        return Resuming(what[1], what[2])
    return Fresh()


def record_returned(
    call: PreparedCall, st: call_state.CallState, git: Git, raw: dict[str, object], path: Path, now: float,
) -> None:
    """Observe returned effects without replacing the memo's admitted identity."""
    st.execution_id = ""
    try:
        current = context(git, call.context.worktree, call.context.cwd)
        st.execution_id = call.at(current).execution_id
    finally:
        st.returned(raw, path, now)


def saved(call: PreparedCall, st: call_state.CallState, current: ExecutionContext) -> PreparedCall:
    """Bind a paused thread to the tree and HEAD saved by the engine's WIP commit."""
    before = call.context
    same_repo = before.cwd_head == before.head and current.cwd_head == current.head
    cwd_head = before.cwd_head if same_repo else current.cwd_head
    cwd_tree = before.cwd_tree if same_repo else current.cwd_tree
    # Saving may include the interrupted worker's edits and engine-owned files.
    # Adopt those effects only here, keeping the admitted request's semantics and
    # requiring an independent cwd's inputs to remain unchanged.
    unchanged = replace(current, tree=before.tree, cwd_tree=cwd_tree, head=before.head, cwd_head=cwd_head) == before
    if st.phase == "calling" and st.ref and st.execution_id == call.execution_id and unchanged:
        call = call.at(current)
        st.execution_id = call.execution_id
        st.save()
    return call
