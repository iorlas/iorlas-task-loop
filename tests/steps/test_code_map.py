"""CODE MAP uses the committed, pinned tree and only established repository hints."""

from pathlib import Path

import pytest
from doubles import PinnedViews
from git_porcelain import GitUnavailable, Recorded, Repo
from git_porcelain.testing import FakeRepo

from taskloop.git_views import GitProfileFiles
from taskloop.input_context import BEGIN, END, InputError, read, refresh
from taskloop.profile import NoCommit, Unavailable

SETTINGS = '[tool.pytest.ini_options]\naddopts = "--import-mode=importlib -p no:cacheprovider"\npythonpath = ["tests/steps"]\n'


def record(repo: FakeRepo, paths: dict[str, str]) -> str:
    worktree = repo.worktree(repo.path)
    for path, text in paths.items():
        worktree.write_file(path, text)
    made = worktree.record("map", paths="all")
    assert isinstance(made, Recorded)
    return made.sha


def test_map_is_the_complete_sorted_committed_path_list(repo: FakeRepo, checkouts: PinnedViews) -> None:
    worktree = repo.worktree(repo.path)
    first = record(repo, {"src/deleted.py": "old"})
    worktree.remove_file("src/deleted.py")
    names = tuple(sorted(("src/a.py", "tests/a.py", "docs/design/task/plan.md", *(f"src/module_{i}.py" for i in range(600)))))
    commit = record(repo, dict.fromkeys((*names, "srcish/a.py", "tests.md", "docs/designer/a.md"), "text"))
    worktree.write_file("src/untracked.py", "dirty")
    worktree.remove_file("src/a.py")
    files = GitProfileFiles(repo.path, checkouts)
    context = read(files, commit)
    assert context.paths == names
    text = context.render()
    assert text.splitlines().count("CODE MAP") == text.splitlines().count(BEGIN) == text.splitlines().count(END) == 1
    assert text.index(BEGIN) < text.index(context.glossary) < text.index("\nCODE MAP\n") < text.index(END)
    assert text.split("\nCODE MAP\n")[1] == "\n".join((*names, END))
    assert "untracked" not in text and "deleted.py" not in text and "srcish/" not in text and "docs/designer/" not in text
    assert not context.layout and "src/taskloop" not in text
    assert "src/deleted.py" in read(files, first).paths


def test_empty_map_is_truthful(repo: FakeRepo, checkouts: PinnedViews) -> None:
    commit = record(repo, {"other.txt": "unrelated"})
    context = read(GitProfileFiles(repo.path, checkouts), commit)
    assert context.paths == () and "no tracked paths" in context.render() and not context.layout


def test_map_refresh_replaces_old_paths_once(repo: FakeRepo, checkouts: PinnedViews) -> None:
    first = record(repo, {"src/old.py": "old"})
    files = GitProfileFiles(repo.path, checkouts)
    original = "retry frame\n" + read(files, first).render() + "\ntask"
    repo.worktree(repo.path).remove_file("src/old.py")
    second = record(repo, {"tests/new.py": "new"})
    text = refresh(original, read(files, second))
    assert text.count("CODE MAP") == 1 and "src/old.py" not in text and "tests/new.py" in text
    assert text.startswith("retry frame\n") and text.endswith("\ntask")


@pytest.mark.parametrize("settings", [SETTINGS, SETTINGS.replace('pythonpath = ["tests/steps"]', 'pythonpath = ["tests"]'),
                                     SETTINGS.replace("--import-mode=importlib", "--import-mode=prepend")])
@pytest.mark.parametrize("missing_folders", [False, True])
def test_taskloop_hints_follow_committed_paths_and_pytest_settings(
    repo: FakeRepo, checkouts: PinnedViews, settings: str, missing_folders: bool,
) -> None:
    paths = ("src/taskloop/app.py", "src/taskloop/agents/a.py", "src/taskloop/drain/a.py", "src/taskloop/check_repeat/a.py",
             "src/taskloop/dash/a.py", "tests/steps/doubles.py", "tests/cli/a.py", "tests/rules/a.py")
    if missing_folders:
        paths = tuple(path for path in paths if path not in ("src/taskloop/drain/a.py", "tests/rules/a.py"))
    commit = record(repo, dict.fromkeys(paths, "") | {"pyproject.toml": settings})
    repo.worktree(repo.path).write_file("pyproject.toml", "dirty invalid toml")
    context = read(GitProfileFiles(repo.path, checkouts), commit)
    hints = ["In this repository, source modules are primarily src/taskloop/*.py.",
             "Feature subfolders: src/taskloop/agents/, src/taskloop/drain/, src/taskloop/check_repeat/, src/taskloop/dash/.",
             "Tests: tests/steps/, tests/cli/, tests/rules/."]
    if missing_folders:
        hints[1] = "Feature subfolders: src/taskloop/agents/, src/taskloop/check_repeat/, src/taskloop/dash/."
        hints[2] = "Tests: tests/steps/, tests/cli/."
    if settings == SETTINGS:
        hints.append('Shared test helpers such as doubles.py live in tests/steps; committed pytest settings use '
                     'importlib mode and pythonpath = ["tests/steps"].')
    text = context.render()
    assert text.splitlines().count("CODE MAP") == text.splitlines().count(BEGIN) == text.splitlines().count(END) == 1
    assert text.index(BEGIN) < text.index(context.glossary) < text.index("\nCODE MAP\n") < text.index(END)
    assert text.split("\nCODE MAP\n")[1] == "\n".join((*hints, *sorted(paths), END))


@pytest.mark.parametrize("failure", [Unavailable("listing failed"), NoCommit()])
def test_listing_failure_prevents_input_with_explanation(
    repo: FakeRepo, checkouts: PinnedViews, monkeypatch: pytest.MonkeyPatch, failure: Unavailable | NoCommit,
) -> None:
    commit = record(repo, {"src/a.py": "code"})
    monkeypatch.setattr(GitProfileFiles, "paths", lambda _self, _commit: failure)
    with pytest.raises(InputError, match=r"listing failed|names no commit"):
        read(GitProfileFiles(repo.path, checkouts), commit)


def test_adapter_preserves_missing_commit_and_unavailable_distinctions(repo: FakeRepo, checkouts: PinnedViews) -> None:
    files = GitProfileFiles(repo.path, checkouts)
    assert files.paths("0" * 40) == files.paths("-x") == NoCommit()

    def broken(_path: Path, /, *, git_dir: Path | None = None) -> Repo:
        raise GitUnavailable("tree unavailable", hint="git_config")

    assert GitProfileFiles(repo.path, broken).paths("HEAD") == Unavailable("tree unavailable")
