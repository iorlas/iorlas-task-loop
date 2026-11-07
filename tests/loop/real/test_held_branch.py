"""A bead branch held by another worktree never fails a slot reset, and a failure before the engine never stops a loop
(tl-bxk.10.26). lifesim 2026-10-22: a pre-slot worktree held task/lifesim-ov3w; two loops failed on it and stopped."""

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from support.case import Case
from support.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: E402, F401
import tl  # noqa: E402
from support import (  # noqa: E402
    looptest,
    tlbd,
)
from support.args import Args  # noqa: E402
from support.checked import run_checked  # noqa: E402
from support.engine_locks import put_lock  # noqa: E402
from support.procsim import real_proc  # noqa: E402
from support.spawn import (  # noqa: E402
    port_git,
    real_spawner,
)
from support.who import who  # noqa: E402

import loop.test_loop as tlp  # noqa: E402
from taskloop.adapters import pidcheck  # noqa: E402
from taskloop.app.loop import verdict as vd  # noqa: E402
from taskloop.app.loop.take import Taker  # noqa: E402
from tlkernel.env import snapshot  # noqa: E402

LIVE_PID = "a live pid that is not this process: a real sleep child (an engine lock, a second loop, a waiter)"


def sh(*a, cwd):
    return run_checked(list(a), str(cwd), text=True).stdout.strip()


class HeldBranch(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        home = Path(os.path.realpath(self.tmp.name))
        env = {"HOME": str(home), "XDG_CONFIG_HOME": str(home / "cfg"), "APPDATA": str(home / "cfg"),
               "CLAUDE_CODE_SESSION_ID": "sess1234-x", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1"}
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)
        origin, self.repo = home / "o.git", home / "repo"
        self.slot, self.old = self.repo / ".slots" / "s1", self.repo / ".worktrees" / "task-x-1"
        sh("git", "init", "-q", "--bare", "-b", "main", str(origin), cwd=home)
        sh("git", "clone", "-q", str(origin), str(self.repo), cwd=home)
        (self.repo / "a.txt").write_text("a\n")
        sh("git", "add", "-A", cwd=self.repo)
        sh("git", "commit", "-qm", "init", cwd=self.repo)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.repo)
        sh("git", "worktree", "add", "-q", "--detach", str(self.slot), "origin/main", cwd=self.repo)
        # the pre-slot worktree: holds task/x-1, which has a commit that never landed
        sh("git", "worktree", "add", "-q", "-b", "task/x-1", str(self.old), "origin/main", cwd=self.repo)
        (self.old / "work.txt").write_text("unlanded\n")
        sh("git", "add", "-A", cwd=self.old)
        sh("git", "commit", "-qm", "unlanded work", cwd=self.old)
        self.tip = sh("git", "rev-parse", "HEAD", cwd=self.old)
        (self.repo / ".task-loop.json").write_text(json.dumps({"slots": {"count": 1, "base": "origin/main"}}))
        tlbd.install(self, lambda *a, **k: tlbd.done("[]"))  # no slot beads in this tracker
        before = os.getcwd()
        os.chdir(self.repo)  # the repo `tl slot` acts on
        self.addCleanup(os.chdir, before)

    def reset(self):
        a = Args(op="reset", name="s1", bead="x-1", n=None, force=False)
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            rc = tl.v_slot(a, tl.Ctx(tl.HERE, tl.trail.now, [], snapshot(), spawner=real_spawner(), git=port_git(), who=who()))
        return rc, out.getvalue(), getattr(a, "error", "")

    def branch_in_slot(self):
        return sh("git", "symbolic-ref", "--short", "HEAD", cwd=self.slot)

    def test_a_clean_worktree_holding_the_branch_is_removed(self):
        rc, out, _ = self.reset()
        assert rc == 0, out
        assert "FREED" in out
        assert self.branch_in_slot() == "task/x-1"
        assert not self.old.exists()
        assert sh("git", "rev-parse", "task/x-1", cwd=self.repo) == self.tip  # the commit stays

    def test_a_dirty_worktree_holding_the_branch_is_detached_with_its_files(self):
        (self.old / "work.txt").write_text("edited, not committed\n")
        (self.old / "new.txt").write_text("untracked\n")
        rc, out, _ = self.reset()
        assert rc == 0, out
        assert "detached" in out
        assert self.branch_in_slot() == "task/x-1"
        assert (self.old / "work.txt").read_text() == "edited, not committed\n"
        assert (self.old / "new.txt").read_text() == "untracked\n"
        assert sh("git", "rev-parse", "HEAD", cwd=self.old) == self.tip
        assert subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=str(self.old), check=False).returncode == 1

    @real_proc(LIVE_PID)
    def test_a_worktree_with_a_live_lock_keeps_the_branch_and_the_answer_is_taken(self):
        k = tlp.subprocess.Popen(["sleep", "60"])
        self.addCleanup(k.wait)
        self.addCleanup(k.kill)
        put_lock(str(self.old), {"pid": k.pid, "start": pidcheck.proc_start(k.pid), "bead": "x-1", "started": 1})
        rc, out, why = self.reset()
        assert rc == 5, out
        assert "TAKEN" in out
        assert str(self.old) in why
        assert sh("git", "symbolic-ref", "--short", "HEAD", cwd=self.old) == "task/x-1"

    def test_a_dead_lock_does_not_hold_the_branch(self):
        put_lock(str(self.old), {"pid": 2 ** 22 + 7, "bead": "x-1", "started": 1})
        assert self.reset()[0] == 0


class PreEngineFailure(tlp.LoopBase):
    def test_infrastructure_before_the_engine_retries_without_resting_beads(self):
        self.beads({"x-1": [tlp.rec("landed")], "x-2": [tlp.rec("landed")], "x-3": [tlp.rec("landed")]})
        calls = []

        def prepare(taker, slot, bead_id):
            calls.append(bead_id)
            if len(calls) <= 2:  # git's own refusal (a branch held by a worktree): not the slot's breakage
                return vd.pre_engine(
                    f"tl slot reset s1 for {bead_id} did not give a clean tree: fatal: 'task/{bead_id}' is already used by worktree at '/w'"
                )

        with mock.patch.object(Taker, "prepare", prepare):
            assert self.run_loop() == 0  # two beads failed before their engines: no "2 failures in a row"
        assert "STOPPED" not in self.out
        assert calls[:2] == ["x-1", "x-2"]
        lines = self.lines()
        assert "did not give a clean tree: fatal: 'task/x-1'" in lines[0]["why"]
        assert "slot reset s1 for x-1" in lines[0]["why"]
        assert looptest.rests(str(self.repo)) == {}

    def test_a_second_loop_leaves_the_bead_the_first_one_rested(self):
        self.beads({"x-1": [tlp.rec("landed")], "x-2": [tlp.rec("landed")]})
        looptest.files(str(self.repo)).rest_bead("x-1", self.clock.t + 3600)  # the other loop's pre-engine failure
        self.run_loop("--max-beads", "1")
        assert [b for b, _ in self.started] == ["x-2"]

    def test_a_real_engine_failure_still_counts(self):
        self.beads({"x-1": [tlp.rec("failed")], "x-2": [tlp.rec("failed")], "x-3": [tlp.rec("landed")]})
        assert self.run_loop() == 0
        assert "WAIT: 2 runs gave no outcome" in self.out
        assert not looptest.rests(str(self.repo))

    def test_a_branch_held_live_is_taken_not_failed(self):
        self.beads({"x-1": [tlp.rec("landed")], "x-2": [tlp.rec("landed")]})
        with mock.patch.object(Taker, "prepare", side_effect=[vd.taken("branch task/x-1 is checked out in /w"), None]):
            assert self.run_loop("--max-beads", "1") == 0
        assert self.lines()[0]["outcome"] == "taken"
        assert [b for b, _ in self.started] == ["x-2"]
