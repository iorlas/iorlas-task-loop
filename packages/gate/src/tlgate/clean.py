"""The land gate's check host: filesystem inputs come from a fresh checkout of the judged commit."""
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from tlkernel.checks import CheckFaultKind
from tlkernel.gitport import Git
from tlkernel.ids import TreeSha

from tlgate.base_tree import clean_tree
from tlgate.domain import inputs
from tlgate.host import CheckFault, CheckHost, CleanHost


class CleanCheckout:
    def __init__(self, git: Git, wt: Path, base: str) -> None:
        self.git, self.wt, self.base = git, str(wt), base

    def tree_hash(self) -> TreeSha:
        return TreeSha(self.git.tree_of(self.wt))

    def changed_paths(self) -> list[str]:
        start = self.git.merge_base(self.wt, "HEAD", self.base) or self.base
        return self.git.changed_paths(self.wt, start, self.tree_hash(), required=True)


def committed_head(host: CheckHost) -> str:
    """HEAD of the slot, when the slot's tree is exactly HEAD's tree (untracked, not ignored, files count); else the fault."""
    wt = str(host.wt)
    head = host.git.rev_parse(wt, "HEAD")
    tree = host.git.rev_parse(wt, "HEAD^{tree}")
    if not head or not tree or host.checkout.tree_hash() != tree:
        raise CheckFault(CheckFaultKind.DIRTY_SLOT, "gate requires a committed tree; commit the slot's changes before gating")
    return head


def guard_slot(host: CheckHost) -> None:
    """engine.gate_tree "slot": what a fresh checkout protected, as far as a guard can. The slot is committed, and no gitignored file
    that looks like source (engine.gate_source_globs, minus engine.gate_ignored_allow) is there for a check to read by accident. Stale
    build output is not claimed covered: the fresh-clone canary owns that residual risk."""
    committed_head(host)
    cfg = host.cfg
    stray = inputs.matching(host.git.ls_files(str(host.wt), "ignored"), cfg.gate_source_globs, cfg.gate_ignored_allow)
    if stray:
        shown = ", ".join(stray[:5]) + (f" and {len(stray) - 5} more" if len(stray) > 5 else "")
        raise CheckFault(CheckFaultKind.DIRTY_SLOT, f"gate.tree is slot, and the slot holds ignored source files a check could read: "
                         f"{shown}; delete them or list them in engine.gate_ignored_allow")


@contextmanager
def isolated(host: CheckHost) -> Generator[CleanHost]:
    wt = str(host.wt)
    head = committed_head(host)
    with clean_tree(host.git, wt, head) as dest:
        yield CleanHost(host, dest, CleanCheckout(host.git, dest, host.cfg.base))
