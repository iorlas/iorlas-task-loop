"""Every directly run script prints its usage for --help, exits 2 on an unknown flag and changes nothing."""

import runpy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = (
    "tools/check_tool_versions.py",
    "tools/generate_import_contracts.py",
    "docs/design/tl-8bh9.14.109/measure.py",
    "docs/design/tl-8bh9.14.109/query_study.py",
)


def run(script: str, flag: str, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(sys, "argv", [script, flag])
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(ROOT / script), run_name="__main__")
    assert isinstance(stopped.value.code, int)
    return stopped.value.code


@pytest.mark.parametrize("script", SCRIPTS)
def test_help_prints_usage_and_exits_zero(
    script: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    assert run(script, "--help", monkeypatch) == 0
    assert capsys.readouterr().out.startswith("usage:")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("script", SCRIPTS)
def test_unknown_flag_exits_two(
    script: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    assert run(script, "--no-such-flag", monkeypatch) == 2
    assert capsys.readouterr().err.startswith("usage:")
    assert list(tmp_path.iterdir()) == []
