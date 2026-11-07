"""Protected changes stop before review or land, including changes hidden by renames."""
from unittest.mock import Mock

import pytest

from tlkernel import trustroots
from tlkernel.bead import Bead
from tlkernel.gitfacts import DiffEntry
from tlkernel.ids import BeadId
from tltestkit.case import Case


class TrustRoots(Case):
    def setup_method(self):
        self.bead = Bead(id=BeadId("t-1"), title="Change", status="open")
        self.git = Mock()
        self.git.merge_base.return_value = "fork"
        self.git.tree_of.return_value = "candidate"
        self.git.diff_entries.return_value = []

    def refusal(self):
        return trustroots.refusal(self.git, "/work", "origin/main", self.bead)

    def test_all_protected_paths_require_owner_approval(self):
        for path in ("AGENTS.md", "CLAUDE.md", ".claude/settings.json", ".claude/hooks/a",
                     "mise.toml", ".codex/config.toml", ".task-loop.json", "githooks/pre-push"):
            for status in ("A", "M", "D", "T"):
                with self.subTest(path=path, status=status):
                    self.git.diff_entries.return_value = [DiffEntry(status=status, path=path)]
                    assert path in self.refusal()
                    assert "owner-approved" in self.refusal()

    def test_rename_into_or_out_of_a_protected_path_is_refused(self):
        for old, path in (("AGENTS.md", "ordinary.md"), ("ordinary.md", ".codex/rules")):
            self.git.diff_entries.return_value = [DiffEntry(status="R", old=old, path=path)]
            assert self.refusal()

    def test_unrelated_paths_are_allowed_and_the_whole_candidate_uses_the_merge_base(self):
        self.git.diff_entries.return_value = [DiffEntry(status="M", path="src/a.py"),
                                               DiffEntry(status="A", path="githooks-example/a")]
        assert self.refusal() == ""
        self.git.merge_base.assert_called_with("/work", "origin/main", "HEAD")
        self.git.tree_of.assert_called_with("/work")
        self.git.diff_entries.assert_called_with("/work", "fork", "candidate", required=True)

    def test_only_the_exact_owner_label_authorizes_the_change(self):
        self.git.diff_entries.return_value = [DiffEntry(status="M", path="CLAUDE.md")]
        self.bead.labels[:] = ["owner-approved-ish"]
        assert self.refusal()
        self.bead.labels[:] = ["owner-approved"]
        assert self.refusal() == ""

    def test_unreadable_diff_or_missing_bead_never_authorizes_review(self):
        self.git.diff_entries.side_effect = ValueError("unreadable diff")
        with pytest.raises(ValueError, match="unreadable diff"):
            self.refusal()
        assert trustroots.refusal(self.git, "/work", "origin/main", None)
