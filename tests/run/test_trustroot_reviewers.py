"""No secondary reviewer loads unapproved worktree trust roots."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from support.engine_case import BEAD, CLEAN, PLAN, WRITE, EngineTest

from taskloop.app.run.blocked import Blocked, blocked_for
from taskloop.app.run.entry import _blocked_by_engine
from taskloop.app.run.reflect import Reflector
from taskloop.app.run.worker_request import request
from taskloop.contracts.bead import Bead, Comment
from taskloop.contracts.gitfacts import DiffEntry
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.contracts.paths import ConfigDir


class ReviewerTrustRoots(unittest.TestCase):
    def host(self):
        git = Mock()
        git.merge_base.return_value = "fork"
        git.tree_of.return_value = "candidate"
        git.diff_entries.return_value = [DiffEntry(status="M", path="CLAUDE.md")]
        bead = Bead(id=BeadId("t-1"), title="Change", status="open")
        return Mock(git=git, wt="/work", cfg=SimpleNamespace(base="origin/main"), bead=bead.id,
                    store=SimpleNamespace(show=lambda _: bead), blocked_for=blocked_for)

    def test_all_reviewers_park_before_dispatch(self):
        for node in ("review", "verify", "look"):
            with self.subTest(node=node):
                with self.assertRaises(Blocked) as caught:
                    request(self.host(), Mock(role="reviewer", node=node), "", 0, 0)
                self.assertEqual(caught.exception.kind, Kind.ASK_DECISION)

    def test_reflection_is_omitted_when_trust_roots_are_unapproved(self):
        host = self.host()
        host.cfg.reflect = True
        host.dry, host.stop_pending, host.route = False, False, "/fake/route.py"
        host.sessions = [{"node": "write"}]
        reflector = Reflector(host)
        reflector.reflect_prompt = Mock(side_effect=AssertionError("must not build a reviewer prompt"))
        self.assertIsNone(reflector.reflect_run("parked", "trust roots changed"))
        reflector.reflect_prompt.assert_not_called()
        self.assertIn("owner-approved", host.warn.call_args.args[0])


class AdmissionAuthors(unittest.TestCase):
    def test_only_the_owner_can_leave_a_parking_instruction_after_an_engine_block(self):
        bead = Bead(id=BeadId("t-1"), title="Change", status="blocked")
        block = Comment(author="tl-engine", text="Blocked: failed", created_at="1")
        for author, expected in (("owner", True), ("writer", False), ("", False), ("tl-writer", False)):
            with self.subTest(author=author):
                note = Comment(author=author, text="Blocked: leave it parked", created_at="2")
                store = Mock()
                store.comments.return_value = [block, note]
                with patch("taskloop.app.run.entry.AskStore.at") as asks:
                    asks.return_value.get.return_value = None
                    why = _blocked_by_engine(bead, store, ConfigDir("/unused"), "owner")
                self.assertEqual(bool(why), expected)


class TrustRootParking(EngineTest):
    def write_trustroot(self, _script, _node, cwd, _resume):
        root = Path(cwd) / ".claude"
        root.mkdir(exist_ok=True)
        (root / "settings.json").write_text("{}\n")
        return WRITE

    def trust_plan(self):
        stage = dict(PLAN["stages"][0], files=["f.txt", ".claude/settings.json"])
        return dict(PLAN, stages=[stage])

    def test_an_unapproved_writer_change_parks_the_bead_without_review_or_reflection(self):
        rc, script = self.run_engine({"plan": [self.trust_plan()], "write": [self.write_trustroot]}, reflect=True)
        self.assertEqual(rc, 2)
        self.assertEqual([call[0] for call in script.calls], ["planner", "worker"])
        self.assertIn(".claude/settings.json", self.ask()["why"])
        self.assertIn("owner-approved", self.ask()["why"])
        self.assertTrue(any("trust roots changed" in why for why in self.blocked))

    def test_owner_approved_changes_continue_through_review_and_land(self):
        with self.store.stub(show=dict(BEAD, labels=["owner-approved"])):
            rc, script = self.run_engine({"plan": [self.trust_plan()], "write": [self.write_trustroot], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([call[0] for call in script.calls], ["planner", "worker", "reviewer"])
        self.assertTrue(self.eng.landed_sha)
