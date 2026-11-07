"""The owner's park, stop and note: asks/owner_verbs.py posts signal rows, pipeline/requests.py consumes them. Requests are merged and
taken once; park ends the run at its next step boundary with the branch and checkpoint kept, stop ends it through the stop flag (the
halt path), a note reaches the next worker's prompt; a request for a run that is not live is refused, one left at the close dropped."""

import argparse
import json
import os
import threading
import time
import types
from pathlib import Path
from unittest import mock

from support import engine_case as te
from support import homes
from support.fake_beads import FakeBeads
from support.memstores import fake_stores

import tltestkit.shellkit
from taskloop.app.asks import ask_verbs, intake, owner_verbs
from taskloop.cli import asks as cli
from tlkernel import log as rec
from tlkernel.beadsport import NewBead
from tlkernel.enums import WhyCode
from tlkernel.ids import BeadId
from tlkernel.paths import ConfigDir
from tlkernel.run import RunState
from tlkernel.runlayout import prune_run_logs
from tlpipeline.api import requests
from tltestkit.case import Case
from tltestkit.logs import typed
from tltestkit.narrow import must
from tltestkit.plans import PLAN, WRITE
from tltestkit.runs import manifest
from tltestkit.tmpdir import TemporaryDirectory

RUN = "tl-5-20261026-100000"


class RequestFile(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = ConfigDir(self.tmp.name)
        self.now = time.time()
        log = manifest(self.cfg, RUN, "tl-5", self.now - 5).log
        log.write_text(json.dumps(typed("run_start", self.now - 5, run_id=RUN, bead="tl-5", worktree="")) + "\n")

    def test_requests_merge_and_are_taken_once(self):
        assert owner_verbs.post(self.cfg, RUN, "dash", self.now, repo="/repo", bead="tl-5", note="one") == ""
        assert owner_verbs.post(self.cfg, RUN, "denis", self.now, repo="/repo", bead="tl-5", park=True, note="two") == ""
        got = must(requests.take(self.cfg, RUN))
        assert (got.park, got.stop, [n.text for n in got.notes], got.by) == (True, False, ["one", "two"], "denis")
        assert requests.take(self.cfg, RUN) is None

    def test_a_run_that_is_not_live_is_refused(self):
        manifest(self.cfg, RUN, "tl-5", self.now - 5, state=RunState.LOST)  # its process is gone, recorded lost
        for run in (RUN, "tl-5-20261026-110000"):
            why = owner_verbs.post(self.cfg, run, "dash", self.now + 3600, repo="/repo", bead="tl-5", stop=True)
            assert why == "no run of this bead is going"
        assert requests.peek(self.cfg, RUN) is None

    def test_a_request_for_another_repo_or_bead_writes_nothing(self):
        before = self.files()
        for repo, bead in (("/other", "tl-5"), ("/repo", "tl-6")):
            with self.subTest(repo=repo, bead=bead):
                why = owner_verbs.post(self.cfg, RUN, "dash", self.now, repo=repo, bead=bead, stop=True)
                assert "repo and bead" in why
        assert self.files() == before

    def files(self):
        """Every file a request could write, and the signal rows."""
        files = {p: p.read_bytes() for p in self.cfg.root.rglob("*")
                 if p.is_file() and "locks" not in p.parts and not p.name.startswith("factory.db")}
        return files, requests.peek(self.cfg, RUN)

    def test_writers_racing_the_taker_lose_nothing_and_double_nothing(self):
        taken: list[str] = []
        stop = threading.Event()

        def taker():
            while not stop.is_set():
                got = requests.take(self.cfg, RUN)
                taken.extend(n.text for n in (got.notes if got else []))

        t = threading.Thread(target=taker)
        t.start()
        try:
            for i in range(60):
                owner_verbs.post(self.cfg, RUN, "dash", self.now, repo="/repo", bead="tl-5", note=f"n{i}")
        finally:
            stop.set()
            t.join(30)
        assert not t.is_alive(), "owner request taker did not settle in 30 s"
        got = requests.take(self.cfg, RUN)
        taken.extend(n.text for n in (got.notes if got else []))
        assert taken == [f"n{i}" for i in range(60)]

    def test_the_newest_run_of_a_bead_and_the_sweep(self):
        for stem, bead, at in (("tl-5-20261026-090000", "tl-5", 100), ("tl-5.1-20261027-090000", "tl-5.1", 50), ("tl-5-x", "tl-5.2", 1)):
            manifest(self.cfg, stem, bead, self.now - at).log.write_text("")
        assert owner_verbs.newest_run(self.cfg, "tl-5") == RUN
        owner_verbs.post(self.cfg, RUN, "dash", self.now, repo="/repo", bead="tl-5", park=True)
        prune_run_logs(self.cfg, self.now + 30 * 86400, 7 * 86400)
        assert requests.peek(self.cfg, RUN) is None

    def test_a_stop_is_acted_on_at_the_beat_through_the_stop_flag(self):
        host = types.SimpleNamespace(home=self.cfg, run_id=RUN, halt=threading.Event())
        side = requests.OwnerRequests(host)
        side.at_beat()
        assert not host.halt.is_set()
        owner_verbs.post(self.cfg, RUN, "dash", self.now, repo="/repo", bead="tl-5", stop=True)
        side.at_beat()
        assert host.halt.is_set() and side.stopped
        side.drop()  # the close: the request no step took is dropped, and nothing is taken after
        assert requests.peek(self.cfg, RUN) is None


class Cli(Case):
    """`tl park BEAD` and `tl note BEAD text`: the newest run of the bead under the config dir."""

    def setup_method(self):
        self.tmp = TemporaryDirectory()
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
        return ask_verbs.run(cli.arguments(ap.parse_args(argv)), fake_stores().asks, lambda _r: self.store, lambda: when,
                             "denis", self.cfg, self.out.append)

    def test_park_and_note_reach_the_live_run(self):
        run = "fk-1-20261026-100000"
        log = manifest(self.cfg, run, "fk-1", time.time(), repo=str(Path.cwd())).log
        log.write_text(json.dumps(typed("run_start", time.time(), run_id=run, bead="fk-1", worktree="")) + "\n")
        assert self.say("note", "fk-1", "use", "blue") == 0
        assert self.say("park", "fk-1") == 0
        got = must(requests.peek(self.cfg, run))
        assert (got.park, [n.text for n in got.notes]) == (True, ["use blue"])
        assert self.store.beads[BeadId("fk-1")].metadata[intake.HOLD] == "denis"

    def test_with_no_run_park_holds_and_note_is_the_hint(self):
        assert self.say("park", "fk-1") == 0
        assert self.say("note", "fk-1", "later") == 0
        meta = self.store.beads[BeadId("fk-1")].metadata
        assert (meta[intake.HOLD], meta[intake.HINT]) == ("denis", "later")
        assert "hint" in self.out[-1]


class EngineRequests(te.EngineTest):
    def records(self):
        return [rec.decode(json.loads(x)) for x in self.eng.log_path.read_text().splitlines()]

    def after_plan(self, **request):
        """A prep that posts `request` to the run once its plan is made (the next boundary is the write's)."""
        def prep(eng):
            plan = eng.planner.plan

            def planned(*a, **kw):
                out = plan(*a, **kw)
                assert owner_verbs.post(homes.cfg(), eng.log_path.parent.name, "denis", time.time(),
                                               repo=str(self.wt), bead=str(eng.bead), **request) == ""
                return out
            eng.planner.plan = planned
        return prep

    def close(self):
        return next(r for r in self.records() if isinstance(r, rec.Close))

    def test_park_ends_the_run_at_the_next_boundary_with_branch_and_checkpoint_kept(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [te.review()]}, prep=self.after_plan(park=True))
        assert rc == 2
        assert [c[0] for c in s.calls] == ["planner"]  # the write never started
        close = self.close()
        assert (close.outcome.value, close.why_code) == ("blocked", WhyCode.PAUSED)
        assert close.why.startswith("parked: by the owner")
        assert self.eng.checkpoints.read() is not None
        tltestkit.shellkit.sh("git", "rev-parse", "--verify", "-q", "task/t-1", cwd=self.wt)  # the branch is kept
        assert self.eng.result().outcome == "parked"

    def test_stop_ends_the_run_through_the_halt_path(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [te.review()]}, prep=self.after_plan(stop=True))
        assert rc == 2
        assert [c[0] for c in s.calls] == ["planner"]
        close = self.close()
        assert (close.why_code, close.why) == (WhyCode.STOPPED_BY_COORDINATOR, requests.STOPPED_WHY)
        assert self.eng.checkpoints.read() is not None

    def test_a_note_reaches_the_next_workers_prompt_once_and_is_said(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [te.review()]}, prep=self.after_plan(note="use the blue one"))
        assert rc == 0
        prompts = dict(zip([c[0] for c in s.calls], s.prompts, strict=False))
        assert requests.NOTE_HEAD + "- use the blue one" in prompts["worker"]
        assert "use the blue one" not in prompts["reviewer"]
        said = [r for r in self.records() if isinstance(r, rec.Said) and r.who == "owner"]
        assert [r.text for r in said] == ["use the blue one"]
