"""Profile stamps follow Git metadata without starting Git, including linked worktrees."""

import tempfile
from pathlib import Path

from support.case import Case

from taskloop.app.doctor import profiles


class ProfileStamp(Case):
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / ".task-loop.json").write_text('{"engine":{"base":"main"}}')
        self.common = self.repo / ".git"
        self.common.mkdir()

    def test_loose_packed_worktree_and_profile_changes(self):
        ref = self.common / "refs" / "heads" / "main"
        ref.parent.mkdir(parents=True)
        ref.write_text("a" * 40 + "\n")
        before = profiles.stamp(self.repo)
        assert before is not None
        assert before == profiles.stamp(self.repo)
        ref.write_text("b" * 40 + "\n")
        assert before != profiles.stamp(self.repo)
        ref.unlink()
        packed = self.common / "packed-refs"
        packed.write_text("a" * 40 + " refs/heads/main\n")
        before = profiles.stamp(self.repo)
        packed.write_text("b" * 40 + " refs/heads/main\n")
        assert before != profiles.stamp(self.repo)
        worktree = self.root / "worktree"
        worktree.mkdir()
        (worktree / ".task-loop.json").write_text('{"engine":{"base":"main"}}')
        gitdir = self.common / "worktrees" / "w"
        gitdir.mkdir(parents=True)
        (gitdir / "commondir").write_text("../..\n")
        (worktree / ".git").write_text(f"gitdir: {gitdir}\n")
        before = profiles.stamp(worktree)
        assert before is not None
        packed.write_text("c" * 40 + " refs/heads/main\n")
        assert before != profiles.stamp(worktree)
        before = profiles.stamp(worktree)
        (worktree / ".task-loop.json").write_text('{"engine":{"base":"other"}}')
        assert before != profiles.stamp(worktree)

    def test_unsupported_backend_or_revision_has_no_stamp(self):
        (self.common / "reftable").mkdir()
        assert profiles.stamp(self.repo) is None
        (self.common / "reftable").rmdir()
        (self.repo / ".task-loop.json").write_text('{"engine":{"base":"main~1"}}')
        assert profiles.stamp(self.repo) is None

    def test_symbolic_base_tracks_its_loose_target(self):
        head = self.common / "HEAD"
        head.write_text("ref: refs/heads/main\n")
        ref = self.common / "refs" / "heads" / "main"
        ref.parent.mkdir(parents=True)
        ref.write_text("a" * 40 + "\n")
        (self.repo / ".task-loop.json").write_text('{"engine":{"base":"HEAD"}}')
        before = profiles.stamp(self.repo)
        ref.write_text("b" * 40 + "\n")
        assert before != profiles.stamp(self.repo)
        alias = self.common / "refs" / "heads" / "alias"
        alias.write_text("ref: refs/heads/main\n")
        (self.repo / ".task-loop.json").write_text('{"engine":{"base":"alias"}}')
        before = profiles.stamp(self.repo)
        ref.write_text("c" * 40 + "\n")
        assert before != profiles.stamp(self.repo)
