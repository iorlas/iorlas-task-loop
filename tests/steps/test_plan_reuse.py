"""Committed plan evidence decides reuse using one patch-free scoped diff and no execution."""

import json
from collections.abc import Sequence

import pytest
from doubles import PinnedViews
from git_porcelain import Diff, GitUnavailable, Recorded
from git_porcelain.testing import FakeRepo, FakeWorktree
from plan_fixtures import PLAN_TEXT
from pydantic import ValidationError

from taskloop.agents.launch import AgentLaunch
from taskloop.plan_reuse import PlanMetadata, ReuseDecision, ReuseReason, evaluate

PLAN_PATH = "docs/design/tl-1/plan.md"
METADATA_PATH = "docs/design/tl-1/plan-metadata.json"


def record(slot: FakeWorktree, message: str = "ordinary result") -> str:
    result = slot.record(message, paths="all", allow_empty=True)
    assert isinstance(result, Recorded)
    return str(result.sha)


@pytest.fixture
def planned(slot: FakeWorktree) -> PlanMetadata:
    slot.write_file("src/cited.py", "original\n")
    slot.write_file("src/folder/child.py", "original\n")
    prepared = record(slot, "source used for planning")
    metadata = PlanMetadata(prepared_commit=prepared, cited_paths=("src/cited.py", "src/folder"))
    slot.write_file(PLAN_PATH, PLAN_TEXT)
    slot.write_file(METADATA_PATH, metadata.model_dump_json())
    record(slot, "committed plan")
    return metadata


@pytest.mark.parametrize("change", ["none", "unrelated", "uncommitted", "file", "folder", "deleted", "folder_deleted"])
def test_only_committed_cited_changes_prevent_reuse_with_one_scoped_patch_free_diff(
    change: str, planned: PlanMetadata, repo: FakeRepo, slot: FakeWorktree, checkouts: PinnedViews,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if change in ("file", "folder", "unrelated", "uncommitted"):
        path = {"file": "src/cited.py", "folder": "src/folder/new.py"}.get(change, "other.py")
        slot.write_file(path, "changed\n")
    elif change in ("deleted", "folder_deleted"):
        slot.remove_file("src/cited.py" if change == "deleted" else "src/folder/child.py")
    if change not in ("none", "uncommitted"):
        record(slot)
    # Even a working copy edit of a cited path is not committed evidence.
    slot.write_file("src/cited.py", "working copy edit\n")
    before = repo.history(["HEAD"]), repo.worktrees(with_dirty=True)
    calls: list[tuple[str, str, tuple[str, ...], tuple[str, ...], int | None]] = []
    original = FakeWorktree.diff

    def diff(
        wt: FakeWorktree, a: str, b: str, *, include: Sequence[str] = (), exclude: Sequence[str] = (), cap: int | None = None,
    ) -> Diff:
        calls.append((a, b, tuple(include), tuple(exclude), cap))
        result = original(wt, a, b, include=include, exclude=exclude, cap=cap)
        assert result.patch == ""
        return result

    def unexpected_agent(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Plan validation must make zero model calls")

    monkeypatch.setattr(AgentLaunch, "build", unexpected_agent)
    monkeypatch.setattr(FakeWorktree, "diff", diff)
    gitdir = checkouts.common / "worktrees" / slot.path.name
    result = evaluate(checkouts, slot.path, PLAN_PATH, git_dir=gitdir)
    changed = change in ("file", "folder", "deleted", "folder_deleted")
    assert result.decision is (ReuseDecision.PLAN if changed else ReuseDecision.REUSE)
    assert result.reason is (ReuseReason.CITED_PATHS_CHANGED if changed else ReuseReason.UNCHANGED)
    assert result.explanation
    assert calls == [(planned.prepared_commit, "HEAD", planned.cited_paths, (), 0)]
    assert (repo.history(["HEAD"]), repo.worktrees(with_dirty=True)) == before
    tip = next(each.head for each in repo.worktrees() if each.path == slot.path)
    assert tip is not None
    tree = repo.tree(str(tip))
    assert tree is not None and tree.read(METADATA_PATH) == planned.model_dump_json().encode()


@pytest.mark.parametrize(("fault", "reason"), [
    ("missing_metadata", ReuseReason.MISSING_METADATA),
    ("malformed_metadata", ReuseReason.INVALID_METADATA),
    ("missing_commit", ReuseReason.MISSING_COMMIT),
    ("missing_plan", ReuseReason.INVALID_PLAN),
    ("invalid_plan", ReuseReason.INVALID_PLAN),
    ("saved_work", ReuseReason.SAVED_WORK),
])
def test_invalid_evidence_requires_planning_without_a_diff(
    fault: str, reason: ReuseReason, planned: PlanMetadata, slot: FakeWorktree, checkouts: PinnedViews,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if fault == "missing_metadata":
        slot.remove_file(METADATA_PATH)
    elif fault == "malformed_metadata":
        slot.write_file(METADATA_PATH, "{broken")
    elif fault == "missing_commit":
        slot.write_file(METADATA_PATH, planned.model_copy(update={"prepared_commit": "f" * 40}).model_dump_json())
    elif fault == "missing_plan":
        slot.remove_file(PLAN_PATH)
    elif fault == "invalid_plan":
        slot.write_file(PLAN_PATH, " ")
    record(slot, "unfinished\n\nTask-Loop-Wip: attempt" if fault == "saved_work" else "change evidence")
    if fault == "saved_work":
        record(slot, "ordinary commit above unfinished work")

    def unexpected_diff(*_args: object, **_kwargs: object) -> Diff:
        pytest.fail("Invalid evidence must not reach the diff")

    monkeypatch.setattr(FakeWorktree, "diff", unexpected_diff)
    gitdir = checkouts.common / "worktrees" / slot.path.name
    result = evaluate(checkouts, slot.path, PLAN_PATH, git_dir=gitdir)
    assert (result.decision, result.reason) == (ReuseDecision.PLAN, reason)
    assert result.explanation


def test_uncommitted_metadata_cannot_supply_missing_evidence(
    planned: PlanMetadata, slot: FakeWorktree, checkouts: PinnedViews,
) -> None:
    slot.remove_file(METADATA_PATH)
    record(slot)
    slot.write_file(METADATA_PATH, planned.model_dump_json())
    gitdir = checkouts.common / "worktrees" / slot.path.name
    assert evaluate(checkouts, slot.path, PLAN_PATH, git_dir=gitdir).reason is ReuseReason.MISSING_METADATA


@pytest.mark.parametrize("operation", ["read", "diff"])
def test_git_failure_is_explicit_and_does_not_suggest_reuse(
    operation: str, planned: PlanMetadata, slot: FakeWorktree, checkouts: PinnedViews, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*_args: object, **_kwargs: object) -> Diff:
        raise GitUnavailable("observation failed")

    monkeypatch.setattr(FakeRepo if operation == "read" else FakeWorktree, "tree" if operation == "read" else "diff", unavailable)
    gitdir = checkouts.common / "worktrees" / slot.path.name
    result = evaluate(checkouts, slot.path, PLAN_PATH, git_dir=gitdir)
    assert (result.decision, result.reason) == (ReuseDecision.UNAVAILABLE, ReuseReason.GIT)
    assert "observation failed" in result.explanation


@pytest.mark.parametrize("paths", [
    [], ["src/a", "src/a"], ["/src/a"], ["../a"], ["src/../a"], ["./src"], ["src//a"], ["src/"],
    [":(glob)src"], ["src/*.py"], ["src/?.py"], ["src/[ab].py"], ["src\\a"], ["src/\na"], [""],
])
def test_metadata_rejects_empty_duplicate_and_nonliteral_citations(paths: list[str]) -> None:
    with pytest.raises(ValidationError):
        PlanMetadata.model_validate_json(json.dumps({"prepared_commit": "a" * 40, "cited_paths": paths}))


@pytest.mark.parametrize("commit", ["HEAD", "abcd123", "g" * 40, "a" * 41])
def test_metadata_requires_a_full_commit_identifier(commit: str) -> None:
    with pytest.raises(ValidationError):
        PlanMetadata(prepared_commit=commit, cited_paths=("src",))


def test_metadata_accepts_literal_spaces_and_rejects_extra_fields() -> None:
    metadata = PlanMetadata(prepared_commit="a" * 40, cited_paths=("src/a file.py",))
    with pytest.raises(ValidationError):
        PlanMetadata.model_validate_json(metadata.model_dump_json()[:-1] + ', "extra": true}')
