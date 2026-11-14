"""The dashboard's read model (board and task detail) over the same factory.db reads as `tl step list`: display only."""

import json
import sqlite3
from dataclasses import astuple
from pathlib import Path

import pytest
from any_agent import RunOutcome, Summary, events
from conftest import DONE
from doubles import CHECKS, REQUIRED, TARGET, D
from sqlite_store import begin_immediate

from taskloop import check_store
from taskloop.agents.stop_models import AgentStop, Identity, StopCause, encode
from taskloop.attempt_status import StatusPorts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, Seen
from taskloop.check_store import CheckStore
from taskloop.command_conclusion import CommandConclusion
from taskloop.command_sink import CommandSink
from taskloop.dash_board import BoardPorts, build_board
from taskloop.dash_model import AttemptBody, Board, Comment, FeedPage, Fields, Ready, Run, TaskDetail
from taskloop.dash_task import TaskPorts, build_body, build_feed, build_task, build_tracker
from taskloop.evidence_files import EvidenceFiles
from taskloop.hold_store import HoldInsert, HoldStore
from taskloop.land_status import LandView, land_state, land_view
from taskloop.profile import LandMode

KEY = AttemptKey("attempt", "dispatch", 1)
FIELDS = Fields("P1", ("auto",), "task/tl-1", "taskloop", "2026-11-12T10:00:00Z", "2026-11-12T11:00:00Z", ("tl-0",), "Why", "Done when",
                "", "")


class Tracker:
    """The tracker reads as a fake: what it lists ready, the titles it knows and the one task it can show."""

    def __init__(self, ready: tuple[Ready, ...] = (), problem: str | None = None) -> None:
        self.listed, self.problem = ready, problem

    def ready(self) -> tuple[Ready, ...]:
        return self.listed

    def titles(self, task_ids: tuple[str, ...]) -> dict[str, str]:
        return {each: f"Title of {each}" for each in task_ids}

    def fields(self, task_id: str) -> tuple[Fields, tuple[Comment, ...]] | None:
        return (FIELDS, (Comment("denis", "2026-11-12T10:30:00Z", "Keep it small"),)) if task_id == "tl-1" else None

    def notice(self) -> str | None:
        return self.problem


def reads_of(con: sqlite3.Connection, now: float = 1000.0) -> StatusPorts:
    return StatusPorts(AttemptStore(lambda: con), lambda _entry: "matching", lambda: now, lambda _key: None, lambda: "boot")


def board_of(con: sqlite3.Connection, files: EvidenceFiles, tracker: Tracker) -> Board:
    found = build_board(BoardPorts(reads_of(con), files, tracker))
    assert isinstance(found, Board)
    return found


def saved_ask(con: sqlite3.Connection, files: EvidenceFiles, key: AttemptKey = KEY, step: str = "plan",
              text: str = "Which database?\nUse <primary>?") -> None:
    answer = {"disposition": "needs_owner", "paths": [], "message": None, "explanation": text}
    if step == "plan":
        answer["plan_path"] = None
    evidence = files.capture(key, RunOutcome(rc=0, summary=Summary(text=json.dumps(answer))))
    refs = tuple(value for ref in astuple(evidence) for value in ref)
    con.execute("""UPDATE attempt SET phase='captured',base_commit=?,step=?,after_commit=?,label='auto'
        WHERE attempt_id=?""", (D, step, D if step == "implement" else None, key.attempt_id))
    con.execute("""INSERT INTO execution (attempt_id,dispatch_token,generation,rc,timed_out,work,stands,stdout_path,
        stdout_digest,stderr_path,stderr_digest,answer_path,answer_digest,diagnostic_path,diagnostic_digest,answer_kind,
        disposition,effect,session_state) VALUES (?,?,?,0,0,1,1,?,?,?,?,?,?,?,?,'valid','needs_owner','none','complete')""",
        (*astuple(key), *refs))


@pytest.mark.parametrize("step", ["plan", "implement"])
@pytest.mark.parametrize("released", [False, True])
def test_current_agent_questions_agree_on_board_and_detail(
    registered: sqlite3.Connection, tmp_path: Path, step: str, released: bool,
) -> None:
    files = EvidenceFiles(tmp_path)
    saved_ask(registered, files, step=step)
    if released:
        store = HoldStore(lambda: registered)
        hold = store.insert(HoldInsert("attempt", "attempt", "failed:needs_owner", 10))
        store.labelled("attempt", hold.rev, "moved", 11)
        registered.execute("INSERT INTO slot_release VALUES ('attempt','dispatch',1,?,12,'unclaimed')", (D,))
        registered.execute("UPDATE task_hold SET commenting_at=12,commented_at=13 WHERE attempt_id='attempt'")
    card, = board_of(registered, files, Tracker()).tasks
    detail = build_task(TaskPorts(reads_of(registered), files, Tracker()), "tasks", "tl-1")
    assert isinstance(detail, TaskDetail) and detail.task == card
    assert (card.column, card.ask, card.question) == ("held", True, "Which database?\nUse <primary>?")
    assert (card.slot is None) == released


@pytest.mark.parametrize("damage", ["missing", "changed", "invalid"])
def test_damaged_question_evidence_preserves_the_ask(
    registered: sqlite3.Connection, tmp_path: Path, damage: str,
) -> None:
    files = EvidenceFiles(tmp_path)
    saved_ask(registered, files)
    path = files.root / files.directory(KEY) / "answer.txt"
    if damage == "missing":
        path.unlink()
    else:
        path.write_text("invalid json")
        if damage == "invalid":
            ref = files.capture_refs(KEY, RunOutcome(rc=0, summary=Summary(text="invalid json"))).answer
            registered.execute("UPDATE execution SET answer_digest=?", (ref.digest,))
    card, = board_of(registered, files, Tracker()).tasks
    assert card.ask and card.question is None
    detail = build_task(TaskPorts(reads_of(registered), files, Tracker()), "tasks", "tl-1")
    assert isinstance(detail, TaskDetail) and detail.task == card


@pytest.mark.parametrize("reason", ["branch_moved", "failed:run:timeout"])
def test_factory_holds_do_not_reuse_an_agent_question(
    registered: sqlite3.Connection, tmp_path: Path, reason: str,
) -> None:
    files = EvidenceFiles(tmp_path)
    saved_ask(registered, files)
    HoldStore(lambda: registered).insert(HoldInsert("attempt", "attempt", reason, 10))
    card, = board_of(registered, files, Tracker()).tasks
    assert (card.column, card.ask, card.question, card.hold_cause) == ("held", False, None, reason)


def test_checks_hold_does_not_reuse_its_agents_question(checking: sqlite3.Connection, tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    saved_ask(checking, files, AttemptKey("implement", "implement-token", 1), "implement")
    HoldStore(lambda: checking).insert(HoldInsert("implement", "checks", "failed:needs_owner", 10))
    card, = board_of(checking, files, Tracker()).tasks
    detail = build_task(TaskPorts(reads_of(checking), files, Tracker()), "tasks", "tl-1")
    assert isinstance(detail, TaskDetail) and detail.task == card
    assert (card.column, card.ask, card.question) == ("held", False, None)


def test_stop_explanation_takes_precedence_over_an_agent_question(registered: sqlite3.Connection, tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    saved_ask(registered, files)
    stop = AgentStop(attempt_id="attempt", dispatch_token="dispatch", generation=1,
                     entry=Identity(pid=7, pgid=7, start="entry-start", boot="boot"),
                     agent=Identity(pid=8, pgid=8, start="agent-start", boot="boot"),
                     cause=StopCause.DEADLINE, requested_signal=15, requested_at=10)
    registered.execute("INSERT INTO agent_stop VALUES (?,?)", ("attempt", encode(stop)))
    card, = board_of(registered, files, Tracker()).tasks
    detail = build_task(TaskPorts(reads_of(registered), files, Tracker()), "tasks", "tl-1")
    assert isinstance(detail, TaskDetail) and detail.task == card
    assert (card.column, card.ask, card.question) == ("held", False, None)
    assert card.hold_cause is not None and "deadline expired" in card.hold_cause


def test_the_board_has_a_card_for_each_attempted_task_and_each_ready_task_without_one(
    registered: sqlite3.Connection, tmp_path: Path,
) -> None:
    files = EvidenceFiles(tmp_path)
    files.put_input(KEY, "Plan the actual task")
    ready = (Ready("tl-1", "taken already", "2026-11-12T09:00:00Z"), Ready("tl-2", "Second", "2026-11-12T09:30:00Z"))
    board = board_of(registered, files, Tracker(ready))
    cards = {card.id: card for card in board.tasks}
    assert sorted(cards) == ["tl-1", "tl-2"] and board.slots == ("s1",)
    assert (cards["tl-1"].column, cards["tl-1"].title, cards["tl-1"].slot, cards["tl-1"].attempt) == ("plan", "Title of tl-1", "s1", 1)
    assert cards["tl-1"].step_started_at is not None and cards["tl-1"].repeat is None and cards["tl-1"].hold_cause is None
    assert not cards["tl-1"].ask and cards["tl-1"].question is None
    assert (cards["tl-2"].column, cards["tl-2"].title, cards["tl-2"].attempt, cards["tl-2"].slot) == ("waiting", "Second", 0, None)
    assert cards["tl-2"].step_started_at == "2026-11-12T09:30:00Z"


def test_a_tracker_problem_reaches_the_board_as_a_notice(registered: sqlite3.Connection, tmp_path: Path) -> None:
    board = board_of(registered, EvidenceFiles(tmp_path), Tracker(problem="Tracker unavailable: down"))
    assert board.notice == "Tracker unavailable: down" and [card.id for card in board.tasks] == ["tl-1"]


def test_a_task_detail_has_the_tracker_text_the_comments_and_each_attempts_prompt(
    registered: sqlite3.Connection, tmp_path: Path,
) -> None:
    files = EvidenceFiles(tmp_path)
    files.put_input(KEY, "Plan the actual task")
    found = build_task(TaskPorts(reads_of(registered), files, Tracker()), "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    tracked = build_tracker(Tracker(), "tl-1")
    assert tracked is not None and tracked.fields.acceptance == "Done when" and [each.author for each in tracked.comments] == ["denis"]
    (attempt,) = found.attempts
    assert (attempt.step, attempt.n, attempt.after, attempt.repeat_of) == ("plan", 1, None, None)
    body = build_body(TaskPorts(reads_of(registered), files, Tracker()), "tasks", "tl-1", "plan", 1)
    assert isinstance(body, AttemptBody) and body.input == "Plan the actual task" and body.result.answer is None
    assert build_body(TaskPorts(reads_of(registered), files, Tracker()), "tasks", "tl-1", "plan", 7) is None
    assert attempt.state == "running" and attempt.feed[0].type == "step"
    assert found.task.column == "plan" and found.task.title == "Title of tl-1"


def test_a_task_with_no_attempt_is_a_waiting_card_and_the_tracker_part_says_whether_it_knows_it(
    registered: sqlite3.Connection, tmp_path: Path,
) -> None:
    ports = TaskPorts(reads_of(registered), EvidenceFiles(tmp_path), Tracker())
    found = build_task(ports, "tasks", "tl-9")
    assert isinstance(found, TaskDetail) and found.attempts == () and found.task.column == "waiting"
    assert build_tracker(Tracker(), "tl-9") is None


def test_the_detail_of_a_task_never_asks_the_tracker_for_its_fields(registered: sqlite3.Connection, tmp_path: Path) -> None:
    class Refusing(Tracker):
        def fields(self, task_id: str) -> tuple[Fields, tuple[Comment, ...]] | None:
            raise AssertionError("the drawer's first answer waits for no tracker read")

    found = build_task(TaskPorts(reads_of(registered), EvidenceFiles(tmp_path), Refusing()), "tasks", "tl-1")
    assert isinstance(found, TaskDetail) and found.task.title == "Title of tl-1"


def test_the_checks_attempt_follows_its_implement_attempt_in_the_history(checking: sqlite3.Connection, tmp_path: Path) -> None:
    found = build_task(TaskPorts(reads_of(checking), EvidenceFiles(tmp_path), Tracker()), "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    assert [(each.step, each.n) for each in found.attempts] == [("implement", 1), ("checks", 1)]
    assert found.attempts[1].state == "running"


def test_an_agent_attempts_detail_and_feed_show_its_commands_and_messages_as_live_lines(
    registered: sqlite3.Connection, tmp_path: Path,
) -> None:
    files = EvidenceFiles(tmp_path)
    files.put_input(KEY, "Plan the actual task")
    sink = CommandSink(files, KEY, iter(range(100, 200, 2)).__next__)
    ports = TaskPorts(reads_of(registered), files, Tracker())
    sink.feed(events.Cmd(id="c1", text="just test"))
    sink.feed(events.CmdEnd(id="c1", text="just test", exit=2))
    sink.feed(events.Msg(text="two checks failed"))
    found = build_task(ports, "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    (attempt,) = found.attempts
    assert [(line.type, line.state, line.cmd or line.text) for line in attempt.feed[1:]] == [
        ("command", "finished", "just test"), ("message", None, "two checks failed")]
    assert attempt.feed[1].exit_code == 2 and attempt.feed_cursor is not None
    sink.feed(events.Msg(text="done"))
    page = build_feed(ports, "tasks", "tl-1", "plan", 1, attempt.feed_cursor)
    assert isinstance(page, FeedPage) and [line.text for line in page.events] == ["done"] and not page.replaced
    assert build_feed(ports, "tasks", "tl-1", "plan", 7, None) is None


def test_an_agent_attempt_says_what_ran_it_in_plain_words(registered: sqlite3.Connection, tmp_path: Path) -> None:
    registered.execute("UPDATE attempt SET harness='opencode', provider='deepseek', model='opencode/deepseek-v4.1-flash-free', "
                       "access_policy=?", ('{"harness":"opencode"}',))
    files = EvidenceFiles(tmp_path)
    files.put_input(KEY, "Plan the actual task")
    found = build_task(TaskPorts(reads_of(registered), files, Tracker()), "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    (attempt,) = found.attempts
    assert attempt.run == Run("OpenCode", "DeepSeek", "opencode/deepseek-v4.1-flash-free", "high",
                              "default sandbox")


def test_a_full_access_attempt_says_the_container_is_the_boundary(registered: sqlite3.Connection, tmp_path: Path) -> None:
    registered.execute("UPDATE attempt SET access_policy=?", ('{"harness":"codex","sandbox":"danger-full-access"}',))
    files = EvidenceFiles(tmp_path)
    files.put_input(KEY, "Plan the actual task")
    found = build_task(TaskPorts(reads_of(registered), files, Tracker()), "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    (attempt,) = found.attempts
    assert attempt.run is not None and attempt.run.access == "full access: the container is the boundary"


def test_reasoning_is_a_collapsed_line_only_when_the_harness_gave_words(registered: sqlite3.Connection, tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    files.put_input(KEY, "Plan the actual task")
    sink = CommandSink(files, KEY, iter(range(100, 200, 2)).__next__)
    sink.feed(events.Think(text="check the schema first"))
    sink.feed(events.Think(text="   "))  # a redacted block: nothing to show
    found = build_task(TaskPorts(reads_of(registered), files, Tracker()), "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    assert [(line.type, line.text) for line in found.attempts[0].feed[1:]] == [("think", "check the schema first")]


def test_a_poisoned_events_file_does_not_break_the_task_detail(registered: sqlite3.Connection, tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    files.put_input(KEY, "Plan the actual task")
    sink = CommandSink(files, KEY, iter(range(100, 200, 2)).__next__)
    sink.feed(events.Msg(text="good"))
    with files.events_path(KEY).open("ab") as stream:
        stream.write(b'{"k":"message","s":"finished","at":Infinity,"t":"inf"}\n{"k":"message","s":"finished","at":1e999,"t":"big"}\n')
    found = build_task(TaskPorts(reads_of(registered), files, Tracker()), "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    assert [line.text for line in found.attempts[0].feed[1:]] == ["good"]


def test_a_command_still_running_in_an_ended_attempt_is_shown_unfinished(checking: sqlite3.Connection, tmp_path: Path) -> None:
    files, key = EvidenceFiles(tmp_path), AttemptKey("implement", "implement-token", 1)
    CommandSink(files, key, iter(range(100, 200, 2)).__next__).feed(events.Cmd(id="c1", text="make"))
    found = build_task(TaskPorts(reads_of(checking), files, Tracker()), "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    agent = next(each for each in found.attempts if each.step == "implement")
    assert agent.state != "running" and [line.state for line in agent.feed if line.type == "command"] == ["unfinished"]


def land_of(con: sqlite3.Connection, seen: Seen) -> LandView | None:
    """The checks attempt's land as `attempt_status` reads it, its land process observed as `seen`."""
    store = AttemptStore(lambda: con)
    return land_view(store, CheckStore(store.connect, store.begin).of_attempt("implement")[-1], lambda _entry: seen)


def test_a_waiting_task_says_manual_only_when_the_profile_says_so(landing: sqlite3.Connection) -> None:
    waiting = land_of(landing, "gone")
    assert land_state(waiting, LandMode.MANUAL) == "manual" and land_state(waiting, LandMode.AUTO) == "waiting"
    assert land_state(waiting, None) == "unknown"
    landing.execute("UPDATE land_candidate SET entry_pid=7,entry_start='entry-start',entry_boot='boot' WHERE candidate_id='candidate'")
    assert land_state(land_of(landing, "matching"), LandMode.MANUAL) == "landing"


def test_a_checked_task_nobody_has_landed_waits_to_be_landed(checking: sqlite3.Connection) -> None:
    checking.execute("UPDATE checks_attempt SET phase='concluded',conclusion='passed',concluded_at=5,released_at=6,parked=? "
                     "WHERE attempt_id='checks'", ("d" * 40,))
    assert land_of(checking, "matching") is None and land_state(None) == "unknown"


def test_a_task_shows_landing_only_while_its_land_process_runs(landing: sqlite3.Connection) -> None:
    assert land_state(land_of(landing, "matching")) == "unknown"  # its candidate has no registered land process
    landing.execute("UPDATE land_candidate SET entry_pid=7,entry_start='entry-start',entry_boot='boot' WHERE candidate_id='candidate'")
    assert land_state(land_of(landing, "matching")) == "landing"
    assert land_state(land_of(landing, "gone")) == "unknown"


def test_each_check_carries_the_end_of_its_log_passed_or_failed_and_none_when_the_log_is_gone(
    checking: sqlite3.Connection, tmp_path: Path,
) -> None:
    files, store = EvidenceFiles(tmp_path), CheckStore(lambda: checking, begin_immediate)
    for position, name, rc, conclusion in ((0, "lint", 0, CommandConclusion.PASSED), (1, "test", 1,
        CommandConclusion.FAILED), (2, "types", 0, CommandConclusion.PASSED)):
        store.start(CHECKS, 1, position, name, "a" * 64, 60, 3)
        store.finish(CHECKS, 1, position, conclusion, rc, 4)
    files.check_log(CHECKS, 1, "lint").write_text("all clean\n")
    files.check_log(CHECKS, 1, "test").write_text("FAILED tests/test_a.py::test_one\n" + "x" * 10000 + "\n1 failed\n")
    body = build_body(TaskPorts(reads_of(checking), files, Tracker()), "tasks", "tl-1", "checks", 1)
    assert isinstance(body, AttemptBody)
    lint, test, types = body.result.checks
    assert (lint.passed, lint.output, lint.block) == (True, "all clean\n", 1)
    assert not test.passed and test.output is not None and test.output.endswith("1 failed\n") and len(test.output) <= 8192
    assert types.passed and types.output is None  # its log file is gone: unavailable, never a made-up empty output


def test_an_answer_file_longer_than_the_bound_is_cut_and_says_so(registered: sqlite3.Connection, tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    files.put_input(KEY, "Plan the actual task")
    (tmp_path / files.directory(KEY) / "answer.txt").write_text("y" * 70000)
    body = build_body(TaskPorts(reads_of(registered), files, Tracker()), "tasks", "tl-1", "plan", 1)
    assert isinstance(body, AttemptBody) and body.result.answer is not None
    assert len(body.result.answer.text) == 65536 and body.result.answer.truncated


def test_a_second_checks_try_is_numbered_across_the_task_and_says_which_try_it_repeats(
    checking: sqlite3.Connection, tmp_path: Path,
) -> None:
    checking.execute("UPDATE checks_attempt SET phase='concluded',conclusion='failed',reason='test:failed',concluded_at=5,released_at=6,"
                     "parked=? WHERE attempt_id='checks'", ("d" * 40,))
    checking.execute("DELETE FROM reservation WHERE attempt_id='checks'")
    again = check_store.ChecksAdmitted(AttemptKey("again", "again-token", 1), "implement", 2, "s2", D, TARGET, REQUIRED, 100.0)
    check_store.insert(checking, again)
    found = build_task(TaskPorts(reads_of(checking), EvidenceFiles(tmp_path), Tracker()), "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    assert [(each.step, each.n, each.after, each.repeat_of) for each in found.attempts[1:]] == [
        ("checks", 1, None, None), ("checks", 2, "repeat", 1)]
    assert found.attempts[2].reason == "test:failed"


def restarted_at_plan(con: sqlite3.Connection) -> None:
    """tl-1's plan attempt `attempt` (seq 1) is followed by an implement attempt and a second plan attempt, each with stored
    number 1, the way a restart at plan starts a new chain."""
    for attempt, step, seq in (("implement", "implement", 2), ("again", "plan", 3)):
        con.execute(
            """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
            input_path,input_digest,schema_version,model,effort,access_policy,deadline,number,seq,slot_head,after_commit)
            SELECT ?,?,1,?,adapter,backlog,
            task_id,tracker_root,repo_id,slot,input_path,input_digest,schema_version,model,effort,access_policy,deadline,1,?,slot_head,?
            FROM attempt WHERE attempt_id='attempt'""", (attempt, f"{attempt}-token", step, seq, "a" * 40 if step == "implement" else None))


def test_a_plan_restarted_at_plan_is_its_own_try_that_can_be_read_by_its_number(
    registered: sqlite3.Connection, tmp_path: Path,
) -> None:
    restarted_at_plan(registered)
    files = EvidenceFiles(tmp_path)
    ports = TaskPorts(reads_of(registered), files, Tracker())
    found = build_task(ports, "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    assert [(each.step, each.n, each.after) for each in found.attempts] == [
        ("plan", 1, None), ("implement", 1, None), ("plan", 2, "restart_at_plan")]
    assert found.task.attempt == 2 and found.task.repeat is not None and found.task.repeat.kind == "restart_at_plan"
    assert found.task.repeat.reason == "Reason not recorded"
    board_task, = board_of(registered, files, Tracker()).tasks
    assert board_task.attempt == 2 and board_task.repeat is not None
    assert (board_task.repeat.kind, board_task.repeat.reason) == ("restart_at_plan", "Reason not recorded")
    files.put_input(KEY, "Plan the actual task")
    ref = files.put_input(AttemptKey("again", "again-token", 1), "Plan it again after the owner's edit")
    registered.execute("UPDATE attempt SET input_path=?,input_digest=? WHERE attempt_id='again'", (ref.path, ref.digest))
    first, second = (build_body(ports, "tasks", "tl-1", "plan", each) for each in (1, 2))
    assert isinstance(first, AttemptBody) and isinstance(second, AttemptBody)
    assert first.input == "Plan the actual task" and second.input == "Plan it again after the owner's edit"
    assert isinstance(build_feed(ports, "tasks", "tl-1", "plan", 2, None), FeedPage)
    assert build_feed(ports, "tasks", "tl-1", "plan", 3, None) is None


def unsafe_repeat(con: sqlite3.Connection, listing: str = '["src/link.py", "src/stray.py"]') -> None:
    """`checking`'s implement attempt answered `implemented` (a valid, committing answer) and its verification was unsettled: it was
    repeated as try 2 for `unsafe`, which stored what the verification listed."""
    con.execute(DONE[0])
    con.execute(
        """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
        input_path,input_digest,schema_version,model,effort,access_policy,deadline,number,seq,slot_head,previous_attempt_id,repeat_reason,
        repeat_listing) SELECT 'again','again-token',2,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,
        schema_version,model,effort,access_policy,deadline,2,3,slot_head,'implement','unsafe',
        ? FROM attempt WHERE attempt_id='implement'""",
        (listing,))


def test_an_unsettled_verification_is_its_own_row_that_names_the_failed_check_and_what_it_listed(
    checking: sqlite3.Connection, tmp_path: Path,
) -> None:
    unsafe_repeat(checking)
    ports = TaskPorts(reads_of(checking), EvidenceFiles(tmp_path), Tracker())
    found = build_task(ports, "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    assert [(each.step, each.n) for each in found.attempts] == [("implement", 1), ("verification", 1), ("checks", 1), ("implement", 2)]
    verifying, repeat = found.attempts[1], found.attempts[3]
    assert (verifying.state, verifying.summary) == ("failed", "unsettled:unsafe")
    assert (repeat.after, repeat.reason, repeat.repeat_of, repeat.led_by) == ("repeat", "unsafe", 1, 1)
    body = build_body(ports, "tasks", "tl-1", "verification", 1)
    assert isinstance(body, AttemptBody) and body.input is None and body.result.verification is not None
    shown = body.result.verification
    assert (shown.of_step, shown.of, shown.result, shown.listing) == ("implement", 1, "unsettled:unsafe", ("src/link.py", "src/stray.py"))
    assert [each.state for each in shown.checks] == ["passed", "failed", "not_run", "not_run", "not_run"]


def test_a_stored_verdict_is_a_verification_row_that_passed_or_broke_a_rule(checking: sqlite3.Connection, tmp_path: Path) -> None:
    checking.execute(DONE[0])
    checking.execute(DONE[1])
    ports = TaskPorts(reads_of(checking), EvidenceFiles(tmp_path), Tracker())
    body = build_body(ports, "tasks", "tl-1", "verification", 1)
    assert isinstance(body, AttemptBody) and body.result.verification is not None
    assert body.result.verification.result == "verified" and {each.state for each in body.result.verification.checks} == {"passed"}
    checking.execute("DELETE FROM verification")
    checking.execute("INSERT INTO verification (attempt_id,dispatch_token,generation,verdict,reason,observed_at) "
                     "VALUES ('implement','implement-token',1,'rejected','paths',5)")
    broken = build_body(ports, "tasks", "tl-1", "verification", 1)
    assert isinstance(broken, AttemptBody) and broken.result.verification is not None
    assert broken.result.verification.result == "rejected:paths"
    assert [each.state for each in broken.result.verification.checks] == ["passed"] * 4 + ["failed"]


def test_an_attempt_that_never_reached_verification_has_no_verification_row(checking: sqlite3.Connection, tmp_path: Path) -> None:
    found = build_task(TaskPorts(reads_of(checking), EvidenceFiles(tmp_path), Tracker()), "tasks", "tl-1")
    assert isinstance(found, TaskDetail) and [each.step for each in found.attempts] == ["implement", "checks"]
    assert build_body(TaskPorts(reads_of(checking), EvidenceFiles(tmp_path), Tracker()), "tasks", "tl-1", "verification", 1) is None


def test_a_repeats_prompt_marks_the_lines_it_added_to_the_prompt_it_repeats(checking: sqlite3.Connection, tmp_path: Path) -> None:
    unsafe_repeat(checking)
    files = EvidenceFiles(tmp_path)
    for key, text in ((AttemptKey("implement", "implement-token", 1), "Title\n\nDo the thing.\n"),
                      (AttemptKey("again", "again-token", 2), "A path cannot be committed.\nsrc/link.py\n\nTitle\n\nDo the thing.\n")):
        ref = files.put_input(key, text)
        checking.execute("UPDATE attempt SET input_path=?,input_digest=? WHERE attempt_id=?", (ref.path, ref.digest, key.attempt_id))
    ports = TaskPorts(reads_of(checking), files, Tracker())
    first, second = (build_body(ports, "tasks", "tl-1", "implement", each) for each in (1, 2))
    assert isinstance(first, AttemptBody) and isinstance(second, AttemptBody)
    assert first.added == () and second.added == ((0, 3),)


def test_a_plan_repeat_is_a_repeat_on_the_board_and_in_history(registered: sqlite3.Connection, tmp_path: Path) -> None:
    registered.execute(
        """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
        input_path,input_digest,schema_version,model,effort,access_policy,deadline,number,seq,slot_head,previous_attempt_id,repeat_reason)
        SELECT 'again','again-token',2,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,
        schema_version,model,effort,access_policy,deadline,2,2,slot_head,'attempt','unsafe' FROM attempt WHERE attempt_id='attempt'""")
    files = EvidenceFiles(tmp_path)
    board_task, = board_of(registered, files, Tracker()).tasks
    assert board_task.repeat is not None
    assert (board_task.repeat.kind, board_task.repeat.reason) == ("repeat", "unsafe")
    found = build_task(TaskPorts(reads_of(registered), files, Tracker()), "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    assert [(a.step, a.n, a.after) for a in found.attempts] == [("plan", 1, None), ("plan", 2, "repeat")]
    assert (found.attempts[-1].reason, found.attempts[-1].repeat_of) == ("unsafe", 1)
