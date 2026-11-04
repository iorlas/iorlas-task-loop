"""The run locator: the three queries answered from manifests alone, an opaque unique time-ordered id per run."""
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import support.paths  # noqa: F401

from taskloop.contracts.ids import RunId
from taskloop.contracts.locator import RunLocator, host_name
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunState

T0 = 1793050200.0


class Locator(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = ConfigDir(Path(tmp.name))
        self.where = RunLocator(self.cfg)

    def test_two_runs_of_one_bead_have_different_ids_that_sort_by_time_and_hold_no_bead(self):
        a = self.where.create("/r/x", "tl-1", T0)
        b = self.where.create("/r/x", "tl-1", T0)  # the same second
        c = self.where.create("/r/x", "tl-1", T0 + 5)
        self.assertEqual(len({a.run, b.run, c.run}), 3)
        self.assertLess(a.run[:10], c.run[:10])
        self.assertTrue(all(RunId.of(x.run) and "tl-1" not in x.run for x in (a, b, c)))

    def test_the_three_queries_come_from_the_manifests(self):
        a = self.where.create("/r/x", "tl-1", T0 + 3)
        b = self.where.create("/r/x", "tl-2", T0 + 1)
        c = self.where.create("/r/y", "tl-1", T0 + 2)
        self.assertEqual(self.where.get(a.run), a)
        self.assertIsNone(self.where.get("01KBN6Z0M4R5E8YQ2T7C9W3XHD"))
        self.assertEqual([x.run for x in self.where.of_bead("tl-1", "/r/x")], [a.run])
        self.assertEqual([x.run for x in self.where.of_bead("tl-1")], [c.run, a.run])  # oldest start first
        self.assertEqual([x.run for x in self.where.of_repo("/r/x")], [b.run, a.run])
        self.assertEqual([x.run for x in self.where.runs()], [b.run, c.run, a.run])
        self.assertEqual(self.where.newest("tl-1").run, a.run)  # type: ignore[union-attr]
        self.assertEqual((a.bead, a.repo, a.started), ("tl-1", "/r/x", T0 + 3))

    def test_a_folder_without_a_database_row_is_no_run(self):
        a = self.where.create("/r/x", "tl-1", T0)
        self.cfg.run_dir("tl-9-20261027-000000").mkdir(parents=True)  # the old layout: a folder named by bead and stamp
        self.cfg.run_dir("01KBN6Z0M4R5E8YQ2T7C9W3XHD").mkdir(parents=True)
        self.assertEqual([x.run for x in self.where.runs()], [a.run])

    def test_a_database_run_does_not_need_its_run_folder(self):
        a = self.where.create("/r/x", "tl-1", T0)
        self.cfg.run_dir(a.run).rmdir()
        self.assertEqual(self.where.get(a.run), a)
        self.assertEqual([x.run for x in self.where.runs()], [a.run])

    def test_taking_a_run_up_counts_an_attempt_and_the_end_is_written_once(self):
        a = self.where.create("/r/x", "tl-1", T0)
        again = self.where.take_up(a.run, "/r/x", "tl-1", T0 + 9)
        self.assertEqual((again.manifest.attempts, again.started), (2, T0))
        self.where.end(a.run, T0 + 60, RunState.DONE)
        self.where.end(a.run, T0 + 99, RunState.FAILED, "later")
        self.assertEqual(RunLocator(self.cfg).get(a.run).manifest.ended, T0 + 60)  # type: ignore[union-attr]

    def test_the_state_goes_created_running_terminal_and_a_terminal_one_stays(self):
        a = self.where.create("/r/x", "tl-1", T0)
        self.assertEqual((a.manifest.state, a.manifest.pid, a.manifest.host), (RunState.CREATED, os.getpid(), host_name()))
        self.where.beat(a.run, T0 + 5)
        got = self.where.get(a.run).manifest  # type: ignore[union-attr]
        self.assertEqual((got.state, got.heartbeat), (RunState.RUNNING, T0 + 5))
        self.where.end(a.run, T0 + 9, RunState.PARKED, "an ask")
        self.where.beat(a.run, T0 + 20)  # a late tick does not bring it back
        got = self.where.get(a.run).manifest  # type: ignore[union-attr]
        self.assertEqual((got.state, got.reason, got.ended), (RunState.PARKED, "an ask", T0 + 9))
        with self.assertRaises(ValueError):
            self.where.end(a.run, T0 + 9, RunState.RUNNING)

    def test_taking_a_terminal_run_up_preserves_the_first_answer(self):
        a = self.where.create("/r/x", "tl-1", T0)
        self.where.end(a.run, T0 + 9, RunState.STOPPED)
        again = self.where.take_up(a.run, "/r/x", "tl-1", T0 + 10).manifest
        self.assertEqual((again.state, again.ended, again.reason), (RunState.STOPPED, T0 + 9, ""))

    def test_terminal_reason_preserves_long_diagnostics_and_evidence_paths(self):
        run = self.where.create("/r/x", "tl-1", T0)
        reason = "push failed: " + "hook details " * 50 + "\npush output: /runs/r/land-push/123.log"
        self.where.end(run.run, T0 + 9, RunState.FAILED, reason)
        saved = RunLocator(self.cfg).get(run.run)
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved.manifest.reason, reason)

    def test_mark_lost_changes_a_live_run_once(self):
        a = self.where.create("/r/x", "tl-1", T0)
        self.where.mark_lost(a.run, "gone")
        got = self.where.get(a.run).manifest  # type: ignore[union-attr]
        self.assertEqual((got.state, got.ended, got.reason), (RunState.LOST, T0, "gone"))
        self.where.mark_lost(a.run, "again")
        self.assertEqual(self.where.get(a.run).manifest.reason, "gone")  # type: ignore[union-attr]

    def test_a_scan_sees_a_manifest_that_changed(self):
        a = self.where.create("/r/x", "tl-1", T0)
        self.assertIsNone(self.where.runs()[0].manifest.ended)
        self.where.end(a.run, T0 + 60, RunState.DONE)
        self.assertEqual(self.where.runs()[0].manifest.ended, T0 + 60)

    def test_a_bundle_names_every_file_of_the_run_from_its_id(self):
        a = self.where.create("/r/x", "tl-1", T0)
        self.assertEqual((a.log, a.err, a.live, a.dir), (self.cfg.engine_log(a.run), self.cfg.engine_log(a.run).with_suffix(".stderr"),
                                                         self.cfg.live_dir(a.run), self.cfg.run_dir(a.run)))

    def test_two_threads_take_up_beat_identify_and_add_beads_without_losing_changes(self):
        a = self.where.create("/r/x", "tl-1", T0)
        barrier = Barrier(2, timeout=5)

        def update(worker):
            where = RunLocator(self.cfg)
            barrier.wait()
            for n in range(10):
                where.take_up(a.run, "/r/x", "tl-1", T0 + n)
                where.beat(a.run, T0 + n)
                where.identify(a.run, "stage:gate", "owner", "session")
                where.add_bead(a.run, f"{worker}-{n}")

        with ThreadPoolExecutor(max_workers=2) as threads:
            list(threads.map(update, ("a", "b")))
        saved = self.where.get(a.run)
        assert saved is not None
        self.assertEqual(saved.manifest.attempts, 21)
        self.assertEqual(set(saved.manifest.beads), {f"{worker}-{n}" for worker in ("a", "b") for n in range(10)})
        self.assertEqual((saved.manifest.mode, saved.manifest.owner, saved.manifest.session), ("stage:gate", "owner", "session"))
        self.assertEqual(saved.manifest.state, RunState.RUNNING)
        self.assertEqual(saved.manifest.heartbeat, T0 + 9)


if __name__ == "__main__":
    unittest.main()
