"""Preserve custody while reconciling one recorded merge abort."""

from dataclasses import dataclass

from git_porcelain import EmbeddedRepositories, GitUnavailable, UnmergedPaths

from taskloop.land_conflict.abort_models import Abort, AbortPhase, Checkout
from taskloop.land_conflict.models import Record, Save
from taskloop.land_conflict.preserve import Preservation
from taskloop.merge.models import Reason, Result, Terminal, Unavailable, Work
from taskloop.slot_state import SlotState, index_status, observe_slot


class AbortRefused(Exception):
    """The observed checkout cannot authorize the recorded abort."""


@dataclass(frozen=True)
class AbortMerge:
    preservation: Preservation

    def __call__(self, record: Record, work: Work, saved: Save, result: Terminal) -> Result:
        try:
            return self._reconcile(record, work, saved, result)
        except AbortRefused as error:
            return Unavailable(reason=Reason.SLOT, explanation=f"{error} The merge work and reservation remain retained.")
        except (GitUnavailable, EmbeddedRepositories, UnmergedPaths) as error:
            return Unavailable(reason=Reason.GIT, explanation=f"The merge abort is pending; its work remains reserved: {error}")

    def _reconcile(self, record: Record, work: Work, saved: Save, result: Terminal) -> Result:
        p = self.preservation
        stopped = p.stopped(work)
        if stopped is not None:
            return stopped
        p.fence()
        if not p.verified(saved):
            raise AbortRefused("The retained conflict object or ref changed.")
        current = self.observe(record, work)
        if saved.abort is None:
            if (current.head, current.branch, current.merging, current.merge_head) != (
                    saved.head, None, True, f"{saved.target}\n".encode().hex()):
                raise AbortRefused("The active merge no longer matches the retained inputs.")
            slot = p.checkouts(work.slot, git_dir=work.gitdir).worktree(work.slot)
            if str(slot.capture()) != saved.tree:
                raise AbortRefused("The checkout changed after preservation.")
            after = self.expected(work, current)
            pending = Abort(work=work, before=current, after=after)
            p.fence()
            saved = p.store.save(record.key, saved, saved.model_copy(update={"abort": pending}))
        abort = saved.abort
        assert abort is not None
        if abort.work != work:
            raise AbortRefused("The recorded resolution process identity changed.")
        p.fence()
        current = self.observe(record, work)
        if current != abort.after:
            if abort.phase is AbortPhase.COMPLETE or current != abort.before:
                raise AbortRefused("The checkout matches neither the recorded abort input nor its expected result.")
            p.fence()
            if p.stopped(work) is not None or not p.verified(saved) or self.observe(record, work) != abort.before:
                raise AbortRefused("The abort precondition changed before the effect.")
            p.fence()
            p.checkouts(work.slot, git_dir=work.gitdir).worktree(work.slot).abort_merge()
        p.fence()
        if p.stopped(work) is not None or not p.verified(saved) or self.observe(record, work) != abort.after:
            raise AbortRefused("The checkout does not match the recorded abort result.")
        if abort.phase is AbortPhase.PENDING:
            complete = abort.model_copy(update={"phase": AbortPhase.COMPLETE})
            p.store.save(record.key, saved, saved.model_copy(update={"abort": complete}))
        return result

    def observe(self, record: Record, work: Work) -> Checkout:
        p = self.preservation
        state = observe_slot(p.checkouts, p.files, record.slot_path, record.request.repo_id)
        if (not isinstance(state, SlotState) or state.head is None
                or (state.root, state.gitdir) != (work.root, work.gitdir)):
            raise GitUnavailable("The reserved checkout's repository or directory identity changed")
        slot = p.checkouts(work.slot, git_dir=work.gitdir).worktree(work.slot)
        merging = slot.merging()
        merge_head = p.files.read(work.gitdir / "MERGE_HEAD", 256)
        snapshot = slot.snapshot(work.source, inputs=(".",))
        tree = p.repo.tree(str(snapshot.tree))
        if tree is None:
            raise GitUnavailable("The checkout's file identity cannot be read")
        return Checkout(repo_id=p.repo.identity().key, root=state.root, path=work.slot, gitdir=state.gitdir,
                        head=state.head, branch=state.branch, merging=merging,
                        merge_head=None if merge_head is None else merge_head.hex(),
                        index=index_status(p.repo, work.slot),
                        files={path: (mode, str(blob)) for path, (mode, blob) in tree.files.items()})

    def expected(self, work: Work, before: Checkout) -> Checkout:
        p = self.preservation
        source = p.repo.tree(work.source)
        if source is None:
            raise GitUnavailable("The recorded merge source cannot be read")
        slot = p.checkouts(work.slot, git_dir=work.gitdir).worktree(work.slot)
        dirty = slot.dirty(ignored_under=(".",))
        survivors = (*dirty.untracked, *dirty.ignored)
        files = {path: (mode, str(blob)) for path, (mode, blob) in source.files.items()}
        for path, identity in before.files.items():
            if any(path == name.rstrip("/") or path.startswith(name.rstrip("/") + "/") for name in survivors):
                if any(path == name or path.startswith(name + "/") or name.startswith(path + "/") for name in files):
                    raise GitUnavailable("A surviving local path overlaps the source checkout; abort waits")
                files[path] = identity
        return before.model_copy(update={"head": work.source, "branch": None, "merging": False,
                                         "merge_head": None, "index": (), "files": files})

