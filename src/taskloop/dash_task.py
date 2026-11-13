"""The dashboard's task detail: the tracker's task, its comments and every attempt of the task in the order it happened
(agent attempts, the checks attempts that follow an implement attempt, the land), each with how it ended, the prompt it
was given and the outputs of its failed checks. Display only. The lines of an agent attempt are its `events.jsonl`, read
behind the evidence files; a checks attempt's are its results."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from difflib import SequenceMatcher

from any_agent.activity import Activity

from taskloop.access import SANDBOX
from taskloop.activity_file import ActivityPage
from taskloop.attempt_reads import AttemptRow, StoreUnavailable
from taskloop.attempt_result import collect, succeeded
from taskloop.attempt_status import StatusPorts, agent_attempt, current_view, with_hold
from taskloop.attempt_types import AttemptResult
from taskloop.check_store import ChecksRow, CheckStore, ResultRow
from taskloop.dash_board import admission_of, card_of, tries
from taskloop.dash_model import (
    Answer,
    AttemptBody,
    AttemptDetail,
    Card,
    CheckLine,
    DashTracker,
    FeedEvent,
    FeedPage,
    Outcome,
    Run,
    State,
    TaskDetail,
    TrackerDetail,
    Verification,
    iso,
)
from taskloop.dash_verify import STEP as VERIFICATION
from taskloop.dash_verify import applies, verification
from taskloop.evidence_files import EvidenceFiles
from taskloop.harness_choice import HARNESS_WORDS, PROVIDER_WORDS
from taskloop.hold_store import HoldStore
from taskloop.operations import Failed
from taskloop.profile import LandMode


@dataclass(frozen=True)
class TaskPorts:
    reads: StatusPorts
    files: EvidenceFiles
    tracker: DashTracker
    mode: Callable[[], LandMode | None] = lambda: None  # the profile's `land` (`dash_board.BoardPorts`)


STEP_CHECKS = "checks"
FEED_LINES = 20  # the agent's latest actions an attempt's detail carries
FOLLOW_LINES = 20  # the tail a replaced follow answers with


def feed_event(a: Activity) -> FeedEvent | None:
    """An agent action as the page's live line: a command, a tool, a message, an error or a wait; None when its time is not one
    (the file is display-only data and may hold anything)."""
    try:
        at = iso(a.at) or ""
    except (ValueError, OverflowError, OSError):
        return None
    finished = a.state == "finished"
    if a.kind in ("command", "tool"):
        took = a.duration_ms if finished else None
        code = (a.exit_code or 0) if finished and a.kind == "command" else None
        return FeedEvent(a.kind, at, id=a.id, state=a.state, cmd=a.text, name=a.name or None, waited_ms=a.waited_ms, duration_ms=took,
                         exit_code=code)
    return FeedEvent(a.kind, at, text=a.text, waited_ms=a.waited_ms)


def _page(page: ActivityPage, ended: bool = False) -> FeedPage:
    """`ended`: the attempt is over, so a command or tool still running in its file never finished (its worker went away)."""
    lines = (feed_event(each) for each in page.events)
    shown = tuple(replace(line, state="unfinished") if ended and line.state == "running" else line for line in lines if line is not None)
    return FeedPage(shown, page.cursor, page.replaced, page.available)


def build_feed(ports: TaskPorts, backlog: str, task_id: str, step: str, number: int, cursor: str | None) -> FeedPage | Failed | None:
    """The agent's lines of one attempt of the task: its latest, or what came after `cursor`. None: no such agent attempt."""
    try:
        rows = ports.reads.store.attempts(backlog, task_id)
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    numbers = tries(rows)
    key = next((row.key for row in rows if row.step == step and numbers[row.key.attempt_id] == number), None)
    if key is None:
        return None
    return _page(ports.files.activity_tail(key, FEED_LINES) if cursor is None else ports.files.activity_after(key, cursor, FOLLOW_LINES))


def _agent(
    ports: TaskPorts, row: AttemptRow, number: int, result: AttemptResult, previous: int | None, led_by: int | None
) -> AttemptDetail:
    state: State = "running" if result.status != "collected" and row.held else "succeeded" if succeeded(result) else "failed"
    started = ports.files.started_at(row.key)
    ended = None if state == "running" or row.release is None else row.release.released_at
    after = "repeat" if row.previous_attempt_id is not None else "restart_at_plan" if row.step == "plan" and row.seq > 1 else None
    reason = row.repeat_reason if after == "repeat" else "restarted at plan" if after else None
    begun = () if started is None else (FeedEvent("step", iso(started) or "", step=row.step, attempt=number),)
    page = _page(ports.files.activity_tail(row.key, FEED_LINES), ended=state != "running")
    return AttemptDetail(row.step, number, state, iso(started), iso(ended), result.reason or result.status, after, reason,
                         previous if after == "repeat" else None, begun + page.events, page.cursor, led_by if after == "repeat" else None,
                         run=_run(row))


def added_lines(before: str, now: str) -> tuple[tuple[int, int], ...]:
    """The line ranges [start, end) of `now` that `before` lacks: what a repeat's prompt added to the attempt it repeats."""
    found = SequenceMatcher(None, before.splitlines(), now.splitlines(), autojunk=False).get_opcodes()
    return tuple((start, end) for kind, _a, _b, start, end in found if kind in ("insert", "replace"))


SANDBOX_WORDS = {SANDBOX: "can write its own workspace only, no network"}


def _run(row: AttemptRow) -> Run | None:
    choices = row.run
    if choices is None:
        return None
    return Run(HARNESS_WORDS[choices.harness], PROVIDER_WORDS[choices.provider], choices.model, choices.effort,
               SANDBOX_WORDS.get(choices.sandbox, choices.sandbox))


def _agent_body(ports: TaskPorts, row: AttemptRow, result: AttemptResult, rows: tuple[AttemptRow, ...]) -> AttemptBody:
    shown = ports.files.text_bounded(row.key, "answer.txt")
    disposition = None if result.execution is None else result.execution.answer.disposition
    answer = None if shown is None else Answer(disposition or "none", shown[0], shown[1])
    shown = ports.files.text(row.key, "input.txt")
    earlier = next((each for each in rows if each.key.attempt_id == row.previous_attempt_id), None)
    before = None if earlier is None else ports.files.text(earlier.key, "input.txt")
    added = () if shown is None or before is None else added_lines(before, shown)
    return AttemptBody(shown, Outcome(result.reason or result.status, answer, (), None), added)


def _took(result: ResultRow) -> int:
    return 0 if result.ended_at is None else int((result.ended_at - result.started_at) * 1000)


def _check_line(ports: TaskPorts, row: ChecksRow, result: ResultRow) -> CheckLine:
    return CheckLine(result.name, result.conclusion == "passed", _took(result),
                     ports.files.check_tail(row.key, result.block, result.name), result.block)


def _checks_state(row: ChecksRow) -> tuple[State, str]:
    state: State = "running" if row.phase == "admitted" else "succeeded" if row.conclusion == "passed" else "failed"
    return state, row.reason or row.conclusion or ("running" if state == "running" else row.phase)


def _checks(store: CheckStore, row: ChecksRow, number: int, earlier: str | None) -> AttemptDetail:
    results = store.results(row.key)
    state, summary = _checks_state(row)
    started = min((each.started_at for each in results), default=None)
    feed = tuple(FeedEvent("check", iso(each.ended_at or each.started_at) or "", name=each.name, passed=each.conclusion == "passed",
                           duration_ms=_took(each)) for each in results if each.conclusion is not None)
    return AttemptDetail("checks", number, state, iso(started), iso(row.concluded_at), summary, "repeat" if earlier is not None else None,
                         earlier, number - 1 if earlier is not None else None, feed)


def _checks_body(ports: TaskPorts, store: CheckStore, row: ChecksRow) -> AttemptBody:
    lines = tuple(_check_line(ports, row, each) for each in store.results(row.key))
    return AttemptBody(None, Outcome(_checks_state(row)[1], None, lines, None))


@dataclass(frozen=True)
class Link:
    """One entry of the task's chain: an agent attempt, the verification of one, or a checks attempt, with its try."""

    number: int
    agent: AttemptRow | None = None
    checks: ChecksRow | None = None
    result: AttemptResult | None = None  # the agent attempt's stored result, for it and for its verification
    verifies: bool = False
    of: int = 0  # a verification's: the try of the agent attempt it verifies
    successor: AttemptRow | None = None  # the repeat of the verified attempt, which records what a failed verification listed


def _chain(ports: TaskPorts, rows: tuple[AttemptRow, ...]) -> tuple[Link, ...]:
    """The task's attempts oldest first: each agent attempt (numbered within its step across the whole task, `tries`, so a restart at
    plan never repeats a number), its verification when the factory verified it (numbered across the task, between it and what follows),
    and the checks attempts after an implement attempt (numbered across the task: a checks try is the check step's, not the implement's)."""
    store = CheckStore(ports.reads.store.connect, ports.reads.store.begin)
    found: list[Link] = []
    numbers = tries(rows)
    verified = checked = 0
    for row in reversed(rows):
        result = collect(ports.reads.store, row.key)
        found.append(Link(numbers[row.key.attempt_id], agent=row, result=result))
        if applies(result):
            verified += 1
            successor = next((each for each in rows if each.previous_attempt_id == row.key.attempt_id), None)
            found.append(Link(verified, agent=row, result=result, verifies=True, of=numbers[row.key.attempt_id], successor=successor))
        for checks in store.of_attempt(row.key.attempt_id) if row.step == "implement" else ():
            checked += 1
            found.append(Link(checked, checks=checks))
    return tuple(found)


def _verification(link: Link) -> tuple[AttemptDetail, Verification]:
    """The verification row: no start or end of its own is stored, so it has none; its result is the typed words."""
    row, result = link.agent, link.result
    if row is None or result is None:
        raise ValueError("A verification belongs to an agent attempt")
    found, state = verification(row, link.of, result, link.successor)
    return AttemptDetail(VERIFICATION, link.number, state, None, None, found.result, None, None, None, ()), found


def history(ports: TaskPorts, rows: tuple[AttemptRow, ...]) -> tuple[AttemptDetail, ...]:
    """Oldest first: each agent attempt, its verification, then the checks attempts after an implement attempt. Every entry up to
    the latest abandoned attempt (the chain boundary) is `past`: a person gave that chain up, it is not the task's current steps."""
    cut = max((each.seq for each in rows if each.release is not None and each.release.abandoned), default=0)
    past = {each.key.attempt_id for each in rows if each.seq <= cut}
    return tuple(replace(each, past=owner in past) for each, owner in _history(ports, rows))


def _history(ports: TaskPorts, rows: tuple[AttemptRow, ...]) -> tuple[tuple[AttemptDetail, str], ...]:
    """Each entry with the agent attempt it belongs to (a checks attempt: the implement attempt it follows)."""
    store = CheckStore(ports.reads.store.connect, ports.reads.store.begin)
    numbers = tries(rows)
    found: list[tuple[AttemptDetail, str]] = []
    earlier: str | None = None
    led: dict[str, int] = {}  # agent attempt id -> the try of its verification
    for link in _chain(ports, rows):
        if link.checks is not None:
            found.append((_checks(store, link.checks, link.number, earlier), link.checks.after))
            earlier = found[-1][0].summary
        elif link.verifies and link.agent is not None:
            found.append((_verification(link)[0], link.agent.key.attempt_id))
            led[link.agent.key.attempt_id] = link.number
        elif link.agent is not None and link.result is not None:
            previous = link.agent.previous_attempt_id or ""
            found.append((_agent(ports, link.agent, link.number, link.result, numbers.get(previous), led.get(previous)),
                          link.agent.key.attempt_id))
    return tuple(found)


def build_body(ports: TaskPorts, backlog: str, task_id: str, step: str, number: int) -> AttemptBody | Failed | None:
    """What one attempt shows besides its lines. None: no such attempt."""
    try:
        store = CheckStore(ports.reads.store.connect, ports.reads.store.begin)
        rows = ports.reads.store.attempts(backlog, task_id)
        for link in _chain(ports, rows):
            if link.checks is not None and (STEP_CHECKS, link.number) == (step, number):
                return _checks_body(ports, store, link.checks)
            if link.agent is None or link.result is None or link.number != number:
                continue
            if link.verifies and step == VERIFICATION:
                found = _verification(link)[1]
                return AttemptBody(None, Outcome(found.result, None, (), None, found))
            if not link.verifies and link.agent.step == step:
                return _agent_body(ports, link.agent, link.result, rows)
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    return None


def build_task(ports: TaskPorts, backlog: str, task_id: str) -> TaskDetail | Failed:
    """A task with no attempt is a waiting card with none. StoreUnavailable becomes a Failed."""
    try:
        rows = ports.reads.store.attempts(backlog, task_id)
        view = current_view(ports.reads, backlog, task_id)
        if view is not None:
            holds = HoldStore(ports.reads.store.connect, ports.reads.store.begin).of_attempts((agent_attempt(view),))
            view = with_hold(view, holds.get(agent_attempt(view)))
        attempts = history(ports, rows)
    except StoreUnavailable as error:
        return Failed("unavailable", "store", str(error))
    title = task_id if view is None else ports.tracker.titles((task_id,)).get(task_id, task_id)  # cached by the board's own read
    card = Card(task_id, title, "waiting", 0, None, None, None, None, None) if view is None else card_of(
        view, rows[0], title, ports.files, ports.reads.clock(), tries(rows).get(view.attempt_id),
        admission_of(ports.reads, frozenset(each.task_id for each in ports.tracker.ready())), ports.mode)
    return TaskDetail(card, attempts)


def build_tracker(tracker: DashTracker, task_id: str) -> TrackerDetail | None:
    """The tracker's task and comments (`bd` calls; a failed read raises); None: the tracker does not know the task."""
    found = tracker.fields(task_id)
    return None if found is None else TrackerDetail(*found)
