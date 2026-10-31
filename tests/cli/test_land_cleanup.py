"""The direct land verb verifies the base and records cleanup independently of its outcome."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fake_beads import FakeBeads
from support.fakegit import ScriptedGit

# isort: split
from taskloop.cli.land import cmd_land
from taskloop.contracts.gitfacts import Ref
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId
from taskloop.contracts.landed import LandedStore
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.slots import Checkout
from taskloop.stores.real import real_stores


class DirectGit(ScriptedGit):
    def __init__(self):
        super().__init__()
        self.delivered = True
        self.remote_oid = "wip"

    def rev_parse(self, d, rev):
        return "head" if rev.startswith("refs/heads/") else "land"

    def ls_remote(self, d, remote, *patterns):
        self.seen("snapshot")
        return [Ref(name="refs/heads/task/a", oid=self.remote_oid)]

    def checkouts(self, d):
        return [Checkout(path="/repo", branch="main", main=True)]

    def is_ancestor(self, d, a, b):
        return self.delivered


class DirectCleanup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.who = Identity(actor="tester", home=self.tmp.name)
        self.git = DirectGit()
        self.record = self.enterContext(mock.patch("taskloop.cli.land.verbs.land", return_value=0))
        self.retry = self.enterContext(mock.patch("taskloop.cli.land.cleanup.retry"))

    def land(self):
        return cmd_land(self.who, BeadId("a"), "land", FakeBeads(), self.git, "/wt", base="origin/main")

    def test_verified_direct_land_records_receipt_and_queues_both_refs(self):
        self.record.side_effect = lambda *args, **kw: self.assertTrue(self.git.ran("snapshot")) or 0
        self.assertEqual(self.land(), 0)
        self.assertEqual(self.record.call_args.kwargs["base"], "origin/main")
        row = self.retry.call_args.args[2]
        self.assertEqual((row.head, row.remote_oid, row.remote_outcome), ("head", "wip", "pending"))
        landed = LandedStore(self.who.config).get(BeadId("a"))
        assert landed is not None
        self.assertEqual(landed.sha, "land")
        run = RunLocator(self.who.config).of_bead("a")[0].run
        rows = [item.rec.kind for item in real_stores(self.who.config).run_log(run).read_from(0).items]
        self.assertIn("land_receipt", rows)
        self.assertIn("land_cleanup", rows)

    def test_refused_land_never_queues_cleanup(self):
        self.record.return_value = 1
        self.assertEqual(self.land(), 1)
        self.retry.assert_not_called()
        self.assertIsNone(LandedStore(self.who.config).get(BeadId("a")))

    def test_direct_refs_with_work_outside_the_landed_commit_are_kept(self):
        self.git.delivered = False
        self.assertEqual(self.land(), 0)
        row = self.retry.call_args.args[2]
        self.assertEqual((row.head, row.remote_oid, row.remote_outcome), ("land", "", "skipped"))

    def test_a_later_invocation_retries_the_original_logged_lease(self):
        self.assertEqual(self.land(), 0)
        self.git.remote_oid = "new"
        self.assertEqual(self.land(), 0)
        row = self.retry.call_args.args[2]
        self.assertEqual(row.remote_oid, "wip")
        runs = RunLocator(self.who.config).of_bead("a")
        self.assertEqual(len(runs), 2)
        rows = real_stores(self.who.config).run_log(runs[-1].run).read_from(0).items
        self.assertTrue(all(item.rec.run_id == runs[-1].run for item in rows))


if __name__ == "__main__":
    unittest.main()
