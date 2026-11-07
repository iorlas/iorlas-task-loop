"""Tracker ID syntax is interpreted only by the beads adapter."""


from taskloop.adapters.bdids import mentioned_ids, prefix_of
from tltestkit.case import Case


class TrackerIds(Case):
    def test_prefix_is_the_tracker_namespace(self):
        for task_id, expected in ((None, ""), ("", ""), ("opaque", "opaque"), ("team-abc.2.3", "team"),
                                  ("team-abc-extra", "team")):
            with self.subTest(task_id=task_id):
                assert prefix_of(task_id) == expected

    def test_mentions_keep_order_children_and_namespace(self):
        text = "team-abc.2.3, team-def and team-abc.2.3; other-xyz; longerteam-123; team-456"
        assert mentioned_ids("team-current", text) == ["team-abc.2.3", "team-def", "team-456"]

    def test_namespace_is_escaped_as_literal_text(self):
        assert mentioned_ids("a.b-current", "axb-123 a.b-456") == ["a.b-456"]
