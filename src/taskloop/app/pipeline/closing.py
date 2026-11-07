"""The close: the one step every run ends with. The branch is saved (a wip commit, the checkpoint marked closed), the outcome is decided by
POLICY, the run is written to the log and the trace, follow-ups are filed, and the bead is closed, blocked or left open. Each of those is
a step of its own with its own small host (closing_*.py); the Closer is the order they run in."""
import signal
import threading
import time
from dataclasses import dataclass, replace
from typing import Protocol, assert_never

from tlkernel import askspecs
from tlkernel import runoutcome as oc
from tlkernel.checkpoint import Checkpoint, Notes
from tlkernel.enums import Outcome
from tlkernel.kinds import ASKS, PAUSES, Kind
from tlkernel.parks import Park
from tlkernel.run import RunFinish

from taskloop.app.pipeline import ended as stored_end
from taskloop.app.pipeline.adapter_ports import PeekBead
from taskloop.app.pipeline.closing_host import CloseHost
from taskloop.app.pipeline.outcomes import DONE
from taskloop.app.pipeline.ports import AskRules, ParkBook
from taskloop.domain import effects
from taskloop.domain.interpret import CheckpointLedger, interpret
from taskloop.domain.lanes import pauses


class DecideStep(Protocol):
    def run(self, o: oc.RunOutcome) -> Kind: ...


class BranchStep(Protocol):
    def run(self, outcome: Outcome, why: str) -> None: ...


class SlotStep(Protocol):
    def run(self, branch: str, outcome: Outcome) -> None: ...


class RecordStep(Protocol):
    def run(self, record: RunFinish, stats: str) -> None: ...


class NotesStep(Protocol):
    def run(self, outcome: Outcome) -> Notes: ...


class ReflectStep(Protocol):
    def comment(self, outcome: Outcome, why: str, stats: str, noted: Notes | None) -> None: ...


class SettleStep(Protocol):
    def run(self, done: oc.RunOutcome, stats: str) -> None: ...


@dataclass(frozen=True)
class CloseParts:
    """The steps the Closer composes; each is built over its own small host ."""

    decide: DecideStep
    branch: BranchStep
    slot: SlotStep
    record: RecordStep
    notes: NotesStep
    reflect: ReflectStep
    settle: SettleStep


class Closer:
    """The close of a run: the order of its steps."""

    def __init__(self, context: CloseHost, parts: CloseParts, rules: AskRules, parks: ParkBook, peek: PeekBead) -> None:
        self.host = context
        self.peek = peek
        self.rules = rules
        self.parks = parks
        self.decide = parts.decide
        self.branch = parts.branch
        self.slot = parts.slot
        self.recording = parts.record
        self.notes = parts.notes
        self.reflecting = parts.reflect
        self.settling = parts.settle
        self.noted: Notes | None = None  # FileNotes' result, for a run with no checkpoint to keep it in

    def close(self, ended: oc.RunOutcome) -> None:
        e = self.host
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
        e = self.host
        why = ended.detail or ("stopped before a reason was recorded" if ended.word is Outcome.FAILED else "")
        bad = self.rules.problems(ended.spec) if ended.spec else []
        if bad:  # an ask that is no ask an owner can answer is the engine's own fault; no prose question takes its place
            first = why.splitlines()[0][:200] if why else ""
            why = f"failed: ask_lint: {'; '.join(bad)[:300]} ({first})"
            ended = oc.make(Kind.FAULT_ENGINE, why)
        kind = self.decide.run(oc.make(ended.kind, why, spec=ended.spec))
        spec = ended.spec
        if e.disp and e.disp.escalated and spec is None:
            spec = askspecs.repeated_fault(oc.KNOBS["fault_retries"], why.splitlines()[0][:200])
        done = oc.make(kind, why, sha=ended.sha, spec=spec if kind in ASKS else None)  # the final outcome: its word is the trace's
        self.finish(done, self.stats_line())

    def resume(self, ck: Checkpoint) -> None:
        """The close of a run that died: its outcome and decision come from the checkpoint (POLICY is not asked
        again), and the effects whose keys are not there run, under the dead run's id."""
        e = self.host
        assert ck.ended is not None
        intent = ck.ended
        pause = intent.pause
        e.pause_reason, e.pause_producer, e.pause_permanence = pause.reason, pause.producer, pause.permanence
        e.retry_after = pause.retry_after
        e.crash_fingerprint, e.crash_site = pause.crash_fingerprint, pause.crash_site
        e.plan_summary, e.asked = intent.plan_summary, intent.asked
        done, e.disp, e.fp = stored_end.loaded(intent.outcome)
        e.kind = done.kind
        e.warn(f"finishing the close of {intent.outcome.run}, which died inside it: {done.word}")
        self.finish(done, intent.stats)

    def stats_line(self) -> str:
        """The run's stats, built once before the close is kept."""
        e = self.host
        counts = "; ".join(f"{k}={v}" for k, v in e.stats.items())
        stats = f"cost=${e.cost:.2f}; minutes={int((time.time() - e.t0) / 60)}; {counts}"
        return stats

    def finish(self, done: oc.RunOutcome, stats: str) -> None:
        e = self.host
        self.pause(done)
        if done.kind is Kind.ENGINE_CRASH:
            done = oc.make(done.kind, e.why)
        if not e.dry:
            done = e.records.finish(done, stats, self.recording.run)
        branch = e.git.branch(e.wt)
        plan = effects.plan_close(done, dry=e.dry, branch=branch, slot_gen=e.claim.slot_gen)
        interpret(e.bead, e.run_id, plan, CheckpointLedger(e.checkpoints), lambda eff: self.apply(eff, done, stats))

    def pause(self, done: oc.RunOutcome) -> None:
        """Persist pause wakes; the close plan files an empty plan's owner ask."""
        e = self.host
        if e.dry or done.finished or (done.kind is not Kind.NOOP and done.kind not in PAUSES):
            return
        bead = self.peek(e.store, e.bead)
        if bead is None:
            return
        rec = self.parks.paused( bead, done.kind, e.run_id, e.clock.now(), reason=e.pause_reason,
                           not_before=e.retry_after, fingerprint=e.crash_fingerprint if done.kind is Kind.ENGINE_CRASH else "",
                           producer=e.pause_producer, permanence=e.pause_permanence)
        e.retry_after = rec.retry_at
        e.pause_reason = rec.reason
        self.ask_pause(rec, done)

    def ask_pause(self, rec: Park, done: oc.RunOutcome) -> None:
        """Ask for owner help or exhausted retries; machine fixes stay pauses, and task asks keep their close effect."""
        e = self.host
        if done.kind is Kind.ENGINE_CRASH:
            e.fp = rec.fingerprint
            if rec.permanence == "needs_owner" and not e.asked:
                count = pauses.history(rec)[pauses.attempt_key(rec.reason, e.pause_producer)]
                e.why = f"engine crashed {count} times at {e.crash_site}: {done.detail}; traceback in {e.run_id}"
                spec = replace(askspecs.repeated_fault(count, " ".join(e.why.splitlines())),
                               decision="The engine keeps crashing; how should it go on?")
                e.asked = bool(e.ask_flow.raise_ask(spec, e.why, Kind.ASK_STUCK))
        elif (rec.permanence == "needs_owner" and rec.reason not in pauses.MACHINE_FIXED
              and done.kind is not Kind.NOOP and not e.asked):
            count = pauses.history(rec)[pauses.attempt_key(rec.reason, e.pause_producer)]
            why = f"{rec.reason} paused {count} times: {done.detail}"
            spec = replace(askspecs.repeated_fault(count, " ".join(why.splitlines())),
                           decision="The run is paused and needs your help; how should it go on?")
            e.asked = bool(e.ask_flow.raise_ask(spec, why, Kind.ASK_STUCK))

    def apply(self, eff: effects.CloseEffect, done: oc.RunOutcome, stats: str) -> None:
        """One effect of the close plan, done. The match is closed: a new effect is one more case here."""
        e = self.host
        outcome, why = done.word, done.detail
        match eff:
            case effects.SaveBranch():
                self.branch.run(outcome, why)
            case effects.RecordRun():
                pass  # finish_run already projected the winning answer; retain the effect key for checkpoint resumes
            case effects.NoteDry():
                e.log.note(f"dry run: bead left as it was. {stats}")
            case effects.NoteWait():  # asked already: the bead stays as the ask left it
                e.log.note(why)
            case effects.RaiseAsk():
                spec = askspecs.plan_noop(str(e.bead), e.plan_summary) if done.kind is Kind.NOOP else done.spec
                e.asked = bool(spec and outcome not in DONE and e.ask_flow.raise_ask(spec, why, done.kind))
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
