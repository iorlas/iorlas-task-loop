"""Decide plan reuse from committed evidence, without invoking an agent or changing Git."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

from git_porcelain import GitUnavailable, Repo, Tree, Worktree
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from taskloop import wip
from taskloop.attempt_types import MODE, Checkouts, Rejected, StepRules, Unreadable
from taskloop.steps import PLAN

METADATA_NAME = "plan-metadata.json"


class PlanMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    prepared_commit: str
    cited_paths: tuple[str, ...] = Field(min_length=1)

    @field_validator("prepared_commit")
    @classmethod
    def full_commit(cls, value: str) -> str:
        if len(value) not in (40, 64) or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("prepared_commit must be a full commit identifier")
        return value

    @field_validator("cited_paths")
    @classmethod
    def literal_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("cited_paths must be unique")
        for value in values:
            if (not value or value.startswith("/") or any(part in ("", ".", "..") for part in value.split("/"))
                    or any(char in ":*?[]\\" or ord(char) < 32 or ord(char) == 127 for char in value)):
                raise ValueError("cited_paths must be literal repository-relative files or folders")
        return values


class ReuseDecision(StrEnum):
    REUSE = "reuse"
    PLAN = "plan"
    UNAVAILABLE = "unavailable"


class ReuseReason(StrEnum):
    UNCHANGED = "unchanged"
    INVALID_PLAN = "invalid_plan"
    MISSING_METADATA = "missing_metadata"
    INVALID_METADATA = "invalid_metadata"
    MISSING_COMMIT = "missing_commit"
    SAVED_WORK = "saved_work"
    CITED_PATHS_CHANGED = "cited_paths_changed"
    GIT = "git"


@dataclass(frozen=True)
class ReuseResult:
    decision: ReuseDecision
    reason: ReuseReason
    explanation: str


def evaluate(checkouts: Checkouts, root: Path, plan_path: str, *, git_dir: Path | None = None) -> ReuseResult:
    """Read the plan and metadata at HEAD; a later admission owns acting on this observation."""
    location = PurePosixPath(plan_path)
    if (len(location.parts) != 4 or location.parts[:2] != ("docs", "design")
            or location.name != "plan.md" or str(location) != plan_path):
        return ReuseResult(ReuseDecision.PLAN, ReuseReason.INVALID_PLAN, "The committed plan location is invalid.")
    try:
        repo = checkouts(root, git_dir=git_dir)
        selected = next((each for each in repo.worktrees() if each.path == root), None)
        tip = None if selected is None or selected.head is None else repo.tree(f"{selected.head}^{{commit}}")
        if tip is None:
            return ReuseResult(ReuseDecision.PLAN, ReuseReason.MISSING_COMMIT, "The plan's current commit is absent.")
        return _evaluate(repo, repo.worktree(root), tip, PLAN.rules(location.parts[2]))
    except (GitUnavailable, Unreadable) as error:
        return ReuseResult(ReuseDecision.UNAVAILABLE, ReuseReason.GIT, f"Plan evidence could not be read: {error}")


def _metadata(tip: Tree, rules: StepRules) -> PlanMetadata | ReuseResult:
    path = rules.root + METADATA_NAME
    entry = tip.files.get(path)
    if entry is None:
        return ReuseResult(ReuseDecision.PLAN, ReuseReason.MISSING_METADATA, "The committed plan has no metadata.")
    if entry[0] != MODE:
        return ReuseResult(ReuseDecision.PLAN, ReuseReason.INVALID_METADATA, "Plan metadata must be a regular file.")
    data = tip.read(path)
    if data is None:
        raise Unreadable("The listed plan metadata could not be read.")
    if len(data) > rules.file_cap:
        return ReuseResult(ReuseDecision.PLAN, ReuseReason.INVALID_METADATA, "The committed plan metadata is too large.")
    try:
        return PlanMetadata.model_validate_json(data)
    except ValidationError as error:
        return ReuseResult(ReuseDecision.PLAN, ReuseReason.INVALID_METADATA, f"The committed plan metadata is invalid: {error}")


def _evaluate(repo: Repo, wt: Worktree, tip: Tree, rules: StepRules) -> ReuseResult:
    artifact = PLAN.artifact(tip, rules)
    if isinstance(artifact, Rejected):
        return ReuseResult(ReuseDecision.PLAN, ReuseReason.INVALID_PLAN, f"The committed plan failed validation: {artifact.reason}")
    metadata = _metadata(tip, rules)
    if isinstance(metadata, ReuseResult):
        return metadata
    prepared = repo.tree(f"{metadata.prepared_commit}^{{commit}}")
    if prepared is None or prepared.sha != metadata.prepared_commit:
        return ReuseResult(ReuseDecision.PLAN, ReuseReason.MISSING_COMMIT, "The plan's preparation commit is absent.")
    if wip.saved_since(repo, metadata.prepared_commit, str(tip.sha)):
        return ReuseResult(ReuseDecision.PLAN, ReuseReason.SAVED_WORK, "Newer saved unfinished work requires planning.")
    changed = wt.diff(metadata.prepared_commit, "HEAD", include=metadata.cited_paths, cap=0).changes
    if changed:
        return ReuseResult(ReuseDecision.PLAN, ReuseReason.CITED_PATHS_CHANGED, "Paths cited by the committed plan have changed.")
    return ReuseResult(
        ReuseDecision.REUSE, ReuseReason.UNCHANGED, "The committed plan's cited paths are unchanged, with no newer saved work.",
    )
