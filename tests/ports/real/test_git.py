"""adapters/git.py on real git, in a throwaway repo: the same Git contract the gitsim runs."""
import sys
from pathlib import Path
from unittest import mock

from support.case import Case
from support.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401
from support.checked import run_checked

from ports.git_contract import GitContract, contract
from ports.git_contract_land import LandContract
from taskloop.adapters.git import RealGit
from taskloop.adapters.git_ops import LandGit
from tlkernel.env import snapshot


@contract
class RealGitContract(GitContract, LandContract, Case):
    def start(self) -> None:
        pass

    def make(self) -> RealGit:
        return RealGit(snapshot())


class IgnoreSpaceDoesNotDependOnTheGitVersion(Case):
    """An older git lists a whitespace-only change as M even under -w: the adapter must drop it itself."""

    def test_a_whitespace_only_m_row_from_git_is_dropped_and_a_real_edit_kept(self) -> None:
        with TemporaryDirectory() as tmp:
            def sh(*a: str) -> None:
                run_checked(["git", "-C", tmp, "-c", "user.name=t", "-c", "user.email=t@t", *a], None)
            sh("init", "-q")
            (Path(tmp) / "w.txt").write_text("a  b\n")
            (Path(tmp) / "x.txt").write_text("x\n")
            sh("add", "-A")
            sh("commit", "-qm", "1")
            (Path(tmp) / "w.txt").write_text("a b\n")
            (Path(tmp) / "x.txt").write_text("y\n")
            sh("commit", "-qam", "2")
            git = RealGit(snapshot())
            listed = ["M", "w.txt", "M", "x.txt"]
            with mock.patch.object(LandGit, "_diff_paths", return_value=listed):
                got = git.diff_entries(tmp, "HEAD~1", "HEAD", ignore_space=True)
        assert [(e.status, e.path) for e in got] == [("M", "x.txt")]
