"""The land side of a run: the tree, the rebase and its salvage, the fixer, the lander, and the receipt a land leaves."""
from functools import cached_property
from pathlib import Path
from typing import override

from taskloop.app.wire import slotfx
from tlkernel.repourl import repo_url

from taskloop.adapters import landlock
from taskloop.app.land import cleanup
from taskloop.app.land.checkout import Checkout
from taskloop.app.land.fixer import Fixer
from taskloop.app.land.lander import lander_over
from taskloop.app.land.push import target
from taskloop.app.land.rebase import Rebase
from taskloop.app.land.restart import Restart
from taskloop.app.land.salvage import Salvage
from taskloop.app.land.tree import Tree
from taskloop.app.run.plumbing import Plumbing
from taskloop.app.track import verbs
from taskloop.app.write.newfiles import NewFiles


class LandParts(Plumbing):
    @cached_property
    def tree(self) -> Tree:
        return Tree(self, fx=slotfx.FX)
    rebase = cached_property(Rebase)
    restart = cached_property(Restart)
    fixer = cached_property(Fixer)
    lander = cached_property(lander_over)

    @cached_property
    @override
    def checkout(self) -> Checkout:
        return Checkout(self)

    @cached_property
    def salvage(self) -> Salvage:
        return Salvage(self, self.rebase)

    @cached_property
    def newfiles(self) -> NewFiles:
        return NewFiles(self, self.git)

    @property
    def tree_writer(self) -> Checkout:
        """The same checkout: app/checks gets the right to stage only through this name (tests/rules/test_tree_writer.py)."""
        return self.checkout

    def record_land(self, sha: str) -> None:
        if verbs.land(self.who, self.bead, sha, self.store, self.git, self.wt, base=self.cfg.base, claim=self.claim):
            raise self.blocked_for("land receipt refused; branch kept", "FAULT_LAND")
        branch = self.task_branch or self.git.branch(self.wt)
        repo = next((co.path for co in self.git.checkouts(self.wt) if co.main), self.wt)
        pr = self.cfg.land_mode == "pr"  # the PR's merge commit is not the branch tip, and the forge owns the remote branch
        want = None if pr else target(self.cfg.land)
        if branch:
            prior = cleanup.previous(self.home, self.bead, repo, branch, sha)
            cleanup.record(self.log, repo, branch, self.git.rev_parse(self.wt, "HEAD") if pr else sha, sha,
                           want[0] if want else "", self.land_state.remote_oid, prior)

    def land_lock_path(self) -> Path:
        return landlock.land_lock_path(self.home, repo_url(self.git, self.wt))

    def diff_text(self) -> str:
        tree = self.checkout.tree_hash()
        return self.git.diff(self.wt, self.checkout.base_sha(), tree) if tree else ""
