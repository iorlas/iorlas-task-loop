"""`tl prune`: run data and saved suite logs past loop.keep_days go (a bead still open or parked keeps its runs), merged clean build
trees and release branches go, nothing is forced, --dry-run only says, and a second run finds nothing."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import cast
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.prune import branches, runs, trees, verb
from taskloop.app.run import layout
from taskloop.contracts.bead import Bead
from taskloop.contracts.config import LoopConfig
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import BdError, BdFailure, Beads

DAY = 86400
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env={**os.environ, **GIT_ENV}, check=False)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


class Store:
    """bd's find: the beads that are not closed."""

    def __init__(self, *ids, fail=False):
        self.beads, self.fail = [Bead(id=i, title="", status=s) for i, s in ids], fail

    def find(self, query):
        if self.fail:
            raise BdFailure(BdError(kind="other", text="down"))
        return self.beads


class RunData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = ConfigDir(self.root / "cfg")
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        self.now = time.time()
        for bead, age in (("x-1", 30), ("x-2", 30), ("x-3", 1)):
            self.run_of(bead, age)

    def run_of(self, bead, age_days):
        stem = f"{bead}-20260101-000000"
        d = self.cfg.run_dir(stem)
        (d / "evidence").mkdir(parents=True)
        (d / "evidence" / "a.png").write_bytes(b"P" * 2048)
        log = self.cfg.engine_log(stem)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("{}\n")
        for p in (d / "evidence" / "a.png", d / "evidence", d, log):
            os.utime(p, (self.now - age_days * DAY,) * 2)

    def prune(self, store, dry_run=False, days=14):
        out = []
        loop = LoopConfig(keep_days=days, build_dir=str(self.root / "nowhere"))
        verb.run(self.cfg, loop, [str(self.root)], lambda r: cast(Beads, store), self.now, dry_run, out.append)
        return out

    def left(self):
        return sorted(p.name for p in (self.cfg.root / "runs").glob("*"))

    def test_an_old_run_of_a_closed_bead_goes_and_a_young_one_stays(self):
        self.prune(Store())
        self.assertEqual(self.left(), ["x-3-20260101-000000"])
        self.assertFalse(self.cfg.engine_log("x-1-20260101-000000").exists())
        self.assertTrue(self.cfg.engine_log("x-3-20260101-000000").exists())

    def test_beads_still_open_and_parked_keep_their_old_runs(self):
        out = self.prune(Store(("x-1", "open"), ("x-2", "blocked")))
        self.assertEqual(self.left(), ["x-1-20260101-000000", "x-2-20260101-000000", "x-3-20260101-000000"])
        self.assertTrue(self.cfg.engine_log("x-2-20260101-000000").exists())
        self.assertIn("2 of beads still open or parked", out[-1])

    def test_bd_not_answering_keeps_all_run_data_and_says_why(self):
        out = self.prune(Store(fail=True))
        self.assertEqual(len(self.left()), 3)
        self.assertTrue(any("run data kept: bd did not answer" in ln for ln in out))

    def test_dry_run_says_what_would_go_and_removes_nothing(self):
        out = self.prune(Store(), dry_run=True)
        self.assertEqual(len(self.left()), 3)
        self.assertTrue(self.cfg.engine_log("x-1-20260101-000000").exists())
        self.assertTrue(any("would remove" in ln and "x-1-20260101-000000" in ln for ln in out))

    def test_the_real_run_deletes_exactly_the_planned_list_from_one_scan(self):
        scans = []
        real_scan = layout.prune_run_dirs

        def scan(runs, days, exempt=(), dry_run=False):
            scans.append(dry_run)
            gone = real_scan(runs, days, exempt, dry_run)
            self.run_of("x-4", 30)  # an old run appears after the scan: it is not in the plan, so it stays
            return gone
        with mock.patch.object(layout, "prune_run_dirs", scan):
            self.prune(Store())
        self.assertEqual(scans, [True])
        self.assertEqual(self.left(), ["x-3-20260101-000000", "x-4-20260101-000000"])

    def test_old_saved_suite_logs_go_and_last_json_stays(self):
        rel = self.cfg.root / "releases"
        rel.mkdir(parents=True)
        for name, age in (("suite-1.log", 30), ("suite-2.log", 1), ("last.json", 30)):
            (rel / name).write_text("x" * 10)
            os.utime(rel / name, (self.now - age * DAY,) * 2)
        self.prune(Store())
        self.assertEqual(sorted(p.name for p in rel.iterdir()), ["last.json", "suite-2.log"])

    def test_a_second_run_removes_nothing(self):
        self.prune(Store())
        again = self.prune(Store())
        self.assertIn("removed 0 item(s)", " ".join(again))

    def test_the_one_age_number_is_the_config_key(self):
        self.prune(Store(), days=60)
        self.assertEqual(len(self.left()), 3)
        self.assertEqual(LoopConfig().keep_days, 14)
        self.assertEqual(runs.size_of(self.cfg.run_dir("x-3-20260101-000000")), 2048)


class Trees(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.origin, self.repo, self.build = self.root / "origin.git", self.root / "repo", self.root / "wt"
        git(self.root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(self.root, "clone", "-q", str(self.origin), str(self.repo))
        self.commit(self.repo, "base.txt")
        git(self.repo, "push", "-q", "origin", "HEAD:main")
        self.build.mkdir()
        self.later = time.time() + 30 * DAY  # "now" for tests that want the trees old

    def commit(self, where, name, text="x"):
        (Path(where) / name).write_text(text)
        git(where, "add", name)
        git(where, "commit", "-q", "-m", "add " + name)

    def tree(self, name, branch=None, merged=True):
        """A worktree under the build dir on a branch with one commit; merged: that commit is on origin/main by ancestry."""
        d = self.build / name
        git(self.repo, "worktree", "add", "-q", "-b", branch or "work/" + name, str(d), "origin/main")
        self.commit(d, name + ".txt")
        if merged:
            git(d, "push", "-q", "origin", "HEAD:main")
            git(self.repo, "fetch", "-q")
        return d

    def prune(self, dry_run=False, now=None, repos=None, days=14):
        return trees.prune_trees(self.build, repos or [str(self.repo)], days, now or self.later, dry_run)


class Landed(unittest.TestCase):
    """Closed beads' local task/* branches: `git branch -d`; origin's task/<bead> of a landed one: `git push origin --delete`."""

    commit = cast(Callable[..., None], Trees.commit)
    origin: Path
    repo: Path
    build: Path

    def store(self, **meta):
        states = (("a-1", "closed"), ("a-2", "open"), ("a-3", "closed"), ("a-4", "closed"), ("a-5", "closed"))
        beads = [Bead(id=i, title="", status=s, metadata=meta.get(i, {})) for i, s in states]
        return type("S", (), {"find": lambda self, q: beads})()

    def prune(self, dry_run=False, **meta):
        return branches.prune_branches([str(self.repo)], lambda r: cast(Beads, self.store(**meta)), dry_run)

    def heads(self):
        return git(self.repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/").split()

    def setUp(self):
        Trees.setUp(cast(Trees, self))
        for b in ("task/a-1", "task/a-2", "worker/a-1", "claude/a-1", "task/a-9", "task/custom"):
            git(self.repo, "branch", b, "origin/main")
        git(self.repo, "checkout", "-q", "-b", "task/a-3")  # unmerged: has a commit of its own
        (self.repo / "own.txt").write_text("x")
        git(self.repo, "add", "own.txt")
        git(self.repo, "commit", "-q", "-m", "own")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "worktree", "add", "-q", str(self.build / "held"), "-b", "task/a-4", "origin/main")


    def land_commit(self, bead):
        (self.repo / f"{bead}.txt").write_text("x")
        git(self.repo, "add", f"{bead}.txt")
        git(self.repo, "commit", "-q", "-m", f"work ({bead})")


if __name__ == "__main__":
    unittest.main()
