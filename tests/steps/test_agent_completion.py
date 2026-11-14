"""Codex completion through the released parser/supervisor and the factory execution boundary, without processes."""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from any_agent import CodexHarness, Harness, LaunchInputs, LaunchSpec, RunHooks, RunOutcome, Supervisor
from any_agent.testing import FakeRun
from test_attempt import ENTRY, KEY, PLAN, WORKER, AttemptSurroundings, app, database
from test_attempt import surroundings as attempt_surroundings

surroundings = attempt_surroundings
COMMENTARY = "I'll make the deciding operation and write the plan."
SESSION = "completion-regression-session"


@dataclass
class Clock:
    now: float = 0

    def __call__(self) -> float:
        return self.now


class Replay:
    """Feed real wire lines, ticking the watchdog as the production output pump does."""

    def __init__(self, harness: CodexHarness, hooks: RunHooks | None = None) -> None:
        self.clock = Clock()
        self.harness = harness
        self.supervisor = Supervisor(harness, hooks, clock=self.clock)
        self.lines: list[str] = []

    def line(self, raw: dict[str, object]) -> None:
        line = json.dumps(raw) + "\n"
        self.lines.append(line)
        self.supervisor.dog.touch()
        assert not self.supervisor.feed(self.harness.parse_line(line))

    def start(self) -> None:
        self.line({"type": "thread.started", "thread_id": SESSION})
        self.line({"type": "turn.started"})

    def item(self, kind: str, text: str) -> None:
        # In the retained failing stdout, agent_message has no phase.
        self.line({"type": "item.completed", "item": {"id": str(len(self.lines)), "type": kind, "text": text}})

    def tool(self) -> None:
        item = {"id": str(len(self.lines)), "type": "command_execution", "command": "read plan"}
        self.line({"type": "item.started", "item": item})
        self.line({"type": "item.completed", "item": {**item, "exit_code": 0, "aggregated_output": "plan"}})

    def tick(self, seconds: int) -> bool:
        # Small polls matter: the watchdog discounts a long poll gap as machine sleep.
        for _ in range(seconds):
            self.clock.now += 1
            if self.supervisor.poll():
                return True
        return False

    def complete(self) -> None:
        self.line({"type": "turn.completed", "usage": {"input_tokens": 29, "cached_input_tokens": 13, "output_tokens": 7}})

    def finish(self, rc: int) -> RunOutcome:
        return self.supervisor.finish(rc, "".join(self.lines), "")


def commentary_gap(replay: Replay) -> None:
    replay.start()
    replay.tool()
    for _ in range(3):
        replay.item("agent_message", "I am checking the operation.")
        assert not replay.tick(2)
        replay.tool()  # earlier messages had prompt tool activity, clearing the old incorrect answer timer
    replay.item("agent_message", COMMENTARY)
    assert not replay.tick(121)  # the old parser armed an answer stop here when no following stdout cleared it
    assert replay.supervisor.turn.stop is None


@pytest.mark.parametrize(("answer", "kind", "reason"), [
    (json.dumps(PLAN), "valid", "verification"),
    ("The plan is ready.", "json_invalid", "answer:json_invalid"),
    ("{}", "schema_invalid", "answer:schema_invalid"),
])
def test_one_attempt_and_session_survive_commentary_until_the_confirmed_answer(
    surroundings: AttemptSurroundings, answer: str, kind: str, reason: str,
) -> None:
    con = database(surroundings)
    registration = FakeRun(RunOutcome(worker=WORKER))

    def execute(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        registered = registration(harness, spec, timeout, hooks)
        assert isinstance(harness, CodexHarness)
        replay = Replay(harness, hooks)
        replay.supervisor.out.worker = registered.worker
        commentary_gap(replay)
        assert con.execute("SELECT attempt_id,phase,session_ref FROM attempt").fetchall() == [(KEY.attempt_id, "registered", SESSION)]
        assert con.execute("SELECT count(*) FROM execution").fetchone() == (0,)
        assert con.execute("SELECT attempt_id FROM reservation").fetchall() == [(KEY.attempt_id,)]
        assert con.execute("SELECT count(*) FROM slot_release").fetchone() == (0,)
        replay.tool()
        replay.item("agent_message", "I am writing the plan now.")
        replay.item("reasoning", "Check the last detail.")
        replay.tool()
        replay.item("agent_message", answer)
        assert not replay.tick(121)  # even the answer text alone does not confirm the end of a turn
        replay.complete()
        result = replay.finish(0)
        assert result.summary.text == answer and result.summary.stands and result.summary.res["answered"] is True
        return result

    attempts = app(con, surroundings, execute)
    result = attempts.execute(KEY, ENTRY)
    assert result.reason == reason and result.execution is not None and result.execution.answer.kind == kind
    assert result.execution.facts.session == SESSION and result.execution.facts.turns == 1
    assert result.execution.facts.tokens == (29, 13, 7)
    assert len(registration.calls) == 1 and con.execute("SELECT count(*) FROM attempt").fetchone() == (1,)
    assert attempts.execute(KEY, ENTRY) == result and len(registration.calls) == 1


@pytest.mark.parametrize("reasoning", [False, True], ids=["no-further-stdout", "reasoning-after-commentary"])
def test_unconfirmed_commentary_is_diagnostic_and_preserves_the_execution_failure(
    surroundings: AttemptSurroundings, reasoning: bool,
) -> None:
    con = database(surroundings)
    registration = FakeRun(RunOutcome(worker=WORKER))

    def execute(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        registered = registration(harness, spec, timeout, hooks)
        assert isinstance(harness, CodexHarness)
        replay = Replay(harness, hooks)
        replay.supervisor.out.worker = registered.worker
        replay.start()
        replay.item("agent_message", COMMENTARY)
        if reasoning:
            replay.item("reasoning", "The operation still needs implementation.")
        assert not replay.tick(121)
        outcome = replay.finish(-9)
        assert outcome.stop is None and outcome.summary.text == COMMENTARY
        assert outcome.summary.res["answered"] is False and not outcome.summary.stands
        return outcome

    result = app(con, surroundings, execute).execute(KEY, ENTRY)
    assert result.reason == "run:killed" and result.execution is not None
    assert result.execution.facts.answered is False and not result.execution.facts.stands
    assert len(registration.calls) == 1 and con.execute("SELECT count(*) FROM attempt").fetchone() == (1,)


def test_completed_turn_arms_the_answer_grace_for_a_worker_that_does_not_exit() -> None:
    replay = Replay(CodexHarness())
    commentary_gap(replay)
    replay.tool()
    answer = json.dumps(PLAN)
    replay.item("agent_message", answer)
    replay.complete()
    assert not replay.tick(119)
    assert replay.tick(1) and replay.supervisor.turn.stop == "answer"
    outcome = replay.finish(-9)
    assert outcome.stop == "answer" and outcome.summary.text == answer
    assert outcome.summary.res["answered"] is True and outcome.summary.stands


def test_terminal_answer_file_is_read_by_the_released_summary(tmp_path: Path) -> None:
    harness = CodexHarness()
    path = tmp_path / "answer.txt"
    harness.launch_spec(LaunchInputs(exe="/bin/codex", cwd=str(tmp_path), model="chosen", effort="high", prompt="Plan the task",
                                   env={}, out_file=str(path)))
    replay = Replay(harness)
    replay.start()
    replay.item("agent_message", COMMENTARY)
    replay.complete()
    answer = json.dumps(PLAN)
    path.write_text(answer, encoding="utf-8")
    outcome = replay.finish(0)
    assert outcome.summary.text == answer and outcome.summary.res["answered"] is True and outcome.summary.stands
    assert not path.exists()


@pytest.mark.parametrize("tool_running", [False, True], ids=["model-stall", "tool-silence"])
def test_unfinished_work_remains_bounded_by_the_existing_watchdog(tool_running: bool) -> None:
    replay = Replay(CodexHarness())
    replay.start()
    replay.item("agent_message", COMMENTARY)
    if tool_running:
        replay.line({"type": "item.started", "item": {"id": "tool", "type": "command_execution", "command": "check"}})
    assert not replay.tick(121)
    assert replay.tick(3600 if tool_running else 900)
    assert replay.supervisor.now.why == "hung"
    assert replay.supervisor.now.kind == ("silence" if tool_running else "stall")
    outcome = replay.finish(-9)
    assert outcome.summary.res["answered"] is False and not outcome.summary.stands
