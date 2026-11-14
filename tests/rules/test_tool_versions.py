"""Local gates reject executable and committed tool-version drift."""

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("check_tool_versions", ROOT / "tools/check_tool_versions.py")
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)

SUPPORTED = {
    "git": "git version 2.56.0",
    "codex": "codex-cli 0.162.1",
    "python": "Python 3.15.0",
    "tailwind": "≈ tailwindcss v4.1.11\n\nUsage:\n  tailwindcss [options]",
}
PINS = {"git": "2.56.0", "codex": "0.162.1", "python": "3.15.0", "tailwind": "4.1.11"}


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


@pytest.mark.parametrize("tool", SUPPORTED)
def test_mismatched_tool_fails(declarations: Path, capsys: pytest.CaptureFixture[str], tool: str) -> None:
    probes = {**SUPPORTED, tool: SUPPORTED[tool].replace(PINS[tool], "0.0.0")}
    assert run(declarations, probes) == 1
    error = capsys.readouterr().err
    assert f"{tool}: expected {PINS[tool]}" in error
    assert "0.0.0" in error


@pytest.mark.parametrize("tool", SUPPORTED)
@pytest.mark.parametrize("detail", ["", "command not found\nprobe failed", "malformed version", "\nprobe failed"])
def test_missing_failed_and_malformed_probes_fail(
    declarations: Path, capsys: pytest.CaptureFixture[str], tool: str, detail: str,
) -> None:
    output = SUPPORTED[tool] + detail if detail == "\nprobe failed" else detail
    assert run(declarations, {**SUPPORTED, tool: output}) == 1
    error = capsys.readouterr().err
    assert f"{tool}: expected {PINS[tool]}" in error
    assert "executable reported" in error


@pytest.mark.parametrize(
    ("name", "old", "new", "tool", "declaration"),
    [
        (".python-version", "3.15.0", "3.15", "python", ".python-version"),
        ("mise.lock", 'version = "0.162.1"', 'version = "0.162.2"', "codex", "mise.lock"),
        ("mise.lock", 'version = "3.15.0"', 'version = "3.15.1"', "python", "mise.lock"),
        ("mise.lock", 'version = "4.1.11"', 'version = "4.1.12"', "tailwind", "mise.lock"),
        ("mise.lock", 'backend = "aqua:openai/codex"', 'backend = "npm:@openai/codex"', "codex", "mise.lock"),
        ("mise.lock", '"aqua:openai/codex"', '"aqua:other"', "codex", "mise.lock"),
        ("src/taskloop/dash/static/dash.css", "v4.1.11", "v4.1.12", "tailwind", "dash.css"),
    ],
)
def test_committed_declaration_drift_fails(
    declarations: Path, capsys: pytest.CaptureFixture[str], name: str, old: str, new: str, tool: str, declaration: str,
) -> None:
    target = declarations / name
    original = target.read_text()
    assert old in original
    target.write_text(original.replace(old, new))
    assert run(declarations, SUPPORTED) == 1
    error = capsys.readouterr().err
    assert f"{tool}: expected {PINS[tool]}" in error
    assert declaration in error


@pytest.mark.parametrize("replacement", ['python = "latest"', 'python = 315'])
def test_authoritative_pins_must_be_exact_versions(
    declarations: Path, capsys: pytest.CaptureFixture[str], replacement: str,
) -> None:
    target = declarations / "mise.toml"
    target.write_text(target.read_text().replace('python = "3.15.0"', replacement))
    assert run(declarations, SUPPORTED) == 1
    assert "tools.python" in capsys.readouterr().err


def test_missing_declaration_is_reported(declarations: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (declarations / "mise.lock").unlink()
    assert run(declarations, SUPPORTED) == 1
    assert "mise.lock" in capsys.readouterr().err
