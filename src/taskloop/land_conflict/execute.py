"""Execute a durably admitted conflict while retaining its reservation and checked task ref."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from git_porcelain import GitUnavailable, Repo

from taskloop.agents.launch import AgentLaunch
from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_types import AttemptKey, Checkouts, FileRef, SlotFiles, WorkerGone
from taskloop.environment import Launch, Preparation, Renew, SetupFor
from taskloop.evidence_files import EvidenceError, EvidenceFiles
from taskloop.land_conflict.cleanup import CleanupSaved
from taskloop.land_conflict.models import Record, SavePhase
from taskloop.land_conflict.preserve import Preservation
from taskloop.land_conflict.release import ReleaseSaved
from taskloop.land_conflict.store import ConflictStore
from taskloop.merge.models import Completed, Phase, Reason, Result, Terminal, Unavailable, Waiting, Work
from taskloop.merge.resolve import Resolution, Run
from taskloop.merge.start import Merge
from taskloop.merge.store import MergeStore
from taskloop.prepare import Prepared
from taskloop.slot_lock import SlotBusy, SlotLockUnavailable, landing
from taskloop.slot_state import SlotState, observe_slot


@dataclass(frozen=True)
class Ports:
    store: ConflictStore
    merges: MergeStore
    repo: Repo
    checkouts: Checkouts
    remotes: Checkouts
    files: SlotFiles
    evidence: EvidenceFiles
    agent: AgentLaunch
    run: Run
    gone: WorkerGone
    clock: Callable[[], float]
    environment: Preparation
    renew: Renew
    credentials: Launch
    probe: tuple[str, ...] | None


def execute(ports: Ports, key: AttemptKey) -> Result:
    """Only the durable admission supplies facts; custody spans all effects and acceptance."""
    try:
        completed = ports.store.completed(key)
        if completed is not None and completed.release is not None:
            return completed.release.result
        record = ports.store.load(key)
        with landing(record.slot_path, key.attempt_id):
            return _execute(ports, record)
    except SlotBusy:
        return Unavailable(reason=Reason.RUNNING, explanation="The reserved merge slot is busy; its work remains reserved.")
    except (SlotLockUnavailable, StoreUnavailable, GitUnavailable, EvidenceError) as error:
        return Unavailable(reason=Reason.UNKNOWN, explanation=f"The retained merge cannot proceed yet: {error}")
    except StoreRefused:
        return Unavailable(reason=Reason.SLOT, explanation="The merge's retained identity or reservation changed; no takeover is allowed.")


def _execute(ports: Ports, record: Record) -> Result:
    def fence() -> None:
        if ports.store.load(record.key) != record or ports.repo.identity().key != record.request.repo_id:
            raise StoreRefused("stale_reservation")

    fence()
    stopped = ports.environment.reconcile_for(record.key)
    if stopped is not None:
        return Unavailable(reason=Reason.UNKNOWN, explanation=f"The previous merge setup is unsettled: {stopped.explanation}")
    state = observe_slot(ports.checkouts, ports.files, record.slot_path, record.request.repo_id)
    if not isinstance(state, SlotState) or state.root != ports.repo.identity().root:
        return Unavailable(reason=Reason.SLOT, explanation="The reserved merge slot's repository identity changed.")
    expected = _work(record, state)
    work = ports.merges.get(record.key.attempt_id)
    if work is None:
        if state.dirty or state.branch is not None or state.head != record.base:
            return Unavailable(reason=Reason.SLOT, explanation="The newly reserved merge slot is no longer clean at its admitted base.")
        ports.evidence.read(FileRef(expected.input_path, expected.input_digest))
        fence()
        work = ports.merges.start(expected)
    fields = tuple(name for name in Work.model_fields if name in expected.model_fields_set)
    if any(getattr(work, name) != getattr(expected, name) for name in fields):
        raise StoreRefused("merge_reservation")
    pending = ports.store.saved(record.key)
    if pending is not None and not (pending.accepted and pending.phase is SavePhase.COMPLETE):
        return _saved_result(ports, record, work, fence)

    def setup(target: Work) -> Waiting | None:
        fence()
        settings = SetupFor(record.key, target.slot, target.target, None, target.deadline, True, fence)
        prepared = Prepared(target.target or target.source, target.gitdir, target.root)
        stopped = ports.environment.prepare_for(settings, prepared, ports.renew, ports.credentials[1],
                    probe=None if ports.probe is None else (ports.probe, ports.credentials[1]))
        return None if stopped is None else Unavailable(reason=Reason.UNKNOWN,
                    explanation=f"The merge environment is waiting: {stopped.status}:{stopped.reason}. {stopped.explanation}")

    resolution = Resolution(ports.merges, ports.agent, ports.evidence, ports.run, ports.gone, ports.clock, fence)
    result = Merge(ports.merges, ports.checkouts, ports.remotes, ports.files, ports.clock, setup, resolution, fence).resume(work)
    fence()
    current = ports.merges.get(record.key.attempt_id)
    if current is None:
        raise StoreRefused("merge_missing")
    if isinstance(result, (Completed, Terminal)) and current.phase in (Phase.COMPLETE, Phase.TERMINAL):
        return _saved_result(ports, record, current, fence)
    return result


def _saved_result(ports: Ports, record: Record, work: Work, fence: Callable[[], None]) -> Result:
    def owned() -> None:
        fence()
        if ports.merges.get(record.key.attempt_id) != work:
            raise StoreRefused("merge_changed")

    if work.phase is Phase.COMPLETE:
        result = Completed(commit=work.result or work.source, source=work.source, target=work.target or work.source,
                           explanation=work.explanation)
    elif work.phase is Phase.TERMINAL:
        result = Terminal(reason=work.reason or Reason.INVALID, explanation=work.explanation)
    else:
        return Unavailable(reason=Reason.UNKNOWN, explanation="The pending conflict save has no matching terminal merge record.")
    preservation = Preservation(ports.store, ports.repo, ports.checkouts, ports.files, ports.gone, ports.clock, owned)
    saved = ports.store.saved(record.key)
    if saved is not None and saved.release is not None and isinstance(result, Terminal):
        return ReleaseSaved(preservation)(record, work, saved, result)
    if saved is not None and (saved.cleanup is not None or saved.abort is not None) and isinstance(result, Terminal):
        retained = result
    else:
        retained = preservation(record, work, result)
    saved = ports.store.saved(record.key)
    if isinstance(retained, Terminal) and saved is not None and not saved.accepted and saved.phase is SavePhase.COMPLETE:
        cleaned = CleanupSaved(preservation)(record, work, saved, retained)
        if not isinstance(cleaned, Terminal):
            return cleaned
        saved = ports.store.saved(record.key)
        assert saved is not None
        return ReleaseSaved(preservation)(record, work, saved, cleaned)
    return retained


def _work(record: Record, state: SlotState) -> Work:
    return Work(attempt_id=record.key.attempt_id, dispatch_token=record.key.dispatch_token,
                generation=record.key.reservation_generation, task_id=record.request.task_id, repo_id=record.request.repo_id,
                root=state.root, slot=Path(record.slot_path), gitdir=state.gitdir, base=record.base,
                source=record.request.checked, target=record.request.target, branch=None, deadline=record.request.deadline,
                setting=record.inputs.setting, input_path=record.inputs.input_ref.path, input_digest=record.inputs.input_ref.digest)
