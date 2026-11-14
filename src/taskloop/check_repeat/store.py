"""A clean-slot implement admission after checks: typed reads and one fenced transaction, no external actions."""

from dataclasses import dataclass

from git_porcelain import Repo

from taskloop.admit import AdmitRefused, Admitted, Free, branched, free_slots, issued, unheld
from taskloop.admit_rows import insert_attempt, reserve
from taskloop.agents.settings import encode_policy
from taskloop.attempt_reads import AttemptRow, StoreConnection, StoreRefused, StoreUnavailable, as_text
from taskloop.attempt_result import collect, succeeded
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, FileRef
from taskloop.check_repeat.feedback import CheckRepeatReason, FailedCheck
from taskloop.check_repeat.status import CheckRepeatDecision, decision, failed_result
from taskloop.check_store import ChecksRow, CheckStore, ResultRow
from taskloop.drain.models import BLOCKED, Reason
from taskloop.drain.store import blocked
from taskloop.hold_store import HoldStore
from taskloop.land_store import LandStore
from taskloop.repo import RepoId
from taskloop.slots import Probe, SlotGit


@dataclass(frozen=True)
class CheckRepeatState:
    previous: AttemptRow
    checks: ChecksRow
    failure: ResultRow


class CheckRepeatStore(StoreConnection):
    def state(self, previous: AttemptKey, source: AttemptKey) -> CheckRepeatState | None:
        """Current, done, still claimed, no hold or active/delivered land; the latest released failure below the cap."""
        attempts = AttemptStore(self.connect, self.begin)
        with self._connection() as con:
            task = con.execute("SELECT backlog,task_id FROM attempt WHERE attempt_id=? AND dispatch_token=? AND generation=?",
                               (previous.attempt_id, previous.dispatch_token, previous.reservation_generation)).fetchone()
        rows = () if task is None else attempts.attempts(as_text(task[0]), as_text(task[1]))
        if not rows or rows[0].key != previous:
            return None
        current = rows[0]
        if (current.step != "implement" or current.release is None or current.release.claim != "kept"
                or current.published is None or current.published.commit != current.end_commit
                or not succeeded(collect(attempts, previous))):
            return None
        checks = CheckStore(self.connect, self.begin)
        latest = checks.of_attempt(previous.attempt_id)
        if not latest or latest[-1].key != source:
            return None
        row = latest[-1]
        land = LandStore(self.connect, self.begin).latest(source.attempt_id)
        held = HoldStore(self.connect, self.begin).of_attempts((previous.attempt_id,)).get(previous.attempt_id)
        blocked = held is not None or (land is not None and (land.delivery is not None or land.holds_slot or land.pushable))
        results = checks.results(source)
        result = failed_result(row, results)
        if decision(current.number, row, results, blocked=blocked) is not CheckRepeatDecision.REPEAT or result is None:
            return None
        return CheckRepeatState(current, row, result)

    def free(self, repo: Repo, git: SlotGit, probe: Probe, state: CheckRepeatState) -> tuple[Free, ...] | AdmitRefused:
        """Observed free, clean slots passing the normal branch rule. Unavailable reads propagate as store errors."""
        with self._connection() as con:
            views = free_slots(con, repo, git, RepoId(state.checks.repo_id), probe)
        if not isinstance(views, tuple):
            if isinstance(views, AdmitRefused):
                return views
            raise StoreUnavailable(views.detail)
        free = branched(repo, state.checks.task_id, views)
        if not isinstance(free, (tuple, AdmitRefused)):
            raise StoreUnavailable(free.detail)
        return free

    def generation(self, repo_id: str, free: tuple[Free, ...]) -> int:
        with self._connection() as con:
            return issued(con, RepoId(repo_id), tuple(each.name for each in free)) + 1

    def admit(self, previous: AttemptKey, evidence: FailedCheck, key: AttemptKey, ref: FileRef,
              free: tuple[Free, ...], deadline: float) -> Admitted | AdmitRefused:
        """Fenced source, current attempt, completed block, cap, release, hold and successor uniqueness under one lock."""
        with self._connection(write=True) as con:
            if blocked(con):
                return AdmitRefused(Reason.DRAINING, detail=BLOCKED)
            state = CheckRepeatStore(lambda: con, self.begin).state(previous, evidence.source)
            if state is None:
                return AdmitRefused("task_attempted")
            row, source, result = state.previous, state.checks, state.failure
            if (result.block, result.name, source.commit) != (evidence.block, evidence.name, evidence.commit):
                return AdmitRefused("task_attempted")
            repo_id = RepoId(source.repo_id)
            chosen = next((slot for each in free if (slot := unheld(con, repo_id, each, key.reservation_generation)) is not None), None)
            if chosen is None:
                return AdmitRefused("no_free_slot")
            name, head = chosen
            choices = row.run
            if choices is None:
                raise StoreRefused("choices")
            reserve(con, repo_id, name, key)
            insert_attempt(con, {
                "attempt_id": key.attempt_id, "dispatch_token": key.dispatch_token, "generation": key.reservation_generation,
                "step": "implement", "adapter": "beads", "backlog": row.backlog, "task_id": row.task_id,
                "tracker_root": source.tracker_root, "repo_id": repo_id, "slot": name,
                "input_path": ref.path, "input_digest": ref.digest, "schema_version": 1,
                "model": choices.model, "effort": choices.effort, "access_policy": encode_policy(choices.access),
                "harness": choices.harness, "provider": choices.provider, "deadline": deadline,
                "number": row.number + 1, "seq": row.seq + 1, "previous_attempt_id": previous.attempt_id,
                "repeat_reason": CheckRepeatReason.FAILED_CHECK.value, "repeat_listing": None,
                "source_checks_id": source.key.attempt_id, "slot_head": head, "after_commit": source.commit, "label": row.label,
            })
        return Admitted(key, name)
