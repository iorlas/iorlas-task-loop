"""Stage test selection follows forward stage imports and selects only contracts of dependencies."""

import io
import sys
from pathlib import Path

import pytest
from test_pkg import closure, main, selection


def tree(root: Path) -> None:
    """Build stage edges write -> look -> checks -> write and an unrelated stage."""
    sources = {
        "write/__init__.py": "",
        "write/body.py": "from taskloop.app.look import api\n",
        "look/__init__.py": "from ..checks import api\n",
        "checks/__init__.py": "",
        "checks/api.py": "import taskloop.app.write.body\n",
        "plan/api.py": "",
        "plan/__init__.py": "",
    }
    for name, source in sources.items():
        path = root / "src/taskloop/app" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    for folder in ("write", "look/contract", "look/unit", "checks/contract", "plan/contract"):
        (root / "tests" / folder).mkdir(parents=True)


def test_selection(tmp_path):
    tree(tmp_path)
    assert closure(tmp_path, "write") == {"look", "checks"}
    assert selection(tmp_path, "write") == ["tests/write", "tests/checks/contract", "tests/look/contract"]


def test_missing_test_folders(tmp_path):
    tree(tmp_path)
    assert selection(tmp_path, "plan") == ["tests/plan"]
    (tmp_path / "tests/write").rmdir()
    (tmp_path / "tests/checks/contract").rmdir()
    assert selection(tmp_path, "write") == ["tests/look/contract"]


def test_unknown_stage(tmp_path, monkeypatch):
    tree(tmp_path)
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr)
    with pytest.raises(SystemExit) as error:
        main(["unknown"], root=tmp_path)
    assert error.value.code == 2
    assert "known stages: checks, look, plan, write" in stderr.getvalue()
