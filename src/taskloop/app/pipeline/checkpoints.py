"""The checkpoint reader and its one fenced writer."""
import contextlib
import copy
import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from tlkernel import fence
from tlkernel.beadsport import Beads
from tlkernel.checkpoint import Checkpoint, CloseIntent, Notes, RunState, StageProgress
from tlkernel.followups import FollowupOutbox
from tlkernel.gitport import Git
from tlkernel.ids import BeadId
from tlkernel.review import Unfiled

from taskloop.app.pipeline.review_glue import ReviewLists, review_of
from taskloop.app.pipeline.store_ports import CheckpointDoc, CheckpointStores
from taskloop.domain.checks import trim
from taskloop.domain.followups import FollowKey


class CheckpointLook(Protocol):
    @property
    def notes(self) -> Sequence[str]: ...
    @property
    def unjudged(self) -> Mapping[str, str]: ...


class CheckpointLand(Protocol):
    @property
    def gate_log(self) -> Path | None: ...


class CheckpointCheckout(Protocol):
    def branch_now(self) -> str: ...


class CheckpointHost(Protocol):
    leftovers: list[dict[str, str]]
    unfiled: list[Unfiled]
    filed: list[str]
    @property
    def state(self) -> RunState: ...
    @property
    def stores(self) -> CheckpointStores: ...
    @property
    def store(self) -> Beads: ...
    @property
    def claim(self) -> fence.Claim: ...
    @property
    def bead(self) -> BeadId: ...
    @property
    def run_id(self) -> str: ...
    @property
    def checkout(self) -> CheckpointCheckout: ...
    @property
    def task_branch(self) -> str: ...
    @property
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...
    @property
    def land_state(self) -> CheckpointLand: ...
    @property
    def review(self) -> ReviewLists: ...
    @property
    def look(self) -> CheckpointLook: ...
    @property
    def followup_ids(self) -> Mapping[str, str]: ...
    @property
    def dry(self) -> bool: ...


def read_checkpoint(stores: CheckpointStores, bead: str) -> Checkpoint | None:
    """Read the stage cursor before an engine exists, without exposing a checkpoint writer."""
    return stores.checkpoints.of(bead).get()


class Checkpoints:
    """checkpoints/<bead>.json: the one writer. Every method is one read-modify-write of a whole record. `host` is the engine:
    its state, its bead, its run, its git."""

    def __init__(self, host: CheckpointHost, hooks: Sequence[Callable[[str, str], tuple[str, str]]] = ()) -> None:
        self.host = host
        self.hooks = hooks

    @property
    def doc(self) -> CheckpointDoc:
        return self.host.stores.checkpoints.of(self.host.bead)

    def writer(self) -> CheckpointDoc:
        """The record's document for a write: only a run that still holds its bead and slot may write it (Fenced otherwise)."""
        fence.check(self.host.store, self.host.claim)
        return self.doc

    def read(self) -> Checkpoint | None:
        """The stored record, None when there is none. A record of another version or a torn one raises Refused (no backward
        compatibility: nothing is migrated, nothing is read past)."""
        return self.doc.need()

    def save(self, *, step: str = "", stage: int = 0, rounds: int = 0, n: int = 0, feedback: str = "",
             progress: StageProgress | None = None) -> None:
        """Where the run stands. Mid-rebase (a conflict fix) HEAD is detached: the record names the task branch the close goes
        back to. Section hooks choose the cursor before the record is written."""
        host = self.host
        for hook in self.hooks:
            step, feedback = hook(step, feedback)
        state = copy.deepcopy(host.state)
        state.review = review_of(host)
        self.writer().write(
            Checkpoint(
                bead=host.bead,
                run=host.run_id,
                t=time.time(),
                branch=host.checkout.branch_now() or host.task_branch,
                head=host.git.rev_parse(host.wt, "HEAD"),
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
        head = self.host.git.rev_parse(self.host.wt, "HEAD")

        def closed(ck: Checkpoint) -> Checkpoint:
            red = why.startswith("gate red") and not ck.state.pending_land_validation
            done = ck.replace(head=head, closed=True, state=ck.state.replace(review=ck.state.review.replace(filed=list(self.host.filed))))
            return done.replace(
                step="gate-red", gate_tail=trim.trim_log(why, log=str(self.host.land_state.gate_log or ""))) if red else done
        self.amend(closed)

    def applied(self) -> frozenset[str]:
        ck = self.read()
        return frozenset(ck.applied if ck else ())

    def mark_applied(self, key: str) -> None:
        """A close effect ran: its key goes into the record, so a kill after it resumes at the next effect. No record, no key kept."""
        self.amend(lambda ck: ck if key in ck.applied else ck.replace(applied=[*ck.applied, key]))

    def keep_end(self, intent: CloseIntent) -> None:
        """The close's outcome goes into the record before its first effect: a restart finishes the close from it. No record, none kept."""
        with contextlib.suppress(fence.Fenced):
            self.amend(lambda ck: ck if ck.ended is not None and ck.ended.outcome.run == intent.outcome.run else ck.replace(ended=intent))

    def keep_notes(self, notes: Notes) -> None:
        """What FileNotes filed and what bd refused, so the Reflect comment says the same after a restart."""
        with contextlib.suppress(fence.Fenced):
            self.amend(lambda ck: ck.replace(notes=notes))

    def notes(self) -> Notes | None:
        ck = self.read()
        return ck.notes if ck else None

    def keep_filed(self, lost: list[dict[str, str]] | None = None) -> None:
        """The follow-ups filed so far and the ones bd refused (`lost`: kept, none lost): written at once, a kill loses no title."""
        self.host.unfiled += [Unfiled(title=lo["title"], why=lo["why"]) for lo in lost or []]
        self.host.leftovers += [dict(lo) for lo in lost or []]
        self.amend(lambda ck: ck.replace(state=ck.state.replace(review=review_of(self.host), followup_ids=dict(self.host.followup_ids))))
        self.keep_pending()

    def keep_pending(self, origin: str = "close") -> None:
        """Merge the bead's durable outbox with this run's queue before any external filing effect."""
        host = self.host
        if host.dry:
            return
        fence.check(host.store, host.claim)
        doc = host.stores.followups.of(host.bead)
        old = doc.need() or FollowupOutbox()
        queued: dict[str, dict[str, str]] = {}
        for lo in [*old.pending, *host.leftovers]:
            key = str(FollowKey.of(host.bead, lo))
            queued.setdefault(key, dict(lo, key=key, origin=lo.get("origin") or origin))
        host.leftovers = list(queued.values())
        pending = [lo for key, lo in queued.items() if key not in host.filed and key not in host.followup_ids]
        if pending or old.pending:
            doc.write(FollowupOutbox(pending=pending))
        self.amend(lambda ck: ck.replace(state=ck.state.replace(leftovers=copy.deepcopy(host.leftovers),
                                                               followup_ids=dict(host.followup_ids))))

    def keep_look(self) -> None:
        """What the owner-look bead needs goes into the record, so a crash after the land still files it."""
        host = self.host
        self.amend(lambda ck: ck.replace(state=ck.state.replace(
            look_notes=list(host.look.notes), look_unjudged=dict(host.look.unjudged), review=review_of(host))))

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
