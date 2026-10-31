"""The push and the look at the remote of a stack delivery, over real git and a bare origin."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401
from support import gitq
from support.engine_case import real_git
from support.fake_beads import FakeBeads
from support.forgesim import ForgeSim

# isort: split
from taskloop.adapters.git import RealGit
from taskloop.app.land.cmds import Cmds, Stop
from taskloop.app.land.forge import Forge
from taskloop.app.land.stack import Stack
from taskloop.app.land.stackgate import StackGate
from taskloop.contracts.env import snapshot
from taskloop.contracts.forge import StackItem
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import DoltPush
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
        self.git, self.log = RealGit(snapshot()), log
        self.cmds = Cmds(ForgeSim(), log, str(self.repo))
        self.forge = Forge(self.cmds, self.git, str(self.repo), "main")

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

    @real_git("a branch only origin has must be found with ls-remote, fetched and resolved to its oid")
    def test_a_branch_only_origin_has_is_resolved_by_fetching_it(self):
        gitq.git("checkout", "-q", "-b", "task/remote-only", cwd=self.repo)
        (self.repo / "g").write_text("2")
        gitq.git("add", "g", cwd=self.repo)
        gitq.git("commit", "-q", "-m", "two", cwd=self.repo)
        oid = gitq.git("rev-parse", "HEAD", cwd=self.repo)
        gitq.git("push", "-q", "origin", "task/remote-only", cwd=self.repo)
        other = Path(self.tmp.name) / "c"
        gitq.git("clone", "-q", str(self.origin), str(other), cwd=Path(self.tmp.name))
        forge = Forge(self.cmds, self.git, str(other), "main")
        stores = real_stores(ConfigDir(Path(self.tmp.name) / "cfg"))
        gate = StackGate(self.cmds, self.git, stores, str(other), "origin/main", ["tl"])
        stack = Stack(forge, self.cmds, self.log, self.git, str(other), Path(self.tmp.name) / "lock",
                      lambda b, s: 0, lambda: DoltPush(0, ""),
                      "me", "s", gate, FakeBeads(actor="me"))
        branch, got, _ = stack.resolve(StackItem(branch="task/remote-only"))
        self.assertEqual((branch, got), ("task/remote-only", oid))
        self.assertEqual(self.git.rev_parse(str(other), oid), oid)
        with self.assertRaises(Stop) as e:
            stack.resolve(StackItem(branch="task/nowhere"))
        self.assertIn("git ls-remote origin refs/heads/task/nowhere", e.exception.why)


if __name__ == "__main__":
    unittest.main()
