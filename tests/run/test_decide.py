"""resume_decision is a pure table: a checkpoint and the world in, resume | amend | replan | fresh | land out."""
import dataclasses
import sys
import unittest
from pathlib import Path
from typing import Any, ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.run.decide import CONFIRMED, OUTSIDE, World, resume_decision
from taskloop.contracts.checkpoint import Checkpoint, RunState

PLAN = {"summary": "s", "stages": [{"goal": "a", "checks": []}, {"goal": "b", "checks": []}]}


def ck(step="write", stage=1, head="h1", closed=False, **state) -> Checkpoint:
    state.setdefault("plan_data", PLAN)
    state.setdefault("brief_hash", "b1")
    st = RunState()
    for k, v in state.items():
        setattr(st, k, v)
    return Checkpoint(
        bead="t-1", run="r", t=0.0, branch="task/t-1", head=head, closed=closed, step=step, stage=stage, rounds=2, n=3, state=st
    )


def world(**kw) -> World:
    return dataclasses.replace(World(branch="task/t-1", head="h1", brief_hash="b1"), **kw)


class Table(unittest.TestCase):
    CASES: ClassVar[Any] = [
        # name, checkpoint, world, kind, why
        ("no checkpoint", None, world(), "fresh", ""),
        ("--fresh", ck(), world(fresh=True), "fresh", ""),
        ("another branch", ck(), world(branch="task/other"), "fresh", ""),
        ("no plan yet", ck(plan_data=None), world(), "fresh", ""),
        ("mid stage", ck(), world(), "resume", ""),
        ("every stage accepted", ck(stage=2), world(), "land", ""),
        ("step land", ck(step="land", stage=1), world(), "land", ""),
        ("edited outside", ck(), world(head="h2"), "amend", OUTSIDE),
        ("one wip commit above, left dirty", ck(), world(head="h2", parent="h1", left_dirty=True), "resume", ""),
        ("one wip commit above a closed run", ck(closed=True), world(head="h2", parent="h1", left_dirty=True), "amend", OUTSIDE),
        ("gate red at land", ck(step="gate-red", stage=2), world(), "replan", ""),
        ("retry validation red", ck(step="land-verify-red", stage=2), world(), "replan", ""),
        (
            "bead changed",
            ck(),
            world(brief_hash="b2", brief_diff="description changed", brief_diff_quiet="description changed"),
            "amend",
            "",
        ),
        ("comment alone", ck(), world(brief_hash="b2", brief_diff="new comment", brief_diff_quiet=""), "resume", ""),
        ("hash moved, nothing read", ck(), world(brief_hash="b2", brief_diff=""), "resume", ""),
        (
            "answered, changed",
            ck(),
            world(answered=True, answer_given=True, answer_words="do x", brief_diff="d", brief_diff_quiet="d"),
            "amend",
            "",
        ),
        ("answered: run again", ck(), world(answered=True, answer_given=True, brief_diff="d", brief_diff_quiet="d"), "resume", ""),
        (
            "verify ask confirmed",
            ck(step="land", stage=2, brief_hash="b0"),
            world(answered=True, answer_given=True, answer_external_fact=True, answer_confirms=True),
            "land",
            CONFIRMED,
        ),
        (
            "verify ask, more than a yes",
            ck(step="land", stage=2, brief_hash="b0"),
            world(answered=True, answer_given=True, answer_external_fact=True, answer_words="add a test"),
            "amend",
            "",
        ),
        ("promised file gone", ck(), world(missing_stage=0), "resume", ""),
    ]

    def test_every_row(self):
        for name, checkpoint, w, kind, why in self.CASES:
            with self.subTest(name):
                d = resume_decision(checkpoint, w)
                self.assertEqual(d.kind, kind)
                if why:
                    self.assertEqual(d.why, why)

    def test_only_a_stale_or_foreign_checkpoint_is_dropped(self):
        drops = {n: resume_decision(c, w).drop for n, c, w, *_ in self.CASES}
        self.assertEqual({n for n, d in drops.items() if d}, {"--fresh", "another branch", "no plan yet"})

    def test_a_resume_keeps_the_stage_and_its_counters(self):
        d = resume_decision(ck(), world())
        self.assertEqual((d.stage, d.continues, d.redo_from), (1, True, None))

    def test_a_missing_file_sends_the_run_back_to_that_stage_without_counters(self):
        d = resume_decision(ck(), world(missing_stage=0))
        self.assertEqual((d.stage, d.continues, d.redo_from), (0, False, 0))

    def test_the_decision_reads_nothing_but_its_arguments(self):
        c, w = ck(), world(brief_hash="b2", brief_diff="x", brief_diff_quiet="x")
        before = (c.model_dump(), w)
        resume_decision(c, w)
        self.assertEqual((c.model_dump(), w), before)


if __name__ == "__main__":
    unittest.main()
