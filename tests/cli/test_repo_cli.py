"""Verify CLI formatting/refusals and real composition without starting Git."""

import json
from pathlib import Path

import pytest
from git_porcelain import GitReadFailure, GitTimeout, GitUnavailable, NotARepo, Repo
from git_porcelain.testing import FakeRepo

from taskloop import git_views
from taskloop.cli import main
from taskloop.git_views import GitViews
from taskloop.repo import RepoInspection, UnsupportedCheckout, inspect_repo


@pytest.mark.parametrize("structured", [False, True])
def test_inspection_output(structured: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo = FakeRepo.init(tmp_path / "repo")

    def inspect(path: str) -> RepoInspection:
        assert path == str(repo.path)
        return inspect_repo(repo, repo.path)

    monkeypatch.setattr(GitViews, "inspect_checkout", lambda _views, path: inspect(path))
    assert main(["repo", "inspect", str(repo.path), *(["--json"] if structured else [])]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    if structured:
        assert json.loads(output.out) == {
            "repo_id": repo.identity().key,
            "common_dir": str(repo.path / ".git"),
            "checkout_path": str(repo.path),
            "origin_url": None,
        }
    else:
        assert f"Repo ID: {repo.identity().key}" in output.out
        assert f"Checkout: {repo.path}" in output.out
        assert "Origin: (not configured)" in output.out


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("error, kind", [
    (NotARepo("missing"), "not_a_repo"),
    (GitReadFailure("read failed"), "git_read_failure"),
    (GitUnavailable("git missing"), "git_unavailable"),
    (GitTimeout("timed out"), "git_timeout"),
    (UnsupportedCheckout("select root"), "unsupported_checkout"),
    (OSError("unavailable"), "path_unavailable"),
])
def test_inspection_failures_are_nonzero(
    error: Exception, kind: str, structured: bool, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(path: str) -> RepoInspection:
        raise error

    monkeypatch.setattr(GitViews, "inspect_checkout", lambda _views, path: fail(path))
    assert main(["repo", "inspect", "missing", *(["--json"] if structured else [])]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    if structured:
        assert json.loads(output.err) == {"error": {"kind": kind, "message": str(error)}}
    else:
        assert output.err == f"tl repo inspect: {error}\n"


@pytest.mark.parametrize("structured", [False, True])
def test_unknown_home_is_a_cli_refusal(structured: bool, capsys: pytest.CaptureFixture[str]) -> None:
    path = "~__taskloop_missing_home_6c6fd109__/repo"
    assert main(["repo", "inspect", path, *(["--json"] if structured else [])]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    message = f"Cannot expand checkout path: {path}"
    if structured:
        assert json.loads(output.err) == {"error": {"kind": "unsupported_checkout", "message": message}}
    else:
        assert output.err == f"tl repo inspect: {message}\n"


@pytest.mark.parametrize("arguments", [["repo"], ["repo", "inspect"], ["repo", "inspect", ".", "--js"]])
def test_inspection_requires_explicit_input(arguments: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as result:
        main(arguments)
    assert result.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_composition_resolves_input_and_disables_memoization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeRepo.init(tmp_path / "repo")
    monkeypatch.chdir(tmp_path)
    observed: list[Path] = []

    def make_repo(path: Path, *, memoize: bool, read_timeout: float) -> Repo:
        assert memoize is False
        observed.append(path)
        return repo

    monkeypatch.setattr(git_views, "RealRepo", make_repo)
    result = GitViews().inspect_checkout("repo/../repo")
    assert result.checkout_path == repo.path
    assert observed == [repo.path]
