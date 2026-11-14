"""Buffered CLI output: no partial digest even when the final package fails."""

import json
import runpy
import sys
from pathlib import Path

import pytest
from git_porcelain import GitUnavailable, Repo
from shelf_digest_fixtures import COMMIT, SOURCE_COMMIT, Case, complete_case

from taskloop.shelf_digest import cli
from taskloop.shelf_digest.generate import Digest


def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Case, list[Path]]:
    case = complete_case(tmp_path)
    case.root.trees["HEAD"] = case.root.trees[SOURCE_COMMIT]
    seen: list[Path] = []

    def checkouts(_views: object, path: Path) -> Repo:
        seen.append(path)
        return case.shelf if path == (tmp_path / "shelf").resolve() else case.root

    monkeypatch.setattr(cli.GitViews, "checkouts", checkouts)
    return case, seen


def test_cli_success_and_default_checkout_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _, seen = wired(tmp_path, monkeypatch)
    assert cli.main(["--shelf", str(tmp_path / "shelf")]) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert captured.err == "" and result["source_commit"] == SOURCE_COMMIT and len(result["packages"]) == 6
    assert seen == [Path.cwd(), (tmp_path / "shelf").resolve()]
    assert captured.out.count('"source_commit"') == 1


def test_module_entry_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    wired(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["taskloop.shelf_digest", "--shelf", str(tmp_path / "shelf")])
    with pytest.raises(SystemExit) as error:
        runpy.run_module("taskloop.shelf_digest", run_name="__main__")
    assert error.value.code == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["source_commit"] == SOURCE_COMMIT and captured.err == ""


@pytest.mark.parametrize("arguments", [[], ["--shelf"], ["--shelf", "path", "--unknown"], ["--shel", "path"]])
def test_invalid_arguments_emit_only_stderr(arguments: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(arguments)
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "error:" in captured.err


@pytest.mark.parametrize("failure", ["revision", "object", "identity", "signature", "documentation", "encoding"])
def test_source_and_late_package_failures_leave_stdout_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failure: str,
) -> None:
    case, seen = wired(tmp_path, monkeypatch)
    revision = SOURCE_COMMIT
    if failure == "revision":
        revision = "missing"
    elif failure == "object":
        case.shelf.trees.clear()
    elif failure == "identity":
        case.shelf_files["packages/stream-proc/pyproject.toml"] = b'[project]\nname = "wrong"\nversion = "1.0"'
    elif failure == "signature":
        case.shelf_files["packages/stream-proc/src/stream_proc/__init__.py"] = b'__all__ = ["missing"]'
    elif failure == "documentation":
        case.shelf_files["packages/stream-proc/README.md"] = b"\xff"
    else:
        case.shelf_files["packages/any-agent/src/any_agent/events.py"] = b"\xff"
    assert cli.main(["--checkout", str(tmp_path / "root"), "--at", revision, "--shelf", str(tmp_path / "shelf")]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.strip()
    assert seen == [(tmp_path / "root").resolve(), (tmp_path / "shelf").resolve()]
    if failure in {"identity", "signature", "documentation"}:
        assert "stream-proc" in captured.err and COMMIT in captured.err


def test_render_failure_is_explained_before_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    wired(tmp_path, monkeypatch)

    def broken(_digest: Digest) -> bytes:
        raise ValueError("cannot serialize the complete digest")

    monkeypatch.setattr(cli, "render_digest", broken)
    assert cli.main(["--shelf", str(tmp_path / "shelf")]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "cannot serialize" in captured.err


def test_git_failure_is_explained_without_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def unavailable(_views: object, _path: Path) -> Repo:
        raise GitUnavailable("object storage unavailable")

    monkeypatch.setattr(cli.GitViews, "checkouts", unavailable)
    assert cli.main(["--shelf", "shelf"]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "object storage unavailable" in captured.err


@pytest.mark.parametrize("failure", ["contract", "overflow"])
def test_fact_and_bound_failures_are_buffered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failure: str,
) -> None:
    case, _ = wired(tmp_path, monkeypatch)
    if failure == "contract":
        path = "packages/any-agent/src/any_agent/events.py"
        case.shelf_files[path] = case.shelf_files[path].replace(b"usage: Tokens | None", b"usage: Tokens")
    else:
        monkeypatch.setattr("taskloop.shelf_digest.render.TOKEN_LIMIT", 1)
    assert cli.main(["--shelf", str(tmp_path / "shelf")]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.strip()
    assert ("contract" if failure == "contract" else "bound") in captured.err
