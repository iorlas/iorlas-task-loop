"""Prove the installed distribution belongs only to this successor."""

import importlib.metadata
import importlib.util
import json
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

import taskloop
from taskloop import cli

ROOT = Path(__file__).resolve().parents[2]


def test_noneditable_install_matches_current_source() -> None:
    assert Path(sys.prefix).resolve() == ROOT / ".venv"
    distribution = importlib.metadata.distribution("iorlas-task-loop")
    origin_text = distribution.read_text("direct_url.json")
    assert origin_text is not None
    origin = json.loads(origin_text)
    assert origin.get("dir_info", {}).get("editable", False) is False
    assert Path(unquote(urlparse(origin["url"]).path)).resolve() == ROOT
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert distribution.requires == project["project"]["dependencies"]
    installed = Path(taskloop.__file__).resolve().parent
    assert installed.is_relative_to(Path(sys.prefix).resolve())
    source = ROOT / "src" / "taskloop"
    assert {path.name for path in installed.glob("*.py")} == {path.name for path in source.glob("*.py")}
    for path in source.glob("*.py"):
        assert (installed / path.name).read_bytes() == path.read_bytes(), path.name
    entries = [entry for entry in distribution.entry_points if entry.group == "console_scripts"]
    assert [(entry.name, entry.value) for entry in entries] == [("tl", "taskloop.cli:main")]
    assert entries[0].load() is cli.main


# Every shared dependency and the shelf tag it is pinned at. stream-proc is pinned at any-agent's tag (a later
# commit than its own stream-proc-v0.7.0 tag): both must resolve to one shelf commit.
SHARED = {
    "git-porcelain": "git-porcelain-v0.18.1",
    "beads-client": "beads-client-v0.2.0",
    "any-agent": "any-agent-v0.9.0",
    "sqlite-store": "sqlite-store-v0.1.0",
    "process-lock": "process-lock-v0.2.1",
    "stream-proc": "any-agent-v0.9.0",
}


# Direct dependencies from PyPI, pinned exactly like the shelf ones, but not shelf packages (no tag, no source entry).
EDGE = {"pydantic"}


def locked_source(name: str) -> str:
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    return next(package for package in lock["package"] if package["name"] == name)["source"]["git"]


@pytest.mark.parametrize("name", sorted(SHARED))
def test_portable_shared_dependency(name: str) -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dependency = importlib.metadata.distribution(name)
    pinned = {f"{package}=={importlib.metadata.version(package)}" for package in set(SHARED) | EDGE}
    assert set(project["project"]["dependencies"]) == pinned
    tag = SHARED[name]
    assert "workspace" not in project.get("tool", {}).get("uv", {})
    assert set(project["tool"]["uv"]["sources"]) == set(SHARED)
    assert project["tool"]["uv"]["sources"][name] == {
        "git": "https://github.com/yoselabs/shelf.git",
        "subdirectory": f"packages/{name}",
        "tag": tag,
    }
    dependency_origin_text = dependency.read_text("direct_url.json")
    assert dependency_origin_text is not None
    dependency_origin = json.loads(dependency_origin_text)
    assert dependency_origin["url"] == "https://github.com/yoselabs/shelf.git"
    assert dependency_origin["subdirectory"] == f"packages/{name}"
    assert dependency_origin["vcs_info"]["requested_revision"] == tag
    source = locked_source(name)
    assert source.startswith("https://github.com/yoselabs/shelf.git?")
    assert f"subdirectory=packages%2F{name}" in source or f"subdirectory=packages/{name}" in source
    assert f"tag={tag}" in source
    assert source.rsplit("#", 1)[1] == dependency_origin["vcs_info"]["commit_id"]


def test_stream_proc_comes_from_any_agents_commit() -> None:
    assert locked_source("stream-proc").rsplit("#", 1)[1] == locked_source("any-agent").rsplit("#", 1)[1]


def test_no_baseline_or_editable_dependencies() -> None:
    assert str(ROOT / "src") not in sys.path
    baseline = (
        "tlkernel",
        "tltestkit",
        "delegate",
        "tlland",
        "tldash",
        "tlwork",
        "tlareas",
        "tlartifacts",
        "tlasks",
        "tldelegate",
        "tlgate",
        "tlpipeline",
        "tlrelease",
        "tlslots",
    )
    for name in baseline:
        assert importlib.util.find_spec(name) is None, name
    for entry in sys.path:
        path = Path(entry).resolve()
        assert not any(part in {"_vendor", "packages"} for part in path.parts), path
