"""R21 (tl-7y6.2.13, tl-7y6.2.15, tl-kyy): a network drop is not a failure. Every workflow step goes on in the same thread after the
network is back (no finished output rerun, no counter charged, no lane marked), the land detects a push that already went through,
a network pause keeps its work, cost and time budget, and a paused bead wakes when its role is usable, not at a clock."""

import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import homes

# isort: split
from run import test_stages_visual
from support import engine_case as te
from support import (
    netgate,
    procsim,
)
from support.engine_case import stop
from support.plans import CLEAN, PLAN, WRITE, verdict

from taskloop.app.release import reexec
from taskloop.app.workers import call_state as callstate
from tlkernel.kinds import Kind
from tlkernel.locator import RunLocator

SAY = "codex: Reconnecting... waiting for network (Connection failed: error sending request)"
REPLAY = te.ROOT / "tests" / "fixtures" / "replay" / "5ban16_plan_network_drop.jsonl"


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


class Flapping:
    """A network that is down at each stop and back at the next look: down, up, down, up ..."""

    def __init__(self):
        self.calls = 0

    def up(self):
        self.calls += 1
        return self.calls % 2 == 0


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
        assert not (list((homes.config_dir() / "storm").glob("*.json")) if (homes.config_dir() / "storm").is_dir() else [])

    def thread_of(self, s, node):
        """(resume ref of each call of `node`, in order)."""
        return [s.calls[i][1] for i, n in enumerate(s.nodes) if n == node]


class EveryStepResumes(NetBase):
    """Plan, write, review and verify: the drop is answered with the thread's ref; the engine waits for the probe, then goes on
    in that thread with the short delta. The other steps are asked once."""

    BASE: ClassVar[Any] = {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}

    def drop_at(self, node, answers=None, probe=None, **cfg):
        answers = {k: list(v) for k, v in (answers or self.BASE).items()}
        answers[node].insert(0, drop("net-" + node))
        probe = probe or Cycling(2)
        rc, s = self.run_engine(answers, probe=probe, **cfg)
        assert rc == 0, self.blocked
        assert self.thread_of(s, node) == [None, "net-" + node], node  # the second call goes on in the first one's thread
        i = [k for k, n in enumerate(s.nodes) if n == node][1]
        assert s.prompts[i] == callstate.NETWORK_RESUME_DELTA  # a short note: the brief is not sent twice
        once = Counter(n for n in s.nodes if n != node)
        assert once and set(once.values()) == {1}, once  # nothing finished was asked again
        assert probe.calls >= 2
        assert self.eng.result().outcome == "landed"
        assert "network_wait" in self.causes()
        self.assert_no_charge()
        return s

    def test_a_drop_in_the_plan_resumes_the_planner_thread(self):
        self.drop_at("plan")

    def test_a_drop_in_the_write_resumes_the_writer_thread_and_the_work_is_kept(self):
        self.drop_at("write")
        assert self.eng.writer.delegate == "ref-write"  # the thread the engine now holds is the one the answer named

    def test_a_drop_in_the_review_resumes_the_reviewer_thread(self):
        self.drop_at("review")

    def test_a_drop_in_the_verify_resumes_the_verifier_thread(self):
        gaps = te.EngineTest.GAPS
        answers = {
            "plan": [PLAN],
            "write": [WRITE],
            "review": [dict(CLEAN, unchecked=gaps)],
            "verify": [{"items": [verdict(n, "settled", f"a.cs:{n}") for n in (1, 2, 3)]}],
        }
        self.drop_at("verify", answers)

    def test_a_drop_costs_no_attempt_whatever_the_number_of_drops(self):
        # no cap counts a network stop: not the one retry of a bead failure, not the three polls, not the crash rests
        answers = {"plan": [PLAN], "write": [drop("net-write")] * 6 + [WRITE], "review": [CLEAN]}
        rc, s = self.run_engine(answers, probe=Flapping())
        assert rc == 0, self.blocked
        assert self.thread_of(s, "write") == [None] + ["net-write"] * 6
        self.assert_no_charge()

    def test_a_probe_that_keeps_failing_calls_pauses_the_run_visibly_and_charges_nothing(self):
        # the probe says up and the calls say down, three times in five minutes: a proxy or DNS fault the probe cannot see
        answers = {"plan": [PLAN], "write": [drop("net-write")] * 4 + [WRITE], "review": [CLEAN]}
        rc, _s = self.run_engine(answers, probe=netgate.FakeProbe([True]))
        assert rc == 2
        r = self.eng.result()
        assert (r.outcome, r.kind) == ("paused", Kind.PAUSE_NETWORK.value)
        assert (self.blocked, self.ask()) == ([], None)
        assert not [c for c in self.bd_calls if c[:2] == ("label", "add")]


class TwoDrops(NetBase):
    def test_two_drops_then_success_is_one_step_in_one_thread_and_charges_nothing(self):
        answers = {"plan": [PLAN], "write": [drop("net-write"), drop("net-write"), WRITE], "review": [CLEAN]}
        rc, s = self.run_engine(answers, probe=Flapping())
        assert rc == 0, self.blocked
        assert self.thread_of(s, "write") == [None, "net-write", "net-write"]  # the ref the first drop named, on both resumes
        ends = [r for r in self.log() if r.get("kind") == "step_end" and r.get("step") == "write"]
        assert len(ends) == 1
        assert self.causes().count("network_wait") == 2
        self.assert_no_charge()


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

    def test_a_drop_with_no_valid_data_is_still_resumed(self):
        answers = {"plan": [PLAN], "write": [drop("net-write", data={"bogus": 1}), WRITE], "review": [CLEAN]}
        rc, s = self.run_engine(answers, probe=Cycling(2))
        assert rc == 0, self.blocked
        assert self.thread_of(s, "write") == [None, "net-write"]
        self.assert_no_charge()


class ResumeRefused(NetBase):
    """The vendor rejects the ref a call resumes: one new thread with the whole prompt, once."""

    def test_a_refused_resume_becomes_one_new_thread(self):
        answers = {"plan": [PLAN], "write": [drop("net-write"), stop("bad_request"), WRITE], "review": [CLEAN]}
        rc, s = self.run_engine(answers, probe=Cycling(2))
        assert rc == 0, self.blocked
        assert self.thread_of(s, "write") == [None, "net-write", None]
        first, _, third = (s.prompts[i] for i, n in enumerate(s.nodes) if n == "write")
        assert third.startswith(first)  # the whole brief again, no transcript seeding
        assert self.eng.result().outcome == "landed"

    def test_a_second_refusal_is_the_fault_not_a_loop(self):
        answers = {"plan": [PLAN], "write": [drop("net-write"), stop("bad_request"), stop("bad_request"), WRITE], "review": [CLEAN]}
        rc, s = self.run_engine(answers, probe=Cycling(2))
        assert rc == 2
        assert self.thread_of(s, "write") == [None, "net-write", None]
        assert self.eng.result().kind == Kind.FAULT_BAD_REQUEST.value


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
        assert s.calls[0][1] == "net-review"
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
        assert s.calls[0][1] == "net-review"
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


class Replay5ban16(NetBase):
    """lifesim 5ban.16, 2026-10-24 07:16: the planner's Codex ran 10 minutes, the network went ('Reconnecting... waiting for
    network'), delegate answered worker_failed, the engine read it as invalid output and asked for the plan on a new thread: 738k
    tokens spent again. Now the same log line is one resume."""

    def facts(self):
        recs = [json.loads(x) for x in REPLAY.read_text().splitlines()]
        sess = next(r for r in recs if r["kind"] == "session")
        note = next(r for r in recs if r["kind"] == "note")
        return sess["ref"], note["text"].split(": ", 2)[2]

    def test_the_logged_drop_replays_to_one_resume_of_the_same_thread(self):
        ref, said = self.facts()
        assert "Reconnecting... waiting for network" in said
        cut = stop("network", ref, partial=True, say=said, tokens={"in": 738090, "cached": 664320, "out": 6851})
        rc, s = self.run_engine({"plan": [cut, PLAN], "write": [WRITE], "review": [CLEAN]}, probe=Cycling(1))
        assert rc == 0, self.blocked
        planner = [c for c in s.calls if c[0] == "planner"]
        assert [c[1] for c in planner] == [None, ref]  # exactly one resume, in the same thread
        plan_ends = [r for r in self.log() if r.get("kind") == "step_end" and r.get("step") == "plan"]
        assert len(plan_ends) == 1  # one plan node, ended once
        assert "invalid_output" not in self.causes()
        assert "plan output invalid" not in self.eng.log_path.read_text()
        sessions = [x for x in self.eng.sessions if x["node"] == "plan"]
        assert [x["attempt"] for x in sessions][-1] == 1  # the attempt counter did not move
        self.assert_no_charge()



class ResumeLook(test_stages_visual.VisualWork):
    """The look judge goes on in its thread after a drop."""

    def test_a_drop_in_the_look_judge_resumes_its_thread(self):
        probe = Cycling(2)
        answers = {"plan": [te.PLAN], "write": [self.write()], "look": [drop("net-look"), self.judged()], "review": [CLEAN]}
        rc, s = self.go(answers, probe=probe)
        assert rc == 0, self.blocked
        assert [s.calls[i][1] for i, n in enumerate(s.nodes) if n == "look"] == [None, "net-look"]
        assert Counter(n for n in s.nodes if n != "look") == Counter({"plan": 1, "write": 1, "review": 1})
        assert "network_wait" in [r.get("cause") for r in self.log() if r.get("kind") == "transition"]
        assert (self.blocked, self.ask()) == ([], None)

    def log(self):
        return [json.loads(x) for x in self.eng.log_path.read_text().splitlines()]


for _name in dir(test_stages_visual.VisualWork):  # the visual fixture only: not every test of its class again
    if _name.startswith("test_") and _name not in ResumeLook.__dict__:
        setattr(ResumeLook, _name, None)
