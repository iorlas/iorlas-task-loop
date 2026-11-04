"""A plain repo reached through a symlinked folder answers like its real path (macOS: the temp dir /var is /private/var; tl-5gzj).

Pins the port's answers (unmerged file, rebase in progress, abort) for the symlinked spelling. Honest scope: these tests also pass on the
unfixed adapter, so they guard against a regression but do not reproduce the Mac suite failures that real_checkout() cured; the unexplained
part is written in the PR. The symlink is built here: any OS, no TMPDIR setting."""

import subprocess
from pathlib import Path

import support.paths  # noqa: F401

# isort: split
from taskloop.adapters.git import RealGit
from taskloop.contracts.env import Env


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                   cwd=cwd, check=True, capture_output=True)


def conflicted_repo(tmp_path: Path) -> tuple[Path, Path]:
    """A plain repo stopped in a rebase on a conflict in f.txt: (its real path, the same folder through a symlink to its parent)."""
    parent = tmp_path / "real"
    parent.mkdir()
    link = tmp_path / "link"
    link.symlink_to(parent, target_is_directory=True)
    repo = parent / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "f.txt").write_text("base\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    git(repo, "checkout", "-q", "-b", "topic")
    (repo / "f.txt").write_text("topic\n")
    git(repo, "commit", "-qam", "topic")
    git(repo, "checkout", "-q", "main")
    (repo / "f.txt").write_text("main\n")
    git(repo, "commit", "-qam", "main")
    git(repo, "checkout", "-q", "topic")
    subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "rebase", "-q", "main"], cwd=repo, capture_output=True, check=False)
    return repo, link / "repo"


def test_the_unmerged_file_is_found_through_a_symlinked_path(tmp_path):
    real, link = conflicted_repo(tmp_path)
    port = RealGit(Env())
    assert port.unmerged(str(real)) == ["f.txt"]
    assert port.unmerged(str(link)) == ["f.txt"]


def test_a_symlinked_path_sees_the_rebase_in_progress_and_can_abort_it(tmp_path):
    real, link = conflicted_repo(tmp_path)
    port = RealGit(Env())
    assert port.rebasing(str(link)) is True
    port.rebase_abort(str(link))
    assert port.rebasing(str(real)) is False
