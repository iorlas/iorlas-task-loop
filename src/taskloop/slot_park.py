"""Park released slots, preserving held work on its task branch first."""

from collections.abc import Callable
from pathlib import Path

from git_porcelain import Repo, Worktree

from taskloop import wip
from taskloop.attempt_types import Checkouts, SlotFiles
from taskloop.release_proof import NOTHING, NotReleased
from taskloop.slot_state import SlotState, listing, observe_slot

type Saver = Callable[[Repo, Worktree, SlotState], wip.Refused | None]


def park_slot(
    checkouts: Checkouts, slot_files: SlotFiles, path: Path, repo_id: str, slot_head: str, branch: str | None,
    save: Saver | None = None,
) -> tuple[str, str | None] | NotReleased:
    """Park a clean slot at its admitted head; authorized held work is saved before parking."""
    state = observe_slot(checkouts, slot_files, str(path), repo_id)
    if isinstance(state, str) or state.head is None:
        return _unreadable(state)
    if save is not None and state.branch in (None, branch):
        return _saved(checkouts, path, state, slot_head, save)
    if state.dirty:
        left = listing(checkouts(path, git_dir=state.gitdir), path)
        again = f"The slot contains changes; its reservation remains held. {NOTHING}"
        return NotReleased("refused", "slot_dirty", "\n".join([*left, again]))
    merging = checkouts(path, git_dir=state.gitdir).worktree(path).merging()
    if state.branch is None and state.head == slot_head and not merging:
        return state.head, None
    if merging or state.branch not in (None, branch):
        return (NotReleased("unavailable", "merge_pending", "An active merge needs owning preservation before the slot can be parked.")
                if merging else NotReleased("refused", "slot_branch", f"The slot is on another branch. {NOTHING}"))
    return slot_head, str(checkouts(path, git_dir=state.gitdir).worktree(path).park(slot_head))


def _unreadable(state: SlotState | str) -> NotReleased:
    if isinstance(state, str):
        reason = "slot_redirected" if state == "redirected" else state
        return NotReleased("refused" if state == "redirected" else "unavailable", reason, f"Inspect the slot. {NOTHING}")
    return NotReleased("refused", "slot_unborn", f"The slot has no commit. {NOTHING}")


def _saved(checkouts: Checkouts, path: Path, state: SlotState, slot_head: str, save: Saver) -> tuple[str, str | None] | NotReleased:
    view = checkouts(path, git_dir=state.gitdir)
    slot = view.worktree(path)
    if state.dirty or state.branch is not None or state.head != slot_head or slot.merging():
        refused = save(view, slot, state)
        if refused is not None:
            return NotReleased("unavailable", refused.reason.value, refused.detail)
    parked = wip.park(slot, slot_head)
    if isinstance(parked, wip.Refused):
        return NotReleased("unavailable", parked.reason.value, parked.detail)
    return slot_head, parked


def saver(log: wip.SavedLog, files: SlotFiles, clock: Callable[[], float], source: wip.Source) -> Saver:
    """Construct the hold's save, retaining merge preservation before any abort."""
    def save(view: Repo, slot: Worktree, state: SlotState) -> wip.Refused | None:
        head = state.head or source.base
        if slot.merging() and source.merge is not None:
            target = files.read(state.gitdir / "MERGE_HEAD", 256)
            if target != f"{source.merge[1]}\n".encode("ascii"):
                return wip.Refused(wip.SaveReason.MERGE_CHANGED,
                                   "The active merge's target changed or cannot be read; work stays reserved.")
        saved_head = any(each.source_head == head for each in log.saved(source.attempt_id))
        if not state.dirty and not slot.merging() and (source.merge is None or saved_head):
            wip.adopt(view, head, source, log)
            return None
        refused = wip.save(view, slot, source, head, int(clock()), log)
        if refused is None and slot.merging() and source.merge is not None:
            slot.abort_merge()
        return refused

    return save
