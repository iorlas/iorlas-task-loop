"""The push and the look at the remote of a stack delivery, over real git and a bare origin."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401
from support import gitq
from support.engine_case import real_git
from support.forgesim import ForgeSim

# isort: split
from taskloop.adapters.git import RealGit
from taskloop.app.land.cmds import Cmds, Stop
from taskloop.app.land.forge import Forge
from taskloop.contracts.env import snapshot
from taskloop.contracts.paths import ConfigDir
from taskloop.stores.real import real_stores
from taskloop.stores.runlog import RunLog


class RealPush(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.origin, self.repo = root / "o.git", root / "w"
        self.repo.mkdir()
        gitq.git("init", "-q", "--bare", "-b", "main", str(self.origin), cwd=root)
        gitq.git("init", "-q", "-b", "task/a", cwd=self.repo)
        for k, v in (("user.name", "t"), ("user.email", "t@x"), ("commit.gpgsign", "false")):
            gitq.git("config", k, v, cwd=self.repo)
        gitq.git("remote", "add", "origin", str(self.origin), cwd=self.repo)
        (self.repo / "f").write_text("1")
        gitq.git("add", "f", cwd=self.repo)
        gitq.git("commit", "-q", "-m", "one", cwd=self.repo)
        self.oid = gitq.git("rev-parse", "HEAD", cwd=self.repo)
        log = RunLog(real_stores(ConfigDir(root / "cfg")).run_log("land-stack-20261031-100000"), run_id="r")
        self.forge = Forge(Cmds(ForgeSim(), log, str(self.repo)), RealGit(snapshot()), str(self.repo), "main")

    @real_git("the push must reach a bare origin and ls-remote must show it")
    def test_a_pushed_branch_is_seen_on_the_remote_and_a_missing_one_is_empty(self):
        self.assertEqual(self.forge.remote_oid("task/a"), "")
        self.forge.push("task/a", self.oid)
        self.assertEqual(self.forge.remote_oid("task/a"), self.oid)
        self.assertEqual(gitq.git("rev-parse", "refs/heads/task/a", cwd=self.origin), self.oid)

    @real_git("a rejected push is git's refusal and stops the delivery")
    def test_a_push_the_remote_rejects_stops_the_delivery(self):
        self.forge.push("task/a", self.oid)
        (self.repo / "f").write_text("2")
        gitq.git("commit", "-q", "-a", "-m", "two", cwd=self.repo)
        gitq.git("checkout", "-q", "--orphan", "other", cwd=self.repo)
        gitq.git("commit", "-q", "--allow-empty", "-m", "unrelated", cwd=self.repo)
        with self.assertRaises(Stop):
            self.forge.push("task/a", gitq.git("rev-parse", "HEAD", cwd=self.repo))


if __name__ == "__main__":
    unittest.main()
