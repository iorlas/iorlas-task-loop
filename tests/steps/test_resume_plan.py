"""Fresh resumes reuse verified plans, with durable admission and entry fences."""

from collections.abc import Generator
from dataclasses import replace
from pathlib import Path

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome
from doubles import Environment, PinnedViews
from git_porcelain import GitUnavailable, Recorded
from git_porcelain.testing import FakeWorktree
from plan_fixtures import PLAN_TEXT
from round_bench import Factory, Tracker, scripted, scripts, task
from sqlite_store import Store

from taskloop.admit import AdmitRefused, AdmitRequest, Admitted, AdmitUnavailable, AttemptAdmission
from taskloop.agents.settings import AgentSetting, ClaudePolicy, Overrides, StepSettings
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import SlotFiles
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.harness_choice import HarnessKind
from taskloop.plan_reuse import PlanMetadata


@pytest.fixture
def plan_calls() -> list[str]:
    return []


@pytest.fixture
def resumable(
    tmp_path: Path, slot: FakeWorktree, checkouts: PinnedViews, slot_files: SlotFiles, plan_calls: list[str],
) -> Generator[Factory]:
    con = Store(SCHEMA).open_rw(tmp_path / "resume.db")
    assert con is not None
    factory = Factory(con, tmp_path, slot, checkouts, slot_files, Tracker(task("tl-1")))
    scripts(factory, slot, "tl-1")

    def plan(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        source = next(each.head for each in slot.repo.worktrees() if each.path == slot.path)
        assert source is not None
        plan_calls.append(str(source))
        path, metadata = "docs/design/tl-1/plan.md", "docs/design/tl-1/plan-metadata.json"
        run = scripted(slot.repo, {"disposition": "planned", "plan_path": path, "paths": [path, metadata],
                                  "message": "Plan", "explanation": "planned"},
                       {path: PLAN_TEXT, metadata: PlanMetadata(prepared_commit=str(source), cited_paths=("README",)).model_dump_json()})
        return run(harness, spec, timeout, hooks)

    factory.agents["tl-1", "plan"] = plan
    factory.agents["tl-1", "implement"] = scripted(
        slot.repo, {"disposition": "needs_owner", "paths": [], "message": None, "explanation": "Choose a shape"}, {})
    assert factory.round() == [("tl-1", "plan", "start", "started")]
    assert factory.round() == [("tl-1", "plan", "verify", "verified release=released branch=published")]
    assert factory.round() == [("tl-1", "implement", "advance", "started")]
    assert factory.round() == [("tl-1", "implement", "hold", "held failed:needs_owner")]
    yield factory
    factory.con.close()


def request(factory: Factory, settings: StepSettings | None = None, overrides: Overrides | None = None) -> AdmitRequest:
    return AdmitRequest("tl-1", "tasks", "/tracker", factory.slot.repo.path,
                        settings or StepSettings(), factory.now + 100, "auto", overrides or Overrides())


def steps(factory: Factory) -> list[tuple[str, int, int]]:
    return factory.con.execute("SELECT step,number,seq FROM attempt ORDER BY seq").fetchall()


def test_two_cleared_holds_reuse_the_plan_then_changed_content_replans(resumable: Factory, plan_calls: list[str]) -> None:
    factory = resumable
    for _ in range(2):
        factory.tracker.answer("tl-1")
        factory.round()
        assert factory.ran[-1] == "collected:needs_owner"
        assert steps(factory)[-1][0:2] == ("implement", 1)
        assert factory.round() == [("tl-1", "implement", "hold", "held failed:needs_owner")]
    assert len(plan_calls) == 1
    assert [row[0] for row in steps(factory)] == ["plan", "implement", "implement", "implement"]
    assert factory.con.execute("SELECT count(*) FROM task_content").fetchone() == (1,)
    bead = factory.tracker.beads["tl-1"]
    factory.tracker.beads["tl-1"] = replace(bead, description="A new requirement")
    factory.tracker.answer("tl-1")
    factory.round()
    assert steps(factory)[-1] == ("plan", 1, 5) and len(plan_calls) == 2


def test_resume_captures_implementation_prompt_settings_overrides_and_latest_answer(resumable: Factory) -> None:
    factory = resumable
    settings = StepSettings(plan=AgentSetting(model="plan-model"), implement=AgentSetting(
        harness=HarnessKind.CLAUDE, model="opus", effort="medium",
        access=ClaudePolicy(settings_file=Path("/settings.json"), settings="{}")))
    admitted = factory.starting().admission.admit(request(factory, settings, Overrides(harness=HarnessKind.CLAUDE, effort="high")))
    assert isinstance(admitted, Admitted)
    factory.con.close()
    reopened = Store(SCHEMA).open_rw(factory.tmp / "resume.db")
    assert reopened is not None
    factory.con, factory.store = reopened, AttemptStore(lambda: reopened)
    assert factory.store.register_entry(admitted.key, (7, "entry-start", "boot"), factory.now) == "accepted"
    record = factory.store.load(admitted.key)
    assert record is not None
    assert record.start is None and record.admission.number == 1
    assert record.admission.after_commit == factory.tip("tl-1")
    assert record.admission.setting == settings.implement.model_copy(update={"effort": "high"})
    text = EvidenceFiles(factory.tmp).read(record.admission.input_ref)
    assert "The plan for this task" in text and "Choose a shape" in text
    row = factory.con.execute("SELECT previous_attempt_id FROM attempt WHERE attempt_id=?", (admitted.key.attempt_id,)).fetchone()
    assert row == (None,)


def test_override_is_validated_for_selected_implementation(resumable: Factory) -> None:
    result = resumable.starting().admission.admit(request(resumable, overrides=Overrides(harness=HarnessKind.CLAUDE)))
    assert isinstance(result, AdmitRefused) and result.reason == "choices" and "matching per-step" in result.detail
    assert len(steps(resumable)) == 2


@pytest.mark.parametrize("change", ["digest", "blob", "verification", "revision", "latest"])
def test_changed_plan_evidence_during_claim_cannot_commit_stale_selection(resumable: Factory, change: str) -> None:
    factory = resumable
    admission = factory.starting().admission
    assert isinstance(admission, AttemptAdmission)
    claim = admission.claim

    def racing(root: str, task_id: str) -> bool:
        taken = claim(root, task_id)
        if change == "digest":
            # Production evidence is immutable; even an external corruption must not admit a stale digest.
            factory.con.execute("UPDATE task_content SET digest=?", ("0" * 64,))
        elif change == "blob":
            factory.con.execute("UPDATE verification SET blob=?", ("0" * 40,))
        elif change == "verification":
            factory.con.execute("UPDATE verification SET verdict='rejected',reason='paths',blob=NULL,reused=0")
        elif change == "revision":
            factory.con.execute("UPDATE attempt SET rev=rev+1 WHERE step='plan'")
        else:
            factory.con.execute("UPDATE attempt SET rev=rev+1 WHERE step='implement'")
        return taken

    admission.claim = racing
    result = admission.admit(request(factory))
    assert isinstance(result, AdmitRefused) and result.reason == "task_attempted"
    assert len(steps(factory)) == 2
    assert factory.con.execute("SELECT count(*) FROM reservation").fetchone() == (0,)
    assert factory.tracker.beads["tl-1"].assignee == ""


@pytest.mark.parametrize("change", ["content", "branch", "eligibility", "tracker_down", "git_down", "none"])
def test_entry_rechecks_after_database_reopen_before_setup_and_dispatch(
    resumable: Factory, change: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = resumable
    admitted = factory.starting().admission.admit(request(factory))
    assert isinstance(admitted, Admitted)
    factory.con.close()
    reopened = Store(SCHEMA).open_rw(factory.tmp / "resume.db")
    assert reopened is not None
    factory.con = reopened
    factory.store = AttemptStore(lambda: reopened)
    factory.environment = Environment(reopened, factory.checkouts, factory.tmp, tmp_bytes=4096)
    factory.merge_before_dispatch = True
    if change == "content":
        factory.tracker.beads["tl-1"] = replace(factory.tracker.beads["tl-1"], description="Changed after admission")
    elif change == "branch":
        factory.slot.checkout("task/tl-1")
        factory.slot.write_file("unrelated", "new tip")
        assert isinstance(factory.slot.record("new tip", paths="all"), Recorded)
    elif change == "eligibility":
        reopened.execute("UPDATE verification SET verdict='rejected',reason='paths',blob=NULL,reused=0")
    elif change == "tracker_down":
        factory.tracker.beads.clear()
    elif change == "git_down":
        monkeypatch.setattr(FakeWorktree, "diff", unavailable)
    before = reopened.execute("SELECT count(*) FROM setup_run").fetchone()
    factory.launch("tasks", "tl-1", 30)
    if change == "none":
        assert factory.ran[-1] == "collected:needs_owner"
    else:
        assert factory.ran[-1].startswith("unavailable:" if change in ("tracker_down", "git_down") else "refused:")
        assert reopened.execute("SELECT phase FROM attempt WHERE attempt_id=?", (admitted.key.attempt_id,)).fetchone() == ("admitted",)
        assert reopened.execute("SELECT count(*) FROM setup_run").fetchone() == before


@pytest.mark.parametrize("change", ["metadata", "cited", "deleted", "artifact", "failed_plan"])
def test_invalid_evidence_replans(resumable: Factory, change: str) -> None:
    factory = resumable
    if change == "failed_plan":
        # A newer failed planning attempt must hide the earlier successful one.
        factory.con.execute("UPDATE attempt SET step='plan',after_commit=NULL WHERE step='implement'")
    else:
        wt = factory.slot.repo.worktree(factory.slot.repo.path)
        wt.checkout("task/tl-1")
        if change == "metadata":
            wt.remove_file("docs/design/tl-1/plan-metadata.json")
        elif change == "deleted":
            wt.remove_file("README")
        elif change == "cited":
            wt.write_file("README", "changed")
        else:
            wt.write_file("docs/design/tl-1/plan.md", PLAN_TEXT + "\nChanged artifact\n")
        assert isinstance(wt.record("changed evidence", paths="all"), Recorded)
        wt.push("task/tl-1")
        wt.checkout("main")
    admitted = factory.starting().admission.admit(request(factory))
    assert isinstance(admitted, Admitted)
    assert steps(factory)[-1] == ("plan", 1, 3)


def unavailable(*_args: object, **_kwargs: object) -> None:
    raise GitUnavailable("evidence read failed")


def test_unavailable_git_evidence_prevents_admission_with_explanation(resumable: Factory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FakeWorktree, "diff", unavailable)
    result = resumable.starting().admission.admit(request(resumable))
    assert isinstance(result, AdmitUnavailable) and result.what == "git" and "evidence read failed" in result.detail
    assert len(steps(resumable)) == 2


