"""Repeat implementation after an ordinary failed check; external reads precede the fenced admission intent."""

import hashlib
from dataclasses import dataclass, replace

from git_porcelain import GitUnavailable, Repo
from pydantic import ValidationError

from taskloop.admit import AdmitRefused, Admitted, Free, Tasks, checkout_repo, read_task
from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, Checkouts, Observe, SlotFiles
from taskloop.check_admit import Profiles
from taskloop.check_release import checks_stopped
from taskloop.check_repeat.feedback import FailedCheck, FeedbackReason
from taskloop.check_repeat.store import CheckRepeatState, CheckRepeatStore
from taskloop.check_store import CheckStore
from taskloop.checks import argv_digest, completed
from taskloop.evidence_files import EvidenceError, EvidenceFiles
from taskloop.ids import Ids
from taskloop.operations import Clock, Failed, Launch, Started, StartRequest, deadline_after, launched
from taskloop.prepare import HEADS, REMOTES
from taskloop.profile import PROFILE_PATH, Profile, read_profile
from taskloop.setup_store import SetupSeen, SetupStore
from taskloop.slot_release import entry_stopped, setup_stopped
from taskloop.slots import Probe, SlotGit
from taskloop.steps import failed_check_feedback
from taskloop.task import TaskInspection
from taskloop.tracker import ACTOR


@dataclass(frozen=True)
class CheckRepeat:
    store: CheckRepeatStore
    files: EvidenceFiles
    tasks: Tasks
    checkouts: Checkouts
    slot_files: SlotFiles
    probe: Probe
    profiles: Profiles
    launcher: Launch
    observe: Observe
    seen: SetupSeen
    clock: Clock
    ids: Ids

    def repair(self, request: StartRequest, previous: AttemptKey, source: AttemptKey) -> Started | Failed:
        try:
            state = self.store.state(previous, source)
            if state is None:
                return self._winner(request, previous)
            ready = self._ready(request, state)
            if isinstance(ready, Failed):
                return ready
            evidence, free = ready
            reader = AttemptStore(self.store.connect, self.store.begin)
            original = self.files.read(reader.chain(previous)[0].input_ref)
            key = AttemptKey(self.ids.hex(), self.ids.token(16), self.store.generation(state.checks.repo_id, free))
            ref = self.files.put_input(key, failed_check_feedback(evidence, original, self.ids.token(16)))
            admitted = self.store.admit(previous, evidence, key, ref, free, deadline_after(request.minutes, self.clock))
            if isinstance(admitted, AdmitRefused):
                return self._winner(request, previous) if admitted.reason == "task_attempted" else Failed("refused", admitted.reason)
        except (StoreUnavailable, EvidenceError, ValidationError, GitUnavailable) as error:
            return Failed("unavailable", FeedbackReason.EVIDENCE, str(error))
        except StoreRefused as error:
            return Failed("refused", error.reason)
        return self._launch(request, admitted, existing=False)

    def _ready(self, request: StartRequest, state: CheckRepeatState) -> tuple[FailedCheck, tuple[Free, ...]] | Failed:
        """Stop proof, exact branch, free slot and the existing claim. None of these reads changes the world."""
        source = state.checks
        checks = CheckStore(self.store.connect, self.store.begin)
        rows = checks.results(source.key)
        setup = SetupStore(self.store.connect, self.store.begin).latest(source.key)
        stopped = (entry_stopped(self.observe, None, source.entry)
                   or setup_stopped(self.seen, None if setup is None else setup.unsettled)
                   or checks_stopped(self.seen, rows))
        if stopped is not None:
            return Failed("unavailable", stopped.reason, stopped.detail)
        repo = self._candidate(request, state)
        if isinstance(repo, Failed):
            return repo
        evidence = self._evidence(request, state)
        if isinstance(evidence, Failed):
            return evidence
        free = self.store.free(repo, SlotGit(self.checkouts, self.slot_files), self.probe, state)
        if isinstance(free, AdmitRefused):
            return Failed("refused", free.reason, free.detail, slots=free.slots)
        return self._claim(state) or (evidence, free)

    def _claim(self, state: CheckRepeatState) -> Failed | None:
        source = state.checks
        task = read_task(self.tasks, source.task_id, source.backlog, source.tracker_root)
        if not isinstance(task, TaskInspection):
            return Failed("refused", task.reason if isinstance(task, AdmitRefused) else task.what, task.detail)
        if task.status != "in_progress" or task.assignee != ACTOR:
            return Failed("refused", "claim_lost", "The task's original factory claim is no longer ours.")
        return None

    def _candidate(self, request: StartRequest, state: CheckRepeatState) -> Repo | Failed:
        checked = checkout_repo(self.checkouts, request.checkout)
        if not isinstance(checked, tuple):
            reason = checked.reason if isinstance(checked, AdmitRefused) else checked.what
            return Failed("refused", reason, checked.detail)
        repo, repo_id = checked
        source = state.checks
        if repo_id != source.repo_id:
            return Failed("refused", "checkout")
        tips = {entry.name: entry.sha for entry in repo.refs([HEADS, REMOTES])}
        if (tips.get(f"{HEADS}/{source.task_id}") or tips.get(f"{REMOTES}/{source.task_id}")) != source.commit:
            return Failed("refused", "branch_moved", "The task branch moved after its failed checks; it cannot be repeated at that commit.")
        return repo

    def _evidence(self, request: StartRequest, state: CheckRepeatState) -> FailedCheck | Failed:
        source, result = state.checks, state.failure
        files = self.profiles(request.checkout)
        profile, blob = read_profile(files, source.commit), files.blob(source.commit, PROFILE_PATH)
        if not isinstance(profile, Profile) or not isinstance(blob, bytes):
            return Failed("unavailable", FeedbackReason.PROFILE, "The checked commit's profile is unavailable or invalid.")
        rows = CheckStore(self.store.connect, self.store.begin).results(source.key)
        command = next((check for check in profile.checks if check.name == result.name), None)
        if (source.profile_digest != hashlib.sha256(blob).hexdigest() or command is None
                or argv_digest(command.argv) != result.argv_digest or not completed(rows, profile.checks, source.required)):
            return Failed("refused", FeedbackReason.PROFILE, "The stored check result and checked profile do not agree.")
        if result.rc is None:
            return Failed("refused", FeedbackReason.EVIDENCE, "The check did not exit with a nonzero status.")
        return FailedCheck(source=source.key, block=result.block, commit=source.commit, name=result.name,
                           argv=command.argv, rc=result.rc, output=self.files.check_output(source.key, result.block, result.name))

    def _winner(self, request: StartRequest, previous: AttemptKey) -> Started | Failed:
        rows = AttemptStore(self.store.connect, self.store.begin).attempts(request.backlog, request.task_id)
        if rows and rows[0].previous_attempt_id == previous.attempt_id and rows[0].source_checks_id is not None:
            return self._launch(request, Admitted(rows[0].key, rows[0].slot), existing=True)
        return Failed("refused", "changed", "The failed checks are no longer eligible for an implement repeat.")

    def _launch(self, request: StartRequest, admitted: Admitted, *, existing: bool) -> Started | Failed:
        result = launched(self.launcher.launch(request.backlog, request.task_id, request.minutes),
                          request.backlog, request.task_id, admitted.key, existing=existing)
        return replace(result, admitted=True) if isinstance(result, Failed) and not existing else result
