"""Flag contracts through main: selected settings, execution requests and dashboard lifetime, without live ports."""

import json
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest

from taskloop import cli_composition, cli_step, dash_composition
from taskloop.cli import main
from taskloop.dash_composition import DashRequest
from taskloop.git_views import GitViews
from taskloop.operations import Adoption, Ended, Failed, Round
from taskloop.round import NextRequest
from taskloop.rounds import RoundsRequest
from taskloop.slots import Adopted, SlotGit

CHOICES = ["--backlog", "tasks", "--tracker-root", "/tracker", "--checkout", "/checkout", "--label", "approved",
           "--model", "m", "--effort", "high", "--minutes", "30"]


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


class Execution:
    """Opaque execution ports returned by composition, and the operation boundaries that consume them."""

    def __init__(self) -> None:
        self.requests: list[NextRequest] = []
        self.rounds: list[RoundsRequest] = []
        self.events: list[str] = []
        self.ctrl_c = True
        self.ending: Ended | KeyboardInterrupt = Ended("tasks", "interrupted")

    @contextmanager
    def open_next(self, _db: Path, _artifacts: Path, _views: GitViews, _tracker: str) -> Generator[Execution]:
        self.events.append("next entered")
        yield self

    @contextmanager
    def open_rounds(self, _db: Path, _artifacts: Path, _views: GitViews, request: NextRequest) -> Generator[Execution]:
        self.requests.append(request)
        self.events.append("rounds entered")
        try:
            yield self
        finally:
            self.events.append("rounds closed")

    def next(self, ports: object, request: NextRequest) -> Round:
        assert ports is self
        self.requests.append(request)
        return Round("tasks", ())

    def run(self, ports: object, request: RoundsRequest) -> Ended:
        assert ports is self
        self.rounds.append(request)
        self.events.append("rounds ran")
        if isinstance(self.ending, KeyboardInterrupt):
            raise self.ending
        return self.ending


@pytest.fixture
def execution(monkeypatch: pytest.MonkeyPatch) -> Execution:
    run = Execution()
    monkeypatch.setattr(cli_composition, "open_next", run.open_next)
    monkeypatch.setattr(cli_composition, "open_rounds", run.open_rounds)
    monkeypatch.setattr(cli_step, "run_round", run.next)
    monkeypatch.setattr(cli_step, "run_rounds", run.run)
    return run


class Dashboard:
    def __init__(self, events: list[str], answer: tuple[str, int] | Failed = ("127.0.0.1", 8123)) -> None:
        self.events, self.answer = events, answer
        self.requests: list[DashRequest | None] = []

    @contextmanager
    def serving(self, request: DashRequest | None, _views: GitViews) -> Generator[tuple[str, int] | Failed | None]:
        self.requests.append(request)
        self.events.append("dashboard entered")
        try:
            yield None if request is None else self.answer
        finally:
            self.events.append("dashboard closed")


@pytest.mark.parametrize("port", [None, 0, 8123])
@pytest.mark.parametrize("structured", [False, True])
def test_dashboard_selection_lifetime_and_output(
    port: int | None, structured: bool, execution: Execution, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    dashboard, db, artifacts = Dashboard(execution.events), tmp_path / "factory.db", tmp_path / "artifacts"
    monkeypatch.setattr(dash_composition, "serving", dashboard.serving)
    flags = ([] if port is None else ["--dash-port", str(port)]) + (["--json"] if structured else [])
    assert main(["step", "rounds", *CHOICES, "--db", str(db), "--artifacts", str(artifacts), *flags]) == 0
    assert dashboard.requests == [None if port is None else DashRequest("tasks", "/tracker", "approved", port, db, artifacts)]
    assert execution.events == ["rounds entered", "dashboard entered", "rounds ran", "dashboard closed", "rounds closed"]
    output = capsys.readouterr()
    notice = "Dashboard: http://127.0.0.1:8123/\n"
    if structured:
        assert [json.loads(line) for line in output.out.splitlines()] == [
            {"status": "rounds", "backlog": "tasks", "every": 60, "log": str(artifacts / "rounds.log"),
             "label": "approved", "max_running": 3},
            {"status": "ended", "backlog": "tasks", "reason": "interrupted", "detail": None},
        ]
        assert output.err == ("" if port is None else notice)
    else:
        assert output.err == ""
        assert (notice in output.out) == (port is not None)


def test_dashboard_closes_when_rounds_are_interrupted(
    execution: Execution, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    dashboard = Dashboard(execution.events)
    execution.ending = KeyboardInterrupt()
    monkeypatch.setattr(dash_composition, "serving", dashboard.serving)
    assert main(["step", "rounds", *CHOICES, "--dash-port", "0", "--json"]) == 130
    output = capsys.readouterr()
    assert json.loads(output.out)["status"] == "rounds"
    notice, ending = output.err.splitlines()
    assert notice == "Dashboard: http://127.0.0.1:8123/"
    assert json.loads(ending) == {"status": "ended", "backlog": "tasks", "reason": "abrupt", "detail": None}
    assert execution.events[-3:] == ["rounds ran", "dashboard closed", "rounds closed"]


@pytest.mark.parametrize("refused", [False, True])
def test_dashboard_startup_warning_leaves_rounds_to_determine_exit(
    refused: bool, execution: Execution, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    dashboard = Dashboard(execution.events, Failed("unavailable", "dashboard_port", "Port 8123 occupied"))
    if refused:
        execution.ending = Ended("tasks", "refused:database", "Database unavailable")
    monkeypatch.setattr(dash_composition, "serving", dashboard.serving)
    assert main(["step", "rounds", *CHOICES, "--dash-port", "8123", "--json"]) == (1 if refused else 0)
    output = capsys.readouterr()
    assert output.err.startswith("Dashboard not started (Port 8123 occupied); the rounds go on without it\n")
    assert execution.rounds == [RoundsRequest("tasks", 60)]
    assert execution.events[-3:] == ["rounds ran", "dashboard closed", "rounds closed"]
    assert len([json.loads(line) for line in output.out.splitlines()]) == (1 if refused else 2)
    if refused:
        assert json.loads(output.err.splitlines()[1])["reason"] == "refused:database"


@pytest.mark.parametrize(("configured", "explicit", "expected", "source"), [
    (None, None, 1, "default"), (4, None, 4, "file"), (4, 2, 2, "flag"),
])
def test_count_selects_effective_setting_and_reaches_adoption(
    configured: int | None, explicit: int | None, expected: int, source: str, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[int] = []

    def adopt(_db: Path, _checkout: Path, root: Path, count: int, _git: SlotGit) -> Adoption:
        calls.append(count)
        return Adoption(tuple(Adopted(f"s{number}", root / "repo" / f"s{number}") for number in range(1, count + 1)))

    monkeypatch.setattr(cli_composition, "adopt", adopt)
    config = tmp_path / "config.toml"
    config.write_text("" if configured is None else f"slot_count = {configured}\n")
    flags = [] if explicit is None else ["--count", str(explicit)]
    assert main(["--config", str(config), "config", "show", *flags, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["settings"]["slot_count"] == {"value": expected, "source": source}
    assert main(["--config", str(config), "slot", "adopt", "/checkout", *flags, "--json"]) == 0
    assert calls == [expected]
    assert len(json.loads(capsys.readouterr().out)["slots"]) == expected


@pytest.mark.parametrize("command", [["config", "show"], ["slot", "adopt", "/checkout"]])
@pytest.mark.parametrize("count", ["0", "-1", "two"])
def test_invalid_count_refuses_before_adoption(
    command: list[str], count: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def unexpected_adoption(*_arguments: object) -> Adoption:
        pytest.fail("invalid counts must not reach adoption")

    monkeypatch.setattr(cli_composition, "adopt", unexpected_adoption)
    if count == "two":
        with pytest.raises(SystemExit) as ended:
            main([*command, "--count", count, "--json"])
        assert ended.value.code == 2
        assert "invalid int value" in capsys.readouterr().err
    else:
        assert main([*command, "--count", count, "--json"]) == 1
        output = capsys.readouterr()
        assert output.out == ""
        assert json.loads(output.err)["error"]["reason"] == "count"


@pytest.mark.parametrize("operation", ["next", "rounds"])
def test_removed_max_new_is_a_usage_error_before_execution_ports(
    operation: str, execution: Execution, capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as ended:
        main(["step", operation, *CHOICES, "--max-new", "2"])
    assert ended.value.code == 2
    assert "unrecognized arguments: --max-new 2" in capsys.readouterr().err
    assert execution.events == [] and execution.requests == []


@pytest.mark.parametrize("operation", ["next", "rounds"])
@pytest.mark.parametrize("maximum", [None, 7])
@pytest.mark.parametrize("retake", [False, True])
def test_scheduling_choices_reach_each_commands_request(
    operation: str, maximum: int | None, retake: bool, execution: Execution, capsys: pytest.CaptureFixture[str],
) -> None:
    flags = ([] if maximum is None else ["--max-running", str(maximum)]) + (["--retake-lapsed"] if retake else [])
    assert main(["step", operation, *CHOICES, *flags, "--json"]) == 0
    expected = 3 if maximum is None else maximum
    assert execution.requests == [NextRequest("tasks", "/tracker", Path("/checkout"), "approved", "m", "high", 30,
                                             max_running=expected, retake=retake)]
    output = capsys.readouterr()
    assert output.err == ""
    if operation == "rounds":
        start, end = [json.loads(line) for line in output.out.splitlines()]
        assert start["max_running"] == expected and start["status"] == "rounds"
        assert end["reason"] == "interrupted"
    else:
        assert json.loads(output.out)["status"] == "round"


@pytest.mark.parametrize("retake", [False, True])
def test_rounds_announces_recovery_only_when_selected(
    retake: bool, execution: Execution, capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["step", "rounds", *CHOICES, *(["--retake-lapsed"] if retake else [])]) == 0
    assert ("(and its own lapsed claims)" in capsys.readouterr().out) == retake


@pytest.mark.parametrize("operation", ["next", "rounds"])
def test_retake_help_keeps_the_recovery_limit(operation: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as ended:
        main(["step", operation, "--help"])
    assert ended.value.code == 0
    shown = " ".join(capsys.readouterr().out.split())
    assert "After a factory.db discard only" in shown
    assert "expired lease and no attempt here" in shown
    assert "assumes this is the one factory on the tracker" in shown
