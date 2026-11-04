"""Trust-root refusal runs before the land's commit, fetch, gate, or push."""
import unittest
from unittest.mock import Mock

from taskloop.app.land.lander import Lander
from taskloop.app.run.blocked import Blocked, blocked_for
from taskloop.contracts.bead import Bead
from taskloop.contracts.gitfacts import DiffEntry
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind


class LandTrustRoots(unittest.TestCase):
    def test_land_is_parked_before_commit_fetch_gate_or_push(self):
        host = Mock(wt="/work", bead=BeadId("t-1"), blocked_for=blocked_for)
        host.git.diff_entries.return_value = [DiffEntry(status="M", path="mise.toml")]
        bead = Bead(id=host.bead, title="t", status="open")
        host.store.show.return_value = bead
        parts = Mock()
        with self.assertRaises(Blocked) as caught:
            Lander(host, parts).finish(bead)
        self.assertEqual(caught.exception.kind, Kind.ASK_DECISION)
        self.assertIn("mise.toml", caught.exception.why)
        self.assertEqual(parts.mock_calls, [])
