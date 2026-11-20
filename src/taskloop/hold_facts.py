"""What a hold's comment states, read when the hold writes it (tl-8bh9.14.9 sections 6 and 12): the abandon's outcome
(`outcome`: the claim returned, kept by a refusal only the person clears, or a transient refusal the next round retries),
and the facts of the hold and its cause (`facts`). Reads only: the stored rows, the slot path, a registered process and
the agent's explanation from its stored valid answer (decoded by the step kind's own decoder, never a second parser).
Agent text goes to the person only, through `hold_text`."""

from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from taskloop.agents.api import AgentStop
from taskloop.agents.stop_store import StopStore
from taskloop.answer_read import read as read_answer
from taskloop.attempt_reads import AttemptRow, StoreRefused, StoreUnavailable
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import StoredExecution
from taskloop.check_status import latest
from taskloop.check_store import ChecksRow, CheckStore
from taskloop.evidence_files import EvidenceError, EvidenceFiles
from taskloop.hold_store import HoldRow
from taskloop.hold_text import FailedCheck, HoldFacts, Kept, KeptWord, LabelsWord, Leftovers, Returned
from taskloop.land_conflict.models import AdmissionRefused, Request
from taskloop.land_conflict.store import ConflictStore
from taskloop.merge.models import Phase
from taskloop.merge.store import MergeStore
from taskloop.operations import Failed, ReleasedTask
from taskloop.setup_store import SetupStore
from taskloop.steps import CHECK
from taskloop.task_event_cause import ChecksCause, LandCause, MergeCause, MergeReason, RepeatCause, RunCause, StuckCause


@dataclass(frozen=True)
class Pending:
    """The abandon did not finish and nothing the person must do is known yet (`slot_busy`, `unavailable:*`,
    `worker_unknown`, ...): no comment; the next round tries again. `word` is the refusal's."""

    word: str


def refusal(failed: Failed) -> str:
    """The abandon refusal's word as a round's line shows it: `held:<slot word>` for a slot left as it is, else the
    refusal's own (`waiting:worker_alive`, `unavailable:tracker`, `refused:landing`)."""
    return f"held:{failed.reason}" if failed.kind == "refused" and failed.reason.startswith("slot_") else failed.word


def outcome(reader: AttemptStore, agent: AttemptRow, released: ReleasedTask | Failed) -> Returned | Kept | Pending:
    """`Returned` once the abandon recorded the claim as no longer the factory's; `Kept` for section 12's refusals only the
    person clears, naming the slot or the process; `Pending` otherwise (an `unclaiming` claim too: the unclaim is retried)."""
    if isinstance(released, ReleasedTask):
        claim = released.result.claim
        return Returned(claim) if claim in ("unclaimed", "not_held") else Pending(f"release:{claim}")
    word = next((each for each in get_args(KeptWord.__value__) if each == released.reason), None)
    if word is None:
        return Pending(refusal(released))
    checks = latest(CheckStore(reader.connect, reader.begin), agent.key.attempt_id) if released.checks else None
    held = agent.key if checks is None else checks.key
    slot = reader.slot_path(held.attempt_id) or ""
    if word == "worker_alive" and agent.worker is not None:
        return Kept(word, slot, *agent.worker)
    if word == "setup_running":
        setup = SetupStore(reader.connect, reader.begin).latest(held)
        found = None if setup is None else setup.unsettled
        return Kept(word, slot) if found is None else Kept(word, slot, found.pid, found.pgid)
    if word == "check_running" and checks is not None:
        found = next(
            (
                row.process
                for row in CheckStore(reader.connect, reader.begin).results(checks.key)
                if row.unsettled and row.process is not None
            ),
            None,
        )
        return Kept(word, slot) if found is None else Kept(word, slot, found.pid, found.pgid)
    return Kept(word, slot)


def explanation(files: EvidenceFiles, execution: StoredExecution | None, step: str, task_id: str) -> str | None:
    """The captured broken rule, otherwise the valid answer's explanation through its owning decoder."""
    if execution is not None and execution.answer.failure is not None:
        return execution.answer.failure.describe()
    try:
        answer = read_answer(files, execution, step, task_id)
    except EvidenceError:
        return None
    return None if answer is None else answer.explanation


def captured_stop(reader: AttemptStore, cause_id: str) -> AgentStop | None:
    return StopStore(reader.connect, reader.begin).get(cause_id)


def merge_cause(reader: AttemptStore, attempt_id: str) -> MergeCause | None:
    work = MergeStore(reader.connect, reader.begin).get(attempt_id)
    if work is None or work.reason is None:
        return None
    return MergeCause(
        reason=MergeReason(work.reason), explanation=work.explanation, source=work.source, target=work.target, conflicts=work.conflicts
    )


def land_cause(reader: AttemptStore, agent: AttemptRow, checks: ChecksRow, cause: LandCause) -> LandCause:
    """Read only the terminal decision belonging to this exact retained admission, even after its release."""
    request = Request(
        source=agent.key,
        checks=checks.key,
        repo_id=checks.repo_id,
        backlog=checks.backlog,
        task_id=checks.task_id,
        tracker_root=checks.tracker_root,
        checked=checks.commit,
        target=checks.commit,
        deadline=0.0,
    )
    try:
        record = ConflictStore(reader.connect, reader.begin).find(request)
    except (AdmissionRefused, ValueError) as error:
        raise StoreUnavailable("The retained conflict admission cannot be verified") from error
    if record is None:
        return cause
    work = MergeStore(reader.connect, reader.begin).get(record.key.attempt_id)
    if work is None:
        return cause
    if (
        (work.attempt_id, work.dispatch_token, work.generation)
        != (record.key.attempt_id, record.key.dispatch_token, record.key.reservation_generation)
        or (work.task_id, work.repo_id, work.source, work.target, work.deadline, work.branch)
        != (request.task_id, request.repo_id, request.checked, record.request.target, record.request.deadline, None)
        or (work.base, work.slot, work.setting, work.input_path, work.input_digest)
        != (record.base, Path(record.slot_path), record.inputs.setting, record.inputs.input_ref.path, record.inputs.input_ref.digest)
        or work.phase is not Phase.TERMINAL
        or not work.explanation.strip()
    ):
        raise StoreUnavailable("The retained terminal conflict decision cannot be verified")
    return LandCause(reason=cause.reason, explanation=work.explanation, source=work.source, target=work.target)


def facts(files: EvidenceFiles, reader: AttemptStore, row: HoldRow, labels: LabelsWord, agent: AttemptRow) -> HoldFacts:
    """Render the recorded cause. Live evidence resolves locations, never replaces the snapshot's context."""
    published = None if agent.published is None else agent.published.commit
    head = (agent.task_id, row.label, labels, row.reason)
    cause = row.event.cause
    failed = (
        tuple(FailedCheck(each.name, str(each.conclusion), each.log or "") for each in cause.checks)
        if isinstance(cause, (ChecksCause, LandCause))
        else ()
    )
    left = (
        Leftovers(str(cause.leftovers.reason), cause.leftovers.paths)
        if isinstance(cause, RepeatCause) and cause.leftovers is not None
        else None
    )
    deadline = cause.deadline if isinstance(cause, (ChecksCause, RunCause, StuckCause)) else None
    stop = cause.stop if isinstance(cause, (RunCause, StuckCause)) else None
    rc = cause.rc if isinstance(cause, (RunCause, StuckCause)) else None
    if row.cause_id != row.attempt_id:
        store = CheckStore(reader.connect, reader.begin)
        checks = next((each for each in store.of_attempt(row.attempt_id) if each.key.attempt_id == row.cause_id), None)
        if checks is None:
            raise StoreRefused("changed")
        return HoldFacts(
            *head,
            CHECK,
            checks.number,
            row.cause_id,
            row.held_at,
            published,
            agent.end_commit,
            cause.explanation,
            failed,
            left,
            str(files.root / files.directory(checks.key)),
            files.last_entry(checks.key),
            deadline,
            stop=stop,
            rc=rc,
        )
    if agent.key.attempt_id != row.cause_id:
        raise StoreRefused("changed")
    return HoldFacts(
        *head,
        agent.step,
        agent.number,
        agent.key.attempt_id,
        row.held_at,
        published,
        agent.end_commit,
        cause.explanation,
        failed,
        left,
        str(files.root / files.directory(agent.key)),
        files.last_entry(agent.key),
        deadline,
        stop=stop,
        rc=rc,
    )
