"""The push and the look at the remote of a stack delivery, over real git and a bare origin."""
import sys
import tempfile
from pathlib import Path

import pytest
from support.case import Case

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
from taskloop.contracts.env import Env, snapshot
from taskloop.contracts.forge import StackItem
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import DoltPush
from taskloop.stores.real import real_stores
from taskloop.stores.runlog import RunLog


class RealPush(Case):
    def setup_method(self):
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
        self.run_dir = root / "cfg" / "runs" / "r"
        self.cmds = Cmds(ForgeSim(), log, str(self.repo), self.run_dir)
        self.forge = Forge(self.cmds, self.git, str(self.repo), "main")

    @real_git("the push must reach a bare origin and ls-remote must show it")
    def test_a_pushed_branch_is_seen_on_the_remote_and_a_missing_one_is_empty(self):
        assert self.forge.remote_oid("task/a") == ""
        self.forge.push("task/a", self.oid)
        assert self.forge.remote_oid("task/a") == self.oid
        assert gitq.git("rev-parse", "refs/heads/task/a", cwd=self.origin) == self.oid

    @real_git("a rejected push is git's refusal and stops the delivery")
    def test_a_push_the_remote_rejects_stops_the_delivery(self):
        self.forge.push("task/a", self.oid)
        (self.repo / "f").write_text("2")
        gitq.git("commit", "-q", "-a", "-m", "two", cwd=self.repo)
        gitq.git("checkout", "-q", "--orphan", "other", cwd=self.repo)
        gitq.git("commit", "-q", "--allow-empty", "-m", "unrelated", cwd=self.repo)
        with pytest.raises(Stop):
            self.forge.push("task/a", gitq.git("rev-parse", "HEAD", cwd=self.repo))

    @real_git("a real pre-push hook's long stdout and refusal must survive git's footer and land's error handling")
    def test_hook_refusal_names_an_uncut_transcript(self):
        env = Env({**snapshot().vars, "XDG_CONFIG_HOME": str(Path(self.tmp.name) / "hook-config")})
        hooks = ConfigDir(Path(self.tmp.name) / "hook-config" / "task-loop").hooks_dir()
        hooks.mkdir(parents=True)
        hook = hooks / "pre-push"
        refusal = "gate: refusing the push: run just check"
        hook.write_text('#!/bin/sh\ni=0\nwhile [ "$i" -lt 500 ]; do\n'
                        '  echo "hook output $i"\n  i=$((i + 1))\ndone\n'
                        f'echo "{refusal}" >&2\nexit 1\n')
        hook.chmod(0o755)
        forge = Forge(self.cmds, RealGit(env), str(self.repo), "main")
        with pytest.raises(Stop) as raised:
            forge.push("task/a", self.oid)
        files = list((self.run_dir / "land-push").glob("*.log"))
        assert len(files) == 1
        assert str(files[0]) in raised.value.why
        assert refusal in raised.value.why
        assert "failed to push some refs" not in raised.value.why
        output = files[0].read_text()
        assert [line for line in output.splitlines() if line.startswith("hook output ")] == [f"hook output {n}" for n in range(500)]
        assert refusal in output
        assert "failed to push some refs" in output
        assert self.forge.remote_oid("task/a") == ""

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
                      "me", "s", gate, FakeBeads(actor="me"), cfg=ConfigDir(Path(self.tmp.name) / "cfg"))
        branch, got, _ = stack.resolve(StackItem(branch="task/remote-only"))
        assert (branch, got) == ("task/remote-only", oid)
        assert self.git.rev_parse(str(other), oid) == oid
        with pytest.raises(Stop) as e:
            stack.resolve(StackItem(branch="task/nowhere"))
        assert "git ls-remote origin refs/heads/task/nowhere" in e.value.why
