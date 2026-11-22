"""The rounds surface: `tl rounds once` and `tl rounds start` flags to requests through stubbed composition openers, the start
and end lines, the refusals, and the real wiring over a factory.db file under tmp_path."""

import json
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlite_store import Store
from step_cli_support import MOVES, NEXT, ROUNDS, admitted

from taskloop import cli_composition, cli_step, rounds_lock, step_guide
from taskloop.agents.settings import Overrides, StepSettings
from taskloop.attempt_types import DEFAULT_GIT_READ_SECONDS
from taskloop.cli import main
from taskloop.factory_schema import SCHEMA
from taskloop.git_views import GitViews
from taskloop.inspection_guide import CONFIG
from taskloop.operations import (
    Ended,
    Failed,
    Round,
)
from taskloop.round import NextRequest, run_round
from taskloop.round_guide import automatic_guide

HIGH_PLAN = Overrides(model="m", plan_effort="high")


class Rounds:
    """`advance`'s ports are opaque to the surface: the opener's value is passed through to the stubbed operation."""


def test_next_flags_reach_the_request_and_the_opener_and_its_json_is_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    opened: list[tuple[Path, Path, str]] = []
    requests: list[object] = []
    ports = Rounds()

    @contextmanager
    def opener(database: Path, artifacts: Path, _views: GitViews, tracker_root: str) -> Generator[Rounds]:
        opened.append((database, artifacts, tracker_root))
        yield ports

    def advanced(given: object, request: object) -> Round:
        assert given is ports
        requests.append(request)
        return Round("tasks", (MOVES[0],), logged=False)

    monkeypatch.setattr(cli_composition, "open_next", opener)
    monkeypatch.setattr(cli_step, "run_round", advanced)
    assert main([*NEXT, "--db", str(tmp_path / "f.db"), "--artifacts", str(tmp_path / "art"), "--json"]) == 0
    assert opened == [(tmp_path / "f.db", tmp_path / "art", "/tracker")]
    assert requests == [cli_step.NextRequest("tasks", "/tracker", Path("/checkout"), "auto", StepSettings(), HIGH_PLAN, 30)]
    assert json.loads(capsys.readouterr().out) == {
        "status": "round",
        "backlog": "tasks",
        "stopped": None,
        "logged": False,
        "moves": [{"task": "tl-3", "action": "start", "word": "started", "attempt_id": "a3", "detail": None}],
    }
    assert main([*NEXT, "--artifacts", str(tmp_path / "art")]) == 0
    assert f"Log: not written ({tmp_path / 'art' / 'rounds.log'})" in capsys.readouterr().out


@pytest.mark.parametrize("missing", ["--label", "--backlog", "--tracker-root", "--checkout"])
def test_a_round_without_a_flag_or_a_config_value_is_refused(missing: str, capsys: pytest.CaptureFixture[str]) -> None:
    at = NEXT.index(missing)
    assert main([*NEXT[:at], *NEXT[at + 2 :]]) == 1
    error = capsys.readouterr().err
    assert ("refused:backlog_missing" if missing == "--backlog" else "refused:binding_missing") in error


def test_next_requires_its_minutes_and_its_help_names_the_round(capsys: pytest.CaptureFixture[str]) -> None:
    at = NEXT.index("--minutes")
    with pytest.raises(SystemExit) as result:
        main([*NEXT[:at], *NEXT[at + 2 :]])
    assert result.value.code == 2 and "--minutes" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["rounds", "once", "--help"])
    shown = " ".join(capsys.readouterr().out.split())
    assert (
        "Run one scheduling round: settle existing attempts, advance claimed tasks whose step is done to the next step "
        "(no label check), start approved ready tasks in the free slots left"
    ) in shown
    assert "read only when a new task is taken; a claimed task advances without it" in shown
    assert "hold each task a round took that stopped" in shown and "`bd list --label held`" in shown


def test_next_refuses_an_unusable_tracker_root_and_a_missing_database(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "factory.db"
    assert main([*NEXT, "--db", str(db), "--json"]) == 1
    assert json.loads(capsys.readouterr().err)["error"]["reason"] == "database" and not db.exists()
    admitted(db)
    assert main([*NEXT[:5], str(tmp_path / "absent"), *NEXT[6:], "--db", str(db), "--json"]) == 1
    assert json.loads(capsys.readouterr().err)["error"]["reason"] == "tracker_root"


def test_one_round_runs_over_the_real_next_wiring_and_an_empty_factory_db(tmp_path: Path) -> None:
    """`open_next`'s real ports, the hold's included: no attempt and no slot, so no tracker call and no process."""
    db = tmp_path / "factory.db"
    con = Store(SCHEMA).open_rw(db)
    assert con is not None
    con.close()
    with cli_composition.open_next(db, tmp_path / "artifacts", GitViews(DEFAULT_GIT_READ_SECONDS), str(tmp_path)) as ports:
        assert not isinstance(ports, Failed) and ports.holding.status("tasks", "tl-1") is None
        found = run_round(ports, NextRequest("tasks", str(tmp_path), tmp_path, "auto", StepSettings(), HIGH_PLAN, 30))
    assert isinstance(found, Round) and (found.moves, found.stopped) == ((), "no_free_slot")


class Run:
    """The stubbed rounds: the opener's value passed through, the requests recorded, `ended` returned or raised."""

    def __init__(self, ended: Ended | BaseException) -> None:
        self.ended, self.opened, self.requests = ended, list[tuple[Path, Path, object]](), list[object]()
        self.ctrl_c = True

    @contextmanager
    def opener(self, database: Path, artifacts: Path, _views: GitViews, request: object) -> Generator[object]:
        self.opened.append((database, artifacts, request))
        yield self

    def run(self, given: object, request: object) -> Ended:
        assert given is self
        self.requests.append(request)
        if isinstance(self.ended, BaseException):
            raise self.ended
        return self.ended


def stubbed(monkeypatch: pytest.MonkeyPatch, ended: Ended | BaseException) -> Run:
    run = Run(ended)
    monkeypatch.setattr(cli_composition, "open_rounds", run.opener)
    monkeypatch.setattr(cli_step, "run_rounds", run.run)
    return run


def test_rounds_flags_reach_the_opener_and_print_a_start_and_an_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run, art = stubbed(monkeypatch, Ended("tasks", "interrupted")), tmp_path / "art"
    assert main([*ROUNDS, "--db", str(tmp_path / "f.db"), "--artifacts", str(art)]) == 0
    request = cli_step.NextRequest("tasks", "/tracker", Path("/checkout"), "auto", StepSettings(), HIGH_PLAN, 30)
    assert run.opened == [(tmp_path / "f.db", art, request)] and run.requests == [cli_step.RoundsRequest("tasks", 60)]
    output = capsys.readouterr()
    assert (
        output.out.splitlines()
        == [
            "Rounds for backlog tasks every 60 s, taking tasks labelled 'auto', none new while 3 or more tasks of this backlog "
            "are in flight "
            "(a step running, or passed and waiting to be landed, by a round under the profile's `land: auto`, else by a person); "
            f"log: {art / 'rounds.log'}; stop with Ctrl-C",
            "Rounds stopped: interrupted. Launched steps keep running; restarting scheduling continues them.",
        ]
        and output.err == ""
    )
    config = tmp_path / "scratch.toml"
    config.write_text("round_seconds = 90\n")
    assert main(["--config", str(config), *ROUNDS, "--round-seconds", "30", "--artifacts", str(art), "--json"]) == 0
    assert run.requests[-1] == cli_step.RoundsRequest("tasks", 30)
    assert [json.loads(line) for line in capsys.readouterr().out.splitlines()] == [
        {"status": "rounds", "backlog": "tasks", "every": 30, "log": str(art / "rounds.log"), "label": "auto", "max_running": 3},
        {"status": "ended", "backlog": "tasks", "reason": "interrupted", "detail": None},
    ]


def test_the_start_line_names_sigterm_when_ctrl_c_is_ignored(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    stubbed(monkeypatch, Ended("tasks", "interrupted")).ctrl_c = False
    assert main(ROUNDS) == 0
    assert "; Ctrl-C is ignored here: stop with SIGTERM\n" in capsys.readouterr().out


def test_a_whole_round_refusal_ends_the_rounds_with_exit_1(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    stubbed(monkeypatch, Ended("tasks", "refused:database", "No readable factory.db"))
    assert main(ROUNDS) == 1
    output = capsys.readouterr()
    assert output.out.startswith("Rounds for backlog tasks every 60 s")
    assert output.err.splitlines() == ["tl rounds start: refused:database", "No readable factory.db", automatic_guide("database")]


@pytest.mark.parametrize("structured", [False, True])
def test_a_second_ctrl_c_exits_130(structured: bool, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    stubbed(monkeypatch, KeyboardInterrupt())
    assert main([*ROUNDS, *(["--json"] if structured else [])]) == 130
    err = capsys.readouterr().err
    assert (
        json.loads(err) == {"status": "ended", "backlog": "tasks", "reason": "abrupt", "detail": None}
        if structured
        else (err == "Stopped at once.\n")
    )


def test_a_factory_db_that_exists_but_cannot_be_opened_backs_off_while_an_absent_one_ends(tmp_path: Path) -> None:
    db = tmp_path / "factory.db"
    request = cli_step.NextRequest("tasks", str(tmp_path), Path("/checkout"), "auto", StepSettings(), HIGH_PLAN, 30)
    once = cli_composition.one_round(db, tmp_path / "art", GitViews(DEFAULT_GIT_READ_SECONDS), request, lambda: False)
    absent = once(frozenset())
    assert isinstance(absent, Failed) and (absent.kind, absent.reason) == ("refused", "database")
    db.write_bytes(b"not a database, or one locked past the busy timeout")
    unopened = once(frozenset())
    assert isinstance(unopened, Failed) and (unopened.kind, unopened.reason) == ("unavailable", "store")


def test_rounds_refuse_a_short_interval_before_opening_anything(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = stubbed(monkeypatch, Ended("tasks", "interrupted"))
    assert main([*ROUNDS, "--round-seconds", "4", "--json"]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert (error["kind"], error["reason"]) == ("refused", "interval") and run.opened == []
    assert main([*ROUNDS, "--round-seconds", "4"]) == 1
    assert CONFIG["interval"] in capsys.readouterr().err


def test_rounds_require_minutes_and_the_help_names_the_stop(capsys: pytest.CaptureFixture[str]) -> None:
    at = ROUNDS.index("--minutes")
    with pytest.raises(SystemExit) as result:
        main([*ROUNDS[:at], *ROUNDS[at + 2 :]])
    assert result.value.code == 2 and "--minutes" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["rounds", "start", "--help"])
    shown = " ".join(capsys.readouterr().out.split())
    assert "Scheduling starts with a round immediately, then repeats at the configured interval and when a slot becomes free." in shown
    assert "Ctrl-C once stops scheduling after the current move; twice exits immediately. Launched steps keep running." in shown
    assert "SIGTERM is needed to stop scheduling" in shown
    assert ("Each round holds stopped tasks it took, advances completed claimed tasks, then starts approved ready tasks") in shown


def test_the_real_opener_refuses_inputs_a_missing_database_and_a_second_rounds_process_before_any_round(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every refusal comes before the lock (except `rounds_running`) and before the SIGINT handler: no handler installed."""
    db = tmp_path / "factory.db"
    at = ROUNDS.index("--label") + 1
    assert main([*ROUNDS[:at], " ", *ROUNDS[at + 1 :], "--db", str(db), "--json"]) == 1
    assert json.loads(capsys.readouterr().err)["error"]["reason"] == "label"
    assert main([*ROUNDS, "--db", str(db), "--json"]) == 1
    assert json.loads(capsys.readouterr().err)["error"]["reason"] == "database" and list(tmp_path.iterdir()) == []
    admitted(db)
    held = rounds_lock.hold(db, "tasks")
    try:
        assert main([*ROUNDS, "--db", str(db)]) == 1
    finally:
        held.release()
    output = capsys.readouterr()
    assert output.out == "" and "tl rounds start: refused:rounds_running" in output.err and step_guide.GUIDE["rounds_running"] in output.err
