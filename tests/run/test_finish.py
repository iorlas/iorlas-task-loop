"""The manifest chooses one answer; concurrent finishers and every history reader see that answer."""
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401
from support import homes
from support.engine_case import CLEAN, PLAN, WRITE, EngineTest

from taskloop.app.run.finish import answer, outcome
from taskloop.contracts import log, runlife, wire
from taskloop.contracts.checkpoint import EndRec
from taskloop.contracts.events import Stage
from taskloop.contracts.finish import finish_run
from taskloop.contracts.ids import loop_key
from taskloop.contracts.kinds import Kind
from taskloop.contracts.locator import RunLocator, host_name
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunState
from taskloop.contracts.runrows import RunRows
from taskloop.contracts.stores import EventLog, LoopLog, RunLog, TraceStore
from taskloop.domain import outcome as oc
from taskloop.domain.asks import specs


class Finish(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = ConfigDir(Path(tmp.name))
        self.where = RunLocator(self.cfg)
        self.key = loop_key("/repo")
        self.bundle = self.where.create("/repo", "t-1", 100.0, loop=self.key, owner="owner", session="session")
        self.run_id = self.bundle.run

    def manifest(self):
        bundle = self.where.get(self.run_id)
        assert bundle is not None
        return bundle.manifest

    def rows(self):
        closes = [i.rec for i in RunLog(self.cfg, self.run_id).read_from().items if isinstance(i.rec, log.Close)]
        traces = [i.rec for i in TraceStore(self.cfg).read_from().items]
        events = [i.rec for i in EventLog(self.cfg).read_from().items]
        loops = [i.rec for i in LoopLog(self.cfg, self.key).read_from().items]
        return closes, traces, events, loops

    def test_two_threads_choose_one_answer_and_project_it_exactly_once(self):
        barrier = threading.Barrier(2)
        candidates = [answer(oc.make(Kind.LANDED, "landed", sha="a" * 40), 150.0),
                      answer(oc.make(Kind.FAULT_ENGINE, "failed", sha="b" * 40), 160.0)]

        def finish(candidate):
            barrier.wait(timeout=5)
            return finish_run(self.cfg, self.run_id, candidate)

        with ThreadPoolExecutor(max_workers=2) as threads:
            results = list(threads.map(finish, candidates))
        self.assertEqual(sum(r.won for r in results), 1)
        self.assertEqual(results[0].record, results[1].record)
        self.assertIn(results[0].record, candidates)
        self.assertEqual(self.manifest().finish, results[0].record)
        for rows in self.rows():
            self.assertEqual(len(rows), 1)

    def test_real_finish_then_mark_lost_preserves_the_entire_answer(self):
        first = finish_run(self.cfg, self.run_id, answer(oc.make(Kind.LANDED, "ok", sha="c" * 40), 155.0))
        before = RunRows(self.cfg).snapshot(self.run_id)
        lost = self.where.mark_lost(self.run_id, "process disappeared")
        assert lost is not None
        self.assertFalse(lost.won)
        self.assertEqual(lost.record, first.record)
        self.assertEqual(RunRows(self.cfg).snapshot(self.run_id), before)
        self.assertEqual([len(rows) for rows in self.rows()], [1, 1, 1, 1])

    def test_mark_lost_then_late_close_returns_the_lost_answer(self):
        self.where.beat(self.run_id, 120.0)
        lost = self.where.mark_lost(self.run_id, "process disappeared")
        assert lost is not None
        late = finish_run(self.cfg, self.run_id, answer(oc.make(Kind.LANDED, "late", sha="d" * 40), 180.0))
        self.assertTrue(lost.won)
        self.assertFalse(late.won)
        self.assertEqual(late.record, lost.record)
        self.assertEqual((late.record.state, late.record.ended, late.record.sha), (RunState.LOST, 120.0, ""))
        self.assertEqual([len(rows) for rows in self.rows()], [1, 1, 1, 1])

    def test_mark_lost_racing_a_real_finish_returns_the_same_winner(self):
        barrier = threading.Barrier(2)

        def close():
            barrier.wait(timeout=5)
            return finish_run(self.cfg, self.run_id, answer(oc.make(Kind.LANDED, sha="e" * 40), 150.0))

        def lose():
            barrier.wait(timeout=5)
            return RunLocator(self.cfg).mark_lost(self.run_id, "gone")

        with ThreadPoolExecutor(max_workers=2) as threads:
            closing, losing = threads.submit(close), threads.submit(lose)
            closed, lost = closing.result(), losing.result()
        assert lost is not None
        self.assertEqual(closed.record, lost.record)
        self.assertEqual(closed.won + lost.won, 1)
        self.assertEqual([len(rows) for rows in self.rows()], [1, 1, 1, 1])

    def test_disk_projections_have_identical_time_sha_and_outcome(self):
        done = answer(oc.make(Kind.LANDED, "delivered", sha="f" * 40), 170.25)
        finish_run(self.cfg, self.run_id, done)
        (close,), (trace,), (event,), (loop,) = self.rows()
        self.assertIsInstance(event, Stage)
        assert isinstance(event, Stage)
        m = self.manifest()
        self.assertEqual([close.t, trace.ended, event.t, loop.t, m.ended], [done.ended] * 5)
        self.assertEqual([close.sha, trace.sha, event.sha, loop.sha, m.sha], [done.sha] * 5)
        self.assertEqual((close.outcome, trace.outcome, event.text, loop.outcome, m.state),
                         (done.outcome, done.outcome, f"close: {done.outcome}", done.result, done.state))
        self.assertEqual((close.why, trace.why, loop.why, m.reason), (done.why,) * 4)
        self.assertEqual((trace.kind, m.finish), (done.kind, done))
        self.assertFalse((self.cfg.loop_runs(self.key) / "exits.jsonl").exists(),
                         "a bead run finishing is not the containing loop process exiting")

    def test_checkpoint_payload_preserves_an_ask_and_disposition(self):
        done = oc.make(Kind.ASK_DECISION, "choose", spec=specs.external_fact(["which API?"]))
        result = finish_run(self.cfg, self.run_id, answer(done, 180.0))
        kept = wire.load(EndRec, result.record.end)
        self.assertEqual(kept.kind, done.kind.value)
        self.assertEqual(outcome(result.record), done)
        row = RunRows(self.cfg).snapshot(self.run_id)
        assert row is not None
        self.assertEqual(json.loads(row[0])["finish"]["ended"], 180.0)

    def test_late_heartbeat_metadata_and_take_up_preserve_the_answer(self):
        first = finish_run(self.cfg, self.run_id, answer(oc.make(Kind.DONE), 190.0))
        self.where.beat(self.run_id, 999.0)
        self.where.identify(self.run_id, "loop", "other", "new-session")
        self.where.worktree(self.run_id, "/another/tree")
        self.where.take_up(self.run_id, "/repo", "t-1", 1000.0)
        self.assertEqual(self.manifest().finish, first.record)
        self.assertEqual((self.manifest().state, self.manifest().ended), (first.record.state, first.record.ended))

    def test_an_inflight_heartbeat_cannot_restore_a_live_snapshot_after_finish(self):
        read, release = threading.Event(), threading.Event()
        original = self.where.rows.read

        def snapshot(con, run):
            bundle = original(con, run)
            read.set()
            self.assertTrue(release.wait(timeout=5))
            return bundle

        with mock.patch.object(self.where.rows, "read", side_effect=snapshot), ThreadPoolExecutor(max_workers=2) as threads:
            beating = threads.submit(self.where.beat, self.run_id, 140.0)
            self.assertTrue(read.wait(timeout=5))
            finishing = threads.submit(finish_run, self.cfg, self.run_id, answer(oc.make(Kind.DONE), 150.0))
            release.set()
            beating.result()
            winner = finishing.result()
        self.assertEqual(self.manifest().finish, winner.record)
        self.assertEqual((self.manifest().state, self.manifest().heartbeat), (RunState.DONE, 150.0))

    def test_reconcile_does_not_report_a_run_lost_if_another_finisher_won(self):
        stale = self.manifest().replace(heartbeat=100.0, host=host_name(), pid=999999)
        with mock.patch.object(RunLocator, "runs", return_value=[self.where.bundle(stale)]), \
                mock.patch("taskloop.contracts.runlife.pid_alive", return_value=False):
            finish_run(self.cfg, self.run_id, answer(oc.make(Kind.DONE), 200.0))
            self.assertEqual(runlife.reconcile(self.cfg, 1000.0), [])

    def test_a_projection_failure_cannot_reopen_the_outcome(self):
        first = answer(oc.make(Kind.LANDED, sha="1" * 40), 200.0)
        with self.assertRaisesRegex(OSError, "disk"), \
                mock.patch("taskloop.contracts.finish.history", side_effect=OSError("disk")):
            finish_run(self.cfg, self.run_id, first)
        late = finish_run(self.cfg, self.run_id, answer(oc.make(Kind.FAULT_ENGINE, "disk"), 210.0))
        self.assertFalse(late.won)
        self.assertEqual(late.record, first)
        self.assertTrue(self.manifest().finish_projected)
        self.assertEqual([len(rows) for rows in self.rows()], [1, 1, 1, 1])

    def test_a_partial_projection_is_repaired_without_duplicate_close_or_trace(self):
        first = answer(oc.make(Kind.LANDED, "first", sha="2" * 40), 220.0)
        with mock.patch("taskloop.contracts.finish_projection.indexes", side_effect=OSError("index disk")), \
                self.assertRaisesRegex(OSError, "index disk"):
            finish_run(self.cfg, self.run_id, first)
        self.assertEqual([len(rows) for rows in self.rows()], [1, 1, 0, 0])
        late = finish_run(self.cfg, self.run_id, answer(oc.make(Kind.FAULT_ENGINE, "later"), 230.0))
        self.assertFalse(late.won)
        self.assertEqual(late.record, first)
        self.assertEqual([len(rows) for rows in self.rows()], [1, 1, 1, 1])
        self.assertTrue(self.manifest().finish_projected)


class EngineParity(EngineTest):
    def test_engine_projects_one_winner_and_late_errors_do_not_change_its_report(self):
        with mock.patch.dict(os.environ, {"TASK_LOOP_LOOP_PID": "123", "TASK_LOOP_RUN_LOG": "/loop/run.log",
                                          "TASK_LOOP_SLOT": "slot-1"}):
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        cfg = homes.cfg()
        bundle = RunLocator(cfg).get(self.eng.run_id)
        assert bundle is not None
        m = bundle.manifest
        assert m.finish is not None and m.loop is not None
        (close,) = [i.rec for i in RunLog(cfg, m.run).read_from().items if isinstance(i.rec, log.Close)]
        (trace,) = [i.rec for i in TraceStore(cfg).read_from().items if str(i.rec.run) == m.run]
        (event,) = [i.rec for i in EventLog(cfg).read_from().items if i.rec.run_id == m.run and i.rec.step == "close"]
        (loop,) = [i.rec for i in LoopLog(cfg, m.loop).read_from().items if i.rec.run_id == m.run]
        self.assertEqual([close.t, trace.ended, event.t, loop.t, m.ended], [m.finish.ended] * 5)
        self.assertEqual([close.sha, trace.sha, event.sha, loop.sha, m.sha], [m.finish.sha] * 5)
        self.assertEqual((close.outcome, trace.outcome, loop.outcome),
                         (m.finish.outcome, m.finish.outcome, m.finish.result))
        self.assertEqual((loop.slot, loop.run_log), ("slot-1", "/loop/run.log"))
        self.assertEqual((loop.rounds, loop.tests_added), (self.eng.stats["rounds"], self.eng.stats["tests_added"]))
        report = self.eng.result()
        late = self.eng.records.finish(oc.make(Kind.FAULT_ENGINE, "error after the close"))
        self.assertEqual(late, outcome(m.finish))
        self.assertEqual(self.eng.result(), report)
        self.assertEqual(len([i for i in RunLog(cfg, m.run).read_from().items if isinstance(i.rec, log.Close)]), 1)
