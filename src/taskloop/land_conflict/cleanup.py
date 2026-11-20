"""Resume saved-work cleanup without releasing slot custody."""

from dataclasses import dataclass

from git_porcelain import EmbeddedRepositories, GitUnavailable, UnmergedPaths
from git_porcelain.ignore_rules import literal_pattern

from taskloop.land_conflict.abort import AbortMerge, AbortRefused
from taskloop.land_conflict.abort_models import Checkout
from taskloop.land_conflict.cleanup_models import Cleanup, CleanupPhase
from taskloop.land_conflict.models import Record, Save
from taskloop.land_conflict.preserve import Preservation
from taskloop.merge.models import Completed, Reason, Result, Terminal, Unavailable, Work


@dataclass(frozen=True)
class CleanupSaved:
    preservation: Preservation

    def __call__(self, record: Record, work: Work, saved: Save, result: Completed | Terminal) -> Result:
        try:
            return self._resume(record, work, saved, result)
        except AbortRefused as error:
            return Unavailable(reason=Reason.SLOT, explanation=f"{error} The saved work and reservation remain retained.")
        except (GitUnavailable, EmbeddedRepositories, UnmergedPaths) as error:
            return Unavailable(reason=Reason.GIT, explanation=f"The saved-work cleanup is pending; its slot stays reserved: {error}")

    def _current(self, record: Record, work: Work, saved: Save) -> Checkout:
        p = self.preservation
        p.fence()
        if p.stopped(work) is not None or not p.verified(saved):
            raise AbortRefused("The stopped worker or retained object and ref could not be verified.")
        current = AbortMerge(p).observe(record, work)
        if saved.cleanup is not None:
            slot = p.checkouts(work.slot, git_dir=work.gitdir).worktree(work.slot)
            ignored = slot.dirty(ignored_under=(".",)).ignored
            identities = {path: identity for path, identity in current.files.items() if _under(path, ignored)}
            if identities != saved.cleanup.ignored:
                raise AbortRefused("The recorded ignored paths or their protection changed.")
        return current

    def _resume(self, record: Record, work: Work, saved: Save, result: Completed | Terminal) -> Result:
        p = self.preservation
        stopped = p.stopped(work)
        if stopped is not None:
            return stopped
        current = self._current(record, work, saved)
        if saved.cleanup is None:
            cleanup = self._intent(work, saved, current)
            p.fence()
            saved = p.store.save(record.key, saved, saved.model_copy(update={"cleanup": cleanup}))
        cleanup = saved.cleanup
        assert cleanup is not None
        if cleanup.work != work:
            raise AbortRefused("The recorded resolution process identity changed.")
        if cleanup.phase is CleanupPhase.EXCLUDE:
            candidates = (cleanup.before,) if saved.abort is None else (saved.abort.before, saved.abort.after)
            if self._current(record, work, saved) not in candidates:
                raise AbortRefused("The checkout changed before ignored paths could be protected.")
            p.fence()
            p.checkouts(work.slot, git_dir=work.gitdir).worktree(work.slot).exclude(
                tuple(literal_pattern(path) for path in cleanup.ignored))
            if saved.merging:
                assert isinstance(result, Terminal)
                aborted = AbortMerge(p)(record, work, saved, result)
                if not isinstance(aborted, Terminal):
                    return aborted
                latest = p.store.saved(record.key)
                assert latest is not None
                saved = latest
            cleanup = cleanup.model_copy(update={"phase": CleanupPhase.PARK})
            p.fence()
            saved = p.store.save(record.key, saved, saved.model_copy(update={"cleanup": cleanup}))
        self._park(record, work, saved)
        return result

    def _intent(self, work: Work, saved: Save, before: Checkout) -> Cleanup:
        p = self.preservation
        slot = p.checkouts(work.slot, git_dir=work.gitdir).worktree(work.slot)
        if saved.abort is None and (
                (before.head, before.branch, before.merging, before.merge_head)
                != (saved.head, None, saved.merging, f"{saved.target}\n".encode().hex() if saved.merging else None)
                or str(slot.capture()) != saved.tree):
            raise AbortRefused("The checkout changed after its work was retained.")
        dirty = slot.dirty(ignored_under=(".",))
        ignored = {path: identity for path, identity in before.files.items() if _under(path, dirty.ignored)}
        target = p.repo.tree(work.source if saved.merging else saved.head)
        if target is None:
            raise GitUnavailable("The cleanup HEAD cannot be read")
        tracked = {path: (mode, str(blob)) for path, (mode, blob) in target.files.items()}
        if any(a == b or a.startswith(b + "/") or b.startswith(a + "/") for a in ignored for b in tracked):
            raise AbortRefused("An ignored path overlaps the cleanup HEAD.")
        survivors = {path: identity for path, identity in before.files.items() if _under(path, (*dirty.untracked, *dirty.ignored))}
        restored = before.model_copy(update={"head": str(target.sha), "branch": None, "merging": False,
                                             "merge_head": None, "index": (), "files": tracked | survivors})
        after = restored.model_copy(update={"files": tracked | ignored})
        return Cleanup(work=work, before=before, restored=restored, after=after, ignored=ignored)

    def _park(self, record: Record, work: Work, saved: Save) -> None:
        p = self.preservation
        cleanup = saved.cleanup
        assert cleanup is not None
        current = self._current(record, work, saved)
        if cleanup.phase is CleanupPhase.COMPLETE:
            if current != cleanup.after:
                raise AbortRefused("The completed cleanup checkout changed.")
            return
        before = cleanup.before if saved.abort is None else saved.abort.after
        slot = p.checkouts(work.slot, git_dir=work.gitdir).worktree(work.slot)
        if current == before and current != cleanup.restored:
            p.fence()
            slot.reset(cleanup.restored.head, mode="hard")
            current = self._current(record, work, saved)
        if not _parking(current, cleanup):
            raise AbortRefused("The checkout matches neither the cleanup input nor its recorded results.")
        if current != cleanup.after:
            p.fence()
            slot.park(cleanup.after.head, clean_keep=(), keep_ignored=True)
        if self._current(record, work, saved) != cleanup.after:
            raise AbortRefused("The cleanup did not produce its recorded checkout and ignored bytes.")
        p.fence()
        complete = cleanup.model_copy(update={"phase": CleanupPhase.COMPLETE})
        p.store.save(record.key, saved, saved.model_copy(update={"cleanup": complete}))


def _under(path: str, names: tuple[str, ...]) -> bool:
    return any(path == name.rstrip("/") or path.startswith(name.rstrip("/") + "/") for name in names)


def _parking(current: Checkout, cleanup: Cleanup) -> bool:
    """Cleaning may have removed any subset of the recorded untracked paths."""
    return (current.model_dump(exclude={"files"}) == cleanup.after.model_dump(exclude={"files"})
            and cleanup.after.files.items() <= current.files.items() <= cleanup.restored.files.items())
