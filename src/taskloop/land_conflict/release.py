"""Verify admitted-base parking before atomically releasing saved conflict custody."""

from dataclasses import dataclass

from git_porcelain import EmbeddedRepositories, GitUnavailable, UnmergedPaths

from taskloop.land_conflict.abort import AbortRefused
from taskloop.land_conflict.cleanup import CleanupSaved
from taskloop.land_conflict.models import Record, Save
from taskloop.land_conflict.preserve import Preservation
from taskloop.land_conflict.release_models import Release, ReleasePhase
from taskloop.merge.models import Completed, Reason, Result, Terminal, Unavailable, Work


@dataclass(frozen=True)
class ReleaseSaved:
    preservation: Preservation

    def __call__(self, record: Record, work: Work, saved: Save, result: Completed | Terminal) -> Result:
        try:
            return self._resume(record, work, saved, result)
        except AbortRefused as error:
            return Unavailable(reason=Reason.SLOT, explanation=f"{error} The saved work and reservation remain retained.")
        except (GitUnavailable, EmbeddedRepositories, UnmergedPaths) as error:
            return Unavailable(reason=Reason.GIT, explanation=f"The saved-work release is pending; its slot stays reserved: {error}")

    def _resume(self, record: Record, work: Work, saved: Save, result: Completed | Terminal) -> Result:
        p = self.preservation
        observer = CleanupSaved(p)
        stopped = p.stopped(work)
        if stopped is not None:
            return stopped
        current = observer._current(record, work, saved)
        if saved.release is None:
            cleanup = saved.cleanup
            if cleanup is None or current != cleanup.after:
                raise AbortRefused("The completed cleanup checkout changed before release.")
            tree = p.repo.tree(record.base)
            if tree is None:
                raise GitUnavailable("The admitted base cannot be read")
            tracked = {path: (mode, str(blob)) for path, (mode, blob) in tree.files.items()}
            if any(a == b or a.startswith(b + "/") or b.startswith(a + "/") for a in cleanup.ignored for b in tracked):
                raise AbortRefused("An ignored path overlaps the admitted base.")
            after = current.model_copy(update={"head": record.base, "files": tracked | cleanup.ignored})
            release = Release(work=work, before=current, after=after, result=result)
            p.fence()
            saved = p.store.save(record.key, saved, saved.model_copy(update={"release": release}))
        release = saved.release
        assert release is not None
        if release.work != work or release.result != result:
            raise AbortRefused("The recorded release work or result changed.")
        current = observer._current(record, work, saved)
        if current != release.after:
            if current != release.before:
                raise AbortRefused("The checkout matches neither the release input nor its recorded output.")
            p.fence()
            p.checkouts(work.slot, git_dir=work.gitdir).worktree(work.slot).park(
                record.base, clean_keep=(), keep_ignored=True)
        if observer._current(record, work, saved) != release.after:
            raise AbortRefused("Parking did not produce the admitted base and recorded ignored bytes.")
        p.fence()
        complete = release.model_copy(update={"phase": ReleasePhase.COMPLETE})
        p.store.release(record.key, saved, saved.model_copy(update={"release": complete}))
        return release.result
