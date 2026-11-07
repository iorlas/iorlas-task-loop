"""Resume restores checkpoint state through capabilities supplied by the root."""
from types import SimpleNamespace

import pytest
from support.pipeline_ports import FakeHeadHistory, FakeNarrate, FakeReviewRestore

from taskloop.app.pipeline.decide import Decision
from taskloop.app.pipeline.resume import GATE_NOTE, KEEP_FOR_ACTIVE, LATE, Resume
from tlkernel import wire
from tlkernel.checkpoint import Checkpoint, RunState


def checkpoint(**kw) -> Checkpoint:
    return Checkpoint(bead="t-1", run="old", t=0.0, branch="task/t-1", head="abcdef0123456789", **kw)


def test_outside_text_asks_history_and_clips():
    history = FakeHeadHistory("x" * 801)
    resume = Resume(SimpleNamespace(wt="tree"), history, FakeReviewRestore(), ())
    text = resume.outside_text(checkpoint())
    assert history.calls == [("tree", "abcdef0123456789", 15)]
    assert "x" * 800 in text and "x" * 801 not in text
    history.result = ""
    assert "(none)" in resume.outside_text(checkpoint())


@pytest.mark.parametrize("late", [False, True])
def test_restore_copies_only_selected_state_and_restores_review(late):
    names = tuple(wire.names(RunState))
    saved = RunState(done=["accepted"], extra=3, planner_ref="old", fixes=2, planned=4)
    state = RunState(extra=5, planner_ref="new")
    pending = []
    host = SimpleNamespace(state=state, extra=state.extra, planner_ref=state.planner_ref,
                           checkpoints=SimpleNamespace(keep_pending=lambda: pending.append(True)))
    review = FakeReviewRestore()
    Resume(host, FakeHeadHistory(), review, names).restore(checkpoint(state=saved), late=late)
    for name in names:
        expected = getattr(saved if name not in KEEP_FOR_ACTIVE and (late or name not in LATE) else RunState(), name)
        if name not in ("extra", "planner_ref"):
            assert getattr(state, name) == expected
    assert (host.extra, host.planner_ref) == (8, "old")
    assert review.calls == [(saved.review, False, late)]
    assert pending == [True]
    assert state.done is not saved.done


def test_replan_note_writes_gate_output_and_marks_first(workdir):
    host = SimpleNamespace(run_dir=workdir, log=FakeNarrate(), done=["stage"], replan_first=False)
    Resume(host, FakeHeadHistory(), FakeReviewRestore(), ()).replan_note(checkpoint(step="gate-red", gate_tail="failure"))
    assert (workdir / "replan.md").read_text() == GATE_NOTE + "failure"
    assert host.replan_first


def test_amend_keeps_verify_answer_for_planning():
    host = SimpleNamespace(log=FakeNarrate(), answered=None, done=["stage"])
    plan = {"summary": "saved"}
    result = Resume(host, FakeHeadHistory(), FakeReviewRestore(), ()).amend(
        checkpoint(state=RunState(plan_data=plan)), Decision(kind="amend", verify_answer="owner asks for a fix"))
    assert result == (None, 0, None)
    assert (host.plan_data, host.plan_summary, host.verify_answer) == (plan, "saved", "owner asks for a fix")
