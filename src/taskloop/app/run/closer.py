"""The close: the one step every run ends with. The branch is saved (a wip commit, the checkpoint marked closed), the outcome is decided by
POLICY, the run is written to the log and the trace, follow-ups are filed, and the bead is closed, blocked or left open. Each of those is
a step of its own with its own small host (closer_*.py); the Closer is the order they run in."""
import signal
import threading
import time
from dataclasses import dataclass
from typing import Protocol, assert_never

from taskloop.app.asks import raiser
from taskloop.app.run import ended as stored_end
from taskloop.app.run.closer_branch import DONE, ReleaseSlot, SaveBranch
from taskloop.app.run.closer_decide import Decide
from taskloop.app.run.closer_host import CloseHost, CloserHost
from taskloop.app.run.closer_notes import FileNotes, Reflect
from taskloop.app.run.closer_record import RecordRun
from taskloop.app.run.closer_settle import Settle
from taskloop.contracts.checkpoint import Checkpoint, Notes
from taskloop.contracts.enums import Outcome
from taskloop.contracts.kinds import ASKS, Kind
from taskloop.domain import effects
from taskloop.domain import outcome as oc
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.interpret import CheckpointLedger, interpret


class DecideStep(Protocol):
    def run(self, o: oc.RunOutcome) -> Kind: ...


class BranchStep(Protocol):
    def run(self, outcome: Outcome, why: str) -> None: ...


class SlotStep(Protocol):
    def run(self, branch: str, outcome: Outcome) -> None: ...


class RecordStep(Protocol):
    def run(self, done: oc.RunOutcome, stats: str) -> None: ...


class NotesStep(Protocol):
    def run(self, outcome: Outcome) -> Notes: ...


class ReflectStep(Protocol):
    def comment(self, outcome: Outcome, why: str, stats: str, noted: Notes | None) -> None: ...


class SettleStep(Protocol):
    def run(self, done: oc.RunOutcome, stats: str) -> None: ...


@dataclass(frozen=True)
class CloseParts:
    """The steps the Closer composes; each is built over its own small host (see Closer.of)."""

    decide: DecideStep
    branch: BranchStep
    slot: SlotStep
    record: RecordStep
    notes: NotesStep
    reflect: ReflectStep
    settle: SettleStep


class Closer:
    """The close of a run: the order of its steps."""

    def __init__(self, host: CloseHost, parts: CloseParts) -> None:
        self.e = host
        self.decide = parts.decide
        self.branch = parts.branch
        self.slot = parts.slot
        self.recording = parts.record
        self.notes = parts.notes
        self.reflecting = parts.reflect
        self.settling = parts.settle
        self.noted: Notes | None = None  # FileNotes' result, for a run with no checkpoint to keep it in

    def close(self, ended: oc.RunOutcome) -> None:
        e = self.e
        e.halt.clear()  # the close-out runs commands: the stop flag has done its work
        old = None
        if hasattr(signal, "SIGTERM") and threading.current_thread() is threading.main_thread():
            old = signal.signal(signal.SIGTERM, signal.SIG_IGN)  # a second stop must not break the close-out
        try:
            if e.dead is not None:  # a run died inside its close: finish that close, from the outcome it kept
                self.resume(e.dead)
            else:
                self.run(ended)
        finally:  # what the process starts after this (a notify command, the next test) must stay stoppable
            if old is not None:
                signal.signal(signal.SIGTERM, old)

    def run(self, ended: oc.RunOutcome) -> None:
        e = self.e
        why = ended.detail or ("stopped before a reason was recorded" if ended.word is Outcome.FAILED else "")
        bad = raiser.problems(ended.spec) if ended.spec else []
        if bad:  # an ask that is no ask an owner can answer is the engine's own fault; no prose question takes its place
            first = why.splitlines()[0][:200] if why else ""
            why = f"failed: ask_lint: {'; '.join(bad)[:300]} ({first})"
            ended = oc.make(Kind.FAULT_ENGINE, why)
        kind = self.decide.run(oc.make(ended.kind, why, spec=ended.spec))
        spec = ended.spec
        if e.disp and e.disp.escalated and spec is None:
            spec = askspecs.repeated_fault(oc.KNOBS["fault_retries"], why.splitlines()[0][:200])
        done = oc.make(kind, why, sha=ended.sha, spec=spec if kind in ASKS else None)  # the final outcome: its word is the trace's
        if not e.dry:
            # before the first effect: a restart rebuilds the plan from it
            e.checkpoints.keep_end(stored_end.stored(e.log_path.stem, done, e.disp, e.fp, e.leftovers))
        self.finish(done)

    def resume(self, ck: Checkpoint) -> None:
        """The close of a run that died: its outcome and decision come from the checkpoint (POLICY and the storm check are not asked
        again), and the effects whose keys are not there run, under the dead run's id."""
        e = self.e
        assert ck.ended is not None
        done, e.disp, e.fp = stored_end.loaded(ck.ended)
        e.kind = done.kind
        e.warn(f"finishing the close of {ck.ended.run}, which died inside it: {done.word}")
        self.finish(done)

    def finish(self, done: oc.RunOutcome) -> None:
        e = self.e
        counts = "; ".join(f"{k}={v}" for k, v in e.stats.items())
        stats = f"cost=${e.cost:.2f}; minutes={int((time.time() - e.t0) / 60)}; {counts}"
        branch = e.git("symbolic-ref", "--short", "-q", "HEAD")
        plan = effects.plan_close(done, dry=e.dry, branch=branch, slot_gen=e.claim.slot_gen)
        interpret(e.bead, e.log_path.stem, plan, CheckpointLedger(e.checkpoints), lambda eff: self.apply(eff, done, stats))

    def apply(self, eff: effects.CloseEffect, done: oc.RunOutcome, stats: str) -> None:
        """One effect of the close plan, done. The match is closed: a new effect is one more case here."""
        e = self.e
        outcome, why = done.word, done.detail
        match eff:
            case effects.SaveBranch():
                self.branch.run(outcome, why)
            case effects.RecordRun():
                self.recording.run(done, stats)
            case effects.NoteDry():
                e.log.note(f"dry run: bead left as it was. {stats}")
            case effects.NoteWait():  # asked already: the bead stays as the ask left it
                e.log.note(why)
            case effects.RaiseAsk():
                e.asked = bool(done.spec and outcome not in DONE and e.ask_flow.raise_ask(done.spec, why, done.kind))
            case effects.FileNotes():
                self.noted = self.notes.run(outcome)
            case effects.Reflect():
                self.reflecting.comment(outcome, why, stats, self.noted)
            case effects.CloseBead() | effects.BlockBead() | effects.LeaveBead():
                self.settling.run(done, stats)
            case effects.ReleaseSlot():
                self.slot.run(eff.branch, outcome)
            case effects.DropCheckpoint():
                e.checkpoints.drop_unless_fenced()
            case _:
                assert_never(eff)


def closer_over(host: CloserHost) -> Closer:
    """The Closer over the engine: each step gets the host typed as that step's own Protocol."""
    return Closer(host, CloseParts(decide=Decide(host), branch=SaveBranch(host), slot=ReleaseSlot(host), record=RecordRun(host),
                                   notes=FileNotes(host), reflect=Reflect(host), settle=Settle(host)))
