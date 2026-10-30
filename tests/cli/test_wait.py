"""`tl wait` (exit code per outcome, timeout, an ask ending the wait) and `tl ask show`: temp config dir, fake clock and sleep."""
import argparse
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fake_beads import FakeBeads
from support.logs import typed, write_log

from taskloop.cli import asks as cli_asks
from taskloop.cli import wait
from taskloop.contracts.ask import Ask, SimilarRef, ThreadEntry
from taskloop.contracts.dash import OwnerCause
from taskloop.contracts.enums import AskClass, AskKind, AskStatus
from taskloop.contracts.ids import BeadId
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.stores import AskStore

BEAD, RUN, T = "t-1", "t-1-20261026-100000", 5000.0


class Clock:
    def __init__(self, on_sleep=None):
        self.t, self.on_sleep, self.slept = T, on_sleep, 0

    def now(self):
        return self.t

    def sleep(self, secs):
        self.t += secs
        self.slept += 1
        if self.on_sleep:
            self.on_sleep(self)


class WaitCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = ConfigDir(self.tmp.name)
        (self.cfg.root / "engine").mkdir()
        self.asks = AskStore.at(self.cfg)
        self.out: list[str] = []

    def log(self, run=RUN, close=None, beat=T):
        rows = [typed("run_start", beat - 10, run=run, bead=run.rsplit("-", 2)[0], worktree="/w/x"), typed("beat", beat)]
        if close:
            rows.append(typed("close", beat + 1, outcome=close, why="because"))
        write_log(self.cfg.engine_log(run), rows)

    def go(self, *argv, clock=None):
        ap = argparse.ArgumentParser()
        wait.add_parser(ap.add_subparsers(dest="cmd"))
        c = clock or Clock()
        rc = wait.wait(ap.parse_args(["wait", *argv]), self.cfg, self.asks, "/repo", lambda _w: "/repo", self.out.append, c.now, c.sleep)
        return rc, c

    def ask(self, t=T + 1):
        a = Ask(id="t-1-1", n=1, bead=BeadId(BEAD), kind=AskKind.DECISION, ask_class=AskClass.OPEN_QUESTION, decision="Keep v1?",
                run=RUN, t=t,
                status=AskStatus.OPEN)
        self.asks.put(a)
        return a

    def test_an_ended_run_exits_by_its_outcome(self):
        for outcome, code in (("landed", 0), ("done", 0), ("parked", 11), ("failed", 11), ("blocked", 11)):
            self.log(close=outcome)
            self.assertEqual(self.go("--bead", BEAD)[0], code, outcome)
        self.assertTrue(self.out[0].startswith("ended landed: " + RUN))

    def test_a_crashed_run_has_its_own_code(self):
        self.log(beat=T - 400)
        self.assertEqual(self.go("--bead", BEAD)[0], wait.CRASHED)

    def test_no_run_has_its_own_code(self):
        self.assertEqual(self.go("--bead", BEAD)[0], wait.NO_RUN)
        self.assertEqual(self.go("--any")[0], wait.NO_RUN)

    def test_a_live_run_waits_then_reports_its_close(self):
        self.log()
        rc, c = self.go("--bead", BEAD, clock=Clock(lambda c: self.log(close="landed", beat=c.t) if c.slept == 3 else None))
        self.assertEqual((rc, c.slept), (0, 3))

    def test_timeout_prints_one_line_and_its_code(self):
        self.log()
        rc, c = self.go("--bead", BEAD, "--timeout", "5")
        self.assertEqual((rc, len(self.out), c.t - T), (wait.TIMEOUT, 1, 5.0))
        self.assertTrue(self.out[0].startswith("timeout"))

    def test_an_ask_that_opens_ends_the_wait(self):
        self.log()
        rc, _ = self.go("--bead", BEAD, clock=Clock(lambda c: self.ask(c.t)))
        self.assertEqual((rc, self.out), (wait.ASK, ["ask: t-1 t-1-1 [decision] Keep v1?"]))

    def test_an_ask_older_than_the_wait_does_not_end_it(self):
        self.log()
        self.ask(t=T - 100)
        self.assertEqual(self.go("--bead", BEAD, "--timeout", "3")[0], wait.TIMEOUT)

    def test_any_waits_for_the_first_live_run_of_the_repo_to_end(self):
        self.log()
        self.log("t-2-20261026-100000")
        rc, _ = self.go("--any", clock=Clock(lambda c: self.log("t-2-20261026-100000", close="failed", beat=c.t)))
        self.assertEqual((rc, self.out[0].startswith("ended failed: t-2-")), (wait.ENDED_NOT_OK, True))

    def test_help_documents_every_code(self):
        for code in (0, wait.ASK, wait.ENDED_NOT_OK, wait.CRASHED, wait.NO_RUN, wait.TIMEOUT):
            self.assertIn(f"  {code}  ", wait.CODES)


class Show(WaitCase):
    def show(self, key):
        ap = argparse.ArgumentParser()
        cli_asks.add_parsers(ap.add_subparsers(dest="cmd"))
        rc = cli_asks.run(ap.parse_args(["ask", "show", key]), self.asks, lambda _r: FakeBeads(), lambda: T, "x", self.cfg, self.out.append)
        return rc

    def test_prints_the_v3_fields(self):
        a = self.ask().replace(owner_cause=OwnerCause.DECISION, blocking=False, default="keep v1",
                                similar=[SimilarRef(kind="adr", id="adr-3")], thread=[ThreadEntry(by="owner", t=1.0, md="why?")])
        self.asks.put(a)
        for key in ("t-1-1", BEAD):
            self.out.clear()
            self.assertEqual(self.show(key), 0)
            text = "\n".join(self.out)
            for want in ("question: Keep v1?", "owner cause: decision", "blocking: no", "default: keep v1", "adr adr-3", "[owner] why?",
                         "outcome: -"):
                self.assertIn(want, text)

    def test_an_unknown_id_is_one_line_and_nonzero(self):
        self.assertEqual((self.show("nope"), self.out), (1, ["tl: no ask nope"]))


if __name__ == "__main__":
    unittest.main()
