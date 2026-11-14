"""The one machine config reader: precedence per key, every refusal word, `~` against the given home, no environment source;
and `tl config show` on a home under tmp_path (the real ~/.config and ~/.local are never read or written)."""

import json
from pathlib import Path

import pytest

from taskloop import cli_composition
from taskloop.cli import main
from taskloop.machine_config import ConfigRefused, Effective, Flags, Setting, config_file, defaults, resolve

HOME = Path("/home/someone")


def test_no_file_and_no_flags_is_every_built_in_default() -> None:
    assert resolve(None, Flags(), HOME) == Effective(
        Setting(HOME / ".local/state/task-loop/factory.db", "default"),
        Setting(HOME / ".local/state/task-loop/artifacts", "default"),
        Setting(HOME / ".local/share/task-loop/slots", "default"),
        Setting(1, "default"),
        Setting(60, "default"),
        Setting(600, "default"),
        Setting(None, "default"),
    )
    assert config_file(HOME) == HOME / ".config/task-loop/config.toml"


@pytest.mark.parametrize("value", ["work", "other.backlog", " a key "])
def test_backlog_is_an_optional_file_default_using_task_scope_validation(value: str) -> None:
    found = resolve(f"backlog = {json.dumps(value)}", Flags(), HOME)
    assert isinstance(found, Effective)
    assert found.backlog == Setting(value, "file")


@pytest.mark.parametrize("key, flags, value", [
    ("db", Flags(db="/flag/f.db"), Path("/flag/f.db")),
    ("artifacts", Flags(artifacts="/flag/art"), Path("/flag/art")),
    ("slots_root", Flags(slots_root="/flag/slots"), Path("/flag/slots")),
    ("slot_count", Flags(slot_count=3), 3),
    ("round_seconds", Flags(round_seconds=30), 30),
    ("git_read_seconds", Flags(git_read_seconds=45), 45),
])
def test_flag_beats_file_beats_default_per_key(key: str, flags: Flags, value: Path | int) -> None:
    text = 'db = "/file/f.db"\nartifacts = "/file/art"\nslots_root = "/file/slots"\nslot_count = 2\nround_seconds = 90\n'
    text += 'git_read_seconds = 120\n'
    from_file = resolve(text, Flags(), HOME)
    assert isinstance(from_file, Effective)
    assert getattr(from_file, key).source == "file"
    flagged = resolve(text, flags, HOME)
    assert isinstance(flagged, Effective)
    assert getattr(flagged, key) == Setting(value, "flag")
    others = [name for name in ("db", "artifacts", "slots_root", "slot_count", "round_seconds", "git_read_seconds") if name != key]
    assert all(getattr(flagged, name).source == "file" for name in others)
    only_flag = resolve(None, flags, HOME)
    assert isinstance(only_flag, Effective)
    assert all(getattr(only_flag, name).source == "default" for name in others)


def test_tilde_is_expanded_against_the_given_home_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/elsewhere")
    found = resolve('db = "~/state/f.db"', Flags(artifacts="~"), HOME)
    assert isinstance(found, Effective)
    assert found.db == Setting(HOME / "state/f.db", "file")
    assert found.artifacts == Setting(HOME, "flag")


@pytest.mark.parametrize("text, flags, reason, key", [
    ("db = ", Flags(), "toml", ""),
    ("[db\n", Flags(), "toml", ""),
    ('db = "/a"\nsandbox = "x"\n', Flags(), "unknown_key", "sandbox"),
    ("[model]\nname = 'x'\n", Flags(), "unknown_key", "model"),
    ("db = 1", Flags(), "type", "db"),
    ("backlog = 1", Flags(), "type", "backlog"),
    ("backlog = true", Flags(), "type", "backlog"),
    ("backlog = []", Flags(), "type", "backlog"),
    ('backlog = ""', Flags(), "type", "backlog"),
    ('backlog = "  "', Flags(), "type", "backlog"),
    ('slot_count = "2"', Flags(), "type", "slot_count"),
    ("slot_count = true", Flags(), "type", "slot_count"),
    ("slot_count = 1.5", Flags(), "type", "slot_count"),
    ('db = "relative/f.db"', Flags(), "relative_path", "db"),
    ('slots_root = "~other/slots"', Flags(), "relative_path", "slots_root"),
    (None, Flags(artifacts="art"), "relative_path", "artifacts"),
    ('db = "relative.db"', Flags(db="/flag.db"), "relative_path", "db"),
    ("slot_count = 0", Flags(), "count", "slot_count"),
    (None, Flags(slot_count=-1), "count", "slot_count"),
    ("round_seconds = 4", Flags(), "interval", "round_seconds"),
    (None, Flags(round_seconds=4), "interval", "round_seconds"),
    ("round_seconds = 60", Flags(round_seconds=0), "interval", "round_seconds"),
    ("round_seconds = true", Flags(), "type", "round_seconds"),
    ("round_seconds = 60.0", Flags(), "type", "round_seconds"),
    ("git_read_seconds = 86401", Flags(), "interval", "git_read_seconds"),
    ("git_read_seconds = 99999999999999999999", Flags(), "interval", "git_read_seconds"),
    ("git_read_seconds = 29", Flags(), "interval", "git_read_seconds"),
    ("git_read_seconds = 600", Flags(git_read_seconds=5), "interval", "git_read_seconds"),
])
def test_every_refusal_has_its_fixed_word(text: str | None, flags: Flags, reason: str, key: str) -> None:
    refused = resolve(text, flags, HOME)
    assert isinstance(refused, ConfigRefused)
    assert (refused.reason, refused.key) == (reason, key)


def test_no_environment_variable_moves_any_fact(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    (tmp_path / "xdg/task-loop").mkdir(parents=True)
    (tmp_path / "xdg/task-loop/config.toml").write_text('db = "/from/xdg.db"')
    loaded = cli_composition.load_config(None, Flags(), lambda: tmp_path / "home")
    assert not isinstance(loaded, ConfigRefused)
    assert loaded.path == tmp_path / "home/.config/task-loop/config.toml"
    assert not loaded.exists
    assert loaded.settings == defaults(tmp_path / "home")


def test_an_unreadable_or_undecodable_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "dir.toml").mkdir()
    unreadable = cli_composition.load_config(str(tmp_path / "dir.toml"), Flags(), lambda: tmp_path)
    assert isinstance(unreadable, ConfigRefused) and unreadable.reason == "unreadable"
    (tmp_path / "bad.toml").write_bytes(b"db = '\xff'")
    undecodable = cli_composition.load_config(str(tmp_path / "bad.toml"), Flags(), lambda: tmp_path)
    assert isinstance(undecodable, ConfigRefused) and undecodable.reason == "toml"
    (tmp_path / "syntax.toml").write_text("db = ")
    syntax = cli_composition.load_config(str(tmp_path / "syntax.toml"), Flags(), lambda: tmp_path)
    assert isinstance(syntax, ConfigRefused) and syntax.detail.startswith(f"{tmp_path / 'syntax.toml'}: ")  # the file is named


def test_config_show_prints_values_sources_and_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    config = tmp_path / "scratch.toml"
    config.write_text('db = "~/scratch/factory.db"\nslot_count = 2\n')
    assert main(["--config", str(config), "config", "show", "--artifacts", str(tmp_path / "art"), "--json"]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    data = json.loads(output.out)
    agents = {key: value for key, value in data["settings"].items() if key.startswith("agents.")}
    assert agents["agents.plan.effort"] == {"value": "high", "source": "default"}
    assert agents["agents.implement.effort"] == {"value": "medium", "source": "default"}
    data["settings"] = {key: value for key, value in data["settings"].items() if not key.startswith("agents.")}
    assert data == {
        "file": {"path": str(config), "exists": True},
        "settings": {
            "db": {"value": str(tmp_path / "scratch/factory.db"), "source": "file"},
            "artifacts": {"value": str(tmp_path / "art"), "source": "flag"},
            "slots_root": {"value": str(tmp_path / ".local/share/task-loop/slots"), "source": "default"},
            "slot_count": {"value": 2, "source": "file"},
            "round_seconds": {"value": 60, "source": "default"},
            "git_read_seconds": {"value": 600, "source": "default"},
            "backlog": {"value": None, "source": "default"},
        },
    }
    assert main(["config", "show"]) == 0
    text = capsys.readouterr().out
    assert f"Config file: {tmp_path / '.config/task-loop/config.toml'} (missing: built-in defaults)" in text
    assert f"db = {tmp_path / '.local/state/task-loop/factory.db'} (default)" in text
    assert "backlog = unset (default)" in text
    assert not (tmp_path / ".config").exists() and not (tmp_path / ".local").exists()


@pytest.mark.parametrize("structured", [False, True])
def test_config_show_reports_the_configured_backlog(
    structured: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    config = tmp_path / "scratch.toml"
    config.write_text('backlog = "work"\n')
    assert main(["--config", str(config), "config", "show", *(["--json"] if structured else [])]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    if structured:
        assert json.loads(output.out)["settings"]["backlog"] == {"value": "work", "source": "file"}
    else:
        assert "backlog = work (file)" in output.out


@pytest.mark.parametrize("text", ['backlog = ""', 'backlog = "  "', "backlog = 7"])
@pytest.mark.parametrize("structured", [False, True])
def test_invalid_backlog_is_refused_even_with_an_explicit_show_override(
    text: str, structured: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    config = tmp_path / "scratch.toml"
    config.write_text(text)
    assert main(["--config", str(config), "step", "show", "t-1", "--backlog", "work", *(["--json"] if structured else [])]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    if structured:
        assert json.loads(output.err)["error"]["reason"] == "type"
        assert "backlog" in json.loads(output.err)["error"]["message"]
    else:
        assert output.err.startswith("tl step show: refused:type") and "backlog" in output.err
    assert not (tmp_path / ".local").exists()


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("argv", [["config", "show"], ["step", "list"], ["slot", "adopt", "."], ["step", "show", "t-1", "--backlog", "b"]])
def test_a_bad_config_refuses_every_command_with_exit_1(
    argv: list[str], structured: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    config = tmp_path / "scratch.toml"
    config.write_text('model = "x"\n')
    assert main(["--config", str(config), *argv, *(["--json"] if structured else [])]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    if structured:
        assert json.loads(output.err)["error"] | {"message": ""} == {"kind": "refused", "reason": "unknown_key", "message": ""}
    else:
        assert output.err.startswith(f"tl {argv[0]} {argv[1]}: refused:unknown_key")
    assert not (tmp_path / ".local").exists()


def test_an_explicit_config_file_must_exist_while_the_fixed_one_may_be_absent(tmp_path: Path) -> None:
    missing = cli_composition.load_config(str(tmp_path / "typo.toml"), Flags(), lambda: tmp_path)
    assert isinstance(missing, ConfigRefused) and missing.reason == "missing"
    absent = cli_composition.load_config(None, Flags(), lambda: tmp_path)
    assert not isinstance(absent, ConfigRefused) and not absent.exists and absent.settings == defaults(tmp_path)


def test_config_show_has_safe_policy_provenance_and_per_field_override_sources(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    policy = tmp_path / "settings.json"
    policy.write_text('{"hooks":{"opaque":"do-not-display"}}')
    config = tmp_path / "config.toml"
    config.write_text(f'''[agents.plan]
harness = "claude"
model = "opus"
[agents.plan.access]
settings_file = "{policy}"
''')
    assert main(["--config", str(config), "config", "show", "--effort", "low", "--json"]) == 0
    output = capsys.readouterr()
    values = json.loads(output.out)["settings"]
    assert "do-not-display" not in output.out and "hooks" not in output.out
    assert values["agents.plan.harness"] == {"value": "claude", "source": "file"}
    assert values["agents.plan.effort"] == values["agents.implement.effort"] == {"value": "low", "source": "flag"}
    assert values["agents.plan.access.settings_file"] == {"value": str(policy), "source": "file"}
    assert values["agents.plan.access.permission_mode"] == {"value": "dontAsk", "source": "default"}
    assert values["agents.plan.provider"] == {"value": "anthropic", "source": "derived"}


def test_invalid_file_choice_is_checked_even_when_a_flag_would_override_it(tmp_path: Path) -> None:
    result = resolve('[agents.implement]\nmodel = ""', Flags(), tmp_path)
    assert isinstance(result, ConfigRefused) and "agents.implement" in result.detail and "model" in result.detail


def test_config_show_compaction_provenance_survives_existing_flags(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[agents.implement]\ncompaction_token_limit = 100000\n")
    assert main(["--config", str(config), "config", "show", "--effort", "low", "--json"]) == 0
    values = json.loads(capsys.readouterr().out)["settings"]
    assert values["agents.implement.compaction_token_limit"] == {"value": "100000", "source": "file"}
    assert values["agents.plan.compaction_token_limit"] == {"value": "null", "source": "default"}


@pytest.mark.parametrize("value", ["true", "false", '"100000"', "100000.0", "0", "-1"])
def test_invalid_compaction_is_refused_before_admission(value: str, tmp_path: Path) -> None:
    result = resolve(f"[agents.implement]\ncompaction_token_limit = {value}\n", Flags(), tmp_path)
    assert isinstance(result, ConfigRefused)
    assert result.key == "agents.implement.compaction_token_limit"
