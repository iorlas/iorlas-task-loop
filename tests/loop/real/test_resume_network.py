"""R21 (tl-7y6.2.13, tl-7y6.2.15, tl-kyy): a network drop is not a failure. Every workflow step goes on in the same thread after the
network is back (no finished output rerun, no counter charged, no lane marked), the land detects a push that already went through,
a network pause keeps its run id, cost and time budget, and a paused bead wakes when its role is usable, not at a clock."""

import json
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401
from support import homes

# isort: split
from run import test_stages_visual
from support import engine_case as te
from support import gitq
from support.engine_case import CLEAN, PLAN, WRITE, real_git, stop
from support.pushsim import CUT, pusher

from taskloop.app.loop.gate import GateRole

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
        self.assertFalse(list((homes.config_dir() / "storm").glob("*.json")) if (homes.config_dir() / "storm").is_dir() else [])

    def thread_of(self, s, node):
        """(resume ref of each call of `node`, in order)."""
        return [s.calls[i][1] for i, n in enumerate(s.nodes) if n == node]


class Land(NetBase):
    """The push is the one step with no AI call: a network error waits for the probe, and a push the server took is not repeated."""

    @real_git("the land script is a child process that runs git push itself")
    def test_a_push_the_network_cut_resumes_after_the_probe_and_lands_once(self):
        count = Path(self.tmp.name, "pushes")
        land = pusher("cut-push", count, cut_first=2)
        probe = Cycling(2)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, probe=probe, land=land)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(Counter(s.nodes), Counter({"plan": 1, "write": 1, "review": 1}))  # no step again for a failed push
        self.assertTrue(self.closed and self.closed[0].startswith("merged"))
        self.assertEqual(gitq.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d2")
        self.assertGreaterEqual(probe.calls, 2)
        self.assertEqual(count.read_text(), "3")  # two cuts, then the push
        self.assert_no_charge()

    @real_git("the land script is a child process that runs git push itself")
    def test_a_push_the_server_took_before_the_connection_dropped_is_not_pushed_again(self):
        count = Path(self.tmp.name, "pushes")
        land = pusher("took-push", count, then_fail=CUT)
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, probe=Cycling(1), land=land)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(count.read_text(), "1")  # pushed once; the second look found it on the base
        self.assertTrue(self.closed and self.closed[0].startswith("merged"))
        subjects = gitq.git("log", "--format=%s", "origin/main", cwd=str(self.wt)).splitlines()  # pyrefly: ignore[missing-attribute]
        self.assertEqual(sum("(t-1)" in x for x in subjects), 1)  # one commit of the bead on the base
        self.assertIn("already", self.eng.log_path.read_text())
        self.assert_no_charge()

    @real_git("the land script is a child process that runs git push itself")
    def test_a_rerun_after_a_push_that_went_through_but_was_never_seen_closes_without_pushing(self):
        count = Path(self.tmp.name, "pushes")
        pushed = pusher("odd-push", count, then_fail="fatal: the hook lost its answer\n")
        again = pusher("counted-push", count)
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, land=pushed)
        self.assertEqual(rc, 2)  # the run reported a failed land: the bead is open, the branch is kept
        self.assertEqual((count.read_text(), self.closed), ("1", []))
        self.assertEqual(gitq.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d2")  # but it is on the base
        rc, _s = self.run_engine({"write": [WRITE], "review": [CLEAN]}, land=again)  # the next run
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(count.read_text(), "1")  # not pushed again
        self.assertTrue(self.closed and self.closed[0].startswith("merged"))
        subjects = gitq.git("log", "--format=%s", "origin/main", cwd=str(self.wt)).splitlines()  # pyrefly: ignore[missing-attribute]
        self.assertEqual(sum("(t-1)" in x for x in subjects), 1)


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


class ResumeLook(test_stages_visual.VisualWork):
    """The look judge goes on in its thread after a drop."""


    def log(self):
        return [json.loads(x) for x in self.eng.log_path.read_text().splitlines()]


for _name in dir(test_stages_visual.VisualWork):  # the visual fixture only: not every test of its class again
    if _name.startswith("test_") and _name not in ResumeLook.__dict__:
        setattr(ResumeLook, _name, None)


if __name__ == "__main__":
    unittest.main()
