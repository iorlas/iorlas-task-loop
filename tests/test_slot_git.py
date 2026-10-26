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
sys.path.insert(0, str(ROOT / "tests"))
import engine  # noqa: E402
import test_engine as te  # noqa: E402
import tl  # noqa: E402
import delegate_link as dl  # noqa: E402
import fake_route  # noqa: E402


def sh(*a, cwd):
    return subprocess.run(list(a), cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()


class SlotGitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
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
        script = fake_route.Script({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        with mock.patch.object(tl, "bd", return_value=mock.Mock(returncode=0, stdout="", stderr="")), \
                mock.patch.object(tl, "show", return_value=te.BEAD), mock.patch.object(tl, "comments", return_value=[]), \
                mock.patch.object(tl, "cmd_close", side_effect=lambda a: closed.append(a.reason) or 0), \
                mock.patch.object(tl, "cmd_block", side_effect=lambda a: blocked.append(a.why) or 0), \
                te.delegate_stack(script):
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
        eng.writer_said = "added f.txt"  # an untracked file is staged only when the writer names it (tl-bxk.10.24)
        self.assertEqual(eng.stage_all(check=True), 0)
        staged = sh("git", "--git-dir", str(self.repo / ".git" / "worktrees" / "s1"), "--work-tree", str(self.wt),
                    "diff", "--cached", "--name-only", cwd=self.wt)
        self.assertEqual(staged, "f.txt")  # only the slot's own path; nothing from the decoy

    def test_stage_all_takes_only_the_slots_status_paths_deletions_and_untracked_included(self):
        eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        (self.wt / "a.txt").unlink()
        (self.wt / "new file.txt").write_text("n\n")
        eng.writer_said = "added new file.txt"
        self.assertEqual(eng.stage_all(check=True), 0)
        self.assertEqual(sh("git", "diff", "--cached", "--name-status", cwd=self.wt).split("\n"),
                         ["D\ta.txt", "A\tnew file.txt"])

    @te.POSIX_CHECK
    def test_workers_and_checks_are_not_pinned_but_the_engines_own_git_is(self):
        route = Path(self.tmp.name) / "route.py"
        route.write_text("import json, os, sys\nsys.path.insert(0, %r)\nimport fake_route\n"
                         "env = [k for k in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE') if k in os.environ]\n"
                         "print(json.dumps(fake_route.answer(fake_route.contract(), None, 'r1', False, {'env': env})))\n"
                         % str(ROOT / "skills" / "task-loop"))
        with mock.patch.dict(os.environ, {"GIT_DIR": "/x", "GIT_WORK_TREE": "/y", "GIT_INDEX_FILE": "/z"}):
            r = dl.call(dl.Resolved(route.parent, str(route), fake_route.CONTRACT, "explicit"),
                        dl.CallRequest("worker", "p", {"type": "object"}, str(self.wt), timeout_s=30),
                        runner=dl.ProcRunner(Path(self.tmp.name) / "err.log"))
            eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
            rc, tail = eng.sh('echo "[$GIT_DIR|$GIT_WORK_TREE|$GIT_INDEX_FILE]"')
            self.assertEqual(r.data["env"], [])
            self.assertEqual((rc, tail), (0, "[||]"))
            rc, tail = eng.sh('echo "$GIT_DIR|$GIT_WORK_TREE"', pin=True)
        gitdir = os.path.realpath(str(self.repo / ".git" / "worktrees" / "s1"))
        d, w = tail.split("|")
        self.assertEqual((os.path.realpath(d), os.path.realpath(w)), (gitdir, str(self.wt)))
        self.assertEqual(tl.pinned_env(self.repo)["GIT_DIR"], str(self.repo / ".git"))

    @te.POSIX_CHECK
    def test_a_check_runs_git_on_another_repo(self):
        other = Path(self.tmp.name) / "other"
        sh("git", "init", "-q", "-b", "main", str(other), cwd=self.tmp.name)
        (other / "o.txt").write_text("o\n")
        sh("git", "add", "-A", cwd=other)
        sh("git", "commit", "-qm", "o", cwd=other)
        sha = sh("git", "rev-parse", "HEAD", cwd=other)
        eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        rc, tail = eng.sh("git -C '%s' rev-parse HEAD && git -C '%s' cat-file -e %s && echo ok" % (other, other, sha))
        self.assertEqual((rc, tail), (0, sha + "\nok"))

    def test_a_worker_that_redirects_git_is_caught_after_its_node(self):
        decoy = self.decoy

        class Planting(fake_route.Script):
            def reply(self, role, prompt, schema, cwd, *a, **kw):
                out = super().reply(role, prompt, schema, cwd, *a, **kw)
                if role == "worker":
                    sh("git", "config", "core.worktree", str(decoy), cwd=cwd)
                return out

        script = Planting({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        before = self.decoy_state()
        landed = []
        with mock.patch.object(tl, "bd", return_value=mock.Mock(returncode=0, stdout="", stderr="")), \
                mock.patch.object(tl, "show", return_value=te.BEAD), mock.patch.object(tl, "comments", return_value=[]), \
                mock.patch.object(tl, "cmd_close", side_effect=lambda a: landed.append(1) or 0), \
                mock.patch.object(tl, "cmd_land", side_effect=lambda a: landed.append(1) or 0), \
                mock.patch.object(tl, "cmd_block", return_value=0), \
                te.delegate_stack(script):
            eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
            rc = eng.run()
        self.assertEqual(rc, 2)
        self.assertIn("after write", eng.why)
        self.assertTrue(eng.why.startswith("tree: core.worktree is set"), eng.why)
        self.assertNotIn("review", [c[0] for c in script.calls])
        self.assertEqual(landed, [])
        self.assertEqual(self.decoy_state(), before)
        self.assertNotIn("decoy.txt", self.all_committed_paths())
        # only the engine's pinned wip checkpoint of the slot's own file; nothing reached origin
        self.assertEqual(sorted(self.all_committed_paths().split()), ["a.txt", "f.txt"])
        self.assertNotIn("task/", sh("git", "ls-remote", "origin", cwd=self.wt))

    def test_samefile_compares_folders_and_falls_back_to_realpath(self):
        link = Path(self.tmp.name) / "link"
        link.symlink_to(self.wt)
        self.assertTrue(engine.same_dir(link, self.wt))
        self.assertFalse(engine.same_dir(self.decoy, self.wt))
        self.assertTrue(engine.same_dir(link / "nope", self.wt / "nope"))

    def test_doctor_warns_when_worktree_config_is_off(self):
        self.assertTrue(any("extensions.worktreeConfig" in w for w in tl.doctor_warnings(str(self.repo))))
        sh("git", "config", "extensions.worktreeConfig", "true", cwd=self.repo)
        self.assertEqual(tl.doctor_warnings(str(self.repo)), [])


if __name__ == "__main__":
    unittest.main()
