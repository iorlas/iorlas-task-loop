"""A bead branch held by another worktree never fails a slot reset, and a failure before the engine never stops a loop
(tl-bxk.10.26). lifesim 2026-10-22: a pre-slot worktree held task/lifesim-ov3w; two loops failed on it and stopped."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
import engine  # noqa: E402
import loop_env  # noqa: E402
from support import looptest  # noqa: E402
from taskloop.app.loop import verdict as vd  # noqa: E402
from taskloop.app.loop.take import Taker  # noqa: E402
from taskloop.contracts.config import SlotsConfig  # noqa: E402
import test_loop as tlp  # noqa: E402
import tl  # noqa: E402


def sh(*a, cwd):
    return subprocess.run(list(a), cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()


class HeldBranch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
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
        for p in (mock.patch.object(tl, "repo_root", return_value=str(self.repo)),
                  mock.patch.object(tl, "event", return_value={}),
                  mock.patch.object(tl, "profile_slots", return_value=SlotsConfig(count=1, base="origin/main")),
                  mock.patch.object(tl, "slot_dir", return_value=str(self.slot)),
                  mock.patch.object(tl, "slot_bead", return_value={})):
            p.start()
            self.addCleanup(p.stop)

    def reset(self):
        a = engine.Args(op="reset", name="s1", bead="x-1", n=None, force=False)
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            rc = tl.cmd_slot(a)
        return rc, out.getvalue(), getattr(a, "error", "")

    def branch_in_slot(self):
        return sh("git", "symbolic-ref", "--short", "HEAD", cwd=self.slot)

    def test_a_clean_worktree_holding_the_branch_is_removed(self):
        rc, out, _ = self.reset()
        self.assertEqual(rc, 0, out)
        self.assertIn("FREED", out)
        self.assertEqual(self.branch_in_slot(), "task/x-1")
        self.assertFalse(self.old.exists())
        self.assertEqual(sh("git", "rev-parse", "task/x-1", cwd=self.repo), self.tip)  # the commit stays

    def test_a_dirty_worktree_holding_the_branch_is_detached_with_its_files(self):
        (self.old / "work.txt").write_text("edited, not committed\n")
        (self.old / "new.txt").write_text("untracked\n")
        rc, out, _ = self.reset()
        self.assertEqual(rc, 0, out)
        self.assertIn("detached", out)
        self.assertEqual(self.branch_in_slot(), "task/x-1")
        self.assertEqual((self.old / "work.txt").read_text(), "edited, not committed\n")
        self.assertEqual((self.old / "new.txt").read_text(), "untracked\n")
        self.assertEqual(sh("git", "rev-parse", "HEAD", cwd=self.old), self.tip)
        self.assertEqual(subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=str(self.old)).returncode, 1)

    def test_a_worktree_with_a_live_lock_keeps_the_branch_and_the_answer_is_taken(self):
        k = tlp.subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(k.wait)
        self.addCleanup(k.kill)
        tl.write_engine_lock(str(self.old), {"pid": k.pid, "start": tl.proc_start(k.pid), "bead": "x-1", "started": 1})
        rc, out, why = self.reset()
        self.assertEqual(rc, 5, out)
        self.assertIn("TAKEN", out)
        self.assertIn(str(self.old), why)
        self.assertEqual(sh("git", "symbolic-ref", "--short", "HEAD", cwd=self.old), "task/x-1")

    def test_a_dead_lock_does_not_hold_the_branch(self):
        tl.write_engine_lock(str(self.old), {"pid": 2 ** 22 + 7, "bead": "x-1", "started": 1})
        self.assertEqual(self.reset()[0], 0)


class PreEngineFailure(tlp.LoopBase):
    def test_a_bead_failing_before_its_engine_rests_for_every_loop_and_stops_none(self):
        self.beads({"x-1": [tlp.rec("landed")], "x-2": [tlp.rec("landed")], "x-3": [tlp.rec("landed")]})
        calls = []

        def prepare(taker, slot, bead_id):
            calls.append(bead_id)
            if len(calls) <= 2:  # git's own refusal (a branch held by a worktree): not the slot's breakage
                return vd.pre_engine("tl slot reset s1 for %s did not give a clean tree: fatal: 'task/%s' is already used by worktree at '/w'"
                                     % (bead_id, bead_id))
        with mock.patch.object(Taker, "prepare", prepare):
            self.assertEqual(self.run_loop(), 0)  # two beads failed before their engines: no "2 failures in a row"
        self.assertNotIn("STOPPED", self.out)
        self.assertEqual(calls[:2], ["x-1", "x-2"])
        lines = self.lines()
        self.assertIn("did not give a clean tree: fatal: 'task/x-1'", lines[0]["why"])
        self.assertIn("slot reset s1 for x-1", lines[0]["why"])
        self.assertEqual(sorted(json.loads(looptest.rest_file(str(self.repo)).read_text())["beads"]), ["x-1", "x-2"])

    def test_a_second_loop_leaves_the_bead_the_first_one_rested(self):
        self.beads({"x-1": [tlp.rec("landed")], "x-2": [tlp.rec("landed")]})
        looptest.files(str(self.repo)).rest_bead("x-1", self.clock.t + 3600)  # the other loop's pre-engine failure
        self.run_loop("--max-beads", "1")
        self.assertEqual([b for b, _ in self.started], ["x-2"])

    def test_a_real_engine_failure_still_counts(self):
        self.beads({"x-1": [tlp.rec("failed")], "x-2": [tlp.rec("failed")], "x-3": [tlp.rec("landed")]})
        self.assertEqual(self.run_loop(), 2)
        self.assertFalse(looptest.rests(str(self.repo)))

    def test_a_branch_held_live_is_taken_not_failed(self):
        self.beads({"x-1": [tlp.rec("landed")], "x-2": [tlp.rec("landed")]})
        with mock.patch.object(Taker, "prepare", side_effect=[vd.taken("branch task/x-1 is checked out in /w"), None]):
            self.assertEqual(self.run_loop("--max-beads", "1"), 0)
        self.assertEqual(self.lines()[0]["outcome"], "taken")
        self.assertEqual([b for b, _ in self.started], ["x-2"])


if __name__ == "__main__":
    unittest.main()
