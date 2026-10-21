"""A slot's git can only touch that slot (tl-bxk.10.12). lifesim-1mm: a core.worktree written into the shared
.git/config pointed every slot's git at another folder. Real git, temp HOME and XDG_CONFIG_HOME, fake delegate."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
import engine  # noqa: E402
import test_engine as te  # noqa: E402
import tl  # noqa: E402


def sh(*a, cwd):
    return subprocess.run(list(a), cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()


class SlotGitTest(unittest.TestCase):
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
        origin, self.repo, self.wt = home / "o.git", home / "repo", home / "repo" / ".slots" / "s1"
        sh("git", "init", "-q", "--bare", "-b", "main", str(origin), cwd=home)
        sh("git", "clone", "-q", str(origin), str(self.repo), cwd=home)
        (self.repo / "a.txt").write_text("a\n")
        sh("git", "add", "-A", cwd=self.repo)
        sh("git", "commit", "-qm", "init", cwd=self.repo)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.repo)
        sh("git", "worktree", "add", "-q", "--detach", str(self.wt), "origin/main", cwd=self.repo)
        sh("git", "fetch", "-q", cwd=self.wt)
        self.decoy = home / "decoy"
        self.decoy.mkdir()
        (self.decoy / "decoy.txt").write_text("not this slot's\n")
        (self.decoy / "a.txt").write_text("a decoy a\n")

    def plant_decoy(self):
        sh("git", "config", "core.worktree", str(self.decoy), cwd=self.repo)  # the shared .git/config

    def decoy_state(self):
        return sorted((p.name, p.read_text()) for p in self.decoy.iterdir())

    def all_committed_paths(self):
        return sh("git", "--git-dir", str(self.repo / ".git"), "log", "--all", "--name-only", "--format=", cwd=self.repo)

    def test_the_slot_stops_before_its_first_step_when_the_shared_config_redirects_git(self):
        self.plant_decoy()
        before = self.decoy_state()
        closed, blocked = [], []
        script = te.DelegateScript({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        with mock.patch.object(tl, "bd", return_value=mock.Mock(returncode=0, stdout="", stderr="")), \
                mock.patch.object(tl, "show", return_value=te.BEAD), mock.patch.object(tl, "comments", return_value=[]), \
                mock.patch.object(tl, "cmd_close", side_effect=lambda a: closed.append(a.reason) or 0), \
                mock.patch.object(tl, "cmd_block", side_effect=lambda a: blocked.append(a.why) or 0), \
                mock.patch.object(engine, "find_route", return_value="/fake/route.py"), \
                mock.patch.object(engine, "contract", return_value=te.CONTRACT), \
                mock.patch.object(engine, "call_delegate", script), mock.patch.object(engine.time, "sleep"):
            eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
            rc = eng.run()
        self.assertEqual(rc, 2)
        self.assertTrue(eng.why.startswith("tree: core.worktree is set"), eng.why)
        self.assertEqual(script.calls, [])  # no worker, reviewer or planner ever ran
        self.assertEqual(closed, [])  # the bead is blocked, not closed
        self.assertEqual(len(blocked), 1)
        ask = json.loads(eng.ask_path().read_text())
        self.assertEqual(ask["status"], "open")
        self.assertIn("git config --unset core.worktree", ask["question"])
        self.assertIn(str(self.repo), ask["question"])
        self.assertIn("config", ask["why"])  # names the setting and the file it came from
        trace = [json.loads(x) for x in eng.log_path.read_text().splitlines()]
        self.assertTrue(any(r["kind"] == "transition" and r.get("cause") == "wrong_tree" for r in trace))
        self.assertEqual(self.decoy_state(), before)
        self.assertNotIn("decoy.txt", self.all_committed_paths())
        self.assertEqual(sh("git", "--git-dir", str(self.repo / ".git"), "branch", "--list", "task/*", cwd=self.repo), "")

    def test_core_bare_true_stops_the_run_too(self):
        sh("git", "config", "core.bare", "true", cwd=self.repo)
        eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        with self.assertRaises(engine.Blocked) as cm:
            eng.assert_tree("write")
        self.assertIn("core.bare", cm.exception.why)

    def test_a_clean_slot_passes_the_tree_assert(self):
        eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        eng.assert_tree("plan")

    def test_pinned_git_stays_in_the_slot_whatever_the_shared_config_says(self):
        self.plant_decoy()
        eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        self.assertEqual(os.path.realpath(eng.git("rev-parse", "--show-toplevel")), str(self.wt))
        (self.wt / "f.txt").write_text("f\n")
        self.assertEqual(eng.stage_all(check=True), 0)
        staged = sh("git", "--git-dir", str(self.repo / ".git" / "worktrees" / "s1"), "--work-tree", str(self.wt),
                    "diff", "--cached", "--name-only", cwd=self.wt)
        self.assertEqual(staged, "f.txt")  # only the slot's own path; nothing from the decoy

    def test_stage_all_takes_only_the_slots_status_paths_deletions_and_untracked_included(self):
        eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        (self.wt / "a.txt").unlink()
        (self.wt / "new file.txt").write_text("n\n")
        self.assertEqual(eng.stage_all(check=True), 0)
        self.assertEqual(sh("git", "diff", "--cached", "--name-status", cwd=self.wt).split("\n"),
                         ["D\ta.txt", "A\tnew file.txt"])

    def test_the_pinned_env_reaches_a_route_run_and_a_check(self):
        gitdir = os.path.realpath(str(self.repo / ".git" / "worktrees" / "s1"))
        route = Path(self.tmp.name) / "route.py"
        route.write_text("import json, os\nprint(json.dumps({'v': 2, 'status': 'done', 'data': {'git_dir': "
                         "os.environ.get('GIT_DIR'), 'work_tree': os.environ.get('GIT_WORK_TREE')}}))\n")
        r, j = engine.call_delegate(str(route), "worker", "p", {"type": "object"}, str(self.wt), None, 30,
                                    Path(self.tmp.name) / "err.log")
        self.assertEqual(os.path.realpath(j["data"]["git_dir"]), gitdir)
        self.assertEqual(os.path.realpath(j["data"]["work_tree"]), str(self.wt))
        eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        rc, tail = eng.sh('echo "$GIT_DIR|$GIT_WORK_TREE"')
        self.assertEqual(rc, 0)
        d, w = tail.split("|")
        self.assertEqual((os.path.realpath(d), os.path.realpath(w)), (gitdir, str(self.wt)))
        # the main checkout is pinned to its own repo, not to a slot
        self.assertEqual(tl.pinned_env(self.repo)["GIT_DIR"], str(self.repo / ".git"))

    def test_doctor_warns_when_worktree_config_is_off(self):
        self.assertTrue(any("extensions.worktreeConfig" in w for w in tl.doctor_warnings(str(self.repo))))
        sh("git", "config", "extensions.worktreeConfig", "true", cwd=self.repo)
        self.assertEqual(tl.doctor_warnings(str(self.repo)), [])


if __name__ == "__main__":
    unittest.main()
