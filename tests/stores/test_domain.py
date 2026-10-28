"""Logic on fakes only: no disk, no process, no sleep beyond a thread hand-off. Shows the fakes are enough to test code that
talks to the engine log, asks, checkpoints and locks through the interfaces."""
import dataclasses
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402,F401
import suites  # noqa: E402
from contracts import samples as S  # noqa: E402
from support.tiers import domain  # noqa: E402
from taskloop.contracts.ask import AskAnswer  # noqa: E402
from taskloop.contracts.enums import AskStatus, LockWhat  # noqa: E402
from taskloop.stores.memory import fake_stores  # noqa: E402
from taskloop.stores.runlog import RunLog  # noqa: E402
from support.narrow import must  # noqa: E402


@domain
class RunLogTest(unittest.TestCase):
    def test_emit_appends_typed_records_and_echoes_all_but_the_quiet_kinds(self) -> None:
        s = fake_stores()
        echoed: list[str] = []
        rl = RunLog(s.run_log("r"), echoed.append, frozenset({"note"}))
        rl.emit(S.LOG["step_start"])
        rl.emit(S.LOG["note"])
        rl.emit(S.LOG["close"])
        self.assertEqual([i.rec for i in s.run_log("r").read_from(0).items], [S.LOG["step_start"], S.LOG["note"], S.LOG["close"]])
        self.assertEqual([e.split()[0] for e in echoed], ["step_start", "close"])
        self.assertIn("step=write", echoed[0])

    def test_no_echo_is_fine(self) -> None:
        s = fake_stores()
        self.assertEqual(RunLog(s.run_log("r")).emit(S.LOG["note"]), 0)


@domain
class EngineAndDashOnFakesTest(unittest.TestCase):
    """The ask round trip the engine and the dashboard make through files today, now through two calls."""

    def test_engine_raises_dashboard_answers_engine_resumes(self) -> None:
        s = fake_stores()
        s.asks.of("tl-1").write(dataclasses.replace(S.ASK, status=AskStatus.OPEN, answer=None, answered=None, consumed=None))
        s.checkpoints.of("tl-1").write(suites.CK)
        self.assertEqual([a.bead for a in s.asks.live()], ["tl-1"])
        s.asks.answer("tl-1", "tl-1-1", AskAnswer(action="confirm", text="ok", t=5.0, by="denis"))  # pyrefly: ignore[unexpected-keyword]
        self.assertEqual(s.asks.live(), [])
        self.assertEqual(s.asks.of("tl-1").read().answer.by, "denis")
        self.assertEqual(s.checkpoints.open_beads(), ["tl-1"])
        s.checkpoints.of("tl-1").write(dataclasses.replace(suites.CK, closed=True))
        self.assertEqual(s.checkpoints.open_beads(), [])

    def test_a_land_lock_holder_is_visible_to_the_dashboard_while_it_lands(self) -> None:
        s = fake_stores()
        with s.locks.hold(LockWhat.LAND, "repo", "tl-1 pushing"):
            self.assertEqual(must(s.locks.holder(LockWhat.LAND, "repo")).holder, "tl-1 pushing")
        self.assertIsNone(s.locks.holder(LockWhat.LAND, "repo"))

    def test_fakes_are_independent_per_call(self) -> None:
        a, b = fake_stores(), fake_stores()
        a.events.append(S.EVENTS["claim"])
        self.assertEqual(b.events.read_from(0).items, [])


if __name__ == "__main__":
    unittest.main()
