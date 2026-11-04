"""A checkout reached through a symlinked folder is the same checkout as its real path (macOS: the temp dir /var is /private/var).

Git answers real paths (tl-5gzj). These tests build the symlink themselves, so they hold on any OS and need no TMPDIR setting. They pin
the port's answers for a symlinked worktree; on the unfixed adapter they already passed (the Mac suite failures were not reproduced by them).
tests/contracts/test_loop_key.py is the test that failed before the fix."""

import subprocess
from pathlib import Path

import support.paths  # noqa: F401

# isort: split
from taskloop.adapters.git import RealGit
from taskloop.contracts.env import Env


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True,
                   capture_output=True)


def symlinked(tmp_path: Path) -> tuple[Path, Path]:
    """(a folder, the same folder reached through a symlink to its parent)."""
    parent = tmp_path / "real"
    parent.mkdir()
    link = tmp_path / "link"
    link.symlink_to(parent, target_is_directory=True)
    return parent, link


def conflicted_worktree(link: Path, real: Path) -> tuple[Path, Path]:
    """A linked worktree (as the engine's slots are) stopped in a rebase on a conflict in f.txt: (its real path, its symlinked path)."""
    main = real / "main"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    (main / "f.txt").write_text("base\n")
    git(main, "add", "-A")
    git(main, "commit", "-qm", "base")
    git(main, "branch", "topic")
    git(main, "worktree", "add", "-q", str(link / "wt"), "topic")
    wt = link / "wt"
    (wt / "f.txt").write_text("topic\n")
    git(wt, "commit", "-qam", "topic")
    (main / "f.txt").write_text("main\n")
    git(main, "commit", "-qam", "main")
    subprocess.run(["git", "rebase", "main"], cwd=wt, capture_output=True, check=False)
    return real / "wt", wt


def test_unmerged_files_are_found_when_the_worktree_is_given_by_its_symlinked_path(tmp_path):
    real, link = symlinked(tmp_path)
    real_wt, link_wt = conflicted_worktree(link, real)
    port = RealGit(Env())
    assert port.unmerged(str(real_wt)) == ["f.txt"]
    assert port.unmerged(str(link_wt)) == ["f.txt"]


def test_a_symlinked_worktree_reads_rebasing_and_dirty_state_like_its_real_path(tmp_path):
    real, link = symlinked(tmp_path)
    real_wt, link_wt = conflicted_worktree(link, real)
    port = RealGit(Env())
    assert port.rebasing(str(link_wt)) is port.rebasing(str(real_wt)) is True
    assert port.dirty(str(link_wt)) == port.dirty(str(real_wt))
