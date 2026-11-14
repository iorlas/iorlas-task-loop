"""Model requests from the normalized stream result survive capture and independent reads."""

import json

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary, events
from any_agent.testing import FakeRun
from test_attempt import ENTRY, KEY, PLAN, WORKER, AttemptSurroundings, Flaky, app, database, fake, owner, registered_run
from test_attempt import surroundings as attempt_surroundings

from taskloop.attempt_types import CaptureResult
from taskloop.command_sink import WatchedHooks

surroundings = attempt_surroundings


def outcome(requests: int | str | float | None) -> RunOutcome:
    summary = Summary(
        text=json.dumps(PLAN), rc=0, work=True, stands=True,
        res={"ref": "native-session", "answered": True, "turns": 1,
             "tokens": {"in": 120, "cached": 30, "out": 6},
             "cumulative": {"in": 240, "cached": 60, "out": 12}},
    )
    if requests is not None:
        summary.res["requests"] = requests
    return RunOutcome(rc=0, worker=WORKER, summary=summary)


class RequestStream(FakeRun):
    """Three usage reports, four tools and one invocation completion; summary is normalized by the adapter."""

    def __call__(self, harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None = None) -> RunOutcome:
        result = super().__call__(harness, spec, timeout, hooks)
        assert isinstance(hooks, WatchedHooks)
        for n in (1, 2, 3):
            hooks.live.feed(events.Tokens(in_=20 * n, cached=5 * n, out=n))
        for n in (1, 2, 3, 4):
            hooks.live.feed(events.Tool(id=str(n), name="inspect"))
            hooks.live.feed(events.ToolEnd(id=str(n), name="inspect", out="done"))
        hooks.live.feed(events.TurnDone(usage=events.Tokens(in_=120, cached=30, out=6)))
        hooks.live.end("done")
        return result


def test_multi_request_stream_is_persisted_and_collected_once(surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)
    stream = RequestStream(outcome(3), refs=("native-session",))
    result = app(con, surroundings, stream).execute(KEY, ENTRY)
    assert result.reason == "verification" and result.execution is not None
    assert result.execution.answer.kind == "valid" and result.execution.session_state == "complete"
    facts = result.execution.facts
    assert facts.turns == 3 and facts.rc == 0 and facts.answered is True
    assert facts.work and facts.stands and facts.session == "native-session"
    assert facts.tokens == (120, 30, 6) and facts.cumulative == (240, 60, 12)
    assert con.execute("SELECT turns,t_in,t_cached,t_out FROM execution").fetchone() == (3, 120, 30, 6)
    unused = fake()
    reader = app(con, surroundings, unused)
    assert reader.collect(KEY) == result and reader.execute(KEY, ENTRY) == result
    assert not unused.calls and len(stream.calls) == 1


def test_repeated_capture_keeps_request_count(surroundings: AttemptSurroundings) -> None:
    flaky = Flaky(database(surroundings))
    run = FakeRun(outcome(3), refs=("native-session",))
    attempts = owner(flaky, surroundings, registered_run(run, flaky, down_after_start=True))
    result = attempts.execute(KEY, ENTRY)
    assert result.pending is not None
    flaky.down = False
    retry = app(flaky.con, surroundings, fake())
    assert retry.capture(result.pending) == CaptureResult("accepted")
    assert retry.capture(result.pending) == CaptureResult("already_same")
    stored = retry.collect(KEY)
    assert stored.execution is not None and stored.execution.facts.turns == 3
    assert flaky.con.execute("SELECT turns FROM execution").fetchall() == [(3,)]


@pytest.mark.parametrize(("requests", "expected"), [
    (0, 0), (None, None), (True, None), (False, None), (-1, None), ("3", None), (3.0, None),
])
def test_only_valid_request_counts_are_persisted(
    surroundings: AttemptSurroundings, requests: int | str | float | None, expected: int | None,
) -> None:
    con = database(surroundings)
    result = app(con, surroundings, FakeRun(outcome(requests))).execute(KEY, ENTRY)
    assert result.execution is not None and result.execution.facts.turns == expected
    assert con.execute("SELECT turns FROM execution").fetchone() == (expected,)
    collected = app(con, surroundings, fake()).collect(KEY)
    assert collected.execution is not None and collected.execution.facts.turns == expected
