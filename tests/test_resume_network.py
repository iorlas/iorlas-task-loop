"""R21 (tl-7y6.2.13, tl-7y6.2.15, tl-kyy): a network drop is not a failure. Every workflow step goes on in the same thread after the
network is back (no finished output rerun, no counter charged, no lane marked), the land detects a push that already went through,
a network pause keeps its run id, cost and time budget, and a paused bead wakes when its role is usable, not at a clock."""

import json
import sys
import time
import unittest
from collections import Counter
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: F401

# isort: split
import test_stages_visual
from support import engine_case as te
from support import (
    tlbd,
)
from support.engine_case import CLEAN, PLAN, WRITE, stop, verdict

from taskloop.adapters import gitrepo, ident
from taskloop.app.loop.gate import GateRole
from taskloop.app.release import reexec
from taskloop.contracts.config import LoopConfig
from taskloop.domain import outcome as oc
from taskloop.domain.lanes import netgate
from taskloop.stores import call_state as callstate

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
            self.assertNotIn(bad, causes)
        self.assertEqual((eng.stats["replans"], eng.stats["rounds"]), (0, 0))
        self.assertEqual((self.blocked, self.ask()), ([], None))
        self.assertFalse([c for c in self.bd_calls if c[:2] == ("label", "add")], self.bd_calls)
        self.assertFalse(list((ident.config_dir() / "storm").glob("*.json")) if (ident.config_dir() / "storm").is_dir() else [])

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
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(self.thread_of(s, node), [None, "net-" + node], node)  # the second call goes on in the first one's thread
        i = [k for k, n in enumerate(s.nodes) if n == node][1]
        self.assertEqual(s.prompts[i], callstate.NETWORK_RESUME_DELTA)  # a short note: the brief is not sent twice
        once = Counter(n for n in s.nodes if n != node)
        self.assertTrue(once and set(once.values()) == {1}, once)  # nothing finished was asked again
        self.assertGreaterEqual(probe.calls, 2)
        self.assertEqual(self.eng.result()["outcome"], "landed")
        self.assertIn("network_wait", self.causes())
        self.assert_no_charge()
        return s

    def test_a_drop_in_the_plan_resumes_the_planner_thread(self):
        self.drop_at("plan")

    def test_a_drop_in_the_write_resumes_the_writer_thread_and_the_work_is_kept(self):
        self.drop_at("write")
        self.assertEqual(self.eng.writer["delegate"], "ref-write")  # the thread the engine now holds is the one the answer named

    def test_a_drop_in_the_review_resumes_the_reviewer_thread(self):
        self.drop_at("review")

    def test_a_drop_in_the_verify_resumes_the_verifier_thread(self):
        gaps = te.EngineTest.GAPS
        answers = {"plan": [PLAN], "write": [WRITE], "review": [dict(CLEAN, unchecked=gaps)],
                   "verify": [{"items": [verdict(n, "settled", f"a.cs:{n}") for n in (1, 2, 3)]}]}
        self.drop_at("verify", answers)

    def test_a_drop_costs_no_attempt_whatever_the_number_of_drops(self):
        # no cap counts a network stop: not the one retry of a bead failure, not the three polls, not the crash rests
        answers = {"plan": [PLAN], "write": [drop("net-write")] * 6 + [WRITE], "review": [CLEAN]}
        rc, s = self.run_engine(answers, probe=Flapping())
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(self.thread_of(s, "write"), [None] + ["net-write"] * 6)
        self.assert_no_charge()

    def test_a_probe_that_keeps_failing_calls_pauses_the_run_visibly_and_charges_nothing(self):
        # the probe says up and the calls say down, three times in five minutes: a proxy or DNS fault the probe cannot see
        answers = {"plan": [PLAN], "write": [drop("net-write")] * 4 + [WRITE], "review": [CLEAN]}
        rc, _s = self.run_engine(answers, probe=netgate.FakeProbe([True]))
        self.assertEqual(rc, 2)
        r = self.eng.result()
        self.assertEqual((r["outcome"], r["kind"]), ("paused", oc.Kind.PAUSE_NETWORK.value))
        self.assertEqual((self.blocked, self.ask()), ([], None))
        self.assertFalse([c for c in self.bd_calls if c[:2] == ("label", "add")])


class Checks(NetBase):
    """The checks that already passed are not run again by the run that goes on after a network pause."""

    def test_a_network_pause_then_a_new_run_does_not_run_the_green_checks_again(self):
        count = Path(self.tmp.name) / "count"
        bump = te.PY + f' -c "open({str(count)!r}, \'a\').write(\'1\')"'
        cfg = {"checks": [{"id": "bump", "cmd": bump, "group": "tests"}]}
        answers = {"plan": [PLAN], "write": [WRITE], "review": [drop("net-review")] * 40}
        rc, s = self.run_engine(answers, probe=netgate.FakeProbe([False]), **cfg)  # the network stays down: the run pauses
        self.assertEqual(rc, 2)
        self.assertEqual(self.eng.result()["kind"], oc.Kind.PAUSE_NETWORK.value)
        self.assertEqual(count.read_text(), "1")
        rc, s = self.run_engine({"review": [CLEAN]}, probe=Cycling(0), **cfg)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(s.nodes, ["review"])  # the plan and the write were not asked again
        self.assertEqual(s.calls[0][1], "net-review")
        self.assertEqual(count.read_text(), "1")  # the tree did not change: the green result was kept
        self.assertEqual(self.eng.result()["outcome"], "landed")


class Land(NetBase):
    """The push is the one step with no AI call: a network error waits for the probe, and a push the server took is not repeated."""

    def push_script(self, name, body):
        p = Path(self.tmp.name, name)
        p.write_text(body)
        return te.PY + " " + str(p).replace("\\", "/")

    CUT = "error: RPC failed; curl 56 Send failure: Broken pipe\nfatal: the remote end hung up unexpectedly\n"

    def test_a_push_the_network_cut_resumes_after_the_probe_and_lands_once(self):
        count = Path(self.tmp.name, "pushes")
        land = self.push_script("cut_push.py",
                                f"import os, subprocess, sys\nm = {str(count)!r}\nn = int(open(m).read()) if os.path.exists(m) else 0\n"
                                f"open(m, 'w').write(str(n + 1))\nif n < 2:\n    sys.stderr.write({self.CUT!r}); sys.exit(1)\n"
                                "sys.exit(subprocess.call(['git', 'push', 'origin', 'HEAD:main']))\n")
        probe = Cycling(2)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, probe=probe, land=land)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(Counter(s.nodes), Counter({"plan": 1, "write": 1, "review": 1}))  # no step again for a failed push
        self.assertTrue(self.closed and self.closed[0].startswith("merged"))
        self.assertEqual(gitrepo.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d2")
        self.assertGreaterEqual(probe.calls, 2)
        self.assertEqual(count.read_text(), "3")  # two cuts, then the push
        self.assert_no_charge()

    def test_a_push_the_server_took_before_the_connection_dropped_is_not_pushed_again(self):
        count = Path(self.tmp.name, "pushes")
        land = self.push_script("took_push.py",
                                f"import os, subprocess, sys\nm = {str(count)!r}\nopen(m, 'a').write('1')\n"
                                "subprocess.call(['git', 'push', 'origin', 'HEAD:main'])\n"
                                f"sys.stderr.write({self.CUT!r}); sys.exit(1)\n")
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, probe=Cycling(1), land=land)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(count.read_text(), "1")  # pushed once; the second look found it on the base
        self.assertTrue(self.closed and self.closed[0].startswith("merged"))
        subjects = gitrepo.git("log", "--format=%s", "origin/main", cwd=str(self.wt)).splitlines()  # pyrefly: ignore[missing-attribute]
        self.assertEqual(sum("(t-1)" in x for x in subjects), 1)  # one commit of the bead on the base
        self.assertIn("already", self.eng.log_path.read_text())
        self.assert_no_charge()

    def test_a_rerun_after_a_push_that_went_through_but_was_never_seen_closes_without_pushing(self):
        count = Path(self.tmp.name, "pushes")
        pushed = self.push_script("odd_push.py", f"import subprocess, sys\nopen({str(count)!r}, 'a').write('1')\n"
                                  "subprocess.call(['git', 'push', 'origin', 'HEAD:main'])\n"
                                  "sys.stderr.write('fatal: the hook lost its answer\\n'); sys.exit(1)\n")
        again = self.push_script("counted_push.py", f"import subprocess, sys\nopen({str(count)!r}, 'a').write('1')\n"
                                 "sys.exit(subprocess.call(['git', 'push', 'origin', 'HEAD:main']))\n")
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, land=pushed)
        self.assertEqual(rc, 2)  # the run reported a failed land: the bead is open, the branch is kept
        self.assertEqual((count.read_text(), self.closed), ("1", []))
        self.assertEqual(gitrepo.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d2")  # but it is on the base
        rc, _s = self.run_engine({"write": [WRITE], "review": [CLEAN]}, land=again)  # the next run
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(count.read_text(), "1")  # not pushed again
        self.assertTrue(self.closed and self.closed[0].startswith("merged"))
        subjects = gitrepo.git("log", "--format=%s", "origin/main", cwd=str(self.wt)).splitlines()  # pyrefly: ignore[missing-attribute]
        self.assertEqual(sum("(t-1)" in x for x in subjects), 1)


class Pause(NetBase):
    """A network pause is not a stop of the bead: the next run is the same run, with the same cost and the same time budget."""

    def pause_in_review(self, probe=None, **kw):
        answers = {"plan": [PLAN], "write": [WRITE], "review": [drop("net-review")] * 40}
        rc, s = self.run_engine(answers, probe=probe or netgate.FakeProbe([False]), **kw)
        self.assertEqual(rc, 2)
        return s

    def test_the_run_that_goes_on_has_the_same_run_id_the_cost_and_no_pause_time_in_its_budget(self):
        self.pause_in_review()
        first = self.eng
        r = first.result()
        self.assertEqual((r["outcome"], r["kind"]), ("paused", oc.Kind.PAUSE_NETWORK.value))
        self.assertEqual((r["retry_after"], r["role"]), (0, "reviewer"))
        self.assertEqual((self.blocked, self.ask()), ([], None))
        self.assertFalse([c for c in self.bd_calls if c[:2] == ("label", "add")])  # no auto label, no engine-fault label
        self.assertTrue(any(c[:1] == ("update",) and "open" in c for c in self.bd_calls))
        cost, run = first.cost, first.log_path.stem
        real = time.time
        with mock.patch.object(time, "time", lambda: real() + 7200):  # the bead waited two hours for the network
            rc, s = self.run_engine({"review": [CLEAN]}, probe=Cycling(0))
            second = self.eng
            self.assertEqual(rc, 0, self.blocked)
            self.assertEqual(second.log_path.stem, run)  # the same run
            self.assertGreaterEqual(second.cost, cost)  # its cost goes on
            self.assertLess(second.budget.spent_min(), 30)  # the two hours of pause are not charged to the time budget
        self.assertEqual(s.nodes, ["review"])
        self.assertEqual(s.calls[0][1], "net-review")
        self.assertFalse((ident.config_dir() / "pauses" / "t-1.json").exists())  # taken once

    def test_the_engine_comment_of_a_pause_does_not_make_the_next_run_plan_again(self):
        self.pause_in_review()
        said = [c[3] for c in self.bd_calls if c[:3] == ("comments", "add", "t-1") and c[3].startswith("Engine paused:")]
        self.assertTrue(said, self.bd_calls)
        with self.store.stub(comments=[{"author": "tl-a", "text": t} for t in said]):
            rc, s = self.run_engine({"review": [CLEAN]}, probe=Cycling(0))
        self.assertEqual(rc, 0, self.blocked)
        self.assertNotIn("plan", s.nodes)  # the brief it was planned from is the same brief

    def test_a_pause_older_than_the_longest_one_is_a_new_run(self):
        self.pause_in_review()
        run = self.eng.log_path.stem
        real = time.time
        with mock.patch.object(time, "time", lambda: real() + reexec.NET_PAUSE_ADOPT_S + 60):
            self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, probe=Cycling(0))
        self.assertNotEqual(self.eng.log_path.stem, run)

    def test_a_lane_pause_names_the_role_the_loop_waits_for(self):
        out = stop("rate_limited", at=time.time() + 3 * 3600, lane="OPENAI_SUBSCRIPTION")
        self.run_engine({"plan": [PLAN], "write": [out]})
        r = self.eng.result()
        self.assertEqual((r["outcome"], r["kind"], r["role"], r["lane"]), ("paused", "pause_lane", "worker", "OPENAI_SUBSCRIPTION"))


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
        self.assertIn("Reconnecting... waiting for network", said)
        cut = stop("network", ref, partial=True, say=said, tokens={"in": 738090, "cached": 664320, "out": 6851})
        rc, s = self.run_engine({"plan": [cut, PLAN], "write": [WRITE], "review": [CLEAN]}, probe=Cycling(1))
        self.assertEqual(rc, 0, self.blocked)
        planner = [c for c in s.calls if c[0] == "planner"]
        self.assertEqual([c[1] for c in planner], [None, ref])  # exactly one resume, in the same thread
        plan_ends = [r for r in self.log() if r.get("kind") == "step_end" and r.get("step") == "plan"]
        self.assertEqual(len(plan_ends), 1)  # one plan node, ended once
        self.assertNotIn("invalid_output", self.causes())
        self.assertNotIn("plan output invalid", self.eng.log_path.read_text())
        sessions = [x for x in self.eng.sessions if x["node"] == "plan"]
        self.assertEqual([x["attempt"] for x in sessions][-1], 1)  # the attempt counter did not move
        self.assert_no_charge()


class Gate(unittest.TestCase):
    """GateRole: a paused bead waits for delegate to call its role usable; a time hint never blocks; unknown fails open."""

    def setUp(self):
        self.t = 1_800_000_000.0
        self.roles: dict[str, bool | None] = {"worker": False}
        self.reads = 0
        self.gate = GateRole(self.read, now=lambda: self.t)

    def read(self):
        self.reads += 1
        return self.roles

    def test_a_bead_wakes_when_its_role_is_usable(self):
        self.gate.hold("x-1", "worker")
        self.assertFalse(self.gate.ready("x-1"))
        self.t += LoopConfig().gate_cache + 1
        self.roles["worker"] = True
        self.assertTrue(self.gate.ready("x-1"))
        self.assertNotIn("x-1", self.gate.held)  # woken once
        self.assertTrue(self.gate.ready("x-2"))  # a bead that is not held is never gated

    def test_the_view_is_cached_for_30_seconds(self):
        self.gate.hold("x-1", "worker")
        for _ in range(5):
            self.gate.ready("x-1")
            self.t += 5
        self.assertEqual(self.reads, 1)
        self.t += LoopConfig().gate_cache
        self.gate.ready("x-1")
        self.assertEqual(self.reads, 2)

    def test_an_unknown_role_fails_open_after_the_unknown_wait_and_not_before(self):
        self.roles.clear()
        self.gate.hold("x-1", "worker")
        self.t += LoopConfig().gate_unknown - 1
        self.assertFalse(self.gate.ready("x-1"))
        self.t += 2
        self.assertTrue(self.gate.ready("x-1"))

    def test_a_role_that_is_down_keeps_the_bead_waiting_however_long(self):
        self.gate.hold("x-1", "worker")
        self.t += 10 * 3600
        self.assertFalse(self.gate.ready("x-1"))

    def test_nothing_is_written_back(self):
        self.gate.hold("x-1", "worker")
        with tlbd.bd_boundary() as bd, mock.patch.object(Path, "write_text") as wt:
            self.gate.ready("x-1")
        bd.assert_not_called()
        wt.assert_not_called()


class ResumeLook(test_stages_visual.VisualWork):
    """The look judge goes on in its thread after a drop."""

    def test_a_drop_in_the_look_judge_resumes_its_thread(self):
        probe = Cycling(2)
        answers = {"plan": [te.PLAN], "write": [self.write()], "look": [drop("net-look"), self.judged()], "review": [CLEAN]}
        rc, s = self.go(answers, probe=probe)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([s.calls[i][1] for i, n in enumerate(s.nodes) if n == "look"], [None, "net-look"])
        self.assertEqual(Counter(n for n in s.nodes if n != "look"), Counter({"plan": 1, "write": 1, "review": 1}))
        self.assertIn("network_wait", [r.get("cause") for r in self.log() if r.get("kind") == "transition"])
        self.assertEqual((self.blocked, self.ask()), ([], None))

    def log(self):
        return [json.loads(x) for x in self.eng.log_path.read_text().splitlines()]



for _name in dir(test_stages_visual.VisualWork):  # the visual fixture only: not every test of its class again
    if _name.startswith("test_") and _name not in ResumeLook.__dict__:
        setattr(ResumeLook, _name, None)


if __name__ == "__main__":
    unittest.main()
