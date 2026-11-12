"""The dashboard's task detail: the tracker's task, its comments and every attempt of the task in the order it happened
(agent attempts, the checks attempts that follow an implement attempt, the land), each with how it ended, the prompt it
was given and the outputs of its failed checks. Display only; the agent's own live lines do not exist yet, so a feed holds
only what the stores record (the attempt's start and each check's result)."""

from dataclasses import dataclass

from taskloop.attempt_reads import AttemptRow, StoreUnavailable
from taskloop.attempt_result import collect, succeeded
from taskloop.attempt_status import StatusPorts, agent_attempt, current_view, with_hold
from taskloop.check_store import ChecksRow, CheckStore, ResultRow
from taskloop.dash_board import card_of
from taskloop.dash_model import Answer, AttemptDetail, Card, CheckLine, DashTracker, FeedEvent, Fields, Outcome, State, TaskDetail, iso
from taskloop.evidence_files import EvidenceFiles
from taskloop.hold_store import HoldStore
from taskloop.operations import Failed

NO_FIELDS = Fields("none", (), None, None, "", "", (), "", "", "", "")


@dataclass(frozen=True)
class TaskPorts:
    reads: StatusPorts
    files: EvidenceFiles
    tracker: DashTracker


def _agent(ports: TaskPorts, row: AttemptRow, step_number: int) -> AttemptDetail:
    result = collect(ports.reads.store, row.key)
    state: State = "running" if result.status != "collected" and row.held else "succeeded" if succeeded(result) else "failed"
    started = ports.files.started_at(row.key)
    ended = None if state == "running" or row.release is None else row.release.released_at
    text = ports.files.text(row.key, "answer.txt")
    disposition = None if result.execution is None else result.execution.answer.disposition
    answer = Answer(disposition or "none", text) if text is not None else None
    after = "repeat" if row.previous_attempt_id is not None else "restart_at_plan" if row.step == "plan" and row.seq > 1 else None
    reason = row.repeat_reason if after == "repeat" else "restarted at plan" if after else None
    summary = result.reason or result.status
    feed = () if started is None else (FeedEvent("step", iso(started) or "", step=row.step, attempt=row.number),)
    return AttemptDetail(row.step, step_number, state, iso(started), iso(ended), summary, after, reason,
                         ports.files.text(row.key, "input.txt"), Outcome(summary, answer, (), None), feed)


def _check_line(ports: TaskPorts, row: ChecksRow, result: ResultRow) -> CheckLine:
    passed = result.conclusion == "passed"
    took = 0 if result.ended_at is None else int((result.ended_at - result.started_at) * 1000)
    output = None if passed else ports.files.check_tail(row.key, result.block, result.name)
    return CheckLine(result.name, passed, took, output)


def _checks(ports: TaskPorts, store: CheckStore, row: ChecksRow, earlier: str | None) -> AttemptDetail:
    results = store.results(row.key)
    lines = tuple(_check_line(ports, row, each) for each in results)
    state: State = "running" if row.phase == "admitted" else "succeeded" if row.conclusion == "passed" else "failed"
    started = min((each.started_at for each in results), default=None)
    summary = row.reason or row.conclusion or ("running" if state == "running" else row.phase)
    feed = tuple(FeedEvent("check", iso(each.ended_at or each.started_at) or "", name=each.name, passed=each.conclusion == "passed",
                           duration_ms=line.duration_ms) for each, line in zip(results, lines, strict=True) if each.conclusion is not None)
    after = "repeat" if earlier is not None else None
    return AttemptDetail("checks", row.number, state, iso(started), iso(row.concluded_at), summary, after, earlier, None,
                         Outcome(summary, None, lines, None), feed)


def history(ports: TaskPorts, rows: tuple[AttemptRow, ...]) -> tuple[AttemptDetail, ...]:
    """Oldest first: each agent attempt (numbered within its step), then the checks attempts after an implement attempt."""
    found: list[AttemptDetail] = []
    store = CheckStore(ports.reads.store.connect, ports.reads.store.begin)
    for row in reversed(rows):
        found.append(_agent(ports, row, row.number))
        if row.step != "implement":
            continue
        earlier = None
        for checks in store.of_attempt(row.key.attempt_id):
            detail = _checks(ports, store, checks, earlier)
            found.append(detail)
            earlier = detail.summary
    return tuple(found)


def build_task(ports: TaskPorts, backlog: str, task_id: str) -> TaskDetail | Failed | None:
    """None: neither factory.db nor the tracker knows the task. StoreUnavailable becomes a Failed."""
    try:
        rows = ports.reads.store.attempts(backlog, task_id)
        view = current_view(ports.reads, backlog, task_id)
        if view is not None:
            holds = HoldStore(ports.reads.store.connect, ports.reads.store.begin).of_attempts((agent_attempt(view),))
            view = with_hold(view, holds.get(agent_attempt(view)))
        attempts = history(ports, rows)
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    found = ports.tracker.fields(task_id)
    if view is None and found is None:
        return None
    title = ports.tracker.titles((task_id,)).get(task_id, task_id)
    waiting = Card(task_id, title, "waiting", 0, None, None, None, None, None)
    card = waiting if view is None else card_of(view, rows[0], title, ports.files, ports.reads.clock())
    fields, comments = found if found is not None else (NO_FIELDS, ())
    return TaskDetail(card, fields, comments, attempts)
