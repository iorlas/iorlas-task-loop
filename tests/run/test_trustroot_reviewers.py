"""No secondary reviewer loads unapproved worktree trust roots."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from support.engine_case import EngineTest
from support.plans import BEAD, CLEAN, PLAN, WRITE

from taskloop.adapters import childenv
from taskloop.app.asks.admission import _blocked_by_engine
from taskloop.app.asks.closing import ClosingTrust
from taskloop.app.pipeline.blocked import Blocked, blocked_for
from taskloop.app.pipeline.reflect import Reflector
from taskloop.app.workers.worker_request import request
from tlkernel.bead import Bead, Comment
from tlkernel.gitfacts import DiffEntry
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.paths import ConfigDir
from tltestkit.case import Case


class ReviewerTrustRoots(Case):
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
                with pytest.raises(Blocked) as caught:
                    request(self.host(), Mock(role="reviewer", node=node), "", 0, 0)
                assert caught.value.kind == Kind.ASK_DECISION

    def test_reflection_is_omitted_when_trust_roots_are_unapproved(self):
        host = self.host()
        host.cfg.reflect = True
        host.dry, host.stop_pending, host.route = False, False, "/fake/route.py"
        host.sessions = [{"node": "write"}]
        reflector = Reflector(host, host, host, ClosingTrust(), childenv.delegate_call_env)
        reflector.reflect_prompt = Mock(side_effect=AssertionError("must not build a reviewer prompt"))
        assert reflector.reflect_run("parked", "trust roots changed") is None
        reflector.reflect_prompt.assert_not_called()
        assert "owner-approved" in host.warn.call_args.args[0]


class AdmissionAuthors(Case):
    def test_only_the_owner_can_leave_a_parking_instruction_after_an_engine_block(self):
        bead = Bead(id=BeadId("t-1"), title="Change", status="blocked")
        block = Comment(author="tl-engine", text="Blocked: failed", created_at="1")
        for author, expected in (("owner", True), ("writer", False), ("", False), ("tl-writer", False)):
            with self.subTest(author=author):
                note = Comment(author=author, text="Blocked: leave it parked", created_at="2")
                store = Mock()
                store.comments.return_value = [block, note]
                with patch("taskloop.app.asks.admission.real_stores") as stores:
                    stores.return_value.asks.get.return_value = None
                    why = _blocked_by_engine(bead, store, ConfigDir("/unused"), "owner")
                assert bool(why) == expected


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
        assert rc == 2
        assert [call[0] for call in script.calls] == ["planner", "worker"]
        assert ".claude/settings.json" in self.ask()["why"]
        assert "owner-approved" in self.ask()["why"]
        assert any("trust roots changed" in why for why in self.blocked)

    def test_owner_approved_changes_continue_through_review_and_land(self):
        with self.store.stub(show=dict(BEAD, labels=["owner-approved"])):
            rc, script = self.run_engine({"plan": [self.trust_plan()], "write": [self.write_trustroot], "review": [CLEAN]})
        assert rc == 0, self.blocked
        assert [call[0] for call in script.calls] == ["planner", "worker", "reviewer"]
        assert self.eng.landed_sha
