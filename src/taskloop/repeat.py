"""Repeat a step whose agent left the slot unsettled: the step's next attempt, admitted by taking over the reservation
the current attempt holds, with the leftovers as feedback in a complete input of its own, launched as a fresh session
exactly as attempt 1 (no resume). Only Git leftovers repeat (`REPEATABLE`), at most ATTEMPTS attempts per step.

No Git or SQL of its own: the verifier, the store reads, the files, the admission, the launcher, the worker observation
and the entry observation are injected. `tl step start` on a captured attempt calls `repeat`; a scheduler would too.
"""

from dataclasses import dataclass, replace
from typing import Protocol

from taskloop.admit import AdmitRefused, Admitted, AdmitUnavailable
from taskloop.admit_chain import RepeatRequest
from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_result import judged
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import (
    ATTEMPTS,
    REPEATABLE,
    AttemptKey,
    AttemptRecord,
    EntryIdentity,
    NotApplicable,
    Observe,
    Rejected,
    RepeatReason,
    Unsettled,
    Verified,
    VerifyRefused,
    VerifyResult,
    WorkerGone,
)
from taskloop.discussion import RefreshDiscussion, replace_block
from taskloop.evidence_files import EvidenceError, EvidenceFiles
from taskloop.ids import Ids
from taskloop.input_context import InputError
from taskloop.operations import Clock, Failed, Launch, Started, deadline_after, launched, verify_failure
from taskloop.slot_lock import SlotBusy, SlotLockUnavailable
from taskloop.slot_release import ParkHold, entry_stopped, worker_stopped
from taskloop.steps import kind


class Settle(Protocol):
    """The verifier as a repeat uses it: the step's own verify, then the slot's staged paths (None: unknown)."""

    def verify(self, key: AttemptKey) -> VerifyResult: ...

    def staged(self, key: AttemptKey) -> tuple[str, ...] | None: ...


class AdmitRepeat(Protocol):
    def admit_repeat(self, request: RepeatRequest) -> Admitted | AdmitRefused | AdmitUnavailable: ...


def _words(found: Verified | Rejected | NotApplicable) -> str:
    return found.what if isinstance(found, NotApplicable) else judged(found)


@dataclass(frozen=True)
class StepRepeat:
    store: AttemptStore
    verifier: Settle
    files: EvidenceFiles
    admission: AdmitRepeat
    launcher: Launch
    gone: WorkerGone
    observe: Observe
    clock: Clock
    hold: ParkHold  # the slot's lock around the takeover (`slot_lock.repeating`), so a concurrent abandon cannot park under it
    ids: Ids
    discussion: RefreshDiscussion | None = None

    def repeat(self, backlog: str, task_id: str, current: AttemptKey, entry: EntryIdentity | None, minutes: int) -> Started | Failed:
        """For the task's captured current attempt C: the stop proof (C's entry, then its worker and group) before any Git
        read; C's own verify (it may finish a crash or settle); only REPEATABLE leftovers below the cap are repeated."""
        stopped = self._stopped(backlog, task_id, current, entry, minutes)
        if not isinstance(stopped, AttemptRecord):
            return stopped
        found = self._leftovers(backlog, task_id, current, minutes)
        if not isinstance(found, tuple):
            return found
        if stopped.admission.number >= ATTEMPTS:
            return Failed("refused", "repeats_exhausted")
        held = self._index(current)
        if held is not None:
            return held
        text = self._input(current, found[0], stopped)
        if isinstance(text, Failed):
            return text
        request = RepeatRequest(current, text, deadline_after(minutes, self.clock), found[1], found[0].listing)
        admitted = self._takeover(request, stopped.admission.slot_path)
        return self._launch(backlog, task_id, current, admitted, stopped.admission.number + 1, minutes)

    def _leftovers(
        self, backlog: str, task_id: str, current: AttemptKey, minutes: int
    ) -> tuple[Unsettled, RepeatReason] | Started | Failed:
        """C's own verify: a stored or new verdict, or no step to verify, is `already_dispatched` with that result; any
        other unsettled reason or unknown is that failure, never a repeat."""
        found = self.verifier.verify(current)
        if isinstance(found, (Verified, Rejected, NotApplicable)):
            return Started("already_dispatched", backlog, task_id, current.attempt_id, True, result=_words(found))
        if isinstance(found, VerifyRefused) and found.reason == "stale_reservation":
            return self._existing(backlog, task_id, current, minutes)  # another start took the step over after this one's read
        if not isinstance(found, Unsettled):
            return verify_failure(found)
        reason = next((each for each in REPEATABLE if each == found.reason), None)
        return verify_failure(found) if reason is None else (found, reason)

    def _index(self, current: AttemptKey) -> Failed | None:
        """A staged index is never repeated: `record` would commit it as the next attempt's, and its dispatch refuses it
        (`slot_staged`). Refused here, before anything is admitted or written; the owner unstages it."""
        held = self.verifier.staged(current)
        if held is None:
            return Failed("unavailable", "staged")
        return Failed("unsettled", "staged", "\n".join(held)) if held else None

    def _input(self, current: AttemptKey, found: Unsettled, record: AttemptRecord) -> str | Failed:
        """The feedback over attempt 1's input, read through its digest."""
        try:
            steps = self.store.chain(current)  # read after the verify: C's commit, if it made one, is stored now
            task = self.files.read(steps[0].input_ref)
            if self.discussion is not None:
                root = self.store.tracker_root(current)
                if root is None:
                    raise InputError("The attempt's tracker binding is unavailable")
                task = replace_block(task, self.discussion(record.admission.task, root))
        except StoreUnavailable as error:
            return Failed("unavailable", "store", str(error))
        except (EvidenceError, InputError) as error:
            return Failed("refused", "input", str(error))
        unrecorded = steps[-1].effect == "commit" and steps[-1].end_commit is None
        admission = record.admission
        step = kind(admission.step)
        rules = step.rules(admission.task.task_id)
        return step.feedback(found, rules, admission.number, task, self.ids.token(8), unrecorded=unrecorded)

    def _stopped(
        self, backlog: str, task_id: str, current: AttemptKey, entry: EntryIdentity | None, minutes: int
    ) -> AttemptRecord | Started | Failed:
        """The stop proof (`slot_release`'s one rule): C's registered entry does not run, then C's worker and its process
        group are gone (unknown counts as alive). A running entry is `already_running`."""
        running = entry_stopped(self.observe, None, entry)
        if running is not None:
            found = Started("already_running", backlog, task_id, current.attempt_id, True, entry)
            return found if running.reason == "entry_running" else Failed("unavailable", "observe")
        try:
            record = self.store.load(current)
        except StoreUnavailable as error:
            return Failed("unavailable", "store", str(error))
        except StoreRefused as error:
            stale = error.reason == "stale_reservation"  # another start took the step over after this one's read
            return self._existing(backlog, task_id, current, minutes) if stale else Failed("refused", error.reason)
        if record is None:
            return Failed("refused", "absent")
        alive = worker_stopped(self.gone, record.phase, record.worker)
        return record if alive is None else Failed("unsettled", alive.reason)

    def _takeover(self, request: RepeatRequest, slot_path: str) -> Admitted | AdmitRefused | AdmitUnavailable | Failed:
        """`admit_repeat` under the slot's lock (a release parks only under it); released before the launch, since the
        new attempt's entry takes it."""
        try:
            with self.hold(slot_path, request.previous.attempt_id):
                return self.admission.admit_repeat(request)
        except SlotBusy:
            return Failed("unavailable", "slot_busy")
        except SlotLockUnavailable:
            return Failed("unavailable", "lock")

    def _launch(
        self, backlog: str, task_id: str, current: AttemptKey, admitted: Admitted | AdmitRefused | AdmitUnavailable | Failed,
        number: int, minutes: int,
    ) -> Started | Failed:
        """The same launcher as attempt 1. A concurrent start that took the step over first (`task_attempted`): its
        attempt is launched as existing."""
        if isinstance(admitted, Failed):
            return admitted
        if isinstance(admitted, AdmitUnavailable):
            return Failed("unavailable", admitted.what, admitted.detail)
        if isinstance(admitted, AdmitRefused):
            refused = Failed("refused", admitted.reason, admitted.detail)
            return self._existing(backlog, task_id, current, minutes) if admitted.reason == "task_attempted" else refused
        result = launched(self.launcher.launch(backlog, task_id, minutes), backlog, task_id, admitted.key, existing=False)
        if isinstance(result, Failed):
            return replace(result, admitted=True)
        return replace(result, status="repeated", number=number) if result.status == "started" else result

    def _existing(self, backlog: str, task_id: str, current: AttemptKey, minutes: int) -> Started | Failed:
        """The attempt that took the step over from `current` (another start's), launched as existing."""
        try:
            found = self.store.attempt_of(backlog, task_id)
        except StoreUnavailable as error:
            return Failed("unavailable", "store", str(error))
        if found is None or found[0] == current:
            return Failed("unavailable", "store", "The winning attempt is not readable")
        return launched(self.launcher.launch(backlog, task_id, minutes), backlog, task_id, found[0], existing=True)
