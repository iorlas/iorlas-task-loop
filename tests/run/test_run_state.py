"""RUNSTATE (tl-9un.48): the engine records its run's state in runs/<run>/manifest.json: running while it goes, and one terminal state
on EVERY exit path of the process (landed, an ask, an engine fault, a SIGTERM, a fence, a close that itself raises). An exec into a newer
install is no exit: the run stays live for the process that takes it up. Fakes throughout; the killed-process case is under real/."""
import contextlib
import signal as sig
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import homes
from support.engine_case import CLEAN, PLAN, WRITE, EngineTest

# isort: split
from taskloop.app.plan.planner import Planner
from taskloop.app.run import engine
from taskloop.app.run.closer import Closer
from taskloop.app.run.records import terminal_state
from taskloop.app.run.run_once import Ended, RunOnce
from taskloop.contracts.kinds import Kind
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.run import RunManifest, RunState
from taskloop.domain import outcome as oc
from taskloop.domain.asks import specs as askspecs

LANDS = {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}


class ExitPaths(EngineTest):
    def manifest(self) -> RunManifest:
        got = RunLocator(homes.cfg()).get(self.eng.run_id)
        assert got is not None
        return got.manifest

    def test_a_run_that_lands_ends_done(self):
        rc, _ = self.run_engine(LANDS)
        m = self.manifest()
        self.assertEqual((rc, m.state), (0, RunState.DONE))
        self.assertIsNotNone(m.ended)

    def test_a_run_that_ends_on_a_question_ends_parked_with_the_reason(self):
        def ask(*a, **k):
            raise self.eng.Blocked("decide: which way?", askspecs.external_fact(["x"]), kind=Kind.ASK_DECISION)
        with mock.patch.object(Planner, "plan", side_effect=ask):
            self.run_engine({})
        m = self.manifest()
        self.assertEqual(m.state, RunState.PARKED)
        self.assertIn("which way", m.reason)

    def test_an_engine_exception_ends_failed(self):
        with mock.patch.object(Planner, "plan", side_effect=RuntimeError("boom")):
            rc, _ = self.run_engine({})
        m = self.manifest()
        self.assertEqual((rc, m.state), (2, RunState.FAILED))
        self.assertIn("boom", m.reason)

    def test_a_sigterm_ends_stopped(self):
        if not hasattr(sig, "SIGTERM"):
            self.skipTest("POSIX signal")
        with mock.patch.object(engine.Engine, "stop_pending", True, create=True):
            rc, _ = self.run_engine({"plan": [PLAN]})
        self.assertEqual((rc, self.manifest().state), (2, RunState.STOPPED))

    def test_a_close_that_raises_still_leaves_a_terminal_state(self):
        with mock.patch.object(Closer, "close", side_effect=OSError("disk")), self.assertRaises(OSError):
            self.run_engine(LANDS)
        self.assertEqual(self.manifest().state, RunState.DONE)  # the run finished its work; the close is what broke


class Settle(unittest.TestCase):
    """close_out's last word, on a stand-in host: the fence and the exec."""

    def host(self, **kw):
        calls: list[tuple[RunState, str]] = []
        h = SimpleNamespace(moved=False, stop_deferred=contextlib.nullcontext, landed_sha="", store=None, claim=None,
                            warn=lambda t: None, closer=SimpleNamespace(close=lambda *a: None),
                            records=SimpleNamespace(settle=lambda state, why: calls.append((state, why))), **{"fenced": "", **kw})
        return h, calls

    def test_a_fenced_run_ends_stopped_and_says_why(self):
        h, calls = self.host(fenced="taken again by another run")
        with mock.patch.object(RunOnce, "close"):
            RunOnce(h).close_out(mock.Mock(), Ended())
        self.assertEqual(calls, [(RunState.STOPPED, "fenced out: taken again by another run")])

    def test_an_exec_into_a_newer_install_ends_nothing(self):
        h, calls = self.host()
        h.moved = True
        RunOnce(h).close_out(mock.Mock(), Ended(oc.make(Kind.LANDED, sha="abc")))
        self.assertEqual(calls, [])

    def test_each_kind_maps_to_one_state(self):
        want = {Kind.LANDED: RunState.DONE, Kind.DONE: RunState.DONE, Kind.FAULT_ENGINE: RunState.FAILED,
                Kind.PAUSE_KILLED: RunState.STOPPED, Kind.PAUSE_NETWORK: RunState.STOPPED, Kind.OWNER_PARK: RunState.PARKED,
                Kind.WAIT_ASK: RunState.PARKED}
        for kind, state in want.items():
            self.assertEqual(terminal_state(oc.make(kind)), state, kind)


if __name__ == "__main__":
    unittest.main()
