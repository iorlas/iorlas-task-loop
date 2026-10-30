"""tidy.drop_branch deletes a landed branch only at the commit on_base was checked on."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

from taskloop.adapters.spawner import RealSpawner
from taskloop.app.release import shell, tidy

SH = shell.of(RealSpawner())

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env={**os.environ, **ENV}, check=False)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


class DropBranch(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "base")
        git(self.repo, "branch", "feat")

    def test_the_branch_goes_at_the_checked_tip(self):
        tip = tidy.tip_of(self.repo, "feat", SH)
        self.assertEqual(tidy.drop_branch(self.repo, "feat", tip, SH), [])
        self.assertEqual(tidy.tip_of(self.repo, "feat", SH), "")

    def test_a_commit_added_after_the_check_keeps_the_branch(self):
        tip = tidy.tip_of(self.repo, "feat", SH)  # checked here (the suite runs next)
        git(self.repo, "checkout", "-q", "feat")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "added during the suite")
        git(self.repo, "checkout", "-q", "main")
        kept = tidy.drop_branch(self.repo, "feat", tip, SH)
        self.assertEqual(len(kept), 1)
        self.assertIn("branch feat kept", kept[0])
        self.assertNotEqual(tidy.tip_of(self.repo, "feat", SH), tip)


if __name__ == "__main__":
    unittest.main()
