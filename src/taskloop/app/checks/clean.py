"""The land gate's check host: filesystem inputs come from a fresh checkout of the judged commit."""
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from taskloop.adapters.base_tree import clean_tree
from taskloop.app.checks.host import CheckFault, CheckHost, CleanHost
from taskloop.contracts.checks import CheckFaultKind
from taskloop.contracts.ids import TreeSha
from taskloop.contracts.ports import Git


class CleanCheckout:
    def __init__(self, git: Git, wt: Path, base: str) -> None:
        self.git, self.wt, self.base = git, str(wt), base

    def tree_hash(self) -> TreeSha:
        return TreeSha(self.git.tree_of(self.wt))

    def changed_paths(self) -> list[str]:
        start = self.git.merge_base(self.wt, "HEAD", self.base) or self.base
        return self.git.changed_paths(self.wt, start, self.tree_hash(), required=True)


@contextmanager
def isolated(host: CheckHost) -> Generator[CleanHost]:
    wt = str(host.wt)
    head = host.git.rev_parse(wt, "HEAD")
    tree = host.git.rev_parse(wt, "HEAD^{tree}")
    if not head or not tree or host.checkout.tree_hash() != tree:
        raise CheckFault(CheckFaultKind.DIRTY_SLOT, "gate requires a committed tree; commit the slot's changes before gating")
    with clean_tree(host.git, wt, head) as dest:
        yield CleanHost(host, dest, CleanCheckout(host.git, dest, host.cfg.base))
