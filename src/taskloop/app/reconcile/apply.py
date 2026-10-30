"""`apply`: run the actions `diff` planned, each against the oid or the lease generation it was observed at. A branch that moved, or a
lease that was retaken, since stays, with the reason."""
from collections.abc import Callable

from taskloop.app.release import tidy
from taskloop.contracts import fence
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import BdFailure, BeadPatch, Beads, Git
from taskloop.contracts.slots import HELD_KEYS
from taskloop.domain.reconcile.facts import (
    Action,
    DeleteBranch,
    DeleteRemote,
    FreeSlot,
    Keep,
    NoLoop,
    ReleaseClaim,
    RemoveTree,
)


def give_back(store: Beads, bead: BeadId, holder: str, gen: int, key: str, patch: BeadPatch) -> str:
    """Give a held bead back while it is still `holder`'s at generation `gen` (read again here: a retake bumped it). -> why not, ""
    when done. bd checks the holder atomically (`if_assignee`), so a retake between the look and the write changes nothing."""
    try:
        b = fence.peek(store, bead)
        if b is None:
            return "bd could not show it"
        if b.status not in ("in_progress", "open") or b.assignee != holder:  # open: a paused run leaves its bead so
            return "no longer held by " + holder
        if fence.gen_of(b, key) != gen:
            return f"taken again (generation {fence.gen_of(b, key)}, seen {gen})"
        store.update(bead, patch)
    except BdFailure as e:
        return f"{holder} no longer holds it ({e.error.text[:60]})"
    return ""


def act_lease(a: ReleaseClaim | FreeSlot, store: Beads) -> str:
    """Give one dead claim or slot back. -> why it stayed, "" when done."""
    if isinstance(a, ReleaseClaim):
        return give_back(store, a.bead, a.holder, a.gen, fence.BEAD_GEN, BeadPatch(status="open", assignee="", if_assignee=a.holder))
    return give_back(store, a.bead, a.holder, a.gen, fence.SLOT_GEN,
                     BeadPatch(status="open", assignee="", if_assignee=a.holder, unset_metadata=list(HELD_KEYS)))


def act(a: Action, git: Git, store_of: Callable[[str], Beads] | None, stayed: set[str]) -> str:
    """Do one action. -> why it stayed, "" when done."""
    why = ""
    if isinstance(a, RemoveTree):
        why = git.remove_worktree_why(a.repo, a.path)
        if why:
            stayed.add(a.key)
    elif isinstance(a, DeleteBranch):
        why = "a worktree still has it" if stayed & set(a.after) else tidy.delete_branch_at(git, a.repo, a.name, a.oid)
    elif isinstance(a, DeleteRemote):
        why = tidy.delete_remote_at(git, a.repo, a.ref, a.oid)
    elif store_of is None:
        why = "bd not asked"
    elif isinstance(a, ReleaseClaim | FreeSlot):
        why = act_lease(a, store_of(a.repo))
    return why


def apply(actions: list[Action], dry_run: bool, git: Git, store_of: Callable[[str], Beads] | None = None) -> tuple[list[str], list[str]]:
    """(removed lines, kept lines with the reason). The plan is the list: nothing is looked at again except by the compare-and-delete
    or the generation check itself. A branch held by a tree of the plan goes only if that tree went. A finding (NoLoop) is not done."""
    removed: list[str] = []
    kept: list[str] = []
    stayed: set[str] = set()
    for a in actions:
        if isinstance(a, NoLoop):
            continue
        why = a.why if isinstance(a, Keep) else ""
        if not why and not dry_run:
            why = act(a, git, store_of, stayed)
        line = f"{'would remove ' if dry_run and not why else ''}{a.line}"
        (kept if why else removed).append(line + (f": {why}" if why else ""))
    return removed, kept
