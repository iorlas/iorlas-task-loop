"""Buffered CLI output: no partial digest even when the final package fails."""

import json
import runpy
import sys
from pathlib import Path

import pytest
from git_porcelain import GitUnavailable, Repo
from shelf_digest_fixtures import SOURCE_COMMIT, MemoryDistributions, complete_case, installed_case

from taskloop.shelf_digest import cli
from taskloop.shelf_digest.generate import Digest


def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[MemoryDistributions, list[Path]]:
    case = complete_case(tmp_path)
    _, distributions = installed_case(case)
    case.root.trees["HEAD"] = case.root.trees[SOURCE_COMMIT]
    seen: list[Path] = []

    def checkouts(_views: object, path: Path) -> Repo:
        seen.append(path)
        return case.root

    monkeypatch.setattr(cli.GitViews, "checkouts", checkouts)
    monkeypatch.setattr(cli, "InstalledDistributions", lambda: distributions)
    return distributions, seen


@pytest.mark.parametrize("explicit", [False, True])
def test_cli_success_and_default_checkout_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], explicit: bool,
) -> None:
    _, seen = wired(tmp_path, monkeypatch)
    arguments = ["--checkout", str(tmp_path / "root"), "--at", SOURCE_COMMIT] if explicit else []
    assert cli.main(arguments) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert captured.err == "" and result["source_commit"] == SOURCE_COMMIT and len(result["packages"]) == 6
    assert seen == [(tmp_path / "root").resolve() if explicit else Path.cwd()]
    assert captured.out.count('"source_commit"') == 1


def test_module_entry_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    wired(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["taskloop.shelf_digest"])
    with pytest.raises(SystemExit) as error:
        runpy.run_module("taskloop.shelf_digest", run_name="__main__")
    assert error.value.code == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["source_commit"] == SOURCE_COMMIT and captured.err == ""


@pytest.mark.parametrize("arguments", [["--checkout"], ["--at"], ["--unknown"], ["--shelf", "path"], ["--check", "path"]])
def test_invalid_arguments_emit_only_stderr(arguments: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(arguments)
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "error:" in captured.err


@pytest.mark.parametrize("failure", ["revision", "missing", "identity", "source", "signature", "documentation", "encoding"])
def test_source_and_late_package_failures_leave_stdout_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failure: str,
) -> None:
    distributions, seen = wired(tmp_path, monkeypatch)
    stream = distributions.records["stream-proc"]
    revision = SOURCE_COMMIT
    if failure == "revision":
        revision = "missing"
    elif failure == "missing":
        del distributions.records["stream-proc"]
    elif failure == "identity":
        stream.record = stream.record.model_copy(update={"version": "wrong"})
    elif failure == "source":
        stream.contents.clear()
    elif failure == "signature":
        stream.contents["stream_proc/__init__.py"] = b'__all__ = ["missing"]'
    elif failure == "documentation":
        stream.contents["README.md"] = b"\xff"
    else:
        distributions.records["any-agent"].contents["any_agent/events.py"] = b"\xff"
    assert cli.main(["--checkout", str(tmp_path / "root"), "--at", revision]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.strip()
    assert seen == [(tmp_path / "root").resolve()]
    if failure in {"missing", "identity", "signature", "documentation"}:
        assert "stream-proc" in captured.err


def test_render_failure_is_explained_before_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    wired(tmp_path, monkeypatch)

    def broken(_digest: Digest) -> bytes:
        raise ValueError("cannot serialize the complete digest")

    monkeypatch.setattr(cli, "render_digest", broken)
    assert cli.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "cannot serialize" in captured.err


def test_git_failure_is_explained_without_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def unavailable(_views: object, _path: Path) -> Repo:
        raise GitUnavailable("object storage unavailable")

    monkeypatch.setattr(cli.GitViews, "checkouts", unavailable)
    assert cli.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "object storage unavailable" in captured.err


@pytest.mark.parametrize("failure", ["contract", "overflow"])
def test_fact_and_bound_failures_are_buffered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failure: str,
) -> None:
    distributions, _ = wired(tmp_path, monkeypatch)
    if failure == "contract":
        record = distributions.records["any-agent"]
        path = "any_agent/events.py"
        original = record.contents[path]
        assert isinstance(original, bytes)
        record.contents[path] = original.replace(b"usage: Tokens | None", b"usage: Tokens")
    else:
        monkeypatch.setattr("taskloop.shelf_digest.render.TOKEN_LIMIT", 1)
    assert cli.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.strip()
    assert ("contract" if failure == "contract" else "bound") in captured.err
