"""A skipped review cannot accept an unapproved trust-root change."""
from unittest.mock import Mock

import pytest
from support.case import Case

from taskloop.app.pipeline.blocked import Blocked, blocked_for
from taskloop.app.write.review_round import ReviewRound
from taskloop.app.write.state import RoundStop
from taskloop.contracts.bead import Bead
from taskloop.contracts.gitfacts import DiffEntry
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind


class ReviewTrustRoots(Case):
    def test_review_is_parked_before_review_off_or_mechanical_skip(self):
        host = Mock(wt="/work", bead=BeadId("t-1"), blocked_for=blocked_for)
        host.git.diff_entries.return_value = [DiffEntry(status="M", path="AGENTS.md")]
        host.store.show.return_value = Bead(id=host.bead, title="t", status="open")
        review = ReviewRound(host)
        review.switched_off = Mock(return_value=True)
        with pytest.raises(RoundStop) as caught:
            review.run(Mock())
        blocked = caught.value.cause
        assert isinstance(blocked, Blocked)
        assert blocked.kind == Kind.ASK_DECISION
        assert blocked.spec is not None
        review.switched_off.assert_not_called()
