"""Linked briefs treat IDs as opaque and ask the tracker reader to find prose references."""
from unittest import mock

import support.paths  # noqa: F401
from support.case import Case

from taskloop.domain.plan.brief import linked
from tlkernel.bead import Bead
from tlkernel.ids import BeadId


class LinkedIds(Case):
    def test_opaque_id_and_parent_are_passed_whole(self):
        task_id = BeadId("opaque-with-dashes.and.dots")
        parent = BeadId("unrelated-parent.namespace")
        named_id = BeadId("different-reference.namespace")
        bead = Bead(id=task_id, title="Use the decision", status="open", parent=parent)
        records = {i: Bead(id=i, title=i, status="open") for i in (parent, named_id)}
        mentions = mock.Mock(return_value=[named_id])
        show = mock.Mock(side_effect=records.get)
        text = linked(task_id, bead, [], "Denis Tomilin", show, lambda _: [], mentions)
        mentions.assert_called_once()
        assert mentions.call_args.args[0] == task_id
        assert "Use the decision" in mentions.call_args.args[1]
        assert show.call_args_list == [mock.call(parent), mock.call(named_id)]
        assert parent in text
        assert named_id in text
