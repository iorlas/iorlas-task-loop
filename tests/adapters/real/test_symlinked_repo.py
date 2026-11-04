"""A repo reached through a symlinked folder (/var is a symlink to /private/var on a Mac) is the same repo to git."""

import subprocess
from pathlib import Path

from taskloop.adapters.git import RealGit
from taskloop.contracts.env import snapshot


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)


def conflicted_repo(real: Path) -> None:
    real.mkdir()
    git(real, "init", "-q", "-b", "main")
    (real / "f").write_text("1\n")
    git(real, "add", ".")
    git(real, "commit", "-qm", "1")
    git(real, "checkout", "-qb", "x")
    (real / "f").write_text("x\n")
    git(real, "commit", "-qam", "x")
    git(real, "checkout", "-q", "main")
    (real / "f").write_text("m\n")
    git(real, "commit", "-qam", "m")
    git(real, "checkout", "-q", "x")


class TestSymlinkedRepo:
    def test_the_unmerged_files_of_a_rebase_conflict_are_found_through_a_symlink(self, tmp_path):
        conflicted_repo(tmp_path / "real")
        (tmp_path / "link").symlink_to(tmp_path / "real")
        port, link = RealGit(snapshot()), str(tmp_path / "link")
        assert not port.rebase(link, "main").ok  # stops on the conflict
        assert port.unmerged(link) == ["f"]
