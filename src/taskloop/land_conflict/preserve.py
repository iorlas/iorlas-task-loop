"""Retain detached conflict work through a fenced, restartable save owned by its operation."""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from any_agent.procs import Worker
from git_porcelain import EmbeddedRepositories, GitUnavailable, RefMoved, Repo, UnmergedPaths

from taskloop.attempt_types import Checkouts, SlotFiles, WorkerGone
from taskloop.land_conflict.models import Record, Save, SavePhase
from taskloop.land_conflict.store import ConflictStore
from taskloop.merge import git
from taskloop.merge.models import Completed, InProgress, Reason, Result, Terminal, Unavailable, Work
from taskloop.slot_state import SlotState, observe_slot
from taskloop.wip import Source, message


@dataclass(frozen=True)
class Preservation:
    store: ConflictStore
    repo: Repo
    checkouts: Checkouts
    files: SlotFiles
    gone: WorkerGone
    clock: Callable[[], float]
    fence: Callable[[], None]

    def __call__(self, record: Record, work: Work, result: Completed | Terminal) -> Result:
        """The executor holds slot custody. Every retry observes the world before performing an effect."""
        try:
            return self._preserve(record, work, result)
        except (EmbeddedRepositories, UnmergedPaths, GitUnavailable) as error:
            return Unavailable(reason=Reason.GIT, explanation=f"The conflict save is pending; its checkout remains reserved: {error}")

    def _stopped(self, work: Work) -> InProgress | Unavailable | None:
        for execution in work.executions:
            worker = execution.worker
            if worker is not None and not self.gone(Worker(pid=worker.pid, pgid=worker.pgid, start=worker.start, boot=worker.boot)):
                return InProgress(reason=Reason.UNKNOWN, explanation="The resolution process may still be live; saving waits for its stop.")
            if worker is None and execution.capturing:
                return Unavailable(reason=Reason.UNKNOWN, explanation="The resolution has no confirmed process identity; saving waits.")
        return None

    def _preserve(self, record: Record, work: Work, result: Completed | Terminal) -> Result:
        stopped = self._stopped(work)
        if stopped is not None:
            return stopped
        self.fence()
        state = observe_slot(self.checkouts, self.files, record.slot_path, record.request.repo_id)
        if (not isinstance(state, SlotState) or state.head is None or state.branch is not None
                or (state.root, state.gitdir) != (work.root, work.gitdir)):
            return Unavailable(reason=Reason.SLOT, explanation="The conflict slot identity changed; its files remain reserved.")
        slot = self.checkouts(work.slot, git_dir=state.gitdir).worktree(work.slot)
        merging = slot.merging()
        refused = self._owned(work, state, merging, result)
        if refused is not None:
            return refused
        saved = self.store.saved(record.key)
        expected = self._intent(record, state, merging, result)
        if saved is None:
            if self._tip(expected.ref) is not None:
                return Unavailable(reason=Reason.MOVED, explanation="The retained conflict ref already belongs to other work.")
            saved = self.store.save(record.key, None, expected)
        identity = ("key", "repo_id", "slot", "slot_path", "gitdir", "source", "target", "head", "merging", "accepted", "ref",
                    "expected", "message", "parents")
        if any(getattr(saved, field) != getattr(expected, field) for field in identity):
            return Unavailable(reason=Reason.SLOT, explanation="The saved conflict inputs changed; its original save remains reserved.")
        return self._save(saved, result)

    def _owned(self, work: Work, state: SlotState, merging: bool, result: Completed | Terminal) -> Terminal | Unavailable | None:
        if merging and (state.head != work.source or self.files.read(state.gitdir / "MERGE_HEAD", 256)
                        != f"{work.target}\n".encode("ascii")):
            return Terminal(reason=Reason.MOVED, explanation="The active merge inputs changed; saving leaves its work reserved.")
        # These terminal outcomes describe foreign work, rather than unfinished work owned by this merge.
        if isinstance(result, Terminal) and result.reason in (Reason.MOVED, Reason.SLOT, Reason.DIVERGED, Reason.TARGET):
            return result
        if isinstance(result, Completed) and (merging or state.dirty or state.head != result.commit):
            return Unavailable(reason=Reason.SLOT, explanation="The completed detached result changed; its files remain reserved.")
        if (isinstance(result, Completed) and state.head is not None and state.head not in (work.source, work.target)
                and not git.completed(self.repo, state.head, work)):
            return Unavailable(reason=Reason.SLOT, explanation="The detached result has different merge provenance; saving waits.")
        if (not merging and state.head not in (work.source, work.target, work.base)
                and not git.completed(self.repo, state.head or "", work)):
            return Unavailable(reason=Reason.SLOT, explanation="The detached HEAD no longer retains the merge inputs; saving waits.")
        return None

    def _intent(self, record: Record, state: SlotState, merging: bool, result: Completed | Terminal) -> Save:
        key = record.key
        identity = f"{key.attempt_id}\0{key.dispatch_token}\0{key.reservation_generation}".encode()
        ref = "refs/heads/task-loop/conflicts/" + hashlib.sha256(identity).hexdigest()
        source = Source(record.request.task_id, key.attempt_id, record.slot, record.base,
                        (record.request.checked, record.request.target))
        return Save(key=key, repo_id=record.request.repo_id, slot=record.slot, slot_path=Path(record.slot_path),
                    gitdir=state.gitdir, source=record.request.checked, target=record.request.target, head=state.head or "",
                    merging=merging, accepted=isinstance(result, Completed), ref=ref, when=int(self.clock()),
                    message=message(source),
                    parents=tuple(dict.fromkeys((state.head or "", record.request.checked, record.request.target))))

    def _tip(self, ref: str) -> str | None:
        return next((entry.sha for entry in self.repo.refs([ref]) if entry.name == ref), None)

    def _put(self, saved: Save, **changes: object) -> Save:
        updated = Save.model_validate(saved.model_dump() | changes)
        return self.store.save(saved.key, saved, updated)

    def _save(self, saved: Save, result: Completed | Terminal) -> Result:
        tip = self._tip(saved.ref)
        if tip not in (saved.expected, saved.commit) or (saved.phase is SavePhase.COMPLETE and tip != saved.commit):
            return Unavailable(reason=Reason.MOVED, explanation="The retained conflict ref changed; saving will not overwrite it.")
        slot = self.checkouts(saved.slot_path, git_dir=saved.gitdir).worktree(saved.slot_path)
        if saved.phase is SavePhase.CAPTURE:
            self.fence()
            paths = slot.unmerged()
            if paths:
                self.fence()
                slot.stage(paths)
            self.fence()
            saved = self._put(saved, tree=str(slot.capture()), phase=SavePhase.OBJECT)
        self.fence()
        if str(slot.capture()) != saved.tree:
            return Unavailable(reason=Reason.SLOT,
                               explanation="The conflict files changed after capture; the original save remains reserved.")
        if saved.phase is SavePhase.OBJECT:
            self.fence()
            if saved.accepted:
                commit = saved.head
            else:
                commit = str(self.repo.commit_tree(saved.tree or "", saved.parents, saved.message, when=saved.when))
            saved = self._put(saved, commit=commit, phase=SavePhase.REF)
        if not self._matches(saved):
            return Unavailable(reason=Reason.GIT, explanation="The retained object does not match its frozen save inputs; saving waits.")
        retained = self._retain(saved)
        if isinstance(retained, Unavailable):
            return retained
        self.fence()
        if not self._current(retained):
            return Unavailable(reason=Reason.SLOT,
                               explanation="The checkout or retained ref changed during saving; its work remains reserved.")
        return result

    def _retain(self, saved: Save) -> Save | Unavailable:
        if saved.phase is SavePhase.REF:
            self.fence()
            tip = self._tip(saved.ref)
            if tip != saved.commit:
                if tip != saved.expected:
                    return Unavailable(reason=Reason.MOVED, explanation="Another writer changed the retained conflict ref; saving waits.")
                self.fence()
                moved = self.repo.update_ref(saved.ref, saved.commit or "", expected=saved.expected)
                if isinstance(moved, RefMoved):
                    return Unavailable(reason=Reason.MOVED,
                                       explanation="The retained conflict ref changed during saving; its work stays reserved.")
            if self._tip(saved.ref) != saved.commit:
                return Unavailable(reason=Reason.MOVED, explanation="The retained ref changed after publication; its save remains pending.")
            saved = self._put(saved, phase=SavePhase.COMPLETE)
        return saved

    def _current(self, saved: Save) -> bool:
        state = observe_slot(self.checkouts, self.files, str(saved.slot_path), saved.repo_id)
        if (not isinstance(state, SlotState) or (state.gitdir, state.head, state.branch) != (saved.gitdir, saved.head, None)
                or self._tip(saved.ref) != saved.commit):
            return False
        slot = self.checkouts(saved.slot_path, git_dir=saved.gitdir).worktree(saved.slot_path)
        return (slot.merging() == saved.merging and (not saved.merging
                or self.files.read(saved.gitdir / "MERGE_HEAD", 256) == f"{saved.target}\n".encode("ascii"))
                and str(slot.capture()) == saved.tree)

    def _matches(self, saved: Save) -> bool:
        commit = self.repo.tree(saved.commit or "")
        tree = self.repo.tree(saved.tree or "")
        if commit is None or tree is None or commit.files != tree.files:
            return False
        if saved.accepted:
            return saved.commit == saved.head
        parents = tuple(self.repo.tree(f"{saved.commit}^{number}") for number in range(1, len(saved.parents) + 2))
        history = self.repo.history([saved.commit or ""], limit=1)
        return (tuple(str(parent.sha) for parent in parents if parent is not None) == saved.parents
                and bool(history) and history[0].subject == saved.message.partition("\n")[0]
                and history[0].body.strip() == saved.message.partition("\n\n")[2])
