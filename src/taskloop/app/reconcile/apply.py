"""`apply`: run the actions `diff` planned, each against the oid it was observed at. A branch that moved since stays, with git's reason."""
from pathlib import Path

from taskloop.app.release import tidy
from taskloop.app.release.shell import Shell
from taskloop.domain.reconcile.facts import Action, DeleteBranch, DeleteRemote, Keep, RemoveTree


def apply(actions: list[Action], dry_run: bool, sh: Shell) -> tuple[list[str], list[str]]:
    """(removed lines, kept lines with the reason). The plan is the list: nothing is looked at again except by the compare-and-delete
    itself. A branch held by a tree of the plan goes only if that tree went."""
    removed: list[str] = []
    kept: list[str] = []
    stayed: set[str] = set()
    for a in actions:
        why = a.why if isinstance(a, Keep) else ""
        if not why and not dry_run:
            if isinstance(a, RemoveTree):
                why = tidy.remove_tree(Path(a.repo), Path(a.path), sh)
                if why:
                    stayed.add(a.key)
            elif isinstance(a, DeleteBranch):
                why = "a worktree still has it" if stayed & set(a.after) else tidy.delete_branch_at(Path(a.repo), a.name, a.oid, sh)
            elif isinstance(a, DeleteRemote):
                why = tidy.delete_remote_at(Path(a.repo), a.ref, a.oid, sh)
        line = f"{'would remove ' if dry_run and not why else ''}{a.line}"
        (kept if why else removed).append(line + (f": {why}" if why else ""))
    return removed, kept
