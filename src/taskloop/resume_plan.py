"""Select and recheck fresh implementation admission from durable plan evidence."""

from dataclasses import dataclass
from pathlib import Path

from git_porcelain import GitUnavailable

from taskloop.attempt_loads import PlanEvidence
from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptRecord, AttemptResult, Checkouts, Step
from taskloop.discussion import RefreshDiscussion
from taskloop.input_context import InputError
from taskloop.plan_reuse import ReuseDecision, evaluate
from taskloop.prepare import Prepared
from taskloop.task_content import TaskContentDigest
from taskloop.task_content_store import TaskContentStore


@dataclass(frozen=True)
class Selection:
    decision: ReuseDecision
    explanation: str
    plan: PlanEvidence | None = None

    @property
    def step(self) -> Step:
        return "implement" if self.decision is ReuseDecision.REUSE else "plan"


class ResumePlans:
    def __init__(self, store: AttemptStore, checkouts: Checkouts) -> None:
        self.store, self.checkouts = store, checkouts
        self.content = TaskContentStore(store.connect)

    def unchanged(self, selection: Selection, repo_id: str, backlog: str, task_id: str, tracker: str,
                  digest: TaskContentDigest | None) -> bool:
        plan = self.store.latest_plan(repo_id, backlog, task_id, tracker)
        return (plan == selection.plan and (selection.decision is not ReuseDecision.REUSE
                or (plan is not None and self.content.read(plan.key.attempt_id) == digest)))

    def required(self, record: AttemptRecord) -> bool:
        admission = record.admission
        return (admission.step == "implement" and record.start is None and admission.source_checks_id is None
                and self.store.previous_abandoned(admission.key))

    def select(
        self, repo_id: str, backlog: str, task_id: str, tracker_root: str, root: Path, source: str,
        digest: TaskContentDigest, *, git_dir: Path | None = None,
    ) -> Selection:
        plan = self.store.latest_plan(repo_id, backlog, task_id, tracker_root)
        if plan is None or self.content.read(plan.key.attempt_id) != digest:
            return Selection(ReuseDecision.PLAN, "No successful plan matches the current task content.", plan)
        path = f"docs/design/{task_id}/plan.md"
        try:
            repo = self.checkouts(root, git_dir=git_dir)
            tip = repo.tree(f"{source}^{{commit}}")
            if (tip is None or tip.files.get(path) != ("100644", plan.blob)
                    or repo.merge_base(plan.end_commit, source) != plan.end_commit):
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
        if discussion is None:
            return AttemptResult("unavailable", "input", explanation="Task-content validation is unavailable.")
        try:
            tracker = self.store.tracker_root(admission.key)
            if tracker is None:
                raise StoreUnavailable("The admitted tracker identity is unavailable.")
            snapshot = discussion(admission.task, tracker)
            selected = self.select(str(admission.repo_id), admission.task.scope.backlog, admission.task.task_id, tracker,
                                   Path(admission.slot_path), base.head, snapshot.digest, git_dir=base.gitdir)
        except (InputError, OSError) as error:
            return AttemptResult("unavailable", "input", explanation=str(error))
        if selected.decision is ReuseDecision.REUSE:
            return None
        status = "unavailable" if selected.decision is ReuseDecision.UNAVAILABLE else "refused"
        return AttemptResult(status, "input", explanation=selected.explanation)
