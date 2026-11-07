"""Bring the ADR cache up to the repo's `docs/adr` files at a commit (the base the run works from). Best effort: a repo without the
folder has no decisions, and a read git cannot make leaves the cache as it was."""
from tlkernel import adrfiles
from tlkernel.adrs import AdrStore
from tlkernel.gitport import Git
from tlkernel.slots import SlotGitError


def files_at(git: Git, wt: str, rev: str) -> dict[str, str] | None:
    """{file name: text} of the ADR files at `rev`; None when git cannot say."""
    try:
        names = [e.path for e in git.ls_tree(wt, rev, adrfiles.DIR + "/") if e.kind == "blob" and e.path.endswith(".md")]
        return {n: git.show(wt, rev, n) for n in names}
    except (SlotGitError, OSError, RuntimeError):
        return None


def refresh(git: Git, wt: str, rev: str, repo: str, store: AdrStore) -> None:
    files = files_at(git, wt, rev)
    if files is not None:
        store.sync(adrfiles.parse_all(files, repo))
