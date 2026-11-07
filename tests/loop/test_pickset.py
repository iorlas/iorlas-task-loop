"""tl-9un.50 PICKSET: a queue (label `queue`, order `queue_at`) or `--only` limits the loop's pick; `tl next` says why a bead is skipped;
the dashboard strip reads the same rows; with nothing chosen today's rules apply."""
from unittest import mock

from tldash.testing import T
from tltestkit.case import Case

# isort: split
from taskloop.app.loop.queue import QueueRule
from taskloop.cli import queue as cli_queue
from tldash.views import snapshot
from tldash.views.world import ProjectIn, World
from tlkernel import pickset
from tlkernel.bead import Bead
from tlkernel.config import EngineConfig
from tlkernel.ids import BeadId
from tlkernel.loop import LoopState, QueueRow


def bead(i, queued=0, prio=2, status="open", assignee=""):
    return Bead(id=BeadId(i), title=f"title {i}", status=status, priority=prio, assignee=assignee, acceptance_criteria="- ok",
                labels=[pickset.LABEL] if queued else [], metadata={pickset.AT: str(queued)} if queued else {})


def rank(ready, all_beads, only=()):
    store = mock.Mock()
    store.show.side_effect = lambda i: next((b for b in all_beads if b.id == i), None)
    rule = QueueRule(store, EngineConfig(), {}, lambda _b: "")
    rule.chosen, rule.only = pickset.members(all_beads, only), bool(only)
    return rule.rank(ready, "/r")


class Pick(Case):
    beads = (bead("t-1", prio=0), bead("t-2", queued=20, prio=3), bead("t-3", queued=10, prio=3), bead("t-4", queued=30, status="blocked"))

    def test_only_queued_beads_are_taken_in_the_order_they_were_queued_not_by_priority(self):
        q = rank(self.beads[:3], self.beads)
        assert [r.bead.id for r in q.ranked] == ["t-3", "t-2"]
        assert q.ranked[0].reason == "1st of 3 chosen"

    def test_a_bead_outside_the_queue_and_a_queued_bead_that_is_not_ready_each_say_why(self):
        q = rank(self.beads[:3], self.beads)
        why = {str(s.bead): s.skip.why for s in q.skipped}
        assert "not in the queue" in why["t-1"]
        assert "queued but not ready" in why["t-4"]
        assert all(s.skip.kind == "queue" for s in q.skipped)

    def test_removing_the_last_queued_bead_restores_the_ordinary_rules(self):
        plain = [bead("t-1", prio=0), bead("t-2", prio=3)]
        q = rank(plain, plain)
        assert ([r.bead.id for r in q.ranked], q.skipped) == (["t-1", "t-2"], [])

    def test_a_closed_queued_bead_no_longer_limits_the_pick(self):
        done = [bead("t-1"), bead("t-2", queued=5, status="closed")]
        assert [r.bead.id for r in rank(done[:1], done).ranked] == ["t-1"]

    def test_only_needs_no_labels_and_wins_over_them(self):
        q = rank(self.beads[:3], self.beads, only=["t-1", "t-2"])
        assert [r.bead.id for r in q.ranked] == ["t-1", "t-2"]
        assert "not in --only" in q.skipped[0].skip.why


class Verb(Case):
    def test_add_labels_in_the_order_given_and_remove_clears_label_and_order(self):
        store, out = mock.Mock(), []
        store.show.return_value = bead("t-1")
        store.find.return_value = []
        assert cli_queue.cmd_queue("add", ["t-2", "t-1"], store, lambda: 100.0, out.append) == 0
        assert [c.args[0] for c in store.add_label.call_args_list] == ["t-2", "t-1"]
        stamps = [c.args[1].set_metadata[pickset.AT] for c in store.update.call_args_list]
        assert stamps == ["100000", "100001"]
        cli_queue.cmd_queue("remove", ["t-2"], store, lambda: 1.0, out.append)
        store.remove_label.assert_called_once_with("t-2", pickset.LABEL)
        assert "queue empty" in out[-1]


class Strip(Case):
    def test_the_dashboard_strip_shows_the_rows_the_loop_ranks_for_tl_next(self):
        all_beads = [bead("t-1"), bead("t-2", queued=20), bead("t-3", queued=10), bead("t-4", queued=30, status="blocked")]
        q = rank(all_beads[:3], all_beads)
        now = T + 100
        rows = [QueueRow(bead=r.bead.id, prio=2, since=now, ahead=i, reason=r.reason) for i, r in enumerate(q.ranked)]
        rows += [QueueRow(bead=s.bead, prio=2, since=now, ahead=-1, skip=s.skip) for s in q.skipped]
        st = LoopState(pid=7, started=now - 99, t=now - 5, repo="/r", version="0", code_dir="/c", actor="tl", queue=rows)
        p = ProjectIn(id="p", name="p", beads=all_beads, loops=[st])
        snap = snapshot.build(World(now=now, host="h", version="v", projects=[p], runs={}, asks={}))
        got = [(x.bead, x.state, x.why) for x in snap.queue]
        want = [("t-3", "next", q.ranked[0].reason), ("t-2", "then", q.ranked[1].reason),
                ("t-4", "skipped", q.skipped[-1].skip.why)]
        assert got == want
