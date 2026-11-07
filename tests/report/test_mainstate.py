"""The scorecard's state of main: red when a revert landed on the base since the window began; the strip shows it."""

from pathlib import Path

import pytest

from taskloop.app.report.card import score_of
from taskloop.app.report.mainstate import main_state
from tlkernel.gitfacts import LogRow
from tlkernel.slots import SlotGitError
from tlkernel.snapshots import ReleaseResult

T = 1793000000.0
CARD = {"since": T, "until": T + 600, "beads": 1, "landed": 1, "landed_no_ask": 1, "asks": {"count": 0}, "lost": 0, "crashes": 0,
        "m2": {"pass": True}}


class FakeGit:
    def __init__(self, rows: list[LogRow] | None) -> None:
        self.rows = rows

    def log(self, d: str, include: list[str], exclude: list[str] | None = None, limit: int = 0, grep: str = "") -> list[LogRow]:
        if self.rows is None:
            raise SlotGitError("no base")
        return self.rows


@pytest.mark.parametrize(("rows", "red"), [
    ([], False),
    ([LogRow(oid="a" * 40, time=int(T) - 5, subject='Revert "x"')], False),  # before the window
    ([LogRow(oid="b" * 40, time=int(T) + 5, subject='Revert "x"')], True),
    ([LogRow(oid="c" * 40, time=int(T) + 5, subject="Say Revert in passing")], False),
    (None, False),  # git cannot answer: nothing is known
])
def test_main_is_red_only_for_a_revert_inside_the_window(rows: list[LogRow] | None, red: bool) -> None:
    got = main_state(FakeGit(rows), "/r", "main", T)
    assert got["red"] is red
    assert bool(got["reverts"]) is red


@pytest.mark.parametrize("red", [False, True])
def test_the_strip_numbers_carry_mains_state(red: bool) -> None:
    assert score_of({**CARD, "main": {"red": red}}).main_red is red


def test_a_card_without_main_is_green() -> None:
    assert score_of(CARD).main_red is False


def test_the_strip_paints_main_red_as_a_red_banner() -> None:
    js = (Path(__file__).resolve().parents[2] / "packages" / "dash" / "src" / "tldash" / "static" / "js" / "app.js").read_text()
    assert "s.lost || s.crashes || s.main_red ? 'ban bad'" in js


def release(ok: bool = False, branch: str = "main", repo: str = "/r") -> ReleaseResult:
    return ReleaseResult(ok=ok, version="1", summary="x", at=T, branch=branch, repo=repo)


@pytest.mark.parametrize(("last", "red"), [
    (None, False),
    (release(ok=True), False),  # a later success clears a failure
    (release(), True),
    (release(branch="claude/x"), False),  # a failed branch says nothing of main
    (release(repo="/other"), False),  # another repo's release
    (release(repo=""), False),  # a row from before the field
])
def test_main_is_red_when_the_last_release_gate_on_main_failed(last: ReleaseResult | None, red: bool) -> None:
    got = main_state(FakeGit([]), "/r", "main", T, last)
    assert (got["red"], got["gate_red"]) == (red, red)


def test_the_strip_numbers_carry_retries_and_the_stored_outcome_kinds() -> None:
    got = score_of({**CARD, "runs": 4, "kinds": {"landed": 1, "ask_decision": 2, "fault_plan": 1}})
    assert (got.retries, got.kinds) == (3, {"landed": 1, "ask_decision": 2, "fault_plan": 1})
    assert score_of(CARD).kinds == {} and score_of(CARD).retries == 0
