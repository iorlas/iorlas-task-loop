"""The run state and its one writer.

`carries_state` gives the engine every `RunState` field as an attribute that reads and writes `engine.state` (adding a field
is one edit, in contracts/checkpoint.py). `Checkpoints` is the only code that writes checkpoints/<bead>.json: save at a
node, close at the end, keep the follow-ups, follow a rebase, drop.
"""

import contextlib
import copy
import time
from collections.abc import Callable
from typing import Any

from taskloop.app.run.review_glue import review_of
from taskloop.contracts import fence, wire
from taskloop.contracts.checkpoint import BriefSnap, Checkpoint, Defect, EndRec, Handoff, Notes, PlanStep, RunState, WriterSession
from taskloop.contracts.plancheck import PlanData
from taskloop.contracts.review import Unfiled
from taskloop.contracts.wire import Open
from taskloop.domain.checks import trim
from taskloop.stores.api import Doc

NOT_ATTRS = ("review",)  # the one field of another lane's type: reached as `engine.state.review` only


class StateField:
    """An engine attribute that lives in `engine.state`."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __get__(self, obj: Any, owner: Any = None) -> Any:
        return self if obj is None else getattr(obj.state, self.name)

    def __set__(self, obj: Any, value: Any) -> None:
        setattr(obj.state, self.name, value)


class StateAttrs:
    """Base of a class decorated with `carries_state`: declares the RunState fields as typed attributes (tests/run/test_state.py holds
    these equal to RunState's)."""

    plan_data: PlanData | None
    brief_hash: str
    snap: BriefSnap | None
    planner_ref: str
    planned: int
    replans: int
    fixes: int
    extra: int
    rebase_resets: int
    plan_log: list[PlanStep]
    done: list[str]
    accepted: list[int]
    accepted_new: list[str]
    denials: list[str]
    writer: WriterSession
    writer_family: str | None
    writer_fallback: bool
    fallback_lane: str
    writer_said: str
    look_paths: list[str]
    look_notes: list[str]
    look_unjudged: dict[str, str]
    look_done: int
    look_prev: list[Defect]
    rendered_names: list[str]
    last_reqs: list[Open]
    render_stale: bool
    handoff: Handoff
    stage_tree: str
    pending_land_validation: str


def state_names() -> tuple[str, ...]:
    return tuple(name for name in wire.names(RunState) if name not in NOT_ATTRS)


def carries_state[T](cls: type[T]) -> type[T]:
    for name in state_names():
        setattr(cls, name, StateField(name))
    return cls


class Checkpoints:
    """checkpoints/<bead>.json: the one writer. Every method is one read-modify-write of a whole record. `host` is the engine:
    its state, its bead, its run, its git."""

    def __init__(self, host: Any) -> None:
        self.e = host

    @property
    def doc(self) -> Any:
        return self.e.stores.checkpoints.of(self.e.bead)

    def writer(self) -> Doc[Checkpoint]:
        """The record's document for a write: only a run that still holds its bead and slot may write it (Fenced otherwise)."""
        fence.check(self.e.store, self.e.claim)
        return self.doc

    def read(self) -> Checkpoint | None:
        return self.doc.get()

    def save(self, *, step: str = "", stage: int = 0, rounds: int = 0, n: int = 0, feedback: str = "") -> None:
        """Where the run stands. Mid-rebase (a conflict fix) HEAD is detached: the record names the task branch the close goes
        back to. A pending land validation always parks at land-verify-red: a fix, a re-plan or an interrupted recovery must never
        turn it into a direct-to-land checkpoint."""
        e = self.e
        if e.pending_land_validation:
            step, feedback = "land-verify-red", e.pending_land_validation
        state = copy.deepcopy(e.state)
        state.review = review_of(e)
        self.writer().write(
            Checkpoint(
                bead=e.bead,
                run=e.log_path.stem,
                t=time.time(),
                branch=e.checkout.branch_now() or e.task_branch,
                head=e.git("rev-parse", "HEAD"),
                step=step,
                stage=stage,
                rounds=rounds,
                n=n,
                feedback=feedback,
                state=state,
            )
        )

    def close(self, why: str = "") -> None:
        """The close step committed everything: the record's head is now what the next run should find. A red gate at land is no
        stop: the next run re-plans with the gate's output, or it would rerun the same red gate."""
        ck = self.read()
        if ck is None:
            return
        red = why.startswith("gate red") and not ck.state.pending_land_validation
        review = ck.state.review.replace(filed=list(self.e.filed))
        state = ck.state.replace(review=review)
        done = ck.replace(head=self.e.git("rev-parse", "HEAD"), closed=True, state=state)
        if red:
            done = done.replace(step="gate-red", gate_tail=trim.trim_log(why, log=str(self.e.gate_log or "")))
        self.writer().write(done)

    def applied(self) -> frozenset[str]:
        ck = self.read()
        return frozenset(ck.applied if ck else ())

    def mark_applied(self, key: str) -> None:
        """A close effect ran: its key goes into the record, so a kill after it resumes at the next effect. No record, no key kept."""
        ck = self.read()
        if ck is not None and key not in ck.applied:
            self.writer().write(ck.replace(applied=[*ck.applied, key]))

    def keep_end(self, end: EndRec) -> None:
        """The close's outcome goes into the record before its first effect: a restart finishes the close from it. No record, none kept."""
        with contextlib.suppress(fence.Fenced):
            self.amend(lambda ck: ck.replace(ended=end))

    def keep_notes(self, notes: Notes) -> None:
        """What FileNotes filed and what bd refused, so the Reflect comment says the same after a restart."""
        with contextlib.suppress(fence.Fenced):
            self.amend(lambda ck: ck.replace(notes=notes))

    def notes(self) -> Notes | None:
        ck = self.read()
        return ck.notes if ck else None

    def keep_filed(self, lost: list[dict[str, str]] | None = None) -> None:
        """The follow-ups filed so far and the ones bd refused (`lost`: kept, none lost): written at once, a kill loses no title."""
        self.e.unfiled += [Unfiled(title=lo["title"], why=lo["why"]) for lo in lost or []]
        ck = self.read()
        if ck is not None:
            kept = ck.state.replace(review=review_of(self.e))
            self.writer().write(ck.replace(state=kept))

    def keep_look(self) -> None:
        """What the owner-look bead needs goes into the record, so a crash after the land still files it."""
        ck, e = self.read(), self.e
        if ck is not None:
            kept = ck.state.replace(look_paths=list(e.look_paths),
                look_notes=list(e.look_notes),
                look_unjudged=dict(e.look_unjudged),
                review=review_of(e))
            self.writer().write(ck.replace(state=kept))

    def amend(self, fn: Callable[[Checkpoint], Checkpoint]) -> bool:
        """Rewrite the stored record with `fn` (a rebase moves its head, a cap grant adds an amend). False when there is none."""
        ck = self.read()
        if ck is None:
            return False
        self.writer().write(fn(ck))
        return True

    def drop(self) -> None:
        self.writer().delete()

    def drop_unless_fenced(self) -> None:
        """The close's last effect: a run whose lease moved on leaves the record to the run that holds the bead."""
        with contextlib.suppress(fence.Fenced):
            self.drop()
