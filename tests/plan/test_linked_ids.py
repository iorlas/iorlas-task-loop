"""Linked briefs treat IDs as opaque and ask the tracker reader to find prose references."""
import unittest
from unittest import mock

import support.paths  # noqa: F401

from taskloop.contracts.bead import Bead
from taskloop.contracts.ids import BeadId
from taskloop.domain.plan.brief import linked


class LinkedIds(unittest.TestCase):
    def test_opaque_id_and_parent_are_passed_whole(self):
        task_id = BeadId("opaque-with-dashes.and.dots")
        parent = BeadId("unrelated-parent.namespace")
        named_id = BeadId("different-reference.namespace")
        bead = Bead(id=task_id, title="Use the decision", status="open", parent=parent)
        records = {i: Bead(id=i, title=i, status="open") for i in (parent, named_id)}
        mentions = mock.Mock(return_value=[named_id])
        show = mock.Mock(side_effect=records.get)
        text = linked(task_id, bead, [], lambda _: False, show, lambda _: [], mentions)
        mentions.assert_called_once()
        self.assertEqual(mentions.call_args.args[0], task_id)
        self.assertIn("Use the decision", mentions.call_args.args[1])
        self.assertEqual(show.call_args_list, [mock.call(parent), mock.call(named_id)])
        self.assertIn(parent, text)
        self.assertIn(named_id, text)
