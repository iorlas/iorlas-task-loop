"""One rule for when a stuck episode ends: tlkernel.stuck, read by the engine's StuckWatch and by the dashboard's run fold."""
import pytest

from taskloop_dash.views import runfacts
from tlkernel import log as rec
from tlkernel.checks import CheckResult, CheckRun
from tlkernel.ids import CheckId
from tlkernel.runlife import SAME_RED, silent_limit
from tlkernel.stuck import open_episode, red_ends, silent_ends
from tlpipeline.stuck_rule import StuckWatch

T = 1_800_000_000.0
SILENT = rec.Stuck(t=T + 1, why="silent", step="write", since=T, limit_s=silent_limit("write"))


def round_of(n, sig="boom", red=True):
    res = CheckResult(id=CheckId("unit"), cmd="python3 -m unittest", group="tests", exit=1 if red else 0,
                      status="failed" if red else "passed", sig=sig)
    return rec.Checks(t=T + n, node_id=f"n{n}", run=CheckRun(round=n, results=[res]))


RED = rec.Stuck(t=T + 1, why="same_red", step="checks", since=T, sig=round_of(1).run.signature())


def test_a_beat_or_a_stuck_does_not_end_a_silent_episode_but_any_other_record_does():
    assert not silent_ends(rec.Beat(t=T + 2))
    assert not silent_ends(SILENT)
    assert silent_ends(rec.Note(t=T + 2, text="the worker answered"))


def test_a_red_episode_ends_on_a_green_round_or_another_signature_not_on_the_same_one():
    sig = RED.sig
    assert not red_ends(sig, round_of(2, "boom"))
    assert red_ends(sig, round_of(2, "other"))
    assert red_ends(sig, round_of(2, red=False))
    assert not red_ends(sig, rec.Note(t=T + 2, text="x"))


@pytest.mark.parametrize(("records", "open_why"), [
    ([SILENT], "silent"),
    ([SILENT, rec.Beat(t=T + 2)], "silent"),
    ([SILENT, rec.Note(t=T + 2, text="x")], None),
    ([RED, round_of(2, "boom")], "same_red"),
    ([RED, round_of(2, "other")], None),
    ([RED, round_of(2, red=False)], None),
    ([RED, rec.Note(t=T + 2, text="x")], "same_red"),
    ([SILENT, rec.Note(t=T + 2, text="x"), RED], "same_red"),
])
def test_the_open_episode_of_a_log(records, open_why):
    got = open_episode(records)
    assert (got.why if got else None) == open_why


def test_the_dashboard_has_no_stuck_rule_of_its_own():
    assert not hasattr(runfacts, "stuck_of")


def test_the_watch_and_the_fold_agree_on_when_an_episode_ends():
    w = StuckWatch()
    w.feed(rec.StepStart(t=T, id="n1", step="write"))
    said = w.tick(T + silent_limit("write"))
    assert [s.why for s in said] == ["silent"]
    log = [rec.StepStart(t=T, id="n1", step="write"), *said]
    assert open_episode(log) is not None and w.silent_said
    follow = rec.Note(t=T + silent_limit("write") + 1, text="the worker answered")
    w.feed(follow)
    assert open_episode([*log, follow]) is None and not w.silent_said
    for n in range(SAME_RED):
        w.feed(round_of(n + 1))
    assert [s.why for s in w.tick(T + 100)] == ["same_red"]
