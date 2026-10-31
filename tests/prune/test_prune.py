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
from support import homes
from support.runs import manifest
from support.shells import quiet_shell
from support.who import who

from taskloop.adapters.git import RealGit
from taskloop.app.prune import runs, verb
from taskloop.app.reconcile.sweep import sweep
from taskloop.app.run import layout
from taskloop.app.run.layout import RunLayout
from taskloop.contracts.bead import Bead
from taskloop.contracts.config import LoopConfig
from taskloop.contracts.env import snapshot
from taskloop.contracts.ids import BeadId
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import BdError, BdFailure, Beads

DAY = 86400
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env={**os.environ, **GIT_ENV}, check=False)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


GIT = RealGit(snapshot())  # the helper classes below drive real git; their tests are in real/


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
        for bead, age in (("x-1", 45), ("x-2", 45), ("x-3", 1)):
            self.run_of(bead, age)

    def run_of(self, bead, age_days):
        stem = f"{bead}-20260101-000000"
        d = manifest(self.cfg, stem, bead, self.now - age_days * DAY).dir
        (d / "evidence").mkdir(parents=True)
        (d / "evidence" / "a.png").write_bytes(b"P" * 2048)
        log = self.cfg.engine_log(stem)
        log.write_text("{}\n")
        for p in (d / "evidence" / "a.png", d / "evidence", d / "manifest.json", d, log):
            os.utime(p, (self.now - age_days * DAY,) * 2)

    def prune(self, store, dry_run=False, days=14):
        out = []
        loop = LoopConfig(keep_days=days, build_dir=str(self.root / "nowhere"))
        verb.run(self.cfg, loop, [str(self.root)], lambda r: cast(Beads, store), self.now, dry_run, quiet_shell(), out.append, who=who())
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

        def scan(cfg, days, exempt=(), dry_run=False):
            scans.append(dry_run)
            gone = real_scan(cfg, days, exempt, dry_run)
            self.run_of("x-4", 45)  # an old run appears after the scan: it is not in the plan, so it stays
            return gone
        with mock.patch.object(layout, "prune_run_dirs", scan):
            self.prune(Store())
        self.assertEqual(scans, [True])
        self.assertEqual(self.left(), ["x-3-20260101-000000", "x-4-20260101-000000"])

    def test_old_saved_suite_logs_go_and_last_json_stays(self):
        rel = self.cfg.root / "releases"
        rel.mkdir(parents=True)
        for name, age in (("suite-1.log", 45), ("suite-2.log", 1), ("last.json", 45)):
            (rel / name).write_text("x" * 10)
            os.utime(rel / name, (self.now - age * DAY,) * 2)
        self.prune(Store())
        self.assertEqual(sorted(p.name for p in rel.iterdir()), ["last.json", "suite-2.log"])

    def test_a_second_run_removes_nothing(self):
        self.prune(Store())
        again = self.prune(Store())
        self.assertIn("removed 0 item(s)", " ".join(again))

    def test_a_closed_bead_keeps_its_run_data_30_days_whatever_the_config_says(self):
        for bead, age in (("x-5", 29), ("x-6", 31)):
            self.run_of(bead, age)
        self.prune(Store(), days=7)
        self.assertEqual(self.left(), ["x-3-20260101-000000", "x-5-20260101-000000"])
        self.assertTrue(self.cfg.engine_log("x-5-20260101-000000").exists())
        self.assertFalse(self.cfg.engine_log("x-6-20260101-000000").exists())

    def test_a_bead_that_is_not_closed_loses_nothing_at_any_age_by_prune_or_by_a_run_starting(self):
        self.run_of("x-7", 400)
        logs = self.cfg.run_dir("x-7-20260101-000000") / "checks"
        logs.mkdir()
        (logs / "00-c.r1.log").write_text("log")
        os.utime(logs / "00-c.r1.log", (self.now - 400 * DAY,) * 2)
        RunLayout.open("x-8", self.root / "wt", None, self.cfg, "/repo", self.now)  # a run starting sweeps nothing
        self.prune(Store(("x-7", "open")), days=7)
        self.assertTrue((logs / "00-c.r1.log").exists())
        self.assertTrue(self.cfg.engine_log("x-7-20260101-000000").exists())
        self.assertFalse(self.cfg.engine_log("x-1-20260101-000000").exists())  # a closed one's, 45 days old, went with prune

    def test_the_evidence_of_a_closed_bead_goes_with_its_run_folder_after_30_days_not_before(self):
        for bead, age in (("x-5", 29), ("x-6", 31)):
            self.run_of(bead, age)
            art = self.cfg.run_dir(f"{bead}-20260101-000000") / "artifacts" / "u" / "attempt-1"
            art.mkdir(parents=True)
            (art / "check.log").write_text("log")
            os.utime(art / "check.log", (self.now - age * DAY,) * 2)
            os.utime(art, (self.now - age * DAY,) * 2)
            os.utime(art.parent, (self.now - age * DAY,) * 2)
            os.utime(art.parent.parent, (self.now - age * DAY,) * 2)
            os.utime(self.cfg.run_dir(f"{bead}-20260101-000000"), (self.now - age * DAY,) * 2)
        self.prune(Store())
        self.assertTrue((self.cfg.run_dir("x-5-20260101-000000") / "artifacts/u/attempt-1/check.log").exists())
        self.assertFalse(self.cfg.run_dir("x-6-20260101-000000").exists())

    def test_the_one_age_number_is_the_config_key(self):
        self.prune(Store(), days=60)
        self.assertEqual(len(self.left()), 3)
        self.assertEqual(LoopConfig().keep_days, 14)
        self.assertEqual(runs.size_of(self.cfg.run_dir("x-3-20260101-000000") / "evidence"), 2048)


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
        return sweep(repos or [str(self.repo)], None, self.build, days, now or self.later, dry_run, GIT, homes.cfg())


class Landed(unittest.TestCase):
    """Closed beads' local task/* branches: `git branch -d`; origin's task/<bead> of a landed one: `git push origin --delete`."""

    commit = cast(Callable[..., None], Trees.commit)
    origin: Path
    repo: Path
    build: Path

    def store(self, **meta):
        states = (("a-1", "closed"), ("a-2", "open"), ("a-3", "closed"), ("a-4", "closed"), ("a-5", "closed"))
        beads = [Bead(id=BeadId(i), title="", status=s, metadata=meta.get(i, {})) for i, s in states]
        return type("S", (), {"find": lambda self, q: beads})()

    def prune(self, dry_run=False, **meta):
        return sweep([str(self.repo)], lambda r: cast(Beads, self.store(**meta)), None, 14, 0, dry_run, GIT, homes.cfg())

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
