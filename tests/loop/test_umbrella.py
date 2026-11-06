"""Ready umbrellas must wait even when their children are absent from bd ready."""
import sys
from pathlib import Path
from unittest import mock

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.loop.queue import QueueRule, rank_ready
from taskloop.contracts.bead import BdError, Bead
from taskloop.contracts.beadsport import BdFailure, BeadQuery
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.ids import BeadId


def bead(name, status="open", parent="", issue_type="task"):
    return Bead(id=BeadId(name), title=name, status=status, parent=parent, issue_type=issue_type)


class Umbrella(Case):
    def test_every_unclosed_child_skips_its_parent_without_suppressing_leaves(self):
        parent, leaf = bead("t-1"), bead("t-2")
        for status in ("open", "in_progress", "blocked"):
            with self.subTest(status=status):
                child = bead("t-1.1", status, parent="t-1")
                rule = QueueRule(mock.Mock(), EngineConfig(), {}, lambda _: "")
                q = rule.rank([parent, leaf], "", [parent, leaf, child])
                assert [r.bead for r in q.ranked] == [leaf]
                assert [(s.bead, s.skip.kind, s.skip.why) for s in q.skipped] == [("t-1", "epic", "an umbrella: it has open children")]

    def test_closed_children_allow_the_parent_and_explicit_epics_still_skip(self):
        parent, epic = bead("t-1"), bead("t-2", issue_type="epic")
        child = bead("t-1.1", "closed", parent="t-1")
        rule = QueueRule(mock.Mock(), EngineConfig(), {}, lambda _: "")
        q = rule.rank([parent, epic], "", [parent, epic, child])
        assert [r.bead for r in q.ranked] == [parent]
        assert q.skipped[0].skip.why == "an epic"

    def test_queue_reads_child_parents_once_across_all_statuses_and_labels(self):
        parent = bead("t-1")
        env = mock.Mock()
        env.store.ready.return_value = [parent]
        env.store.find.return_value = [parent, bead("t-1.1", "blocked", parent="t-1")]
        env.running.return_value = {}
        env.now.return_value = 100
        q, _ = rank_ready(env, EngineConfig(), only=["t-1"])
        assert q.ranked == []
        assert q.skipped[0].skip.kind == "epic"
        env.store.find.assert_called_once_with(BeadQuery())

    def test_failed_child_read_does_not_offer_an_umbrella(self):
        env = mock.Mock()
        env.store.ready.return_value = [bead("t-1")]
        env.store.find.side_effect = BdFailure(BdError(kind="other", text="unavailable"))
        env.running.return_value = {}
        q, _ = rank_ready(env, EngineConfig(), only=["t-1"])
        assert q.ranked == []
