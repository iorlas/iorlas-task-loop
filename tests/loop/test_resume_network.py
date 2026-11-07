"""Network pauses preserve work and budgets; finished data is kept and role availability wakes paused beads."""

import json
import sys
import time
from collections import Counter
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import homes

# isort: split
from support import engine_case as te
from support import netgate
from support.engine_case import stop

from taskloop.app.release import reexec
from tlkernel.kinds import Kind
from tlkernel.locator import RunLocator
from tltestkit import procsim
from tltestkit.plans import CLEAN, PLAN, WRITE

SAY = "codex: Reconnecting... waiting for network (Connection failed: error sending request)"


def drop(ref, **kw):
    """The delegate's answer to a call the network cut: reason network, the vendor thread to go on in, work seen before the cut."""
    return stop("network", ref, partial=True, say=SAY, **kw)


class Cycling:
    """A network probe that is down for `down` looks, then up for the rest (netgate.FakeProbe's last answer repeats)."""

    def __init__(self, down=2):
        self.down, self.calls = down, 0

    def up(self):
        self.calls += 1
        return self.calls > self.down


class NetBase(te.EngineTest):
    def log(self, eng=None):
        return [json.loads(x) for x in (eng or self.eng).log_path.read_text().splitlines()]

    def causes(self, eng=None):
        return [r.get("cause") for r in self.log(eng) if r.get("kind") == "transition"]

    def assert_no_charge(self, eng=None):
        """What a network drop must leave alone: the lane (no 'out'), the retry and replan counters, the asks and the labels."""
        eng = eng or self.eng
        causes = self.causes(eng)
        for bad in ("lane_out", "fallback_retake", "denied_retry", "delegate_crash", "lane_wait", "invalid_output", "replan"):
            assert bad not in causes
        assert (eng.stats["replans"], eng.stats["rounds"]) == (0, 0)
        assert (self.blocked, self.ask()) == ([], None)
        assert not [c for c in self.bd_calls if c[:2] == ("label", "add")], self.bd_calls

    def thread_of(self, s, node):
        """(resume ref of each call of `node`, in order)."""
        return [s.calls[i][1] for i, n in enumerate(s.nodes) if n == node]




class FinishedOutput(NetBase):
    """tl-7y6.2.13: the transport failed after the worker had finished. Its answer is the answer: not discarded, not asked again."""

    def test_a_drop_that_carries_finished_data_is_the_answer_and_the_step_is_not_redone(self):
        def cut_after_writing(script, node, cwd, resume):
            Path(cwd, "f.txt").write_text("d\n")  # the worker finished its file, then the connection broke
            return drop("net-write", data=WRITE)

        answers = {"plan": [PLAN], "write": [cut_after_writing], "review": [CLEAN]}
        rc, s = self.run_engine(answers, probe=Cycling(2))
        assert rc == 0, self.blocked
        assert Counter(s.nodes) == Counter({"plan": 1, "write": 1, "review": 1})  # the write is not a redo
        assert list(self.eng.run_dir.glob("write-*.json"))
        assert self.eng.result().outcome == "landed"
        self.assert_no_charge()



class Checks(NetBase):
    """The checks that already passed are not run again by the run that goes on after a network pause."""

    def test_a_network_pause_then_a_new_run_does_not_run_the_green_checks_again(self):
        count = Path(self.tmp.name) / "count"
        bump = procsim.fake("bump", procsim.appends(count))
        cfg = {"checks": [{"id": "bump", "cmd": bump, "group": "tests"}]}
        answers = {"plan": [PLAN], "write": [WRITE], "review": [drop("net-review")] * 40}
        rc, s = self.run_engine(answers, probe=netgate.FakeProbe([False]), **cfg)  # the network stays down: the run pauses
        assert rc == 2
        assert self.eng.result().kind == Kind.PAUSE_NETWORK.value
        assert count.read_text() == "1"
        rc, s = self.run_engine({"review": [CLEAN]}, probe=Cycling(0), **cfg)
        assert rc == 0, self.blocked
        assert s.nodes == ["review"]  # the plan and the write were not asked again
        assert s.requests[0].thread.startswith("review/")
        assert s.requests[0].delta_file
        assert s.requests[0].resume is None
        assert count.read_text() == "1"  # the tree did not change: the green result was kept
        assert self.eng.result().outcome == "landed"


class Pause(NetBase):
    """A network pause keeps the bead's work and budget; a new run preserves the paused run's immutable answer."""

    def pause_in_review(self, probe=None, **kw):
        answers = {"plan": [PLAN], "write": [WRITE], "review": [drop("net-review")] * 40}
        rc, s = self.run_engine(answers, probe=probe or netgate.FakeProbe([False]), **kw)
        assert rc == 2
        return s

    def test_continuing_uses_a_new_run_id_but_keeps_cost_and_excludes_pause_time_from_its_budget(self):
        self.pause_in_review()
        first = self.eng
        r = first.result()
        assert (r.outcome, r.kind) == ("paused", Kind.PAUSE_NETWORK.value)
        assert first.retry_after > 0  # the Park receives the retry time
        assert (self.blocked, self.ask()) == ([], None)
        assert not [c for c in self.bd_calls if c[:2] == ("label", "add")]  # no auto label, no engine-fault label
        assert any(c[:1] == ("update",) and "open" in c for c in self.bd_calls)
        cost, run = first.cost, first.log_path.parent.name
        real = time.time
        with mock.patch.object(time, "time", lambda: real() + 7200):  # the bead waited two hours for the network
            rc, s = self.run_engine({"review": [CLEAN]}, probe=Cycling(0))
            second = self.eng
            assert rc == 0, self.blocked
            assert second.log_path.parent.name != run
            before = RunLocator(first.home).get(run)
            after = RunLocator(second.home).get(second.run_id)
            assert before is not None and after is not None
            assert before.manifest.finish is not None and after.manifest.finish is not None
            assert before.manifest.finish.kind == Kind.PAUSE_NETWORK.value
            assert after.manifest.finish.kind == Kind.LANDED.value
            assert second.cost >= cost  # its cost goes on
            assert second.budget.spent_min() < 30  # the two hours of pause are not charged to the time budget
        assert s.nodes == ["review"]
        assert s.requests[0].thread.startswith("review/")
        assert s.requests[0].delta_file
        assert s.requests[0].resume is None
        assert not (homes.config_dir() / "pauses" / "t-1.json").exists()  # taken once

    def test_the_engine_comment_of_a_pause_does_not_make_the_next_run_plan_again(self):
        self.pause_in_review()
        said = [c[3] for c in self.bd_calls if c[:3] == ("comments", "add", "t-1") and c[3].startswith("Engine paused:")]
        assert said, self.bd_calls
        with self.store.stub(comments=[{"author": "tl-a", "text": t} for t in said]):
            rc, s = self.run_engine({"review": [CLEAN]}, probe=Cycling(0))
        assert rc == 0, self.blocked
        assert "plan" not in s.nodes  # the brief it was planned from is the same brief

    def test_a_pause_older_than_the_longest_one_is_a_new_run(self):
        self.pause_in_review()
        run = self.eng.log_path.parent.name
        real = time.time
        with mock.patch.object(time, "time", lambda: real() + reexec.NET_PAUSE_ADOPT_S + 60):
            self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, probe=Cycling(0))
        assert self.eng.log_path.parent.name != run

    def test_a_lane_pause_names_the_role_the_loop_waits_for(self):
        out = stop("rate_limited", at=time.time() + 3 * 3600, lane="OPENAI_SUBSCRIPTION")
        self.run_engine({"plan": [PLAN], "write": [out]})
        r = self.eng.result()
        assert (r.outcome, r.kind) == ("paused", "pause_lane")
