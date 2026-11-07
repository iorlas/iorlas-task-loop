"""The classification of a bead-branch commit (domain/reconcile/lost.py), one table row per class and per rule that decides it."""
from dataclasses import replace
from typing import Any

from taskloop.domain.reconcile.diff import findings
from taskloop.domain.reconcile.facts import Observed
from taskloop.domain.reconcile.lost import (
    LANDED,
    LOST,
    PENDING,
    RECLAIMED,
    SUPERSEDED,
    UNKNOWN,
    UNKNOWN_STATE,
    BranchCommit,
)
from tltestkit.case import Case

BASE = BranchCommit(branch="task/t-1", bead="t-1", sha="abc", time=100, subject="work", base="main")


def commit(**kw: Any) -> BranchCommit:
    return replace(BASE, **kw)


ROWS = [
    ("its patch is on the base", commit(patch_on_base=True, state="closed"), LANDED, "its patch is on main"),
    ("a land of the bead came after it", commit(lands=(150.0,), state="closed"), LANDED, "t-1 landed on main after it"),
    ("a land before the commit does not count", commit(lands=(50.0,), state="closed"), LOST, "t-1 is closed and never landed this commit"),
    ("set aside by --fresh", commit(branch="task/t-1-stale-2026", aside=True, state="open"), SUPERSEDED, "--fresh set"),
    ("a dead session's wip branch", commit(branch="wip/s1", bead=None), LOST, "a dead session's work on wip/s1"),
    ("a closed bead that never landed it", commit(state="closed"), LOST, "t-1 is closed and never landed this commit"),
    ("a bead the tracker lacks", commit(state=None), LOST, "no bead t-1 in the tracker"),
    ("a later run took it up", commit(state="in_progress", runs=((90.0, "r0"), (120.0, "r1"))), RECLAIMED, "run r1 took it up"),
    ("only an earlier run exists", commit(state="open", runs=((90.0, "r0"),)), PENDING, "t-1 is open: its next run continues the branch"),
    ("an open bead with no run", commit(state="blocked"), PENDING, "t-1 is blocked"),
    ("bd failed", commit(state=UNKNOWN_STATE), UNKNOWN, "tracker is unreachable"),
]


class Classify(Case):
    def test_every_row_of_the_table(self) -> None:
        for name, c, cls, why in ROWS:
            with self.subTest(name):
                [f] = findings(Observed(now=0.0, keep_days=0.0, commits=(c,)))
                assert f.cls == cls
                assert why in f.why

    def test_every_class_has_a_row(self) -> None:
        assert {r[2] for r in ROWS} == {LANDED, SUPERSEDED, RECLAIMED, PENDING, UNKNOWN, LOST}

    def test_findings_keep_the_order_seen(self) -> None:
        cs = tuple(commit(sha=str(i)) for i in range(3))
        assert [f.commit.sha for f in findings(Observed(now=0.0, keep_days=0.0, commits=cs))] == ["0", "1", "2"]
