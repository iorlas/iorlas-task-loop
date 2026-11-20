"""Local gates reject executable and committed tool-version drift."""

import importlib.util
import shutil
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("check_tool_versions", ROOT / "tools/check_tool_versions.py")
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)

SUPPORTED = {
    "git": "git version 2.54.0",
    "python": "Python 3.15.0",
    "tailwind": "≈ tailwindcss v4.1.11\n\nUsage:\n  tailwindcss [options]",
}
PINS = {"git": "2.54.0", "python": "3.15.0", "tailwind": "4.1.11"}


@pytest.fixture
def declarations(tmp_path: Path) -> Path:
    for name in ("mise.toml", "mise.lock", ".python-version", "src/taskloop/dash/static/dash.css"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    return tmp_path


def run(root: Path, probes: dict[str, str]) -> int:
    arguments = ["--root", str(root)]
    for name, output in probes.items():
        arguments.extend((f"--{name}", output))
    return validator.main(arguments)


def test_supported_executables_and_declarations_pass(declarations: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(declarations, SUPPORTED) == 0
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("tool", ["python", "tailwind"])
def test_mismatched_tool_fails(declarations: Path, capsys: pytest.CaptureFixture[str], tool: str) -> None:
    probes = {**SUPPORTED, tool: SUPPORTED[tool].replace(PINS[tool], "0.0.0")}
    assert run(declarations, probes) == 1
    error = capsys.readouterr().err
    assert f"{tool}: expected {PINS[tool]}" in error
    assert "0.0.0" in error


@pytest.mark.parametrize("tool", SUPPORTED)
@pytest.mark.parametrize("detail", ["", "command not found\nprobe failed", "malformed version", "\nprobe failed"])
def test_missing_failed_and_malformed_probes_fail(
    declarations: Path,
    capsys: pytest.CaptureFixture[str],
    tool: str,
    detail: str,
) -> None:
    output = SUPPORTED[tool] + detail if detail == "\nprobe failed" else detail
    assert run(declarations, {**SUPPORTED, tool: output}) == 1
    error = capsys.readouterr().err
    assert tool in error
    assert "executable reported" in error


@pytest.mark.parametrize(
    ("name", "old", "new", "tool", "declaration"),
    [
        ("mise.lock", 'version = "4.1.11"', 'version = "4.1.12"', "tailwind", "mise.lock"),
        ("src/taskloop/dash/static/dash.css", "v4.1.11", "v4.1.12", "tailwind", "dash.css"),
    ],
)
def test_committed_declaration_drift_fails(
    declarations: Path,
    capsys: pytest.CaptureFixture[str],
    name: str,
    old: str,
    new: str,
    tool: str,
    declaration: str,
) -> None:
    target = declarations / name
    original = target.read_text()
    assert old in original
    target.write_text(original.replace(old, new))
    assert run(declarations, SUPPORTED) == 1
    error = capsys.readouterr().err
    assert f"{tool}: expected {PINS[tool]}" in error
    assert declaration in error


@pytest.mark.parametrize("version", ["git version 2.54.1", "git version 2.60.0", "git version 3.0.0"])
def test_git_at_or_above_the_floor_passes(declarations: Path, version: str) -> None:
    assert run(declarations, {**SUPPORTED, "git": version}) == 0


@pytest.mark.parametrize("version", ["git version 2.53.9", "git version 1.99.0", "git version 2.9.0"])
def test_git_below_the_floor_fails(declarations: Path, capsys: pytest.CaptureFixture[str], version: str) -> None:
    assert run(declarations, {**SUPPORTED, "git": version}) == 1
    error = capsys.readouterr().err
    assert "git: expected at least 2.54.0" in error and version.rpartition(" ")[2] in error


def test_mise_has_no_codex_and_names_git_as_a_minimum() -> None:
    config = tomllib.loads((ROOT / "mise.toml").read_text())
    assert "aqua:openai/codex" not in config["tools"] and "git_version" not in config["vars"]
    assert config["vars"]["git_min_version"] == "2.54.0"
    assert "openai/codex" not in (ROOT / "mise.lock").read_text()


@pytest.mark.parametrize("replacement", ["3.15", "latest", ""])
def test_python_pin_is_one_exact_version_in_python_version_file(
    declarations: Path,
    capsys: pytest.CaptureFixture[str],
    replacement: str,
) -> None:
    (declarations / ".python-version").write_text(replacement + "\n")
    assert run(declarations, SUPPORTED) == 1
    assert "python" in capsys.readouterr().err


def test_mise_does_not_pin_python() -> None:
    assert "python" not in tomllib.loads((ROOT / "mise.toml").read_text())["tools"]


def test_missing_declaration_is_reported(declarations: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (declarations / "mise.lock").unlink()
    assert run(declarations, SUPPORTED) == 1
    assert "mise.lock" in capsys.readouterr().err
