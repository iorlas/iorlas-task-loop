"""The observed world of the merge queue (what the reconcile of queue_reconcile.py is given): its refs, scratch worktrees and PR states,
read through the git port. Shared by the land stage's recovery and `tl doctor`'s read-only report."""
from collections.abc import Mapping, Sequence
from pathlib import Path

from taskloop.domain.land.queue_model import Entry, Phase
from taskloop.domain.land.queue_reconcile import PREFIX, BuildFact, Facts, PrFact
from tlkernel.gitport import Git


def world(git: Git, repo: str, main_ref: str, entries: Sequence[Entry],
          builds: Mapping[str, BuildFact], prs: Mapping[str, PrFact], now: float) -> Facts:
    """Observe queue resources through ports, without owning any stored process."""
    return Facts(
        refs=frozenset(ref.name for ref in git.for_each_ref(repo, PREFIX)),
        worktrees=frozenset(tree.path for tree in git.checkouts(repo)
                            if Path(tree.path).name.startswith("tl-land-gate-")),
        alive={}, main_sha=git.rev_parse(repo, main_ref),
        prs=prs, builds=builds,
        recorded=frozenset(e.branch for e in entries if e.phase is Phase.MERGED),
        notified=frozenset(), now=now,
    )
