"""The release gate and the judge share one receipt: the RunKey row of the suite check on a tree. Green once, read by everyone."""
import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest
from support.case import Case
from support.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.checked import run_checked

from taskloop.adapters.git import RealGit
from taskloop.adapters.spawner import RealSpawner
from taskloop.app.checks import authorization
from taskloop.app.release import gate, shell
from taskloop.app.release.shell import Abort, Shell
from taskloop.stores.real import real_stores
from tlkernel.env import Env
from tlkernel.ids import CheckId, TreeSha
from tlkernel.paths import ConfigDir
from tlkernel.runkey import BaseSha


class Verify(Case):
    def setup_method(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.repo, origin = root / "repo", root / "origin.git"
        self.repo.mkdir()
        self.env = Env({"PATH": os.environ["PATH"], "HOME": str(root), "XDG_CONFIG_HOME": str(root / "cfg"),
                        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        self.port = RealGit(self.env)
        self.sh: Shell = shell.of(RealSpawner(self.env), self.port, self.env)
        run_checked(["git", "init", "-q", "--bare", "-b", "main", str(origin)], root, env=self.env.vars)
        self.git("init", "-q", "-b", "main")
        (self.repo / ".task-loop.json").write_text(json.dumps({"engine": {"checks": [
            {"id": "suite", "argv": ["just", "test"], "run": "gate"}]}}))
        self.commit("a.txt", "one")
        self.git("remote", "add", "origin", str(origin))
        self.git("push", "-q", "-u", "origin", "main")
        self.ran: list[str] = []

    def git(self, *a: str) -> str:
        return run_checked(["git", *a], self.repo, env=self.env.vars, text=True).stdout.strip()

    def commit(self, name: str, text: str) -> None:
        (self.repo / name).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-qm", text)

    def checks(self, repo: Path, sh: Shell) -> None:
        self.ran.append("ran")

    def red(self, repo: Path, sh: Shell) -> None:
        self.ran.append("red")
        raise Abort("the suite is red")

    def judge_view(self):
        """What the pre-push judge reads for this tree: the suite check's result under the judged profile."""
        d, tree, base = str(self.repo), self.git("rev-parse", "HEAD^{tree}"), self.git("rev-parse", "origin/main")
        cfg = authorization.profile(self.port, d, TreeSha(base))
        return authorization.results(real_stores(ConfigDir(self.env.get("XDG_CONFIG_HOME") + "/task-loop")), self.port, d, cfg,
                                     TreeSha(tree), BaseSha(base), self.env)[CheckId("suite")]

    def test_the_same_tree_under_the_same_command_runs_once(self):
        assert not gate.verify(self.repo, self.sh, self.checks)
        assert gate.verify(self.repo, self.sh, self.checks)
        assert self.ran == ["ran"]

    def test_the_receipt_the_gate_wrote_is_the_one_the_judge_reads(self):
        assert self.judge_view() is None
        gate.verify(self.repo, self.sh, self.checks)
        assert self.judge_view() is not None

    def test_a_miss_says_which_tree_and_command_have_no_green_run(self):
        with mock.patch.object(gate, "say") as said:
            gate.verify(self.repo, self.sh, self.checks)
            gate.verify(self.repo, self.sh, self.checks)
        assert said.call_args_list[0].args[0].startswith(
            f"gate receipt miss: no green run of tree {self.git('rev-parse', 'HEAD^{tree}')[:12]} under `just test`")
        assert said.call_args_list[1].args[0].startswith("gate receipt hit:")

    def test_a_changed_tree_runs_again(self):
        gate.verify(self.repo, self.sh, self.checks)
        self.commit("a.txt", "two")
        assert not gate.verify(self.repo, self.sh, self.checks)
        assert self.ran == ["ran", "ran"]

    def test_a_red_run_is_never_remembered_so_the_next_run_is_real(self):
        with pytest.raises(Abort):
            gate.verify(self.repo, self.sh, self.red)
        with pytest.raises(Abort):
            gate.verify(self.repo, self.sh, self.red)
        assert self.ran == ["red", "red"]
        assert self.judge_view() is None

    def declare_gate(self, check_rc: str, test_rc: str) -> None:
        """Commit a justfile whose `gate` is check then test and a profile that declares it (`just gate`)."""
        (self.repo / "justfile").write_text(f"check:\n    {check_rc}\ntest:\n    {test_rc}\ngate: check test\n")
        (self.repo / ".task-loop.json").write_text(json.dumps({"engine": {"checks": [
            {"id": "suite", "argv": ["just", "gate"], "run": "gate"}]}}))
        self.git("add", "-A")
        self.git("commit", "-qm", "declare the gate")
        self.git("push", "-q", "origin", "main")

    def test_a_check_red_test_green_run_writes_no_receipt(self):
        self.declare_gate("false", "true")
        with pytest.raises(Abort):
            gate.verify(self.repo, self.sh)
        assert self.judge_view() is None

    def test_a_receipt_exists_only_after_check_and_test_are_both_green(self):
        self.declare_gate("true", "true")
        assert not gate.verify(self.repo, self.sh)
        assert self.judge_view() is not None

    def test_a_moved_base_is_a_miss(self):
        gate.verify(self.repo, self.sh, self.checks)
        clone = Path(self.tmp.name) / "other"
        run_checked(["git", "clone", "-q", str(Path(self.tmp.name) / "origin.git"), str(clone)], clone.parent, env=self.env.vars)
        (clone / "b.txt").write_text("b")
        for cmd in (["add", "-A"], ["commit", "-qm", "b"], ["push", "-q", "origin", "main"]):
            run_checked(["git", *cmd], clone, env=self.env.vars)
        self.git("fetch", "-q", "origin")
        assert not gate.verify(self.repo, self.sh, self.checks)
        assert self.ran == ["ran", "ran"]
