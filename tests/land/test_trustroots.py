"""Trust-root refusal runs before the land's commit, fetch, gate, or push."""
from unittest.mock import Mock

import pytest
from support.case import Case

from taskloop.app.land.lander import Lander
from taskloop.app.run.blocked import Blocked, blocked_for
from taskloop.contracts.bead import Bead
from taskloop.contracts.gitfacts import DiffEntry
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind


class LandTrustRoots(Case):
    def test_land_is_parked_before_commit_fetch_gate_or_push(self):
        host = Mock(wt="/work", bead=BeadId("t-1"), blocked_for=blocked_for)
        host.git.diff_entries.return_value = [DiffEntry(status="M", path="mise.toml")]
        bead = Bead(id=host.bead, title="t", status="open")
        host.store.show.return_value = bead
        parts = Mock()
        with pytest.raises(Blocked) as caught:
            Lander(host, parts).finish(bead)
        assert caught.value.kind == Kind.ASK_DECISION
        assert "mise.toml" in caught.value.why
        assert parts.mock_calls == []
