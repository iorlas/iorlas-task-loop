"""Select and recheck fresh implementation admission from durable plan evidence."""

from dataclasses import dataclass
from pathlib import Path

from git_porcelain import GitUnavailable

from taskloop.attempt_loads import PlanEvidence
from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import Admission, AttemptRecord, AttemptResult, Checkouts
from taskloop.discussion import RefreshDiscussion
from taskloop.input_context import InputError
from taskloop.plan_reuse import ReuseDecision, evaluate
from taskloop.prepare import Prepared
from taskloop.step import Step
from taskloop.task_content import TaskContentDigest
from taskloop.task_content_store import TaskContentStore


@dataclass(frozen=True)
class Selection:
    decision: ReuseDecision
    explanation: str
    plan: PlanEvidence | None = None
    declared: bool = False  # the run named its start step: the database holds no evidence the decision rests on

    @property
    def step(self) -> Step:
        return Step.IMPLEMENT if self.decision is ReuseDecision.REUSE else Step.PLAN


class ResumePlans:
    def __init__(self, store: AttemptStore, checkouts: Checkouts) -> None:
        self.store, self.checkouts = store, checkouts
        self.content = TaskContentStore(store.connect)

    def unchanged(
        self, selection: Selection, repo_id: str, backlog: str, task_id: str, tracker: str, digest: TaskContentDigest | None
    ) -> bool:
        plan = self.store.latest_plan(repo_id, backlog, task_id, tracker)
        return plan == selection.plan and (
            selection.declared
            or selection.decision is not ReuseDecision.REUSE
            or (plan is not None and self.content.read(plan.key.attempt_id) == digest)
        )

    def required(self, record: AttemptRecord) -> bool:
        admission = record.admission
        return (
            admission.step == Step.IMPLEMENT
            and record.start is None
            and admission.source_checks_id is None
            and (admission.declared_start or self.store.previous_abandoned(admission.key))
        )

    def select(
        self,
        repo_id: str,
        backlog: str,
        task_id: str,
        tracker_root: str,
        root: Path,
        source: str,
        digest: TaskContentDigest,
        *,
        git_dir: Path | None = None,
        start: Step | None = None,
    ) -> Selection:
        """Plan again or implement the committed plan. `start=IMPLEMENT` names the choice: only the plan committed at `source`
        counts (the database's plan evidence is not read for it), so the decision is REUSE or a refusal the caller reports."""
        plan = self.store.latest_plan(repo_id, backlog, task_id, tracker_root)
        if start is Step.IMPLEMENT:
            result = evaluate(self.checkouts, root, f"docs/design/{task_id}/plan.md", source=source, git_dir=git_dir)
            return Selection(result.decision, result.explanation, plan, declared=True)
        if plan is None or self.content.read(plan.key.attempt_id) != digest:
            return Selection(ReuseDecision.PLAN, "No successful plan matches the current task content.", plan)
        path = f"docs/design/{task_id}/plan.md"
        try:
            repo = self.checkouts(root, git_dir=git_dir)
            tip = repo.tree(f"{source}^{{commit}}")
            if tip is None or tip.files.get(path) != ("100644", plan.blob) or repo.merge_base(plan.end_commit, source) != plan.end_commit:
                return Selection(ReuseDecision.PLAN, "The selected source does not retain the recorded plan.", plan)
        except GitUnavailable as error:
            return Selection(ReuseDecision.UNAVAILABLE, f"Plan evidence could not be read: {error}", plan)
        result = evaluate(self.checkouts, root, path, source=source, git_dir=git_dir)
        return Selection(result.decision, result.explanation, plan)

    def entry(self, record: AttemptRecord, base: Prepared, discussion: RefreshDiscussion | None) -> AttemptResult | None:
        admission = record.admission
        if not self.required(record):
            return None
        if base.head != admission.after_commit:
            return AttemptResult("refused", "branch_moved", explanation="The selected plan source changed before entry.")
        if admission.declared_start:  # the run named its start: only the committed plan counts, as at admission
            return self._declared(admission, base)
        if discussion is None:
            return AttemptResult("unavailable", "input", explanation="Task-content validation is unavailable.")
        try:
            tracker = self.store.tracker_root(admission.key)
            if tracker is None:
                raise StoreUnavailable("The admitted tracker identity is unavailable.")
            snapshot = discussion(admission.task, tracker)
            selected = self.select(
                str(admission.repo_id),
                admission.task.scope.backlog,
                admission.task.task_id,
                tracker,
                Path(admission.slot_path),
                base.head,
                snapshot.digest,
                git_dir=base.gitdir,
            )
        except (InputError, OSError) as error:
            return AttemptResult("unavailable", "input", explanation=str(error))
        return self._judged(selected.decision, selected.explanation)

    def _declared(self, admission: Admission, base: Prepared) -> AttemptResult | None:
        path = f"docs/design/{admission.task.task_id}/plan.md"
        result = evaluate(self.checkouts, Path(admission.slot_path), path, source=base.head, git_dir=base.gitdir)
        return self._judged(result.decision, result.explanation)

    @staticmethod
    def _judged(decision: ReuseDecision, explanation: str) -> AttemptResult | None:
        """None when the committed plan is still the one to implement, else the entry's refusal."""
        if decision is ReuseDecision.REUSE:
            return None
        return AttemptResult("unavailable" if decision is ReuseDecision.UNAVAILABLE else "refused", "input", explanation=explanation)
