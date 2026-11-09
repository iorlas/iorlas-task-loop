"""Prove the installed distribution belongs only to this successor."""

import importlib.metadata
import importlib.util
import json
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlparse

import taskloop
from taskloop.cli import main

ROOT = Path(__file__).resolve().parents[2]


def test_noneditable_install_matches_current_source() -> None:
    assert Path(sys.prefix).resolve() == ROOT / ".venv"
    distribution = importlib.metadata.distribution("iorlas-task-loop")
    origin_text = distribution.read_text("direct_url.json")
    assert origin_text is not None
    origin = json.loads(origin_text)
    assert origin.get("dir_info", {}).get("editable", False) is False
    assert Path(unquote(urlparse(origin["url"]).path)).resolve() == ROOT
    assert distribution.requires is None
    installed = Path(taskloop.__file__).resolve().parent
    assert installed.is_relative_to(Path(sys.prefix).resolve())
    source = ROOT / "src" / "taskloop"
    assert {path.name for path in installed.glob("*.py")} == {path.name for path in source.glob("*.py")}
    for path in source.glob("*.py"):
        assert (installed / path.name).read_bytes() == path.read_bytes(), path.name
    entries = [entry for entry in distribution.entry_points if entry.group == "console_scripts"]
    assert [(entry.name, entry.value) for entry in entries] == [("tl", "taskloop.cli:main")]
    assert entries[0].load() is main


def test_no_baseline_or_editable_dependencies() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert project["project"]["dependencies"] == []
    assert "workspace" not in project.get("tool", {}).get("uv", {})
    assert "sources" not in project.get("tool", {}).get("uv", {})
    assert str(ROOT / "src") not in sys.path
    baseline = (
        "tlkernel", "tltestkit", "delegate", "tlland", "tldash", "tlwork", "tlareas", "tlartifacts",
        "tlasks", "tldelegate", "tlgate", "tlpipeline", "tlrelease", "tlslots",
    )
    for name in baseline:
        assert importlib.util.find_spec(name) is None, name
    for entry in sys.path:
        path = Path(entry).resolve()
        assert not any(part in {"_vendor", "packages"} for part in path.parts), path
