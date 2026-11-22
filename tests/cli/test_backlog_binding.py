"""Per-backlog bindings in the machine config: the pure resolver (flag > file), their refusals, and the commands that use them."""

import json
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest

from taskloop import cli_composition, cli_step
from taskloop.agents.settings import Overrides, StepSettings
from taskloop.cli import main
from taskloop.git_views import GitViews
from taskloop.inspection_guide import CONFIG
from taskloop.machine_config import (
    Binding,
    ConfigRefused,
    Effective,
    Flags,
    resolve,
    resolve_backlog,
    resolve_checkout,
    resolve_label,
    resolve_tracker_root,
)
from taskloop.operations import Round

HOME = Path("/home/someone")
TABLE = 'backlog = "tasks"\n[backlogs.tasks]\ntracker_root = "~/tracker"\ncheckout = "/checkout"\nlabel = "auto"\n'


def settings(text: str = TABLE) -> Effective:
    found = resolve(text, Flags(), HOME)
    assert isinstance(found, Effective)
    return found


def test_the_file_fills_each_binding_field_and_the_flag_wins() -> None:
    found = settings()
    assert found.backlogs == {"tasks": Binding(HOME / "tracker", Path("/checkout"), "auto")}
    assert resolve_backlog(found, None) == "tasks" and resolve_backlog(found, "other") == "other"
    assert resolve_tracker_root(found, "tasks", None) == str(HOME / "tracker")
    assert resolve_tracker_root(found, "tasks", "/flag") == "/flag"
    assert resolve_checkout(found, "tasks", None) == Path("/checkout") and resolve_checkout(found, "tasks", "/c") == Path("/c")
    assert resolve_label(found, "tasks", None) == "auto" and resolve_label(found, "tasks", "x") == "x"


def test_a_missing_backlog_or_binding_value_is_refused_by_name() -> None:
    assert resolve_backlog(settings(""), None) == ConfigRefused("backlog_missing", "backlog", "No backlog is given or configured")
    partial = settings('[backlogs.tasks]\nlabel = "auto"\n')
    refused = resolve_checkout(partial, "tasks", None)
    assert isinstance(refused, ConfigRefused) and (refused.reason, refused.key) == ("binding_missing", "checkout")
    other = resolve_label(partial, "other", None)  # a backlog the file does not mention
    assert isinstance(other, ConfigRefused) and (other.reason, other.key) == ("binding_missing", "label")
    assert resolve_label(partial, "other", "flag") == "flag"


@pytest.mark.parametrize(
    "text, reason, key",
    [
        ('[backlogs.tasks]\ncheckout = "relative"\n', "relative_path", "backlogs.tasks.checkout"),
        ("[backlogs.tasks]\ntracker_root = 3\n", "type", "backlogs.tasks.tracker_root"),
        ('[backlogs.tasks]\nlabel = ""\n', "type", "backlogs.tasks.label"),
        ("[backlogs.tasks]\nlabel = 1\n", "type", "backlogs.tasks.label"),
        ('[backlogs.tasks]\nbranch = "x"\n', "unknown_key", "backlogs.tasks.branch"),
        ('backlogs = "tasks"\n', "type", "backlogs"),
        ("[backlogs]\ntasks = 1\n", "type", "backlogs.tasks"),
    ],
)
def test_a_bad_backlogs_table_is_refused(text: str, reason: str, key: str) -> None:
    refused = resolve(text, Flags(), HOME)
    assert isinstance(refused, ConfigRefused) and (refused.reason, refused.key) == (reason, key)


def test_every_new_reason_has_a_plain_guide() -> None:
    for reason in ("backlog_missing", "binding_missing"):
        assert len(CONFIG[reason].split()) >= 6


def test_config_show_prints_each_binding_key_with_its_file_source(capsys: pytest.CaptureFixture[str]) -> None:
    config = Path.home() / "c.toml"
    config.parent.mkdir(parents=True)
    config.write_text('[backlogs.b]\nlabel = "auto"\n[backlogs.a]\ncheckout = "/c"\ntracker_root = "/t"\n')
    assert main(["--config", str(config), "config", "show", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)["settings"]
    keys = [key for key in shown if key.startswith("backlogs.")]
    assert keys == ["backlogs.a.tracker_root", "backlogs.a.checkout", "backlogs.b.label"]
    assert shown["backlogs.a.checkout"] == {"value": "/c", "source": "file"}
    assert main(["--config", str(config), "config", "show"]) == 0
    assert "backlogs.b.label = auto (file)" in capsys.readouterr().out


def test_a_round_with_only_the_config_binding_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    config = Path.home() / "c.toml"
    config.parent.mkdir(parents=True)
    config.write_text(TABLE.replace("~/tracker", "/tracker"))
    opened: list[str] = []
    requests: list[object] = []

    @contextmanager
    def opener(_database: Path, _artifacts: Path, _views: GitViews, tracker_root: str) -> Generator[object]:
        opened.append(tracker_root)
        yield object()

    monkeypatch.setattr(cli_composition, "open_next", opener)
    monkeypatch.setattr(cli_step, "run_round", lambda _ports, request: requests.append(request) or Round("tasks", ()))
    assert main(["--config", str(config), "rounds", "once", "--model", "m", "--plan-effort", "high", "--minutes", "30"]) == 0
    assert opened == ["/tracker"]
    assert requests == [
        cli_step.NextRequest("tasks", "/tracker", Path("/checkout"), "auto", StepSettings(), Overrides(model="m", plan_effort="high"), 30)
    ]


@pytest.mark.parametrize("structured", [False, True])
def test_a_missing_binding_value_is_refused_with_the_guide(structured: bool, capsys: pytest.CaptureFixture[str]) -> None:
    config = Path.home() / "c.toml"
    config.parent.mkdir(parents=True)
    config.write_text('backlog = "tasks"\n[backlogs.tasks]\ntracker_root = "/tracker"\ncheckout = "/checkout"\n')
    argv = ["--config", str(config), "rounds", "once", "--minutes", "30", *(["--json"] if structured else [])]
    assert main(argv) == 1
    output = capsys.readouterr()
    assert output.out == ""
    if structured:
        error = json.loads(output.err)["error"]
        assert (error["kind"], error["reason"]) == ("refused", "binding_missing") and "label" in error["message"]
    else:
        assert output.err.startswith("tl rounds once: refused:binding_missing") and CONFIG["binding_missing"] in output.err


def test_task_show_without_a_backlog_is_refused_and_a_configured_one_is_read(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["task", "show", "t-1", "--tracker-root", "/tracker"]) == 1
    assert CONFIG["backlog_missing"] in capsys.readouterr().err
    config = Path.home() / "c.toml"
    config.parent.mkdir(parents=True)
    config.write_text('backlog = "tasks"\n[backlogs.tasks]\ntracker_root = "/tracker"\n')
    assert main(["--config", str(config), "task", "show", "t-1", "--json"]) == 1  # reaches the tracker, which is absent here
    assert "backlog_missing" not in capsys.readouterr().err
