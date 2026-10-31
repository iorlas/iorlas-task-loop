"""Backend item 7: the owner's park, stop and note as a run's request file (app/run/requests.py). The file is merged under its lock and
taken once; park ends the run at its next step boundary with the branch and checkpoint kept, stop ends it through the stop flag (the
halt path), a note reaches the next worker's prompt; a request for a run that is not live is refused, one left at the close dropped."""

import argparse
import json
import os
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401
from support import engine_case as te
from support import homes
from support.engine_case import PLAN, WRITE
from support.fake_beads import FakeBeads
from support.logs import typed
from support.narrow import must

from taskloop.app.asks import intake
from taskloop.app.run import requests
from taskloop.app.run.layout import prune_run_logs
from taskloop.cli import asks as cli
from taskloop.contracts import log as rec
from taskloop.contracts.enums import WhyCode
from taskloop.contracts.ids import BeadId
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import NewBead
from taskloop.stores.memory import fake_stores

RUN = "tl-5-20261026-100000"


class RequestFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = ConfigDir(self.tmp.name)
        self.now = time.time()
        log = self.cfg.engine_log(RUN)
        log.parent.mkdir(parents=True)
        log.write_text(json.dumps(typed("run_start", self.now - 5, run_id=RUN, bead="tl-5", worktree="")) + "\n")

    def test_requests_merge_and_are_taken_once(self):
        self.assertEqual(requests.post(self.cfg, RUN, "dash", self.now, note="one"), "")
        self.assertEqual(requests.post(self.cfg, RUN, "denis", self.now, park=True, note="two"), "")
        got = must(requests.take(self.cfg, RUN))
        self.assertEqual((got.park, got.stop, [n.text for n in got.notes], got.by), (True, False, ["one", "two"], "denis"))
        self.assertIsNone(requests.take(self.cfg, RUN))

    def test_a_run_that_is_not_live_is_refused(self):
        self.assertEqual(requests.post(self.cfg, RUN, "dash", self.now + 3600, stop=True), "no run of this bead is going")
        self.assertEqual(requests.post(self.cfg, "tl-5-20261026-110000", "dash", self.now, stop=True), "no run of this bead is going")
        self.assertIsNone(requests.peek(self.cfg, RUN))

    def test_writers_racing_the_taker_lose_nothing_and_double_nothing(self):
        taken: list[str] = []
        stop = threading.Event()

        def taker():
            while not stop.is_set():
                got = requests.take(self.cfg, RUN)
                taken.extend(n.text for n in (got.notes if got else []))

        t = threading.Thread(target=taker)
        t.start()
        for i in range(60):
            requests.post(self.cfg, RUN, "dash", self.now, note=f"n{i}")
        stop.set()
        t.join()
        got = requests.take(self.cfg, RUN)
        taken.extend(n.text for n in (got.notes if got else []))
        self.assertEqual(taken, [f"n{i}" for i in range(60)])

    def test_the_newest_run_of_a_bead_and_the_sweep(self):
        for stem in ("tl-5-20261026-090000", "tl-5.1-20261027-090000", "tl-5-x"):
            self.cfg.engine_log(stem).write_text("")
        self.assertEqual(requests.newest_run(self.cfg, "tl-5"), RUN)
        requests.post(self.cfg, RUN, "dash", self.now, park=True)
        prune_run_logs(self.cfg, self.now + 30 * 86400)
        self.assertFalse(self.cfg.run_request(RUN).exists())

    def test_a_stop_is_acted_on_at_the_beat_through_the_stop_flag(self):
        host = types.SimpleNamespace(run_dir=self.cfg.run_dir(RUN), halt=threading.Event())
        side = requests.OwnerRequests(host)
        side.at_beat()
        self.assertFalse(host.halt.is_set())
        requests.post(self.cfg, RUN, "dash", self.now, stop=True)
        side.at_beat()
        self.assertTrue(host.halt.is_set() and side.stopped)
        side.drop()  # the close: the request no step took is dropped, and nothing is taken after
        self.assertIsNone(requests.peek(self.cfg, RUN))


class Cli(unittest.TestCase):
    """`tl park BEAD` and `tl note BEAD text`: the newest run of the bead under the config dir."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.cfg = homes.cfg()
        self.store = FakeBeads()
        self.store.create(NewBead(title="x"))
        self.out: list[str] = []

    def say(self, *argv, now=None):
        ap = argparse.ArgumentParser()
        cli.add_parsers(ap.add_subparsers(dest="cmd"))
        when = now or time.time()
        return cli.run(ap.parse_args(argv), fake_stores().asks, lambda _r: self.store, lambda: when, "denis", self.cfg, self.out.append)

    def test_park_and_note_reach_the_live_run(self):
        run = "fk-1-20261026-100000"
        log = self.cfg.engine_log(run)
        log.parent.mkdir(parents=True)
        log.write_text(json.dumps(typed("run_start", time.time(), run_id=run, bead="fk-1", worktree="")) + "\n")
        self.assertEqual(self.say("note", "fk-1", "use", "blue"), 0)
        self.assertEqual(self.say("park", "fk-1"), 0)
        got = must(requests.peek(self.cfg, run))
        self.assertEqual((got.park, [n.text for n in got.notes]), (True, ["use blue"]))
        self.assertEqual(self.store.beads[BeadId("fk-1")].metadata[intake.HOLD], "denis")

    def test_with_no_run_park_holds_and_note_is_the_hint(self):
        self.assertEqual(self.say("park", "fk-1"), 0)
        self.assertEqual(self.say("note", "fk-1", "later"), 0)
        meta = self.store.beads[BeadId("fk-1")].metadata
        self.assertEqual((meta[intake.HOLD], meta[intake.HINT]), ("denis", "later"))
        self.assertIn("hint", self.out[-1])


class EngineRequests(te.EngineTest):
    def records(self):
        return [rec.decode(json.loads(x)) for x in self.eng.log_path.read_text().splitlines()]

    def after_plan(self, **request):
        """A prep that posts `request` to the run once its plan is made (the next boundary is the write's)."""
        def prep(eng):
            plan = eng.planner.plan

            def planned(*a, **kw):
                out = plan(*a, **kw)
                self.assertEqual(requests.post(homes.cfg(), eng.log_path.stem, "denis", time.time(), **request), "")
                return out
            eng.planner.plan = planned
        return prep

    def close(self):
        return next(r for r in self.records() if isinstance(r, rec.Close))

    def test_park_ends_the_run_at_the_next_boundary_with_branch_and_checkpoint_kept(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [te.review()]}, prep=self.after_plan(park=True))
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls], ["planner"])  # the write never started
        close = self.close()
        self.assertEqual((close.outcome.value, close.why_code), ("blocked", WhyCode.PAUSED))
        self.assertTrue(close.why.startswith("parked: by the owner"))
        self.assertIsNotNone(self.eng.checkpoints.read())
        te.sh("git", "rev-parse", "--verify", "-q", "task/t-1", cwd=self.wt)  # the branch is kept
        self.assertEqual(self.eng.result().outcome, "parked")
        self.assertFalse(Path(self.eng.run_dir, homes.cfg().run_request("x").name).exists())

    def test_stop_ends_the_run_through_the_halt_path(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [te.review()]}, prep=self.after_plan(stop=True))
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls], ["planner"])
        close = self.close()
        self.assertEqual((close.why_code, close.why), (WhyCode.STOPPED_BY_COORDINATOR, requests.STOPPED_WHY))
        self.assertIsNotNone(self.eng.checkpoints.read())

    def test_a_note_reaches_the_next_workers_prompt_once_and_is_said(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [te.review()]}, prep=self.after_plan(note="use the blue one"))
        self.assertEqual(rc, 0)
        prompts = dict(zip([c[0] for c in s.calls], s.prompts, strict=False))
        self.assertIn(requests.NOTE_HEAD + "- use the blue one", prompts["worker"])
        self.assertNotIn("use the blue one", prompts["reviewer"])
        said = [r for r in self.records() if isinstance(r, rec.Said) and r.who == "owner"]
        self.assertEqual([r.text for r in said], ["use the blue one"])


if __name__ == "__main__":
    unittest.main()
