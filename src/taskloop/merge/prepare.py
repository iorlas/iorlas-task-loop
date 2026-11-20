"""Preparation's continuation: complete a retained merge, attach it, then allow ordinary setup/dispatch."""

from collections.abc import Callable
from pathlib import Path

from taskloop.agents.launch import AgentLaunch
from taskloop.attempt_reads import StoreRefused
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptRecord, AttemptResult, Checkouts, SlotFiles, WorkerGone
from taskloop.environment import Launch, Preparation, Renew, SetupFor
from taskloop.evidence_files import EvidenceFiles
from taskloop.merge.models import PREFIX, Completed, InProgress, Reason, Terminal, Unavailable, Waiting, Work
from taskloop.merge.resolve import Resolution, Run
from taskloop.merge.start import Merge
from taskloop.merge.store import MergeStore
from taskloop.prepare import Prepared, base, task_branch
from taskloop.slot_state import SlotState, observe_slot


class SourcePreparation:
    def __init__(self, store: AttemptStore, checkouts: Checkouts, remotes: Checkouts, files: SlotFiles,
                 clock: Callable[[], float], environment: Preparation, agent: AgentLaunch,
                 evidence: EvidenceFiles, run: Run, gone: WorkerGone) -> None:
        self.attempts, self.checkouts, self.remotes, self.files = store, checkouts, remotes, files
        self.clock, self.environment, self.agent, self.evidence, self.run, self.gone = clock, environment, agent, evidence, run, gone
        self.store = MergeStore(store.connect, store.begin)

    def prepare(self, record: AttemptRecord, renew: Renew | None, credentials: Launch,
                probe: tuple[str, ...] | None) -> Prepared | AttemptResult:
        if record.start is not None and record.admission.source_checks_id is None:
            return base(self.checkouts, self.files, record, self.clock)  # repeat leftovers are never merged over
        admission = record.admission
        work = self.store.get(admission.key.attempt_id)
        if work is None:
            original = base(self.checkouts, self.files, record, self.clock)
            if isinstance(original, AttemptResult):
                return original
            work = self.store.start(Work(
                attempt_id=admission.key.attempt_id, dispatch_token=admission.key.dispatch_token,
                generation=admission.key.reservation_generation, task_id=admission.task.task_id, repo_id=admission.repo_id,
                root=original.root, slot=Path(admission.slot_path), gitdir=original.gitdir,
                base=self.attempts.slot_base(admission.key), source=original.head, branch=task_branch(admission.task.task_id),
                deadline=admission.deadline, setting=admission.setting,
                input_path=admission.input_ref.path, input_digest=admission.input_ref.digest))
        self._fence(record, work)
        if work.deadline != admission.deadline:
            work = self.store.put(work, work.model_copy(update={"deadline": admission.deadline}))
        resolution = Resolution(self.store, self.agent, self.evidence, self.run, self.gone, self.clock,
                                lambda: self._fence(record, work))

        def setup(target: Work) -> Waiting | None:
            if renew is None:
                return Unavailable(reason=Reason.UNKNOWN, explanation="The merge environment has no claim renewal port.")
            settings = SetupFor(admission.key, target.slot, target.target, None, target.deadline, True)
            prepared = Prepared(target.target or target.source, target.gitdir, target.root)
            stopped = self.environment.prepare_for(settings, prepared, renew, credentials[1],
                                                   probe=None if probe is None else (probe, credentials[1]))
            return None if stopped is None else Unavailable(reason=Reason.UNKNOWN,
                                      explanation=f"The merge environment is waiting: {stopped.status}:{stopped.reason}.")

        result = Merge(self.store, self.checkouts, self.remotes, self.files, self.clock, setup, resolution,
                       lambda: self._fence(record, work)).resume(work)
        if isinstance(result, Completed):
            observed = observe_slot(self.checkouts, self.files, admission.slot_path, admission.repo_id)
            if (not isinstance(observed, SlotState) or observed.dirty or observed.head != result.commit
                    or observed.branch != work.branch):
                return AttemptResult("refused", "branch_moved", explanation="The prepared task branch changed before dispatch.")
            return Prepared(result.commit, work.gitdir, work.root)
        latest = self.store.get(work.attempt_id)
        if latest is not None and latest.explanation != result.explanation:
            self.store.put(latest, latest.model_copy(update={"explanation": result.explanation}))
        status = "pending" if isinstance(result, InProgress) else "refused" if isinstance(result, Terminal) else "unavailable"
        return AttemptResult(status, PREFIX + result.reason, explanation=result.explanation)

    def _fence(self, record: AttemptRecord, work: Work) -> None:
        current = self.attempts.load(record.admission.key)
        if (current is None or current.phase != "admitted" or current.admission != record.admission
                or work.dispatch_token != record.admission.key.dispatch_token
                or work.generation != record.admission.key.reservation_generation
                or work.task_id != record.admission.task.task_id or work.repo_id != record.admission.repo_id
                or work.slot != Path(record.admission.slot_path) or work.setting != record.admission.setting
                or work.base != self.attempts.slot_base(record.admission.key)):
            raise StoreRefused("merge_reservation")
