"""Start/resume one retained merge and accept its result for the owning continuation."""

from collections.abc import Callable

from git_porcelain import GitUnavailable, Repo

from taskloop.attempt_types import Checkouts, SlotFiles
from taskloop.merge import git
from taskloop.merge.models import Completed, Disposition, InProgress, Phase, Reason, Result, Terminal, Unavailable, Waiting, Work
from taskloop.merge.store import MergeStore
from taskloop.slot_state import SlotState, observe_slot

type Resolve = Callable[[Work], Work | Waiting]
type Setup = Callable[[Work], Waiting | None]


class Merge:
    def __init__(self, store: MergeStore, checkouts: Checkouts, remotes: Checkouts, files: SlotFiles,
                 clock: Callable[[], float], setup: Setup, resolve: Resolve, fence: Callable[[], None] = lambda: None) -> None:
        self.store, self.checkouts, self.remotes, self.files = store, checkouts, remotes, files
        self.clock, self.setup, self.resolve = clock, setup, resolve
        self.fence = fence

    def resume(self, work: Work) -> Result:
        """The caller holds reservation, entry/process and slot custody fences. Every phase is an effect's intent."""
        try:
            for _ in range(16):  # bounded local phase transitions; IO failures retain their exact intent
                done = self._done(work)
                if done is not None:
                    return done
                state = observe_slot(self.checkouts, self.files, str(work.slot), work.repo_id)
                if not isinstance(state, SlotState) or (state.root, state.gitdir) != (work.root, work.gitdir):
                    return Unavailable(reason=Reason.SLOT,
                                       explanation="The reserved slot's repository or pointer is unavailable or changed.")
                if self.clock() >= work.deadline:
                    return self._terminal(work, Reason.EXPIRED, "Preparation reached its deadline; retained work awaits a decision.")
                found = self._advance(work, state)
                if not isinstance(found, Work):
                    if isinstance(found, Terminal):
                        return self._terminal(work, found.reason, found.explanation)
                    return found
                work = found
            result: Result = InProgress(reason=Reason.RUNNING, explanation=work.explanation)
        except GitUnavailable as error:
            result = Unavailable(reason=Reason.GIT, explanation=f"The retained merge is waiting for Git: {error}")
        return result

    def _done(self, work: Work) -> Result | None:
        if work.phase is Phase.TERMINAL:
            return Terminal(reason=work.reason or Reason.INVALID, explanation=work.explanation)
        if work.phase is Phase.COMPLETE:
            return Completed(commit=work.result or work.source, source=work.source, target=work.target or work.source,
                             explanation=work.explanation)
        return None

    def _put(self, work: Work, **changes: object) -> Work:
        # Revalidate model_copy updates before crossing the database boundary.
        self.fence()
        updated = Work.model_validate(work.model_dump() | changes)
        return self.store.put(work, updated)

    def _terminal(self, work: Work, reason: Reason, explanation: str) -> Terminal:
        self._put(work, phase=Phase.TERMINAL, reason=reason, explanation=explanation)
        return Terminal(reason=reason, explanation=explanation)

    def _advance(self, work: Work, state: SlotState) -> Work | Result:
        self.fence()
        view = self.checkouts(work.slot, git_dir=work.gitdir)
        if view.worktree(work.slot).merging():
            target = self.files.read(work.gitdir / "MERGE_HEAD", 256)
            if target is None:
                return Unavailable(reason=Reason.GIT,
                                   explanation="The active merge's target could not be read; its reservation is retained.")
            if target != f"{work.target}\n".encode("ascii"):
                return Terminal(reason=Reason.MOVED,
                                explanation="The active merge no longer has its recorded target; its work is retained.")
        if work.phase is Phase.RESOLVE:
            if state.branch is not None or state.head != work.source:
                return Terminal(reason=Reason.SLOT, explanation="The resolution moved the reserved source or attached a branch.")
            return self._resolve(work, view)
        if (work.phase is Phase.START and state.branch is None and not state.dirty and state.head is not None
                and not view.worktree(work.slot).merging() and git.completed(view, state.head, work)):
            return self._put(work, phase=Phase.ATTACH, result=state.head)
        actions = {Phase.FETCH: lambda: self._fetch(work, view), Phase.SETUP: lambda: self._setup(work, state, view),
                   Phase.START: lambda: self._start(work, state, view), Phase.FINISH: lambda: self._finish(work, state, view),
                   Phase.ATTACH: lambda: self._attach(work, state, view)}
        action = actions.get(work.phase)
        return (Unavailable(reason=Reason.UNKNOWN, explanation="The merge phase could not be resumed.") if action is None
                else action())

    def _setup(self, work: Work, state: SlotState, view: Repo) -> Work | Result:
        setup_leftovers = state.branch is None and state.head == work.target
        allowed = (work.source, work.target, work.base) if work.branch is None else (work.source, work.target)
        if ((state.dirty and not setup_leftovers) or state.branch not in (None, work.branch)
                or state.head not in allowed or view.worktree(work.slot).merging()):
            return Terminal(reason=Reason.SLOT, explanation="The slot changed before the merge environment was prepared.")
        if state.branch is not None or state.head != work.target:
            self.fence()
            view.worktree(work.slot).park(work.target or work.source)
        self.fence()
        stopped = self.setup(work)
        return stopped or self._put(work, phase=Phase.START)

    def _finish(self, work: Work, state: SlotState, view: Repo) -> Work | Result:
        slot = view.worktree(work.slot)
        if slot.merging() and state.head == work.source and state.branch is None:
            self.fence()
            result = str(slot.finish_merge(git.message(work)))
        elif not state.dirty and state.branch is None and state.head is not None and git.completed(view, state.head, work):
            result = state.head
        else:
            return Terminal(reason=Reason.SLOT, explanation="The merge's HEAD or parents changed before completion.")
        if not git.completed(view, result, work):
            return Terminal(reason=Reason.SLOT, explanation="The completed merge does not retain the recorded parents and provenance.")
        return self._put(work, phase=Phase.ATTACH, result=result)

    def _attach(self, work: Work, state: SlotState, view: Repo) -> Work | Result:
        slot = view.worktree(work.slot)
        allowed = (work.base, work.source, work.result) if work.branch is None else (work.source, work.result)
        if state.dirty or slot.merging() or state.head not in allowed:
            return Terminal(reason=Reason.SLOT, explanation="The slot changed before the prepared commit could be attached.")
        if state.branch is not None and state.branch != work.branch:
            return Terminal(reason=Reason.MOVED, explanation="The task branch changed before the prepared commit could be attached.")
        if state.head != work.result:
            self.fence()
            slot.park(work.result or work.source)
        self.fence()
        refused = git.attach(view, slot, work, self.fence)
        return refused or self._put(work, phase=Phase.COMPLETE,
                                   explanation="Current main and the retained task work are prepared; the ordinary step continues.")

    def _fetch(self, work: Work, view: Repo) -> Work | Result:
        target = work.target
        if target is None:
            remote = self.remotes(work.root)
            self.fence()
            fetched = remote.fetch("origin", refspecs=("+refs/heads/main:refs/remotes/origin/main",), timeout=120)
            if not fetched.ok:
                return Unavailable(reason=Reason.GIT, explanation=f"Current main could not be refreshed: {fetched.output}")
            target = next((entry.sha for entry in remote.refs(["refs/remotes/origin/main"])
                           if entry.name == "refs/remotes/origin/main"), None)
        if target is None:
            return Unavailable(reason=Reason.TARGET, explanation="Origin has no known main commit; retained work is unchanged.")
        return self._target(work, view, target)

    def _target(self, work: Work, view: Repo, target: str) -> Work:
        view.is_ancestor(work.source, work.source)
        view.is_ancestor(target, target)
        if work.branch is not None and not (view.is_ancestor(work.base, target) or view.is_ancestor(work.base, work.source)):
            return self._put(work, target=target, phase=Phase.TERMINAL, reason=Reason.DIVERGED,
                             explanation="The reserved slot's base belongs to neither the retained source nor refreshed main.")
        if view.merge_base(work.source, target) is None:
            return self._put(work, target=target, phase=Phase.TERMINAL, reason=Reason.DIVERGED,
                             explanation="The task and current main have unrelated histories; the retained work needs a decision.")
        if view.is_ancestor(target, work.source):
            return self._put(work, target=target, result=work.source, phase=Phase.ATTACH)
        if view.is_ancestor(work.source, target):
            return self._put(work, target=target, result=target, phase=Phase.ATTACH)
        return self._put(work, target=target, phase=Phase.SETUP)

    def _start(self, work: Work, state: SlotState, view: Repo) -> Work | Result:
        slot = view.worktree(work.slot)
        if state.branch is not None:
            return Terminal(reason=Reason.SLOT, explanation="The merge slot was attached to a branch unexpectedly.")
        if not slot.merging():
            if state.dirty or state.head not in (work.target, work.source):
                return Terminal(reason=Reason.SLOT, explanation="The reserved source changed before merging main.")
            if state.head != work.source:
                self.fence()
                slot.park(work.source)
            self.fence()
            slot.start_merge(work.target or work.source)
        elif state.head != work.source:
            return Terminal(reason=Reason.SLOT, explanation="The active merge no longer starts at the retained source.")
        conflicts = slot.unmerged()
        if not conflicts:
            return self._put(work, phase=Phase.FINISH)
        pending = Work.model_validate(work.model_dump() | {"conflicts": conflicts})
        if not git.supported(view, pending):
            return self._put(work, conflicts=conflicts, phase=Phase.TERMINAL, reason=Reason.UNSUPPORTED,
                             explanation="The merge includes unsupported non-textual or unsafe conflicts; work remains reserved.")
        # Capture automatic changes plus markers without accepting them as a resolution. The recorded conflict list
        # remains authoritative after staging, including across a crash between staging and recording the baseline.
        work = self._put(work, conflicts=conflicts, phase=Phase.RESOLVE)
        return work

    def _resolve(self, work: Work, view: Repo) -> Work | Result:
        slot = view.worktree(work.slot)
        if not slot.merging():
            return Terminal(reason=Reason.SLOT, explanation="The reserved merge disappeared before resolution.")
        if work.baseline is None:
            self.fence()
            slot.stage(work.conflicts)
            self.fence()
            work = self._put(work, baseline=str(slot.capture()))
        resolved = self.resolve(work)
        if not isinstance(resolved, Work):
            return (self._put(work, phase=Phase.TERMINAL, reason=resolved.reason, explanation=resolved.explanation)
                    if isinstance(resolved, Terminal) else resolved)
        execution = resolved.executions[-1]
        answer = execution.answer
        if answer is not None and answer.disposition is Disposition.OWNER:
            return self._put(resolved, phase=Phase.TERMINAL, reason=Reason.OWNER, explanation=answer.explanation)
        if answer is not None and answer.disposition is Disposition.RESOLVED:
            problem = git.accepted(view, slot, self.files, resolved, answer, self.fence)
            if problem is None:
                return self._put(resolved, phase=Phase.FINISH)
        else:
            problem = execution.explanation or "The resolution did not finish."
        if len(resolved.executions) >= 3:
            return self._put(resolved, phase=Phase.TERMINAL, reason=Reason.EXHAUSTED,
                             explanation=f"Three merge resolution executions ended without an accepted result. {problem}")
        self.fence()
        self.store.put(resolved, resolved.model_copy(update={"executions": (*resolved.executions[:-1],
                                      execution.model_copy(update={"reviewed": True}))}))
        return InProgress(reason=Reason.RUNNING, explanation=f"Main's merge is awaiting another resolution execution. {problem}")
