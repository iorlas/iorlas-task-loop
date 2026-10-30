"""What leaves the machine at a land: --no-verify on the push, the LFS objects before it, bd's Dolt data after the lock is let go."""
import os
import shutil
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.engine_case import CLEAN, PLAN, WRITE, EngineTest
from support.logs import records
from support.narrow_hosts import BdOut, FakeOutboundHost, FakeSyncHost

# isort: split
from taskloop.app.land import outbound
from taskloop.app.land.lander import Lander
from taskloop.app.land.sync import Sync as AfterLand

ATTR = "*.bin filter=lfs diff=lfs merge=lfs -text\n"
RUN = ({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})


class Argv(EngineTest):
    def test_a_git_push_gets_no_verify_after_push(self):
        self.assertEqual(outbound.land_argv(["git", "push", "origin", "HEAD:main"]), ["git", "push", "--no-verify", "origin", "HEAD:main"])
        again = ["git", "push", "--no-verify", "o", "HEAD:main"]
        self.assertEqual(outbound.land_argv(again), again)

    def test_a_custom_land_command_is_left_alone(self):
        self.assertEqual(outbound.land_argv(["just", "land"]), ["just", "land"])
        self.assertIsNone(outbound.target(["just", "land"]))

    def test_the_remote_and_the_pushed_ref_come_from_the_push_argv(self):
        self.assertEqual(outbound.target(["git", "push", "origin", "HEAD:main"]), ("origin", ["HEAD"]))
        self.assertEqual(outbound.target(["git", "push", "-q", "up", "+bd/x:main"]), ("up", ["bd/x"]))
        self.assertEqual(outbound.target(["git", "push"]), ("origin", ["HEAD"]))

    no_repo = True


class Sync(EngineTest):
    """bd's Dolt data after the land, over a small typed host (support/narrow_hosts.py FakeSyncHost, FakeOutboundHost), not an Engine."""

    def test_a_dry_run_syncs_nothing(self):
        events: list[str] = []
        self.assertEqual(AfterLand(FakeSyncHost(events, dry=True), BdOut(events)).run("abc"), "abc")
        self.assertEqual(events, [])

    def test_no_landed_sha_syncs_nothing(self):
        events: list[str] = []
        AfterLand(FakeSyncHost(events), BdOut(events)).run("")
        self.assertEqual(events, [])

    def test_a_failed_sync_blocks_the_bead_with_the_error_and_a_missing_remote_is_quiet(self):
        host = FakeOutboundHost(result=(1, "dolt: could not read Username for 'https://github.com'"))
        with self.assertRaises(RuntimeError) as cm:
            outbound.Outbound(host).bd_sync("abc1234567890")
        self.assertTrue(str(cm.exception).startswith("FAULT_LAND: "))
        self.assertIn("failed in", host.lines[0])
        self.assertIn("landed abc123456789", str(cm.exception))
        self.assertIn("could not read Username", str(cm.exception))
        quiet = FakeOutboundHost(result=(1, "Error: no remote configured"))
        outbound.Outbound(quiet).bd_sync("abc")
        self.assertEqual(quiet.lines, [])

    no_repo = True


class Land(EngineTest):
    def fake_lfs(self):
        """A git-lfs on PATH that notes its argv and what origin's main was at that moment."""
        d = Path(self.tmp.name) / "bin"
        d.mkdir()
        self.lfs_log = Path(self.tmp.name) / "lfs.log"
        origin = Path(self.tmp.name) / "o.git"
        tool = d / "git-lfs"
        tool.write_text(f'#!/bin/sh\necho "$@" >> {self.lfs_log}\ngit --git-dir={origin} rev-parse main >> {self.lfs_log}\n')
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
        return mock.patch.dict(os.environ, {"PATH": f"{d}{os.pathsep}{os.environ['PATH']}"})


    def test_an_lfs_repo_without_git_lfs_is_a_fault_with_the_branch_kept(self):
        self.put_repo_file(".gitattributes", ATTR)
        which = shutil.which
        with mock.patch("taskloop.app.land.outbound.shutil.which", lambda w, *a, **kw: None if w == "git-lfs" else which(w, *a, **kw)):
            rc, _ = self.run_engine(RUN)
        self.assertNotEqual(rc, 0)
        self.assertTrue(any("git-lfs is not installed" in r["text"] for r in records(self.eng, "warn")))
        self.assertFalse(self.closed)

    def test_a_repo_without_lfs_runs_no_lfs_and_syncs_bd_after_the_lock(self):
        held, seen = [], []

        @contextmanager
        def lock(this):
            held.append(True)
            try:
                yield
            finally:
                held.clear()

        def bd(*argv):
            seen.append((argv[:1], bool(held)))
            return mock.Mock(returncode=1 if argv[:1] == ("sync",) else 0, stdout="", stderr="dolt: boom")
        with mock.patch.object(Lander, "lock", lock), self.store.stub(bd_fn=bd):
            rc, _ = self.run_engine(RUN)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([h for a, h in seen if a == ("sync",)], [False])  # once, outside the lock, and its failure did not stop
        self.assertTrue(any("bd sync" in r["text"] for r in records(self.eng, "warn")))
