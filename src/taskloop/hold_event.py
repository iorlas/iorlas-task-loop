"""Capture a hold's cause before its tracker and release effects; never decode display reasons."""

from taskloop.attempt_reads import AttemptRow, StoreUnavailable
from taskloop.attempt_result import collect
from taskloop.attempt_status import AttemptView
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import Rejected
from taskloop.check_store import CheckStore
from taskloop.command_conclusion import CommandConclusion, encode
from taskloop.evidence_files import EvidenceFiles
from taskloop.hold_facts import captured_stop, explanation, land_cause, merge_cause
from taskloop.land_store import LandStore
from taskloop.step import Step
from taskloop.task_event import EventStep, TaskEvent
from taskloop.task_event_cause import (
    AnswerCause,
    AnswerReason,
    ChecksCause,
    ChecksReason,
    DispositionCause,
    DispositionReason,
    FailedCheck,
    LandCause,
    LandReason,
    Leftovers,
    NotRun,
    ProfileReason,
    RejectionCause,
    RejectionReason,
    RepeatCause,
    RepeatReason,
    RunCause,
    RunReason,
    StuckCause,
    StuckReason,
    TaskEventCause,
)


def event(files: EvidenceFiles, reader: AttemptStore, agent: AttemptRow, view: AttemptView,
          decided: TaskEventCause | None = None) -> TaskEvent:
    """Only called for a new hold; all mandatory context is validated before insertion."""
    try:
        cause = decided if decided is not None else _cause(files, reader, agent, view)
        if isinstance(cause, LandCause) and cause.reason is LandReason.CONFLICT and view.checks is not None:
            cause = land_cause(reader, agent, view.checks.row, cause)
        if isinstance(cause, LandCause):
            cause = _land(files, reader, view, cause)
        return TaskEvent(attempt_id=agent.key.attempt_id, agent_step=Step(agent.step), cause_id=view.attempt_id,
                         step=EventStep(view.step), cause=cause)
    except ValueError as error:
        raise StoreUnavailable("The deciding hold context is missing or inconsistent") from error


def _cause(files: EvidenceFiles, reader: AttemptStore, agent: AttemptRow, view: AttemptView) -> TaskEventCause:
    action = view.hold_action or view.next
    stuck = {"stuck:expired_admitted": StuckReason.EXPIRED_ADMITTED, "stuck:entry_lost": StuckReason.ENTRY_LOST,
             "stuck:uncollected": StuckReason.UNCOLLECTED, "stuck:conflict": StuckReason.CONFLICT,
             "stuck:setup_failed": StuckReason.SETUP_FAILED, "stuck:checks_refused": StuckReason.CHECKS_REFUSED}.get(action)
    execution = view.result.execution or collect(reader, agent.key).execution
    stop = captured_stop(reader, view.attempt_id)
    deadline = agent.deadline if view.checks is None else view.checks.row.deadline
    if stuck is not None:
        return StuckCause(reason=stuck, deadline=deadline,
                          rc=execution.facts.rc if execution is not None and stuck is StuckReason.ENTRY_LOST else None,
                          stop=stop if stuck is StuckReason.ENTRY_LOST else None)
    if action == "repeats_exhausted":
        left = Leftovers(reason=RepeatReason(view.leftovers[0]), paths=view.leftovers[1:]) if view.leftovers else None
        return RepeatCause(leftovers=left)
    if view.checks is not None:
        return _checks(files, reader, view)
    merged = merge_cause(reader, agent.key.attempt_id)
    if merged is not None:
        return merged
    return _agent_cause(files, reader, agent, view)


def _agent_cause(files: EvidenceFiles, reader: AttemptStore, agent: AttemptRow, view: AttemptView) -> TaskEventCause:
    execution = view.result.execution or collect(reader, agent.key).execution
    if execution is None:
        raise ValueError("A failed agent decision requires its captured execution")
    told = explanation(files, execution, agent.step, agent.task_id)
    run, answer = execution.facts, execution.answer
    if run.timed_out or run.rc != 0:
        return RunCause(reason=RunReason(run.reason or ("timeout" if run.timed_out else "exit")), explanation=told,
                        deadline=agent.deadline, timed_out=run.timed_out, rc=run.rc,
                        stop=captured_stop(reader, view.attempt_id))
    if answer.kind != "valid":
        return AnswerCause(reason=AnswerReason(answer.kind), failure=answer.failure, explanation=told)
    if isinstance(execution.verdict, Rejected):
        return RejectionCause(reason=RejectionReason(execution.verdict.reason), explanation=told)
    if told is None:
        raise ValueError("A disposition requires the agent's explanation")
    return DispositionCause(reason=DispositionReason(answer.disposition), explanation=told)


def _land(files: EvidenceFiles, reader: AttemptStore, view: AttemptView, cause: LandCause) -> LandCause:
    if cause.reason not in (LandReason.CHECKS_FAILED, LandReason.REMOTE_REJECTED):
        return cause
    candidate = LandStore(reader.connect, reader.begin).latest(view.attempt_id)
    if candidate is None:
        return cause
    checks = tuple(FailedCheck(name=each.name, conclusion=each.conclusion or NotRun.NOT_RUN,
                              log=None if each.conclusion is CommandConclusion.UNDEFINED else
                              str(files.check_path(candidate.key, each.block, each.name)))
                   for each in CheckStore(reader.connect, reader.begin).results(candidate.key)
                   if each.conclusion is not CommandConclusion.PASSED) if cause.reason is LandReason.CHECKS_FAILED else ()
    return LandCause(reason=cause.reason, explanation=cause.explanation, source=candidate.commit,
                     target=candidate.origin, checks=checks)


def _checks(files: EvidenceFiles, reader: AttemptStore, view: AttemptView) -> ChecksCause:
    checks = view.checks
    if checks is None:
        raise ValueError("A checks cause requires its checks view")
    row = checks.row
    results = CheckStore(reader.connect, reader.begin).results(row.key)
    failed = tuple(FailedCheck(name=each.name, conclusion=each.conclusion or NotRun.NOT_RUN,
                              log=None if each.conclusion is CommandConclusion.UNDEFINED else
                              str(files.check_path(row.key, each.block, each.name)))
                   for each in results if each.conclusion is not CommandConclusion.PASSED)
    # `row.reason` is the stored validation verdict. Match structured candidates through their existing codec;
    # check names may themselves contain colons, so splitting that verdict would lose information.
    check = next((each for each in failed if row.reason == f"{each.name}:{each.conclusion!s}"), None)
    missing = next((name for name, _digest in row.required if row.reason == f"{name}:not_run"), None)
    if check is not None or missing is not None:
        return ChecksCause(check=check or FailedCheck(name=missing or "", conclusion=NotRun.NOT_RUN),
                           checks=failed, deadline=row.deadline)
    setup = next((each for each in CommandConclusion if row.reason == f"setup:{encode(each)}"), None)
    profile = next((each for each in ProfileReason if row.reason == f"profile:{each!s}"), None)
    if setup is not None or profile is not None:
        return ChecksCause(setup=setup, profile=profile, checks=failed, deadline=row.deadline)
    return ChecksCause(reason=ChecksReason(row.reason), checks=failed, deadline=row.deadline)
