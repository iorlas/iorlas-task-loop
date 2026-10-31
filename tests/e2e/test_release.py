"""dev/release.py against a fake remote: bare git repos in a temp dir. The release runs in this process (support.release_world: git real,
claude, just, bd and the suite faked); the launcher's re-exec and one red suite through real pytest run as real processes."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

import support.paths  # noqa: F401
from support import homes

# isort: split
import contextlib

from support.narrow import must
from support.procsim import real_proc
from support.release_world import IDENTITY, MARKET, PLUGIN, World, git

from taskloop.adapters import childenv, landlock
from taskloop.app.release import clone, manifest, selfupdate, shell
from taskloop.contracts.env import Env, snapshot
from taskloop.contracts.envvars import EnvVar

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "dev" / "release.py"
PYTEST_RED = ("FAILED tests/test_red.py::R::test_red_one - AssertionError: boom\n"  # the summary lines of a real pytest run
              "FAILED tests/test_red.py::R::test_red_two - ValueError: bang\n2 failed in 0.05s\n")


@unittest.skipIf(os.name == "nt", "the lock is fcntl")
class Release(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.rmtree)
        h = self.home = Path(self.tmp.name)
        self.origin, self.seed, self.repo = h / "o.git", h / "seed", h / "repo"
        self.morigin, self.market = h / "m.git", h / "market"
        self.world = World(h, self.repo, self.market)
        self.sh = shell.of(self.world.spawner, self.world.port, snapshot())
        env = dict(IDENTITY, TASK_LOOP_SUITE_HOST="1", TASK_LOOP_SUITE_WORKERS="1", XDG_CONFIG_HOME=str(h / "cfg"),
                   CLAUDE_CONFIG_DIR=str(h / "claude"))
        self.enterContext(self.world.active(env))
        self.git("init", "-q", "--bare", "-b", "main", str(self.origin), cwd=h)
        self.git("clone", "-q", str(self.origin), str(self.seed), cwd=h)
        self.git("checkout", "-q", "-B", "main", cwd=self.seed)  # an empty clone's branch follows init.defaultBranch
        self.write(self.seed / PLUGIN, json.dumps({"name": "iorlas-task-loop", "version": "0.1.0",
                                                   "author": {"name": "t"}}, indent=2) + "\n")
        self.write(self.seed / ".gitignore", "__pycache__/\n")
        self.write(self.seed / "tests" / "test_ok.py", "import unittest\n\n\nclass T(unittest.TestCase):\n"
                                                        "    def test_ok(self):\n        pass\n")
        self.commit(self.seed, "init")
        self.git("clone", "-q", str(self.origin), str(self.repo), cwd=h)
        self.git("init", "-q", "--bare", "-b", "main", str(self.morigin), cwd=h)
        self.git("clone", "-q", str(self.morigin), str(self.market), cwd=h)
        self.git("checkout", "-q", "-B", "main", cwd=self.market)
        self.write(self.market / MARKET, json.dumps({"name": "iorlas-marketplace", "plugins": [
            {"name": "other", "source": "./other", "version": "0.1.0"},
            {"name": "iorlas-task-loop", "source": "x", "version": "0.1.0"}]}, indent=2) + "\n")
        self.commit(self.market, "init")

    def rmtree(self):
        def force(fn, path, _):
            os.chmod(path, stat.S_IWRITE)
            fn(path)
        shutil.rmtree(self.tmp.name, onerror=force)
        with contextlib.suppress(OSError):
            self.tmp.cleanup()

    def git(self, *a, cwd):
        return git(*a, cwd=cwd)

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def sync_repo(self):
        """The main checkout follows origin: a release leaves it as it was, so a test that branches from it pulls first."""
        self.git("pull", "-q", "--ff-only", "origin", "main", cwd=self.repo)

    def commit(self, wt, msg):
        self.git("add", "-A", cwd=wt)
        self.git("commit", "-qm", msg, cwd=wt)
        self.git("push", "-q", "origin", "HEAD:main", cwd=wt)

    def release(self, *args):
        return self.world.release(*args)

    def real_release(self, *args):
        """dev/release.py as its own process, with a `uv` and a `bd` that only log (the venv is there; the tracker is not)."""
        shim = self.home / "bin"
        shim.mkdir(exist_ok=True)
        (shim / "bd").write_text('#!/bin/sh\necho "$@" >> "{}"\n'.format(self.home / "bd.log"))
        (shim / "uv").write_text("#!/bin/sh\nexit 0\n")
        for f in shim.iterdir():
            f.chmod(0o755)
        env = dict(os.environ, PATH=str(shim) + os.pathsep + os.environ["PATH"])
        return subprocess.run([sys.executable, str(RELEASE), *args, "--repo", str(self.repo), "--marketplace", str(self.market)],
                              env=env, capture_output=True, text=True, timeout=120, check=False)

    def version(self, bare, path=PLUGIN):
        return json.loads(self.git("show", "main:" + path, cwd=bare))

    def market_versions(self):
        return {p["name"]: p["version"] for p in self.version(self.morigin, MARKET)["plugins"]}

    def updates(self):
        return self.world.claude_log.count(["plugin", "update", "iorlas-task-loop@iorlas-marketplace"])

    @real_proc("the launcher replaces itself (os.execv) by origin/main's release.py: an exec, the lock dropped before it")
    def test_a_launcher_behind_origin_main_execs_origin_mains_release_once_with_the_same_args_and_no_lock_held(self):
        self.write(self.seed / "dev" / "release.py", "import os, sys\nprint('CHILD', sys.argv[1:], os.environ.get('TL_RELEASE_REEXEC'))\n"
                   "import fcntl, glob\nfor f in glob.glob(os.environ['XDG_CONFIG_HOME'] + '/task-loop/locks/release-*.lock'):\n"
                   "    fcntl.flock(os.open(f, os.O_RDWR), fcntl.LOCK_EX | fcntl.LOCK_NB)\nprint('LOCK TAKEN')\n")
        self.commit(self.seed, "newer release code")
        r = self.real_release("msg", "--minor")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"CHILD ['msg', '--minor', '--repo', '{self.repo}', '--marketplace', '{self.market}'] 1", r.stdout)
        self.assertIn("LOCK TAKEN", r.stdout)
        self.assertEqual(self.version(self.origin)["version"], "0.1.0")  # the fake child released nothing; this run did not either
        where = clone.clone_dir(homes.config_dir(), str(self.origin))
        self.assertIsNotNone(selfupdate.newer_release(ROOT, where, self.sh, Env({})))
        handed = Env({EnvVar.TL_RELEASE_REEXEC.value: "1"})
        self.assertIsNone(selfupdate.newer_release(ROOT, where, self.sh, handed))  # an exec'd release never execs again

    def test_the_exec_marker_reaches_no_child_the_release_starts(self):
        handed = Env({EnvVar.TL_RELEASE_REEXEC.value: "1", "PATH": "/bin"})
        self.assertIsNone(selfupdate.newer_release(self.repo, self.repo, self.sh, handed))
        self.assertNotIn(EnvVar.TL_RELEASE_REEXEC.value, childenv.tool_env(handed.vars))
        self.assertEqual(childenv.exec_env(handed, {EnvVar.TL_RELEASE_REEXEC: "1"})[EnvVar.TL_RELEASE_REEXEC.value], "1")

    def test_a_dirty_main_checkout_on_another_branch_is_released_from_and_left_byte_identical(self):
        self.git("checkout", "-q", "-b", "task/wip", cwd=self.repo)
        (self.repo / "stray.txt").write_text("x")
        (self.repo / PLUGIN).write_text("edited by hand\n")
        before = (self.git("rev-parse", "HEAD", cwd=self.repo), self.git("status", "--porcelain", cwd=self.repo),
                  (self.repo / PLUGIN).read_bytes())
        r = self.release("fix")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.version(self.origin)["version"], "0.1.1")
        self.assertEqual((self.git("rev-parse", "HEAD", cwd=self.repo), self.git("status", "--porcelain", cwd=self.repo),
                          (self.repo / PLUGIN).read_bytes()), before)
        self.assertEqual(self.git("branch", "--show-current", cwd=self.repo), "task/wip")
        clones = list((self.home / "cfg" / "task-loop" / "release").iterdir())
        self.assertEqual(len(clones), 1)  # the persistent clone: the next release reuses it
        self.assertEqual(self.release("fix again").returncode, 0)
        self.assertEqual(list((self.home / "cfg" / "task-loop" / "release").iterdir()), clones)
        self.assertEqual(self.version(self.origin)["version"], "0.1.2")

    def test_a_dirty_marketplace_checkout_is_refused_before_anything_moves(self):
        (self.market / "stray.txt").write_text("x")
        r = self.release("fix")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("dirty", r.stderr)
        self.assertEqual(self.version(self.origin)["version"], "0.1.0")
        self.assertEqual(self.world.claude_log, [])

    def test_a_red_gate_aborts_before_the_suite_with_the_output_tail_and_a_green_one_runs_just_check(self):
        self.write(self.seed / "justfile", "check:\n    true\n")
        self.commit(self.seed, "gate")
        self.git("pull", "-q", cwd=self.repo)
        self.world.just_exit = 1
        r = self.release("fix")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("gate is red", r.stderr)
        self.assertIn("ruff: E501 somewhere", r.stderr)
        self.assertEqual(self.version(self.origin)["version"], "0.1.0")
        self.assertEqual(self.git("status", "--porcelain", cwd=self.repo), "")
        self.world.just_exit = 0
        r = self.release("fix")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.version(self.origin)["version"], "0.1.1")
        self.assertEqual([c[-1] for c in self.world.just_log], ["check", "check"])

    def test_a_repo_without_a_justfile_skips_the_gate(self):
        r = self.release("fix", "--minor")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.world.just_log, [])
        self.assertEqual(self.version(self.origin)["version"], "0.2.0")  # --minor bumps the minor, resets the patch

    def test_a_red_suite_aborts_and_leaves_main_where_it_was(self):
        # the branch is stale (origin moved on) and rebase.updateRefs is on: a red suite after the rebase keeps the branch ref
        self.git("config", "rebase.updateRefs", "true", cwd=self.repo)
        start = self.git("rev-parse", "HEAD", cwd=self.repo)
        wt = self.branch_in_worktree("task/x")
        self.write(wt / "tests" / "RED", "FAILED tests/test_red.py::R::test_red - AssertionError: red after rebase\n1 failed\n")
        self.git("add", "-A", cwd=wt)
        self.git("commit", "-qm", "broken", cwd=wt)
        source = self.git("rev-parse", "task/x", cwd=self.repo)
        self.write(self.seed / "other.txt", "x\n")
        self.commit(self.seed, "advance main")
        origin = self.git("rev-parse", "main", cwd=self.origin)
        r = self.release("fix", "--from-branch", "task/x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("suite", r.stderr)
        self.assertIn("red after rebase", r.stderr)
        self.assertEqual(self.git("rev-parse", "main", cwd=self.origin), origin)
        self.assertEqual(self.git("rev-parse", "task/x", cwd=self.repo), source)  # a red release keeps the branch and worktree
        self.assertTrue(wt.is_dir())
        self.assertEqual(self.git("config", "--get", "rebase.updateRefs", cwd=self.repo), "true")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.repo), start)
        self.assertEqual(self.git("status", "--porcelain", cwd=self.repo), "")
        self.assertEqual(self.market_versions()["iorlas-task-loop"], "0.1.0")
        self.assertEqual(self.world.claude_log, [])

    def test_the_version_comes_from_origin_and_the_branch_lands_fast_forward(self):
        bumped = json.loads((self.seed / PLUGIN).read_text())
        bumped["version"] = "0.1.5"
        self.write(self.seed / PLUGIN, json.dumps(bumped, indent=2) + "\n")
        self.commit(self.seed, "0.1.5: elsewhere")  # the main checkout is not pulled: its plugin.json says 0.1.0
        self.git("fetch", "-q", "origin", cwd=self.repo)
        self.git("checkout", "-q", "-b", "task/y", "origin/main", cwd=self.repo)
        (self.repo / "feature.txt").write_text("y\n")
        self.git("add", "-A", cwd=self.repo)
        self.git("commit", "-qm", "Add feature (tl-1)", cwd=self.repo)
        self.git("checkout", "-q", "main", cwd=self.repo)
        r = self.release("feature", "--from-branch", "task/y", "--bead", "tl-1", "--reason", "landed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.version(self.origin)["version"], "0.1.6")
        self.assertEqual(self.git("log", "--format=%s", "-2", "main", cwd=self.origin).splitlines(),
                         ["0.1.6: feature", "Add feature (tl-1)"])
        self.assertIn("Co-Authored-By: Claude", self.git("log", "-1", "--format=%B", "main", cwd=self.origin))
        calls = self.world.store.calls  # bd's own argv: tests/adapters; the release is the bead's land, then the close
        self.assertEqual([c[:2] for c in calls], [("provenance", "record"), ("close", "tl-1")])
        self.assertEqual(calls[-1], ("close", "tl-1", "--reason", "landed"))
        self.assertEqual(self.market_versions()["iorlas-task-loop"], "0.1.6")
        self.assertEqual(json.loads((self.repo / PLUGIN).read_text())["author"], {"name": "t"})  # the rest kept

    def test_a_stale_branch_is_rebased_before_the_suite(self):
        self.git("config", "rebase.updateRefs", "true", cwd=self.repo)  # the removal of the source branch must survive it
        for remote_only in (False, True):
            with self.subTest(remote_only=remote_only):
                name = "task/remote" if remote_only else "task/local"
                worktree = self.home / "source-worktree"
                self.sync_repo()
                self.git("checkout", "-q", "-b", name, cwd=self.repo)
                self.write(self.repo / "z.txt", name + "\n")
                self.git("add", "-A", cwd=self.repo)
                self.git("commit", "-qm", name, cwd=self.repo)
                source = self.git("rev-parse", "HEAD", cwd=self.repo)
                self.git("checkout", "-q", "main", cwd=self.repo)
                if remote_only:
                    self.git("push", "-q", "origin", name, cwd=self.repo)
                    self.git("branch", "-D", name, cwd=self.repo)
                else:
                    self.git("worktree", "add", "-q", str(worktree), name, cwd=self.repo)
                self.git("pull", "-q", "--ff-only", "origin", "main", cwd=self.seed)
                self.write(self.seed / "other.txt", name + "\n")
                self.commit(self.seed, "moved on")
                runs = len(self.world.trees)
                r = self.release("z", "--from-branch", name)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(r.stdout.count("running the full suite"), 1)
                tested = self.world.trees[runs:]  # the suite saw both changes: the branch's and the one origin moved on with
                self.assertEqual([(t["z.txt"], t["other.txt"]) for t in tested], [((name + "\n").encode(),) * 2])
                if remote_only:  # no local branch to remove: the remote one stays
                    self.assertEqual(self.git("rev-parse", "origin/" + name, cwd=self.repo), source)
                else:  # the clean worktree and the local branch are gone
                    self.assertFalse(worktree.exists())
                    self.assertEqual(self.git("branch", "--list", name, cwd=self.repo), "")
                self.assertEqual(self.git("show", "main:z.txt", cwd=self.origin), name)
                self.assertEqual(self.git("show", "main:other.txt", cwd=self.origin), name)
                self.assertEqual(self.git("rev-list", "--merges", "main", cwd=self.origin), "")

    def test_a_rebase_conflict_aborts_and_restores_main(self):
        start = self.git("rev-parse", "HEAD", cwd=self.repo)
        self.git("checkout", "-q", "-b", "task/conflict", cwd=self.repo)
        self.write(self.repo / "conflict.txt", "branch\n")
        self.git("add", "-A", cwd=self.repo)
        self.git("commit", "-qm", "branch change", cwd=self.repo)
        source = self.git("rev-parse", "HEAD", cwd=self.repo)
        self.git("checkout", "-q", "main", cwd=self.repo)
        self.write(self.seed / "conflict.txt", "origin\n")
        self.commit(self.seed, "conflicting change")
        origin = self.git("rev-parse", "main", cwd=self.origin)
        r = self.release("conflict", "--from-branch", "task/conflict")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("rebase", r.stderr)
        self.assertNotIn("running the full suite", r.stdout)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.repo), start)
        self.assertEqual(self.git("branch", "--show-current", cwd=self.repo), "main")
        self.assertEqual(self.git("status", "--porcelain", cwd=self.repo), "")
        self.assertEqual(self.git("rev-parse", "task/conflict", cwd=self.repo), source)
        self.assertEqual(self.git("rev-parse", "main", cwd=self.origin), origin)
        self.assertFalse((self.repo / ".git" / "rebase-merge").exists())
        self.assertFalse((self.repo / ".git" / "rebase-apply").exists())
        self.assertEqual(self.market_versions()["iorlas-task-loop"], "0.1.0")
        self.assertEqual(self.world.claude_log, [])

    def test_two_branch_releases_queue_rebase_and_test_the_pushed_tree(self):
        # two releases at once, as threads of this process (the lock is the kernel's, per open file): the first holds its suite open
        ready, proceed = threading.Event(), threading.Event()
        self.git("pull", "-q", "--ff-only", "origin", "main", cwd=self.repo)
        for name in ("first", "second"):
            self.git("checkout", "-q", "-b", "task/" + name, "main", cwd=self.repo)
            self.write(self.repo / (name + ".txt"), name + "\n")
            self.git("add", "-A", cwd=self.repo)
            self.git("commit", "-qm", name + " change", cwd=self.repo)
            self.git("checkout", "-q", "main", cwd=self.repo)

        def hold_first(repo):
            if json.loads((repo / PLUGIN).read_text())["version"] == "0.1.1":
                ready.set()
                self.assertTrue(proceed.wait(120), "first suite was not released")

        def wait_for(predicate):
            deadline = time.monotonic() + 120
            while not predicate():
                self.assertLess(time.monotonic(), deadline, "release did not reach synchronization point")
                time.sleep(0.02)

        self.world.on_suite = hold_first
        results = {}
        threads = [threading.Thread(target=lambda n=n: results.update({n: self.release(n, "--from-branch", "task/" + n)}))
                   for n in ("first", "second")]
        try:
            threads[0].start()
            wait_for(ready.is_set)
            threads[1].start()
            wait_for(lambda: "waiting for the release lock" in self.world.stdout.bufs["second"].getvalue())
            self.assertRegex(self.world.stdout.bufs["second"].getvalue(),
                             rf"held by pid {os.getpid()} since \d{{2}}:\d{{2}}:\d{{2}}: first")
            self.assertTrue(threads[1].is_alive())
            self.assertEqual(self.version(self.origin)["version"], "0.1.0")
            self.assertEqual(len(self.world.trees), 1)  # the second release has not reached its suite
            proceed.set()
        finally:
            proceed.set()
            for t in threads:
                t.join(60)
        self.assertEqual({n: r.returncode for n, r in results.items()}, {"first": 0, "second": 0}, results)
        for version, message in (("0.1.1", "first"), ("0.1.2", "second")):
            commit = self.git("log", "--format=%H", "--fixed-strings", "--grep=" + version + ": " + message, "main", cwd=self.origin)
            self.assertTrue(commit)
            paths = self.git("ls-tree", "-r", "--name-only", commit, cwd=self.origin).splitlines()
            pushed = {p: subprocess.check_output(["git", "show", commit + ":" + p], cwd=self.origin) for p in paths}
            tested = [t for t in self.world.trees if json.loads(t[PLUGIN])["version"] == version]
            self.assertEqual(tested, [pushed])  # once, on exactly the tracked contents that landed
        for name in ("first", "second"):
            self.assertEqual(self.git("branch", "--list", "task/" + name, cwd=self.repo), "")  # landed: removed after the install
            self.assertEqual(self.git("show", "main:" + name + ".txt", cwd=self.origin), name)
            self.assertEqual(results[name].stdout.count("running the full suite"), 1)
        self.assertEqual(self.version(self.origin)["version"], "0.1.2")
        self.assertEqual(self.market_versions()["iorlas-task-loop"], "0.1.2")
        self.assertEqual(self.updates(), 2)
        self.assertEqual(self.git("status", "--porcelain", cwd=self.repo), "")

    def test_a_push_race_rebases_reruns_the_suite_and_takes_the_next_version(self):
        self.git("config", "rebase.updateRefs", "true", cwd=self.repo)
        self.git("checkout", "-q", "-b", "task/race", cwd=self.repo)
        self.write(self.repo / "feature.txt", "survives the push race\n")
        self.git("add", "-A", cwd=self.repo)
        self.git("commit", "-qm", "branch change", cwd=self.repo)
        self.git("checkout", "-q", "main", cwd=self.repo)

        def racer():  # another release lands between our fetch and our push
            self.write(self.seed / PLUGIN, (self.seed / PLUGIN).read_text().replace("0.1.0", "0.1.1"))
            self.git("commit", "-qam", "0.1.1: racer", cwd=self.seed)
            self.git("push", "-q", "origin", "HEAD:main", cwd=self.seed)

        self.world.before_push = racer
        r = self.release("mine", "--from-branch", "task/race")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("push race", r.stdout)
        self.assertRegex(r.stdout, r"origin/main [0-9a-f]{40} is not the base [0-9a-f]{40}")
        self.assertEqual(len(self.world.trees), 2)  # the suite ran again on the rebased tree
        self.assertEqual(self.git("log", "--format=%s", "-3", "main", cwd=self.origin).splitlines(),
                         ["0.1.2: mine", "branch change", "0.1.1: racer"])
        self.assertEqual(self.git("branch", "--list", "task/race", cwd=self.repo), "")  # landed: removed after the install
        self.assertEqual(self.git("show", "main:feature.txt", cwd=self.origin), "survives the push race")
        self.assertEqual(self.market_versions()["iorlas-task-loop"], "0.1.2")

    def test_a_clone_reset_under_the_release_pushes_nothing_and_tags_nothing(self):
        # 0.23.198: a second release (an older caller under another lock key) reset the shared clone to origin/main during the
        # suite; the push of HEAD:main was then a no-op that exited 0, and the tag went on the previous release's commit
        before = self.git("rev-parse", "main", cwd=self.origin)

        def reset_clone(tree):
            where = clone.clone_dir(homes.config_dir(), str(self.origin))
            self.git("reset", "-q", "--hard", "origin/main", cwd=where)
        self.world.on_suite = reset_clone
        r = self.release("fix")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("HEAD is not the 0.1.1 commit", r.stderr)
        self.assertEqual(self.git("rev-parse", "main", cwd=self.origin), before)
        self.assertEqual(self.tags(self.origin), [])

    def branch_in_worktree(self, name="task/y", dirty=False):
        """Branch `name` with one commit, checked out in its own worktree next to the main checkout; -> the worktree."""
        wt = self.home / "wt" / name.split("/")[1]
        self.git("fetch", "-q", "origin", cwd=self.repo)
        self.git("worktree", "add", "-q", "-b", name, str(wt), "origin/main", cwd=self.repo)
        (wt / "feature.txt").write_text("y\n")
        self.git("add", "-A", cwd=wt)
        self.git("commit", "-qm", "Add feature (tl-1)", cwd=wt)
        if dirty:
            (wt / "scratch.txt").write_text("not committed\n")
        return wt

    def branches(self):
        return self.git("for-each-ref", "--format=%(refname:short)", "refs/heads/task/", cwd=self.repo).split()

    def test_from_branch_removes_the_branch_and_its_worktree_after_the_push_and_the_install(self):
        wt = self.branch_in_worktree()
        r = self.release("feature", "--from-branch", "task/y")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(wt.exists())
        self.assertEqual(self.branches(), [])
        self.assertIn("removed branch task/y and its worktrees", r.stdout)
        self.assertEqual(self.git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.repo), "main")  # the main checkout was not touched
        # nothing landed meanwhile: no push race (tl-bxk.12.8), and the branch landed fast-forward under the version commit
        self.assertNotIn("push race", r.stdout)
        self.assertEqual(self.git("log", "--format=%s", "-2", "main", cwd=self.origin).splitlines(),
                         ["0.1.1: feature", "Add feature (tl-1)"])

    def test_a_worktree_with_an_untracked_file_is_never_forced_so_it_and_the_branch_stay(self):
        wt = self.branch_in_worktree(dirty=True)
        r = self.release("feature", "--from-branch", "task/y")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)  # the release itself succeeded
        self.assertTrue((wt / "scratch.txt").is_file())
        self.assertEqual(self.branches(), ["task/y"])
        self.assertIn("worktree", r.stdout)
        self.assertIn("kept", r.stdout)

    def test_a_loop_landing_during_every_suite_run_never_fails_the_release(self):
        # race test (tl-bxk.11.1): loops land on the same origin; each lands when the land lock is free. A land during
        # the suite moved origin/main, the retry's suite saw another land, and the release aborted. The release now
        # pushes under the land lock: after the first suite no land gets in between its rebase, suite and push.
        side = self.home / "side"
        self.git("clone", "-q", str(self.origin), str(side), cwd=self.home)
        self.git("pull", "-q", "origin", "main", cwd=self.repo)

        def a_loop_lands_meanwhile(_repo):  # what an engine does at land, the lock taken as it takes it
            try:
                with landlock.os_lock(landlock.land_lock_path(homes.cfg(), str(self.origin)), "a loop's land", timeout=0):
                    self.git("pull", "-q", "--rebase", "origin", "main", cwd=side)
                    name = f"land-{time.time_ns()}.txt"
                    self.write(side / name, "x")
                    self.git("add", name, cwd=side)
                    self.git("commit", "-qm", f"a bead (x-{name})", cwd=side)
                    self.git("push", "-q", "origin", "HEAD:main", cwd=side)
            except TimeoutError:
                pass  # a land would wait here

        self.world.on_suite = a_loop_lands_meanwhile
        r = self.release("mine")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        subjects = self.git("log", "--format=%s", "main", cwd=self.origin).splitlines()
        self.assertEqual(subjects[0], "0.1.1: mine")
        self.assertTrue(any(s.startswith("a bead") for s in subjects), subjects)
        self.assertEqual(self.git("rev-list", "--merges", "main", cwd=self.origin), "")
        self.assertEqual(len(self.world.trees), 2)  # the first suite, then the one after the land it let in

    def last(self):
        return json.loads((self.home / "cfg" / "task-loop" / "releases" / "last.json").read_text())

    def tags(self, bare):
        return self.git("tag", "-l", cwd=bare).split()

    def test_a_release_tags_both_repos_and_pushes_the_tags(self):
        r = self.release("fix")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.tags(self.origin), ["v0.1.1"])
        self.assertEqual(self.tags(self.morigin), ["iorlas-task-loop-v0.1.1"])
        self.assertEqual(self.git("rev-parse", "v0.1.1^{commit}", cwd=self.origin), self.git("rev-parse", "main", cwd=self.origin))
        self.assertEqual(self.git("rev-parse", "iorlas-task-loop-v0.1.1^{commit}", cwd=self.morigin),
                         self.git("rev-parse", "main", cwd=self.morigin))
        self.assertEqual(self.last()["ok"], True)
        self.assertEqual(self.last()["version"], "0.1.1")
        out = self.home / "shipped"  # the committed manifest matches exactly what was pushed
        self.git("clone", "-q", str(self.origin), str(out), cwd=self.home)
        self.assertEqual(manifest.verify(out), [])
        listed = {line.split("  ", 1)[1] for line in (out / manifest.NAME).read_text().splitlines()}
        self.assertEqual(listed, {PLUGIN, ".gitignore", "tests/test_ok.py"})
        (out / "tests" / "test_ok.py").write_text("changed")
        self.assertEqual(manifest.verify(out), ["tests/test_ok.py differs from MANIFEST.sha256"])

    def test_a_forced_install_error_exits_nonzero_after_one_retry_and_reports_to_the_bead(self):
        self.world.claude_fail = "always"
        wt = self.branch_in_worktree()
        r = self.release("fix", "--from-branch", "task/y", "--bead", "tl-x1", "--reason", "done")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(wt.is_dir())  # a failed install keeps the branch and its worktree
        self.assertEqual(self.branches(), ["task/y"])
        self.assertEqual(self.updates(), 2)
        self.assertIn("claude plugin update iorlas-task-loop@iorlas-marketplace", r.stderr)  # the failing command
        self.assertIn("fetch-pack", r.stderr)
        last_line = r.stderr.strip().splitlines()[-1]
        self.assertTrue(last_line.startswith("release FAILED: 0.1.1 was pushed but"), last_line)
        rec = self.last()
        self.assertEqual((rec["ok"], rec["version"]), (False, "0.1.1"))
        (comment,) = self.world.store.said("comments", "add")
        self.assertTrue(comment[2] == "tl-x1" and comment[3].startswith("release FAILED"), comment)
        self.assertEqual(self.version(self.origin)["version"], "0.1.1")  # pushed all the same: the failure is the install's
        self.assertEqual(self.tags(self.origin), ["v0.1.1"])

    def test_an_install_that_fails_once_is_retried_and_the_release_succeeds(self):
        self.world.claude_fail = "once"
        r = self.release("fix")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.updates(), 2)
        self.assertTrue((self.home / "claude/plugins/cache/iorlas-marketplace/iorlas-task-loop/0.1.1/.claude-plugin/plugin.json").is_file())

    def test_a_red_suite_writes_a_failure_record_with_the_failing_tests_and_comments_on_the_bead(self):
        """The suite's output (pytest's summary lines): the failing ids, the saved log, the record."""
        self.write(self.seed / "tests" / "RED", PYTEST_RED)
        self.commit(self.seed, "red")
        self.git("pull", "-q", "origin", "main", cwd=self.repo)
        r = self.release("fix", "--bead", "tl-x2")
        self.assertNotEqual(r.returncode, 0)
        for want in ("FAILED tests/test_red.py::R::test_red_one", "FAILED tests/test_red.py::R::test_red_two", "AssertionError: boom",
                     "ValueError: bang", "2 failed"):
            self.assertIn(want, r.stderr)
        m = re.search(r"full output: (\S+)", r.stderr)
        self.assertTrue(m, r.stderr)
        saved = Path(must(m).group(1))
        self.assertIn(str(self.home / "cfg" / "task-loop" / "releases"), str(saved))
        self.assertIn("FAILED tests/test_red.py::R::test_red_one", saved.read_text())
        self.assertEqual(self.git("status", "--porcelain", cwd=self.repo), "")
        self.assertEqual((self.tags(self.origin), self.tags(self.repo), self.tags(self.morigin)), ([], [], []))  # no tag when red
        rec = self.last()
        self.assertFalse(rec["ok"])
        self.assertEqual(rec["branch"], "main")
        self.assertTrue(any("test_red_one" in t for t in rec["tests"]), rec)
        self.assertTrue(Path(rec["log"]).is_file())
        (comment,) = self.world.store.said("comments", "add")
        self.assertTrue(comment[2] == "tl-x2" and comment[3].startswith("release FAILED"), comment)
        self.assertTrue(r.stderr.strip().splitlines()[-1].startswith("release FAILED: nothing released: "))
        self.assertEqual(self.world.store.said("close"), [])

    def test_a_later_success_replaces_the_failure_record(self):
        self.write(self.seed / "tests" / "RED", "FAILED tests/test_red.py::R::test_red_one - AssertionError: boom\n1 failed\n")
        self.commit(self.seed, "red")
        self.git("pull", "-q", "origin", "main", cwd=self.repo)
        self.assertNotEqual(self.release("fix", "--bead", "tl-x2").returncode, 0)
        self.assertFalse(self.last()["ok"])
        self.assertEqual(self.world.store.said("close"), [])
        self.git("rm", "-q", "tests/RED", cwd=self.repo)
        self.git("commit", "-qm", "green", cwd=self.repo)
        self.git("push", "-q", "origin", "HEAD:main", cwd=self.repo)
        self.assertEqual(self.release("fix").returncode, 0)
        self.assertTrue(self.last()["ok"])

    def test_a_bead_with_an_open_child_is_refused_before_anything_is_pushed(self):
        """tl-t7i.5 was closed by a release while its other half was open: --bead names finished work."""
        self.world.store.put({"id": "tl-kid", "title": "other half", "status": "open", "parent": "tl-half"})
        before = self.git("rev-parse", "origin/main", cwd=self.repo)
        r = self.release("fix", "--bead", "tl-half", "--reason", "done")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("tl-half has open children (tl-kid)", r.stderr)
        self.assertEqual(self.git("rev-parse", "origin/main", cwd=self.repo), before)
        self.assertEqual(self.world.store.said("close"), [])
        self.assertEqual(self.tags(self.origin), [])

    def test_a_bead_whose_children_are_closed_is_released_and_closed(self):
        self.world.store.put({"id": "tl-kid", "title": "other half", "status": "closed", "parent": "tl-half"})
        r = self.release("fix", "--bead", "tl-half", "--reason", "done")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.world.store.said("close", "tl-half")), 1)


if __name__ == "__main__":
    unittest.main()
