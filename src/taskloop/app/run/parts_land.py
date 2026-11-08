"""The land side of a run: the tree, the rebase and its salvage, the fixer, the lander, and the receipt a land leaves."""
from functools import cached_property, partial
from pathlib import Path
from typing import override

from tlkernel.checks import CheckRun
from tlkernel.repourl import repo_url
from tlkernel.storeapi import Doc
from tlland import cleanup
from tlland.checkout import Checkout
from tlland.fix import Fixer
from tlland.lander import Lander, lander_over
from tlland.lander_host import LanderHost
from tlland.push import target
from tlland.rebase import Rebase
from tlland.record import Restart, Salvage
from tlland.tree import Tree, TreeHost
from tlwork.api import NewFiles

from taskloop.adapters import landlock
from taskloop.adapters.deadline import deadline
from taskloop.adapters.ignored import ignored_by
from taskloop.app.run.plumbing import Plumbing
from taskloop.app.track import verbs
from taskloop.app.wire import slotfx


def tree_over(host: TreeHost) -> Tree:
    return Tree(host, fx=slotfx.FX)


def lander_bound(host: LanderHost) -> Lander:
    return lander_over(host, deadline=deadline)


class LandParts(Plumbing):
    @property
    def latest_check(self) -> Doc[CheckRun]:
        return self.stores.check_run(self.run_dir.name, None)

    tree = cached_property(tree_over)
    rebase = cached_property(Rebase)
    restart = cached_property(Restart)
    fixer = cached_property(Fixer)

    lander = cached_property(lander_bound)

    @cached_property
    @override
    def checkout(self) -> Checkout:
        return Checkout(self, ignore_rules=partial(ignored_by, self.git, self.wt))

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
            prior = cleanup.previous(self.home, self.bead, repo, branch, sha, self.stores.run_log)
            cleanup.record(self.log, repo, branch, self.git.rev_parse(self.wt, "HEAD") if pr else sha, sha,
                           want[0] if want else "", self.land_state.remote_oid, prior)

    def land_lock_path(self) -> Path:
        return landlock.land_lock_path(self.home, repo_url(self.git, self.wt))

    def diff_text(self) -> str:
        tree = self.checkout.tree_hash()
        return self.git.diff(self.wt, self.checkout.base_sha(), tree) if tree else ""
