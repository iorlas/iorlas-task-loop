"""Logic on fakes only: no disk, no process, no sleep beyond a thread hand-off. Shows the fakes are enough to test code that
talks to the engine log, asks, checkpoints and locks through the interfaces."""
import sys
from pathlib import Path

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

# isort: split
import suites
from contracts import samples as S
from support.memstores import fake_stores
from support.narrow import must
from support.tiers import domain

from taskloop.stores.runlog import RunLog
from tlkernel.ask import AskAnswer
from tlkernel.enums import AskStatus, LockWhat
from tlkernel.ids import BeadId


@domain
class RunLogTest(Case):
    def test_emit_appends_typed_records_and_echoes_all_but_the_quiet_kinds(self) -> None:
        s = fake_stores()
        echoed: list[str] = []
        rl = RunLog(s.run_log("r"), echoed.append, frozenset({"note"}))
        rl.emit(S.LOG["step_start"])
        rl.emit(S.LOG["note"])
        rl.emit(S.LOG["close"])
        assert [i.rec for i in s.run_log("r").read_from(0).items] == [S.LOG["step_start"], S.LOG["note"], S.LOG["close"]]
        assert [e.split()[0] for e in echoed] == ["step_start", "close"]
        assert "step=write" in echoed[0]

    def test_no_echo_is_fine(self) -> None:
        s = fake_stores()
        assert RunLog(s.run_log("r")).emit(S.LOG["note"]) == 0


@domain
class EngineAndDashOnFakesTest(Case):
    """The ask round trip the engine and the dashboard make through files today, now through two calls."""

    def test_engine_raises_dashboard_answers_engine_resumes(self) -> None:
        s = fake_stores()
        s.asks.of(BeadId("tl-1")).write(S.ASK.replace(status=AskStatus.OPEN, answer=None, answered=None, consumed=None))
        s.checkpoints.of("tl-1").write(suites.CK)
        assert [a.bead for a in s.asks.live()] == ["tl-1"]
        s.asks.answer(BeadId("tl-1"), "tl-1-1", AskAnswer(action="confirm", text="ok", t=5.0, by="denis"))  # pyrefly: ignore[unexpected-keyword]
        assert s.asks.live() == []
        assert s.asks.of(BeadId("tl-1")).get().answer.by == "denis"
        assert s.checkpoints.open_beads() == ["tl-1"]
        s.checkpoints.of("tl-1").write(suites.CK.replace(closed=True))
        assert s.checkpoints.open_beads() == []

    def test_a_land_lock_holder_is_visible_to_the_dashboard_while_it_lands(self) -> None:
        s = fake_stores()
        with s.locks.hold(LockWhat.LAND, "repo", "tl-1 pushing"):
            assert must(s.locks.holder(LockWhat.LAND, "repo")).holder == "tl-1 pushing"
        assert s.locks.holder(LockWhat.LAND, "repo") is None

    def test_fakes_are_independent_per_call(self) -> None:
        a, b = fake_stores(), fake_stores()
        a.events.append(S.EVENTS["claim"])
        assert b.events.read_from(0).items == []
