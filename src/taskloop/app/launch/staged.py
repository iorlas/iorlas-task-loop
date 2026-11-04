"""tl check --staged: the checks judge what the index holds (a person's pre-commit hook), not the worktree. The index is laid over a
throwaway checkout of HEAD, so unstaged edits are out of sight and no stash or index write is made."""
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from taskloop.adapters.base_tree import clean_tree
from taskloop.app.checks.host import CheckoutView
from taskloop.contracts.ids import TreeSha
from taskloop.contracts.ports import Git


class StagedCheckout:
    """The throwaway checkout, whose changed paths are the staged ones: `when` and pass_files follow the commit, not the branch."""

    def __init__(self, inner: CheckoutView, names: list[str]) -> None:
        self.inner, self.names = inner, names

    def tree_hash(self) -> TreeSha:
        return self.inner.tree_hash()

    def changed_paths(self) -> list[str]:
        return list(self.names)


@contextmanager
def staged_tree(vcs: Git, repo: str) -> Generator[tuple[Path, list[str]]]:
    """(a checkout of HEAD with the index laid over it, the staged paths that still exist). Gone on exit."""
    head = vcs.rev_parse(repo, "HEAD")
    if not head:
        raise SystemExit("tl check --staged: the repo has no commit to lay the index over")
    with clean_tree(vcs, repo, head) as dest:
        vcs.export_index(repo, str(dest))
        yield dest, vcs.staged_paths(repo)
