"""bd outages retain the last observation without renewing its age or hiding the failure."""

import json
import tempfile
import unittest
from pathlib import Path

from support.dashlogs import bead
from support.fakes import FakeBeadStore
from support.narrow import must
from support.repos import write_repos

from taskloop.contracts.bead import BdError
from taskloop.contracts.ids import BeadId, loop_key
from taskloop.contracts.ports import BdFailure
from taskloop_dash.app import Dash
from taskloop_dash.env import Env, Ports

ERROR = "other: database locked\nretry later"


def unreadable(_):
    raise BdFailure(BdError(kind="other", text="database locked\nretry later"))


class BdHealth(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.repo = str(root / "project")
        Path(self.repo).mkdir()
        self.cfg = root / "cfg"
        self.cfg.mkdir()
        write_repos(self.cfg / "repos.json", Path(self.repo))
        self.store = FakeBeadStore()
        self.store.put(bead("b-1", "Old claim", "in_progress"))
        self.store.note("b-1", "Old comment")
        self.now = 1000.0
        self.env = Env(self.cfg, home=root, ports=Ports(store=lambda _: self.store), clock=lambda: self.now)
        self.dash = Dash(self.env)

    def test_failed_reads_keep_rows_and_time_then_recover_without_caching_failure(self):
        for comment in (False, True):
            with self.subTest(comments=comment):
                reader = self.dash.beads
                bid = BeadId("b-1") if comment else ""
                def read(reader=reader, bid=bid, comment=comment):
                    return reader.comments(self.repo, BeadId(bid)) if comment else reader.beads_of(self.repo)
                old = read()
                ok_at = self.now
                self.assertEqual(reader.health(self.repo, bid), (ok_at, ""))
                self.now += 61
                stub = {"comments_fn" if comment else "find_fn": unreadable}
                with self.store.stub(**stub):
                    self.assertEqual(read(), old)
                    self.assertEqual(reader.health(self.repo, bid), (ok_at, ERROR))
                    self.now += 1
                    self.assertEqual(read(), old)
                    self.assertEqual(reader.health(self.repo, bid)[0], ok_at)
                self.assertEqual(read(), old)
                self.assertEqual(reader.health(self.repo, bid), (self.now, ""))

    def test_cold_failure_has_no_success_time_and_is_retried_immediately(self):
        with self.store.stub(find_fn=unreadable, comments_fn=unreadable):
            self.assertEqual(self.dash.beads.beads_of(self.repo), [])
            self.assertEqual(self.dash.beads.comments(self.repo, BeadId("b-1")), [])
        for bid in ("", "b-1"):
            self.assertEqual(self.dash.beads.health(self.repo, bid), (None, ERROR))
        self.assertTrue(self.dash.beads.beads_of(self.repo))
        self.assertTrue(self.dash.beads.comments(self.repo, BeadId("b-1")))

    def test_snapshot_publishes_health_and_changes_version_on_failure_and_recovery(self):
        before = self.dash.reads.snapshot()
        self.now += 61
        with self.store.stub(find_fn=unreadable):
            failed = self.dash.reads.snapshot()
        self.assertEqual(failed.beads, before.beads)
        self.assertEqual(failed.projects[0].bd_ok_at, 1000.0)
        self.assertEqual(failed.projects[0].bd_error, ERROR)
        self.assertNotEqual(failed.version, before.version)
        self.now += 2
        recovered = self.dash.reads.snapshot()
        self.assertEqual((recovered.projects[0].bd_ok_at, recovered.projects[0].bd_error), (self.now, ""))
        self.assertNotEqual(recovered.version, failed.version)

    def test_detail_publishes_comment_failure_and_keeps_last_comments(self):
        query = {"project": loop_key(self.repo), "id": "b-1"}
        before = json.loads(self.dash.reads.get("/api/bead", query)[1])
        self.now += 16
        with self.store.stub(comments_fn=unreadable):
            failed = json.loads(self.dash.reads.get("/api/bead", query)[1])
        self.assertEqual(failed["comments"], before["comments"])
        self.assertEqual(failed["bd_ok_at"], 1000.0)
        self.assertEqual(failed["bd_error"], ERROR)
        self.assertNotEqual(failed["version"], before["version"])
        recovered = json.loads(self.dash.reads.get("/api/bead", query)[1])
        self.assertEqual((recovered["bd_ok_at"], recovered["bd_error"]), (self.now, ""))

    def test_shared_read_preserves_original_success_time(self):
        self.dash.beads.beads_of(self.repo)
        self.now += 10
        fresh = Dash(Env(self.cfg, home=Path(self.tmp.name), ports=self.env.ports, clock=lambda: self.now))
        with self.store.stub(find_fn=unreadable):
            self.assertTrue(fresh.beads.beads_of(self.repo))
            self.assertEqual(fresh.beads.health(self.repo), (1000.0, ""))
            self.now += 51
            self.assertTrue(fresh.beads.beads_of(self.repo))
            self.assertEqual(fresh.beads.health(self.repo), (1000.0, ERROR))

    def test_os_and_decode_failures_preserve_rows_time_and_shared_success(self):
        reader = self.dash.beads
        rows = reader.beads_of(self.repo)
        comments = reader.comments(self.repo, BeadId("b-1"))
        shared = self.env.config.beads_cache(self.repo).read_text()
        self.now += 61
        for error in (OSError("bd missing"), ValueError("invalid bd JSON"), UnicodeDecodeError("utf8", b"\xff", 0, 1, "invalid")):
            with self.subTest(error=type(error).__name__):
                def fail(_, error=error):
                    raise error
                with self.store.stub(find_fn=fail, comments_fn=fail):
                    self.assertEqual(reader.beads_of(self.repo), rows)
                    self.assertEqual(reader.comments(self.repo, BeadId("b-1")), comments)
                for bid in ("", "b-1"):
                    self.assertEqual(reader.health(self.repo, bid), (1000.0, str(error)))
                self.assertEqual(self.env.config.beads_cache(self.repo).read_text(), shared)

    def test_cold_snapshot_and_comment_detail_publish_failure(self):
        with self.store.stub(find_fn=unreadable):
            snap = self.dash.reads.snapshot()
        self.assertEqual(snap.beads, [])
        self.assertEqual((snap.projects[0].bd_ok_at, snap.projects[0].bd_error), (None, ERROR))
        with self.store.stub(comments_fn=unreadable):
            detail = must(self.dash.reads.bead(loop_key(self.repo), "b-1"))
        self.assertEqual((detail.bd_ok_at, detail.bd_error, detail.comments), (None, ERROR, []))

    def test_health_is_separate_for_each_repo_and_comment_read(self):
        reader = self.dash.beads
        other = self.repo + "-other"
        reader.beads_of(self.repo)
        reader.beads_of(other)
        reader.comments(self.repo, BeadId("b-1"))
        reader.comments(self.repo, BeadId("b-2"))
        self.now += 61
        with self.store.stub(find_fn=unreadable, comments_fn=unreadable):
            reader.beads_of(self.repo)
            reader.comments(self.repo, BeadId("b-1"))
        self.assertEqual(reader.health(other), (1000.0, ""))
        self.assertEqual(reader.health(self.repo, "b-2"), (1000.0, ""))
        self.assertEqual(reader.health(self.repo), (1000.0, ERROR))
        self.assertEqual(reader.health(self.repo, "b-1"), (1000.0, ERROR))
