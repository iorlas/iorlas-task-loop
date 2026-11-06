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

import pytest
from support.case import Case
from support.narrow import must
from support.procsim import real_proc
from support.release_world import IDENTITY, MARKET, PLUGIN, World, git

from taskloop.adapters import childenv, landlock
from taskloop.app.release import canary, clone, manifest, publish, selfupdate, shell
from taskloop.contracts import wire
from taskloop.contracts.env import Env, snapshot
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.stores import ReleaseResultStore

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "dev" / "release.py"
PYTEST_RED = ("FAILED tests/test_red.py::R::test_red_one - AssertionError: boom\n"  # the summary lines of a real pytest run
              "FAILED tests/test_red.py::R::test_red_two - ValueError: bang\n2 failed in 0.05s\n")


@pytest.mark.skipif(os.name == "nt", reason="the lock is fcntl")
class Release(Case):
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.rmtree)
        h = self.home = Path(self.tmp.name)
        self.origin, self.seed, self.repo = h / "o.git", h / "seed", h / "repo"
        self.morigin, self.market = h / "m.git", h / "market"
        self.world = World(h, self.repo, self.market)
        self.sh = shell.of(self.world.spawner, self.world.port, snapshot())
        env = dict(IDENTITY, XDG_CONFIG_HOME=str(h / "cfg"),
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

    def test_consecutive_releases_succeed_without_a_minimum_interval(self):
        first = self.release("first")
        assert first.returncode == 0, first.stdout + first.stderr
        runs = len(self.world.trees)
        second = self.release("second")
        assert second.returncode == 0, second.stdout + second.stderr
        assert len(self.world.trees) == runs + 1
        assert self.version(self.origin)["version"] == "0.1.2"
        assert self.last()["ok"]
        assert self.last()["version"] == "0.1.2"
        assert self.world.store.said("comments", "add") == []
        assert self.git("log", "-1", "--format=%B", "main", cwd=self.origin) == "0.1.2: second" + publish.TRAILER

    def test_devbox_acknowledgement_records_the_ring_without_releasing_again(self):
        first = self.release("first")
        assert first.returncode == 0, first.stdout + first.stderr
        runs = len(self.world.trees)
        with unittest.mock.patch.dict(os.environ, XDG_CONFIG_HOME=str(self.home / "other-machine")):
            result = self.world.release("--devbox-ok", "0.1.1")
        assert result.returncode == 0, result.stdout + result.stderr
        assert self.git("rev-parse", "devbox-ok/v0.1.1", cwd=self.origin) == self.git("rev-parse", "v0.1.1", cwd=self.origin)
        assert len(self.world.trees) == runs
        assert self.version(self.origin)["version"] == "0.1.1"
        assert canary.mac_pin_refusal(self.home, str(self.origin), "0.1.1", self.world.port) == ""

    def test_consecutive_releases_across_config_dirs_and_url_spellings(self):
        first = self.release("first")
        assert first.returncode == 0, first.stderr
        self.git("remote", "set-url", "origin", self.origin.as_uri(), cwd=self.repo)
        other = self.home / "other-machine"
        with unittest.mock.patch.dict(os.environ, XDG_CONFIG_HOME=str(other)):
            result = self.release("second")
        assert result.returncode == 0, result.stdout + result.stderr
        assert self.version(self.origin)["version"] == "0.1.2"
        assert ReleaseResultStore(ConfigDir(other / "task-loop")).get() is not None
        assert self.world.store.said("comments", "add") == []

    def test_another_release_during_the_suite_retries_with_the_next_version(self):
        def racer(_tree):
            self.world.on_suite = None
            self.write(self.seed / PLUGIN, (self.seed / PLUGIN).read_text().replace("0.1.0", "0.1.1"))
            self.commit(self.seed, "0.1.1: racer")

        self.world.on_suite = racer
        result = self.release("mine")
        assert result.returncode == 0, result.stdout + result.stderr
        assert self.version(self.origin)["version"] == "0.1.2"
        assert len(self.world.trees) == 2
        assert self.world.store.said("comments", "add") == []
        assert self.last()["ok"]

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
        assert r.returncode == 0, r.stderr
        assert f"CHILD ['msg', '--minor', '--repo', '{self.repo}', '--marketplace', '{self.market}'] 1" in r.stdout
        assert "LOCK TAKEN" in r.stdout
        assert self.version(self.origin)["version"] == "0.1.0"  # the fake child released nothing; this run did not either
        where = clone.clone_dir(homes.config_dir(), str(self.origin))
        assert selfupdate.newer_release(ROOT, where, self.sh, Env({})) is not None
        handed = Env({EnvVar.TL_RELEASE_REEXEC.value: "1"})
        assert selfupdate.newer_release(ROOT, where, self.sh, handed) is None  # an exec'd release never execs again

    def test_the_exec_marker_reaches_no_child_the_release_starts(self):
        handed = Env({EnvVar.TL_RELEASE_REEXEC.value: "1", "PATH": "/bin"})
        assert selfupdate.newer_release(self.repo, self.repo, self.sh, handed) is None
        assert EnvVar.TL_RELEASE_REEXEC.value not in childenv.tool_env(handed.vars)
        assert childenv.exec_env(handed, {EnvVar.TL_RELEASE_REEXEC: "1"})[EnvVar.TL_RELEASE_REEXEC.value] == "1"

    def test_a_dirty_main_checkout_on_another_branch_is_released_from_and_left_byte_identical(self):
        self.git("checkout", "-q", "-b", "task/wip", cwd=self.repo)
        (self.repo / "stray.txt").write_text("x")
        (self.repo / PLUGIN).write_text("edited by hand\n")
        before = (self.git("rev-parse", "HEAD", cwd=self.repo), self.git("status", "--porcelain", cwd=self.repo),
                  (self.repo / PLUGIN).read_bytes())
        r = self.release("fix")
        assert r.returncode == 0, r.stdout + r.stderr
        assert self.version(self.origin)["version"] == "0.1.1"
        assert (self.git("rev-parse", "HEAD", cwd=self.repo), self.git("status", "--porcelain", cwd=self.repo),
                          (self.repo / PLUGIN).read_bytes()) == before
        assert self.git("branch", "--show-current", cwd=self.repo) == "task/wip"
        clones = list((self.home / "cfg" / "task-loop" / "release").glob("*/.git"))
        assert len(clones) == 1  # the persistent clone: the next release reuses it
        assert self.release("fix again").returncode == 0
        assert list((self.home / "cfg" / "task-loop" / "release").glob("*/.git")) == clones
        assert self.version(self.origin)["version"] == "0.1.2"

    def test_a_dirty_marketplace_checkout_is_refused_before_anything_moves(self):
        (self.market / "stray.txt").write_text("x")
        r = self.release("fix")
        assert r.returncode != 0
        assert "dirty" in r.stderr
        assert self.version(self.origin)["version"] == "0.1.0"
        assert self.world.claude_log == []

    def test_a_push_the_origin_refuses_prints_the_refusal_and_moves_nothing(self):
        hook = self.origin / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\necho 'tl pre-push: refused: refs/heads/main is not green for suite' >&2\nexit 1\n")
        hook.chmod(0o755)
        r = self.release("fix")
        assert r.returncode != 0
        assert "refused: refs/heads/main is not green for suite" in r.stderr
        assert self.version(self.origin)["version"] == "0.1.0"

    def test_a_red_gate_aborts_before_the_suite_with_the_output_tail_and_a_green_one_runs_just_check(self):
        self.write(self.seed / "justfile", "check:\n    true\n")
        self.commit(self.seed, "gate")
        self.git("pull", "-q", cwd=self.repo)
        self.world.just_exit = 1
        r = self.release("fix")
        assert r.returncode != 0
        assert "gate is red" in r.stderr
        assert "ruff: E501 somewhere" in r.stderr
        assert self.version(self.origin)["version"] == "0.1.0"
        assert self.git("status", "--porcelain", cwd=self.repo) == ""
        self.world.just_exit = 0
        r = self.release("fix")
        assert r.returncode == 0, r.stderr
        assert self.version(self.origin)["version"] == "0.1.1"
        assert [c[-1] for c in self.world.just_log] == ["check", "check"]

    def test_a_repo_without_a_justfile_skips_the_gate(self):
        r = self.release("fix", "--minor")
        assert r.returncode == 0, r.stderr
        assert self.world.just_log == []
        assert self.version(self.origin)["version"] == "0.2.0"  # --minor bumps the minor, resets the patch

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
        assert r.returncode != 0
        assert "suite" in r.stderr
        assert "red after rebase" in r.stderr
        assert self.git("rev-parse", "main", cwd=self.origin) == origin
        assert self.git("rev-parse", "task/x", cwd=self.repo) == source  # a red release keeps the branch and worktree
        assert wt.is_dir()
        assert self.git("config", "--get", "rebase.updateRefs", cwd=self.repo) == "true"
        assert self.git("rev-parse", "HEAD", cwd=self.repo) == start
        assert self.git("status", "--porcelain", cwd=self.repo) == ""
        assert self.market_versions()["iorlas-task-loop"] == "0.1.0"
        assert self.world.claude_log == []

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
        assert r.returncode == 0, r.stdout + r.stderr
        assert self.version(self.origin)["version"] == "0.1.6"
        assert self.git("log", "--format=%s", "-2", "main", cwd=self.origin).splitlines() == ["0.1.6: feature", "Add feature (tl-1)"]
        assert "Co-Authored-By: Claude" in self.git("log", "-1", "--format=%B", "main", cwd=self.origin)
        calls = self.world.store.calls  # bd's own argv: tests/adapters; the release is the bead's land, its landed record, then the close
        assert [c[:2] for c in calls] == [("provenance", "record"), ("update", "tl-1"), ("close", "tl-1")]  # update: landed sha
        assert calls[-1] == ("close", "tl-1", "--reason", "landed")
        assert self.market_versions()["iorlas-task-loop"] == "0.1.6"
        assert json.loads((self.repo / PLUGIN).read_text())["author"] == {"name": "t"}  # the rest kept

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
                assert r.returncode == 0, r.stdout + r.stderr
                assert r.stdout.count("running the tests") == 1
                tested = self.world.trees[runs:]  # the suite saw both changes: the branch's and the one origin moved on with
                assert [(t["z.txt"], t["other.txt"]) for t in tested] == [((name + "\n").encode(),) * 2]
                if remote_only:  # no local branch to remove: the remote one stays
                    assert self.git("rev-parse", "origin/" + name, cwd=self.repo) == source
                else:  # the clean worktree and the local branch are gone
                    assert not worktree.exists()
                    assert self.git("branch", "--list", name, cwd=self.repo) == ""
                assert self.git("show", "main:z.txt", cwd=self.origin) == name
                assert self.git("show", "main:other.txt", cwd=self.origin) == name
                assert self.git("rev-list", "--merges", "main", cwd=self.origin) == ""

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
        assert r.returncode != 0
        assert "rebase" in r.stderr
        assert "running the tests" not in r.stdout
        assert self.git("rev-parse", "HEAD", cwd=self.repo) == start
        assert self.git("branch", "--show-current", cwd=self.repo) == "main"
        assert self.git("status", "--porcelain", cwd=self.repo) == ""
        assert self.git("rev-parse", "task/conflict", cwd=self.repo) == source
        assert self.git("rev-parse", "main", cwd=self.origin) == origin
        assert not (self.repo / ".git" / "rebase-merge").exists()
        assert not (self.repo / ".git" / "rebase-apply").exists()
        assert self.market_versions()["iorlas-task-loop"] == "0.1.0"
        assert self.world.claude_log == []

    def test_two_branch_releases_queue_rebase_and_test_the_pushed_tree(self):  # noqa: PLR0915
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
            if json.loads((repo / PLUGIN).read_text())["version"] == "0.1.0":
                ready.set()
                assert proceed.wait(120), "first suite was not released"

        def wait_for(predicate):
            deadline = time.monotonic() + 120
            while not predicate():
                assert time.monotonic() < deadline, "release did not reach synchronization point"
                time.sleep(0.02)

        self.world.on_suite = hold_first
        results = {}
        threads = [threading.Thread(target=lambda n=n: results.update({n: self.release(
            n, "--from-branch", "task/" + n)}))
                   for n in ("first", "second")]
        try:
            threads[0].start()
            wait_for(ready.is_set)
            threads[1].start()
            wait_for(lambda: "waiting for the release lock" in self.world.stdout.bufs["second"].getvalue())
            assert re.search(rf"held by pid {os.getpid()} since \d{{2}}:\d{{2}}:\d{{2}}: first",
                             self.world.stdout.bufs["second"].getvalue())
            assert threads[1].is_alive()
            assert self.version(self.origin)["version"] == "0.1.0"
            assert len(self.world.trees) == 1  # the second release has not reached its suite
            proceed.set()
        finally:
            proceed.set()
            for t in threads:
                t.join(60)
        assert {n: r.returncode for n, r in results.items()} == {"first": 0, "second": 0}, results
        for version, message in (("0.1.1", "first"), ("0.1.2", "second")):
            commit = self.git("log", "--format=%H", "--fixed-strings", "--grep=" + version + ": " + message, "main", cwd=self.origin)
            assert commit
            paths = self.git("ls-tree", "-r", "--name-only", commit, cwd=self.origin).splitlines()
            pushed = {p: subprocess.check_output(["git", "show", commit + ":" + p], cwd=self.origin) for p in paths}
            tested = [t for t in self.world.trees if t.get(message + ".txt") == (message + "\n").encode()]
            if message == "first":
                tested = [t for t in tested if "second.txt" not in t]
            assert len(tested) == 1
            for generated in (PLUGIN, manifest.NAME):
                pushed.pop(generated, None)
            assert {p: b for p, b in tested[0].items() if p not in (PLUGIN, manifest.NAME)} == pushed
        for name in ("first", "second"):
            assert self.git("branch", "--list", "task/" + name, cwd=self.repo) == ""  # landed: removed after the install
            assert self.git("show", "main:" + name + ".txt", cwd=self.origin) == name
            assert results[name].stdout.count("running the tests") == 1
        assert self.version(self.origin)["version"] == "0.1.2"
        assert self.market_versions()["iorlas-task-loop"] == "0.1.2"
        assert self.updates() == 2
        assert self.git("status", "--porcelain", cwd=self.repo) == ""

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
        assert r.returncode == 0, r.stdout + r.stderr
        assert "push race" in r.stdout
        assert re.search(r"origin/main [0-9a-f]{40} is not the base [0-9a-f]{40}", r.stdout)
        assert len(self.world.trees) == 2  # the suite ran again on the rebased tree
        assert (
            self.git("log", "--format=%s", "-3", "main", cwd=self.origin).splitlines()
            == ["0.1.2: mine", "branch change", "0.1.1: racer"]
        )
        assert self.git("branch", "--list", "task/race", cwd=self.repo) == ""  # landed: removed after the install
        assert self.git("show", "main:feature.txt", cwd=self.origin) == "survives the push race"
        assert self.market_versions()["iorlas-task-loop"] == "0.1.2"

    def test_a_clone_reset_under_the_release_pushes_nothing_and_tags_nothing(self):
        # 0.23.198: a second release (an older caller under another lock key) reset the shared clone to origin/main during the
        # suite; the push of HEAD:main was then a no-op that exited 0, and the tag went on the previous release's commit
        before = self.git("rev-parse", "main", cwd=self.origin)

        def reset_clone(tree):
            where = clone.clone_dir(homes.config_dir(), str(self.origin))
            self.git("commit", "--allow-empty", "-qm", "unexpected clone mutation", cwd=where)
        self.world.on_suite = reset_clone
        r = self.release("fix")
        assert r.returncode == 1, r.stdout + r.stderr
        assert "release clone HEAD changed during the suite" in r.stderr
        assert self.git("rev-parse", "main", cwd=self.origin) == before
        assert self.tags(self.origin) == []

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
        assert r.returncode == 0, r.stdout + r.stderr
        assert not wt.exists()
        assert self.branches() == []
        assert "removed branch task/y and its worktrees" in r.stdout
        assert self.git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.repo) == "main"  # the main checkout was not touched
        # nothing landed meanwhile: no push race (tl-bxk.12.8), and the branch landed fast-forward under the version commit
        assert "push race" not in r.stdout
        assert self.git("log", "--format=%s", "-2", "main", cwd=self.origin).splitlines() == ["0.1.1: feature", "Add feature (tl-1)"]

    def test_a_worktree_with_an_untracked_file_is_never_forced_so_it_and_the_branch_stay(self):
        wt = self.branch_in_worktree(dirty=True)
        r = self.release("feature", "--from-branch", "task/y")
        assert r.returncode == 0, r.stdout + r.stderr  # the release itself succeeded
        assert (wt / "scratch.txt").is_file()
        assert self.branches() == ["task/y"]
        assert "worktree" in r.stdout
        assert "kept" in r.stdout

    def test_a_loop_landing_during_the_suite_is_reverified_outside_the_land_lock(self):
        # Both suite runs allow a loop to acquire the land lock; only the first introduces a new tree.
        side = self.home / "side"
        self.git("clone", "-q", str(self.origin), str(side), cwd=self.home)
        self.git("pull", "-q", "origin", "main", cwd=self.repo)

        def a_loop_lands_meanwhile(_repo):  # what an engine does at land, the lock taken as it takes it
            assert len(self.world.trees) <= 2
            try:
                with landlock.os_lock(landlock.land_lock_path(homes.cfg(), str(self.origin)), "a loop's land", timeout=0):
                    if len(self.world.trees) > 1:
                        return
                    self.git("pull", "-q", "--rebase", "origin", "main", cwd=side)
                    name = f"land-{time.time_ns()}.txt"
                    self.write(side / name, "x")
                    self.git("add", name, cwd=side)
                    self.git("commit", "-qm", f"a bead (x-{name})", cwd=side)
                    self.git("push", "-q", "origin", "HEAD:main", cwd=side)
            except TimeoutError:
                pytest.fail("suite ran while the release held the land lock")

        self.world.on_suite = a_loop_lands_meanwhile
        r = self.release("mine")
        assert r.returncode == 0, r.stdout + r.stderr
        subjects = self.git("log", "--format=%s", "main", cwd=self.origin).splitlines()
        assert subjects[0] == "0.1.1: mine"
        assert any(s.startswith("a bead") for s in subjects), subjects
        assert self.git("rev-list", "--merges", "main", cwd=self.origin) == ""
        assert len(self.world.trees) == 2  # the first suite, then the one after the land it let in

    def last(self):
        return wire.dump(must(ReleaseResultStore(ConfigDir(self.home / "cfg" / "task-loop")).get()))

    def tags(self, bare):
        return self.git("tag", "-l", cwd=bare).split()

    def test_a_release_tags_both_repos_and_pushes_the_tags(self):
        r = self.release("fix")
        assert r.returncode == 0, r.stdout + r.stderr
        assert self.tags(self.origin) == ["v0.1.1"]
        assert self.tags(self.morigin) == ["iorlas-task-loop-v0.1.1"]
        assert self.git("rev-parse", "v0.1.1^{commit}", cwd=self.origin) == self.git("rev-parse", "main", cwd=self.origin)
        assert (
            self.git("rev-parse", "iorlas-task-loop-v0.1.1^{commit}", cwd=self.morigin)
            == self.git("rev-parse", "main", cwd=self.morigin)
        )
        assert self.last()["ok"] is True
        assert self.last()["version"] == "0.1.1"
        out = self.home / "shipped"  # the committed manifest matches exactly what was pushed
        self.git("clone", "-q", str(self.origin), str(out), cwd=self.home)
        assert manifest.verify(out) == []
        listed = {line.split("  ", 1)[1] for line in (out / manifest.NAME).read_text().splitlines()}
        assert listed == {PLUGIN, ".gitignore", "tests/test_ok.py"}
        (out / "tests" / "test_ok.py").write_text("changed")
        assert manifest.verify(out) == ["tests/test_ok.py differs from MANIFEST.sha256"]

    def test_a_forced_install_error_exits_nonzero_after_one_retry_and_reports_to_the_bead(self):
        self.world.claude_fail = "always"
        wt = self.branch_in_worktree()
        r = self.release("fix", "--from-branch", "task/y", "--bead", "tl-x1", "--reason", "done")
        assert r.returncode != 0, r.stdout + r.stderr
        assert wt.is_dir()  # a failed install keeps the branch and its worktree
        assert self.branches() == ["task/y"]
        assert self.updates() == 2
        assert "claude plugin update iorlas-task-loop@iorlas-marketplace" in r.stderr  # the failing command
        assert "fetch-pack" in r.stderr
        last_line = r.stderr.strip().splitlines()[-1]
        assert last_line.startswith("release FAILED: 0.1.1 was pushed but"), last_line
        rec = self.last()
        assert (rec["ok"], rec["version"]) == (False, "0.1.1")
        (comment,) = self.world.store.said("comments", "add")
        assert comment[2] == "tl-x1" and comment[3].startswith("release FAILED"), comment
        assert self.version(self.origin)["version"] == "0.1.1"  # pushed all the same: the failure is the install's
        assert self.tags(self.origin) == ["v0.1.1"]

    def test_an_install_that_fails_once_is_retried_and_the_release_succeeds(self):
        self.world.claude_fail = "once"
        r = self.release("fix")
        assert r.returncode == 0, r.stdout + r.stderr
        assert self.updates() == 2
        assert (self.home / "claude/plugins/cache/iorlas-marketplace/iorlas-task-loop/0.1.1/.claude-plugin/plugin.json").is_file()

    def test_a_red_suite_writes_a_failure_record_with_the_failing_tests_and_comments_on_the_bead(self):
        """The suite's output (pytest's summary lines): the failing ids, the saved log, the record."""
        self.write(self.seed / "tests" / "RED", PYTEST_RED)
        self.commit(self.seed, "red")
        self.git("pull", "-q", "origin", "main", cwd=self.repo)
        r = self.release("fix", "--bead", "tl-x2")
        assert r.returncode != 0
        for want in ("FAILED tests/test_red.py::R::test_red_one", "FAILED tests/test_red.py::R::test_red_two", "AssertionError: boom",
                     "ValueError: bang", "2 failed"):
            assert want in r.stderr
        m = re.search(r"full output: (\S+)", r.stderr)
        assert m, r.stderr
        saved = Path(must(m).group(1))
        assert str(self.home / "cfg" / "task-loop" / "releases") in str(saved)
        assert "FAILED tests/test_red.py::R::test_red_one" in saved.read_text()
        assert self.git("status", "--porcelain", cwd=self.repo) == ""
        assert (self.tags(self.origin), self.tags(self.repo), self.tags(self.morigin)) == ([], [], [])  # no tag when red
        rec = self.last()
        assert not rec["ok"]
        assert rec["branch"] == "main"
        assert any("test_red_one" in t for t in rec["tests"]), rec
        assert Path(rec["log"]).is_file()
        (comment,) = self.world.store.said("comments", "add")
        assert comment[2] == "tl-x2" and comment[3].startswith("release FAILED"), comment
        assert r.stderr.strip().splitlines()[-1].startswith("release FAILED: nothing released: ")
        assert self.world.store.said("close") == []

    def test_a_later_success_replaces_the_failure_record(self):
        self.write(self.seed / "tests" / "RED", "FAILED tests/test_red.py::R::test_red_one - AssertionError: boom\n1 failed\n")
        self.commit(self.seed, "red")
        self.git("pull", "-q", "origin", "main", cwd=self.repo)
        assert self.release("fix", "--bead", "tl-x2").returncode != 0
        assert not self.last()["ok"]
        assert self.world.store.said("close") == []
        self.git("rm", "-q", "tests/RED", cwd=self.repo)
        self.git("commit", "-qm", "green", cwd=self.repo)
        self.git("push", "-q", "origin", "HEAD:main", cwd=self.repo)
        assert self.release("fix").returncode == 0
        assert self.last()["ok"]

    def test_a_bead_with_an_open_child_is_refused_before_anything_is_pushed(self):
        """tl-t7i.5 was closed by a release while its other half was open: --bead names finished work."""
        self.world.store.put({"id": "tl-kid", "title": "other half", "status": "open", "parent": "tl-half"})
        before = self.git("rev-parse", "origin/main", cwd=self.repo)
        r = self.release("fix", "--bead", "tl-half", "--reason", "done")
        assert r.returncode != 0
        assert "tl-half has open children (tl-kid)" in r.stderr
        assert self.git("rev-parse", "origin/main", cwd=self.repo) == before
        assert self.world.store.said("close") == []
        assert self.tags(self.origin) == []

    def test_a_bead_whose_children_are_closed_is_released_and_closed(self):
        self.world.store.put({"id": "tl-kid", "title": "other half", "status": "closed", "parent": "tl-half"})
        r = self.release("fix", "--bead", "tl-half", "--reason", "done")
        assert r.returncode == 0, r.stdout + r.stderr
        assert len(self.world.store.said("close", "tl-half")) == 1
