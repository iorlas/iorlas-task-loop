"""The run state and its one writer.

`carries_state` gives the engine every `RunState` field as an attribute that reads and writes `engine.state` (adding a field
is one edit, in contracts/checkpoint.py). `Checkpoints` is the only code that writes checkpoints/<bead>.json: save at a
node, close at the end, keep the follow-ups, follow a rebase, drop.
"""

import contextlib
import copy
import sqlite3
import time
from collections.abc import Callable
from typing import Any

from tlkernel import fence, wire
from tlkernel.checkpoint import (
    BriefSnap,
    Checkpoint,
    EndRec,
    Handoff,
    Notes,
    PlanStep,
    RunState,
    StageProgress,
    WriterSession,
)
from tlkernel.followups import FollowupOutbox
from tlkernel.plancheck import PlanData
from tlkernel.review import Unfiled

from taskloop.app.look.state import LOOK_FIELDS
from taskloop.app.run.review_glue import review_of
from taskloop.domain.checks import trim
from taskloop.domain.followups import FollowKey
from taskloop.stores.api import AmendDoc
from taskloop.stores.bundle import Stores

NOT_ATTRS = ("review",)  # the one field of another lane's type: reached as `engine.state.review` only


def read_checkpoint(stores: Stores, bead: str) -> Checkpoint | None:
    """Read the stage cursor before an engine exists, without exposing a checkpoint writer."""
    return stores.checkpoints.of(bead).get()


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
    render_stale: bool
    handoff: Handoff
    stage_tree: str
    pending_land_validation: str
    leftovers: list[dict[str, str]]
    followup_ids: dict[str, str]


def state_names() -> tuple[str, ...]:
    return tuple(name for name in wire.names(RunState) if name not in NOT_ATTRS)


def attr_names() -> tuple[str, ...]:
    """The RunState fields that are engine attributes: all but the look stage's, which it holds as `engine.look`."""
    return tuple(name for name in state_names() if name not in LOOK_FIELDS)


def carries_state[T](cls: type[T]) -> type[T]:
    for name in attr_names():
        setattr(cls, name, StateField(name))
    return cls


class Checkpoints:
    """checkpoints/<bead>.json: the one writer. Every method is one read-modify-write of a whole record. `host` is the engine:
    its state, its bead, its run, its git."""

    def __init__(self, host: Any) -> None:
        self.e = host

    @property
    def doc(self) -> AmendDoc[Checkpoint]:
        return self.e.stores.checkpoints.of(self.e.bead)

    def writer(self) -> AmendDoc[Checkpoint]:
        """The record's document for a write: only a run that still holds its bead and slot may write it (Fenced otherwise)."""
        fence.check(self.e.store, self.e.claim)
        return self.doc

    def read(self) -> Checkpoint | None:
        """The stored record, None when there is none. A record of another version or a torn one raises Refused (no backward
        compatibility: nothing is migrated, nothing is read past)."""
        return self.doc.need()

    def save(self, *, step: str = "", stage: int = 0, rounds: int = 0, n: int = 0, feedback: str = "",
             progress: StageProgress | None = None) -> None:
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
                run=e.run_id,
                t=time.time(),
                branch=e.checkout.branch_now() or e.task_branch,
                head=e.git.rev_parse(e.wt, "HEAD"),
                step=step,
                stage=stage,
                rounds=rounds,
                n=n,
                feedback=feedback,
                state=state,
                progress=progress,
            )
        )

    def close(self, why: str = "") -> None:
        """The close step committed everything: the record's head is now what the next run should find. A red gate at land is no
        stop: the next run re-plans with the gate's output, or it would rerun the same red gate."""
        head = self.e.git.rev_parse(self.e.wt, "HEAD")

        def closed(ck: Checkpoint) -> Checkpoint:
            red = why.startswith("gate red") and not ck.state.pending_land_validation
            done = ck.replace(head=head, closed=True, state=ck.state.replace(review=ck.state.review.replace(filed=list(self.e.filed))))
            return done.replace(step="gate-red", gate_tail=trim.trim_log(why, log=str(self.e.land_state.gate_log or ""))) if red else done
        self.amend(closed)

    def applied(self) -> frozenset[str]:
        ck = self.read()
        return frozenset(ck.applied if ck else ())

    def mark_applied(self, key: str) -> None:
        """A close effect ran: its key goes into the record, so a kill after it resumes at the next effect. No record, no key kept."""
        self.amend(lambda ck: ck if key in ck.applied else ck.replace(applied=[*ck.applied, key]))

    def keep_end(self, end: EndRec) -> None:
        """The close's outcome goes into the record before its first effect: a restart finishes the close from it. No record, none kept."""
        with contextlib.suppress(fence.Fenced):
            self.amend(lambda ck: ck if ck.ended is not None and ck.ended.run == end.run else ck.replace(ended=end))

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
        self.e.leftovers += [dict(lo) for lo in lost or []]
        self.amend(lambda ck: ck.replace(state=ck.state.replace(review=review_of(self.e), followup_ids=dict(self.e.followup_ids))))
        self.keep_pending()

    def keep_pending(self, origin: str = "close") -> None:
        """Merge the bead's durable outbox with this run's queue before any external filing effect."""
        e = self.e
        if e.dry:
            return
        fence.check(e.store, e.claim)
        doc = e.stores.followups.of(e.bead)
        old = doc.need() or FollowupOutbox()
        queued: dict[str, dict[str, str]] = {}
        for lo in [*old.pending, *e.leftovers]:
            key = str(FollowKey.of(e.bead, lo))
            queued.setdefault(key, dict(lo, key=key, origin=lo.get("origin") or origin))
        e.leftovers = list(queued.values())
        pending = [lo for key, lo in queued.items() if key not in e.filed and key not in e.followup_ids]
        if pending or old.pending:
            doc.write(FollowupOutbox(pending=pending))
        self.amend(lambda ck: ck.replace(state=ck.state.replace(leftovers=copy.deepcopy(e.leftovers),
                                                               followup_ids=dict(e.followup_ids))))

    def keep_look(self) -> None:
        """What the owner-look bead needs goes into the record, so a crash after the land still files it."""
        e = self.e
        self.amend(lambda ck: ck.replace(state=ck.state.replace(
            look_notes=list(e.look.notes), look_unjudged=dict(e.look.unjudged), review=review_of(e))))

    def amend(self, fn: Callable[[Checkpoint], Checkpoint]) -> bool:
        """Rewrite the stored record with `fn` (a rebase moves its head, a cap grant adds an amend). False when there is none. The
        write is checked against the revision `fn` saw: another writer's change in between makes `fn` run again on the newer record."""
        return self.writer().modify(fn)

    def amend_with(self, fn: Callable[[Checkpoint], Checkpoint], also: Callable[[sqlite3.Connection | None], None]) -> bool:
        """`amend`, and `also(con)` in the same transaction: both land or neither (a record that is not there: `also` alone)."""
        return self.writer().modify_with(fn, also)

    def drop(self) -> None:
        self.writer().delete()

    def drop_unless_fenced(self) -> None:
        """The close's last effect: a run whose lease moved on leaves the record to the run that holds the bead."""
        with contextlib.suppress(fence.Fenced):
            self.drop()
