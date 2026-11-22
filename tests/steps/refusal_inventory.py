"""Producer census, independent of presentation tables; dynamic edges are explicitly reviewed below."""

import ast
from pathlib import Path

from taskloop.attempt_types import CommitWaitingReason
from taskloop.publish import PublishRefusalReason
from taskloop.recovery.models import Outcome
from taskloop.release_proof import RecoveryReason

ROOT = Path(__file__).resolve().parents[2] / "src" / "taskloop"
# Argument carrying a refusal reason, including helpers that construct owning results.
PRODUCERS = {
    "Failed": 1,
    "AdmitRefused": 0,
    "AdmitUnavailable": 0,
    "LaunchRefused": 0,
    "LaunchUnavailable": 0,
    "CommitRefused": 0,
    "CommitWaiting": 0,
    "NotApplicable": 0,
    "Uncommitted": 0,
    "NotReleased": 1,
    "NotPublished": 1,
    "_refused": 0,
    "_unavailable": 0,
    "StoreRefused": 0,
    "Rejected": 0,
}


def census() -> tuple[set[tuple[str, str]], set[tuple[str, str, str]]]:
    literals: set[tuple[str, str]] = set()
    dynamic: set[tuple[str, str, str]] = set()
    for path in ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text())
        constants = {
            node.target.id: node.value
            for node in tree.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and isinstance(node.annotation, ast.Name)
            and node.annotation.id == "Final"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            index = 0 if path.name == "wip.py" and node.func.id == "Refused" else PRODUCERS.get(node.func.id)
            if index is None:
                continue
            reason = (
                node.args[index]
                if len(node.args) > index
                else next((keyword.value for keyword in node.keywords if keyword.arg == "reason"), None)
            )
            if reason is None:
                continue
            if isinstance(reason, ast.Name) and reason.id in constants:
                reason = constants[reason.id]
            if isinstance(reason, ast.Constant) and isinstance(reason.value, str):
                context = "land" if path.name.startswith("land_") or path.name == "land.py" or "land_conflict" in path.parts else "step"
                literals.add((context, reason.value))
            else:
                dynamic.add((str(path.relative_to(ROOT)), node.func.id, ast.unparse(reason)))
    return literals, dynamic


def typed_reasons() -> set[str]:
    """Read owning finite aliases and fields, rather than copying their values into the guides' test."""
    aliases = {"admit.py": {"Refusal"}, "attempt_types.py": {"Rule"}}
    fields = {"launch.py": {"LaunchRefused", "LaunchUnavailable"}}
    reasons: set[str] = set()
    for name, names in aliases.items():
        for node in ast.walk(ast.parse((ROOT / name).read_text())):
            if isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name) and node.name.id in names:
                reasons.update(n.value for n in ast.walk(node.value) if isinstance(n, ast.Constant) and isinstance(n.value, str))
            if name == "attempt_types.py" and isinstance(node, ast.ClassDef) and node.name == "PlanContentRule":
                reasons.update(
                    n.value
                    for field in node.body
                    if isinstance(field, ast.Assign)
                    for n in ast.walk(field.value)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                )
    for name, names in fields.items():
        for node in ast.walk(ast.parse((ROOT / name).read_text())):
            if not isinstance(node, ast.ClassDef) or node.name not in names:
                continue
            for field in node.body:
                if isinstance(field, ast.AnnAssign) and isinstance(field.target, ast.Name) and field.target.id == "reason":
                    reasons.update(n.value for n in ast.walk(field.annotation) if isinstance(n, ast.Constant) and isinstance(n.value, str))
    return (
        reasons
        | {reason.value for reason in RecoveryReason}
        | {str(reason) for reason in CommitWaitingReason}
        | {reason.value for reason in PublishRefusalReason}
    )


# Forwarded values originate in admission, launch, store, factory commit, publication,
# release and status domains covered by census()/typed_reasons(). Expressions that
# build a domain (slot state, environment, session, end_word, Git errors) have explicit
# rendered cases in DYNAMIC_REASONS. A new expression or forwarding site fails review.
REVIEWED_DYNAMIC = {
    ("admit.py", "AdmitRefused", "Reason.DRAINING"),
    ("admit.py", "AdmitRefused", "found"),
    ("admit.py", "AdmitRefused", "'workflow' if isinstance(error, WorkflowRefusal) else 'input'"),
    ("admit_chain.py", "AdmitRefused", "Reason.DRAINING"),
    ("admit_chain.py", "AdmitRefused", "'workflow' if isinstance(error, WorkflowRefusal) else 'input'"),
    ("answer_repair_route.py", "Failed", "RepairReason.ADMISSION"),
    ("answer_repair_route.py", "Failed", "result.reason"),  # captured answer failures, listed in DYNAMIC_REASONS
    ("attempt_loads.py", "Rejected", "rule"),
    ("check_admit.py", "AdmitRefused", "Reason.DRAINING"),
    ("check_release.py", "NotReleased", "Reason.DRAINING"),
    ("check_repeat/repair.py", "Failed", "FeedbackReason.EVIDENCE"),
    ("check_repeat/repair.py", "Failed", "FeedbackReason.PROFILE"),
    ("check_repeat/repair.py", "Failed", "admitted.reason"),
    ("check_repeat/repair.py", "Failed", "error.reason"),
    ("check_repeat/repair.py", "Failed", "free.reason"),
    ("check_repeat/repair.py", "Failed", "reason"),
    ("check_repeat/repair.py", "Failed", "stopped.reason"),
    ("check_repeat/repair.py", "Failed", "task.reason if isinstance(task, AdmitRefused) else task.what"),
    ("check_repeat/store.py", "AdmitRefused", "Reason.DRAINING"),
    ("checks.py", "_refused", "f'expired:{check.name}'"),
    ("cli_composition.py", "Failed", "Reason.DRAINING"),
    ("cli_land.py", "Failed", "INTERRUPTED"),
    ("land.py", "Failed", "'task' if isinstance(read, AdmitRefused) else 'tracker'"),
    ("land.py", "Failed", "Reason.DRAINING"),
    ("land.py", "Failed", "checked.what"),
    ("land.py", "Failed", "refused.reason"),
    ("land_check.py", "Failed", "'land_running' if seen == 'matching' else 'observe'"),
    ("land_check.py", "Failed", "ended.reason"),
    ("land_check.py", "Failed", "free.reason if isinstance(free, AdmitRefused) else free.what"),
    ("land_check.py", "Failed", "refused.reason"),
    ("land_check.py", "Failed", "refused_by.reason"),
    ("land_check.py", "Failed", "result.reason"),
    ("land_close.py", "_refused", "row"),
    ("land_conflict/handoff.py", "Failed", "outcome.value if kind == 'unavailable' else 'conflict'"),
    ("land_conflict/handoff.py", "Failed", "result.reason.value"),
    ("land_summary.py", "Failed", "'profile' if kind == 'refused' else 'git'"),
    ("land_target.py", "Failed", "found.reason"),
    ("launch.py", "LaunchRefused", "Reason.DRAINING"),
    ("launch.py", "LaunchRefused", "authorized.outcome"),
    ("launch.py", "LaunchRefused", "'registration_conflict' if answer == 'conflict' else 'registration_refused'"),
    ("launch.py", "LaunchUnavailable", "'exec_failed_after_commit' if committed else 'start'"),
    ("operations.py", "Failed", "'abandoned' if row.abandoned else found[1]"),
    ("operations.py", "Failed", "FeedbackReason.EVIDENCE"),
    ("operations.py", "Failed", "admitted.reason"),
    ("operations.py", "Failed", "admitted.what"),
    ("operations.py", "Failed", "error.reason"),
    ("operations.py", "Failed", "first.reason"),
    ("operations.py", "Failed", "land.reason"),
    ("operations.py", "Failed", "refused.reason"),
    ("operations.py", "Failed", "result.reason"),
    ("plan_step.py", "Rejected", "broken"),
    ("prepare.py", "_refused", "'branch_moved' if moved else 'branch_diverged'"),
    ("prepare.py", "_refused", "f'slot_{problem}'"),
    ("prepare.py", "_refused", "found"),
    ("publish.py", "NotPublished", "'abandoned' if gone else 'changed'"),
    ("publish.py", "NotPublished", "reason"),
    ("publish.py", "_refused", "PublishRefusalReason.NOT_COMMITTED"),
    ("publish.py", "_refused", "Reason.DRAINING"),
    ("repeat.py", "Failed", "admitted.reason"),
    ("repeat.py", "Failed", "admitted.what"),
    ("repeat.py", "Failed", "alive.reason"),
    ("repeat.py", "Failed", "error.reason"),
    ("round.py", "Failed", "'abandoned' if ended.abandoned else 'released'"),
    ("round.py", "Failed", "Reason.DRAINING"),
    ("slot_release.py", "NotReleased", "Reason.DRAINING"),
    ("slot_release.py", "NotReleased", "reason"),
    ("slot_park.py", "NotReleased", "reason"),
    ("slot_park.py", "NotReleased", "parked.reason.value"),
    ("slot_park.py", "NotReleased", "refused.reason.value"),
    ("release_proof.py", "NotReleased", "RecoveryReason.RUNNING"),
    ("release_proof.py", "NotReleased", "RecoveryReason.UNKNOWN"),
    ("wip.py", "Refused", "SaveReason.MERGE_CHANGED"),
    ("wip.py", "Refused", "SaveReason.MERGE_INPUTS"),
    ("wip.py", "Refused", "SaveReason.MERGE_PENDING"),
    ("wip.py", "Refused", "SaveReason.REF_MOVED"),
    ("verdict.py", "Rejected", "broken"),
    ("commit.py", "NotApplicable", "end_word(stored)"),
    ("commit_failure.py", "Failed", "reason"),
    ("commit_failure.py", "Failed", "result.reason"),
    ("commit.py", "CommitRefused", "'absent' if record is None else 'no_base'"),
    ("commit.py", "CommitRefused", "Reason.DRAINING"),
    ("commit.py", "CommitRefused", "str(error)"),
    ("commit.py", "CommitRefused", "'session' if stored.session_state == 'conflict' else 'session_fault'"),
    ("factory_commit.py", "CommitRefused", "'unborn' if head is None else 'branch'"),
    ("factory_commit.py", "CommitRefused", "'unborn' if state.head is None else 'branch'"),
    ("factory_commit.py", "CommitRefused", "problem"),
    ("commit.py", "CommitWaiting", "CommitWaitingReason.VALIDATION_PENDING"),
    ("commit.py", "CommitWaiting", "CommitWaitingReason.SESSION_PENDING"),
    ("commit.py", "CommitWaiting", "CommitWaitingReason.OBSERVE"),
    ("commit.py", "CommitWaiting", "CommitWaitingReason.STORE"),
    ("commit.py", "CommitWaiting", "CommitWaitingReason.GIT"),
    ("commit.py", "CommitWaiting", "CommitWaitingReason.WORKER_ALIVE"),
    ("commit.py", "CommitWaiting", "LOCK_WORDS[type(error)]"),
    ("commit.py", "CommitWaiting", "CommitWaitingReason(reason)"),
    ("repeat.py", "CommitWaiting", "CommitWaitingReason.WORKER_ALIVE"),
}

DYNAMIC_REASONS = {
    "answer_repair",
    "draining",
    "drained",
    "idle",
    "check_feedback",
    "check_profile",
    "interrupted",
    "released",
    "land_running",
    "branch",
    "unborn",
    "slot_branch",
    "slot_redirected",
    "slot_dirty",
    "head_moved",
    "repo",
    "not_listed",
    "dirty",
    "slot_head_moved",
    "ref_moved",
    "slot:branch",
    "slot:moved",
    "slot:redirected",
    "expired:check-name",
    "read_only",
    "session_pending",
    "session_fault",
    "git:GitReadFailure",
    "git:GitTimeout",
    "git:GitUnavailable",
    "git:Unreadable",
    "run:timeout",
    "run:exit",
    "answer:missing",
    "answer:json_invalid",
    "answer:schema_invalid",
    "answer:validation_pending",
    "incomplete",
    "needs_owner",
    "environment:dirty",
    "environment:failed",
    "environment:moved",
    "environment:path_long",
    "environment:platform",
    "environment:profile",
    "environment:remove_unsafe",
    "environment:reset",
    "environment:roots",
    "environment:sandbox",
    "environment:exit",
    "environment:files",
    "environment:lingering",
    "environment:running",
    "environment:uncertain",
    "environment:unknown",
    "checks:uncertain",
}
DYNAMIC_REASONS |= {
    outcome.value
    for outcome in Outcome
    if outcome
    not in {
        Outcome.AUTHORIZED,
        Outcome.INTENDED,
        Outcome.REGISTERED,
        Outcome.ACCEPTED,
    }
}
