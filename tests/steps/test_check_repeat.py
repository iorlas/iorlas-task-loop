"""Check-driven repeats through start and rounds, with real SQLite, admission, dispatch, verification and publication."""

import json
from collections.abc import Generator
from dataclasses import replace
from pathlib import Path

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome
from check_repeat_bench import ASSERTION, Repairing
from doubles import MAIN_PROFILE, PinnedViews
from git_porcelain import Recorded
from git_porcelain.testing import FakeWorktree
from round_bench import Tracker, scripted, scripts, task
from sqlite_store import Store
from test_checks_round import implemented

from taskloop.admit import AdmitRefused, Admitted, Free
from taskloop.agents.config import resolve_agents
from taskloop.agents.settings import Overrides
from taskloop.attempt_status import current_view, list_attempts, show_attempt
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, FileRef, SlotFiles, Unsettled
from taskloop.check_admit import ChecksRequest
from taskloop.check_repeat.feedback import FailedCheck
from taskloop.check_repeat.status import CheckRepeatDecision, decision
from taskloop.check_repeat.store import CheckRepeatStore
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.harness_choice import HarnessKind
from taskloop.launch import LaunchUnavailable
from taskloop.operations import Failed, Round, Started, release_task, start
from taskloop.round import NextRequest, run_round
from taskloop.setup_store import SetupStore
from taskloop.steps import kind


@pytest.fixture
def rig(tmp_path: Path, slot: FakeWorktree, checkouts: PinnedViews, slot_files: SlotFiles) -> Generator[Repairing]:
    root = slot.repo.worktree(slot.repo.identity().root)
    root.write_file(".task-loop.json", json.dumps(MAIN_PROFILE))
    assert isinstance(root.record("profile", paths="all"), Recorded)
    path = tmp_path / "factory.db"
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    built = Repairing(path, con, tmp_path, slot, checkouts, slot_files, Tracker(task("tl-1")))
    scripts(built, slot, "tl-1")
    yield built
    con.close()


def failed(rig: Repairing, body: str = "failed") -> tuple[AttemptKey, AttemptKey]:
    implemented(rig)
    previous = rig.store.attempts("tasks", "tl-1")[0].key
    rig.bodies = [body]
    assert rig.round() == [("tl-1", "check", "advance", "started")]
    return previous, rig.key("tl-1")


def repair_agent(rig: Repairing, *, change: bool = False) -> list[LaunchSpec]:
    specs: list[LaunchSpec] = []
    answer = {"disposition": "implemented" if change else "unchanged", "paths": ["src/fix.py"] if change else [],
              "message": "Fix columns" if change else None, "explanation": "Ran checks"}
    agent = scripted(rig.slot.repo, answer, {"src/fix.py": "fixed = True\n"} if change else {})

    def run(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        specs.append(spec)
        return agent(harness, spec, timeout, hooks)

    rig.agents["tl-1", "implement"] = run
    return specs


@pytest.mark.parametrize("change", [False, True])
def test_start_dispatches_failed_check_output_at_x_and_fresh_checks_can_pass(rig: Repairing, change: bool) -> None:
    previous, source = failed(rig, "unreleased_failed")
    assert rig.next_words() == {"tl-1": ("check", "release")} and not rig.tracker.holds
    released = release_task(rig.store, rig.releaser(), rig.releasing(), "tasks", "tl-1", abandon=False)
    assert not isinstance(released, Failed)
    x = rig.tip("tl-1")
    specs = repair_agent(rig, change=change)
    result = start(rig.starting(), rig.request())
    assert isinstance(result, Started) and result.step == "implement"
    (spec,) = specs
    assert "Failed check\n" in spec.stdin and "Check: test" in spec.stdin
    assert 'Command argv: ["just", "test"]' in spec.stdin and all(line in spec.stdin for line in ASSERTION.splitlines())
    assert "Widget tl-1" in spec.stdin and "docs/design/tl-1/plan.md" in spec.stdin
    assert "List only your new changes" in spec.stdin
    assert "--resume" not in spec.argv and "changed-model" not in spec.argv
    row = rig.store.attempts("tasks", "tl-1")[0]
    assert (row.number, row.previous_attempt_id, row.source_checks_id) == (2, previous.attempt_id, source.attempt_id)
    assert row.label == "auto" and row.run is not None and row.run.model == "m"
    assert rig.con.execute("SELECT base_commit,after_commit FROM attempt WHERE attempt_id=?", (row.key.attempt_id,)).fetchone() == (x, x)
    assert rig.ran[-1] == "pending:verification"
    setup = SetupStore(lambda: rig.con).latest(row.key)
    assert setup is not None and setup.commit == x and setup.conclusion == "passed"
    assert rig.round() == [("tl-1", "implement", "verify", "verified release=released branch=published")]
    rig.bodies = ["passed"]
    assert rig.round() == [("tl-1", "check", "advance", "started")]
    assert rig.next_words() == {"tl-1": ("check", "land")}
    assert len(rig.rows()) == 2 and rig.tracker.claims == ["tl-1"] and not rig.tracker.holds


def test_rounds_share_the_implement_cap_and_hold_once_after_three_attempts(rig: Repairing) -> None:
    failed(rig)
    repair_agent(rig)
    for number in (2, 3):
        assert rig.next_words() == {"tl-1": ("check", "repeat")}
        assert rig.round() == [("tl-1", "implement", "repeat", "started")]
        assert rig.store.attempts("tasks", "tl-1")[0].number == number and not rig.tracker.holds
        rig.round()  # verify, release, publish
        rig.bodies = ["failed"]
        rig.round()
    assert rig.next_words() == {"tl-1": ("check", "hold")}
    assert rig.round() == [("tl-1", "check", "hold", "held failed:test:failed")]
    assert rig.round() == [] and len(rig.tracker.comments) == 1


def test_restart_after_admission_uses_one_successor_and_the_captured_input(rig: Repairing) -> None:
    previous, source = failed(rig)
    rig.failing = LaunchUnavailable("start")
    first = start(rig.starting(), rig.request())
    assert isinstance(first, Failed)
    row = rig.store.attempts("tasks", "tl-1")[0]
    files = EvidenceFiles(rig.tmp)
    prompt = files.text(row.key, "input.txt")
    files.check_log(source, 1, "test").write_text("different output after admission\n")
    specs = repair_agent(rig)
    # A losing caller with the old source adopts the admitted successor; the normal restart does too.
    repair = rig.starting().check_repeat
    assert repair is not None
    second = repair.repair(rig.request(), previous, source)
    assert isinstance(second, Started) and second.attempt_id == row.key.attempt_id and len(specs) == 1
    assert prompt is not None and specs[0].stdin.startswith(prompt) and all(line in specs[0].stdin for line in ASSERTION.splitlines())
    assert len(rig.store.attempts("tasks", "tl-1")) == 3  # plan, implement, repeat


@pytest.mark.parametrize("condition", ["held", "abandoned", "old", "cap", "running", "claim_lost", "branch_moved"])
def test_ineligible_or_changed_sources_never_launch_an_implement_repeat(rig: Repairing, condition: str) -> None:
    previous, source = failed(rig)
    if condition == "held":
        rig.con.execute("INSERT INTO task_hold (attempt_id,cause_id,reason,held_at) VALUES (?,?,?,?)",
                        (previous.attempt_id, source.attempt_id, "explicit", rig.now))
    elif condition == "abandoned":
        rig.con.execute("UPDATE checks_attempt SET abandoned=1")
    elif condition == "old":
        rig.bodies = ["passed"]
        assert isinstance(rig.starting().checks.admission.admit_checks(
            ChecksRequest(previous, rig.slot.repo.path, 1000, 2)), Admitted)
    elif condition == "cap":
        # The shared decision uses the implement number, regardless of the checks attempt's number.
        row = rig.checks.row(source)
        assert row is not None
        assert decision(3, row, rig.checks.results(source)) is CheckRepeatDecision.EXHAUSTED
        return
    elif condition == "running":
        row = rig.checks.row(source)
        assert row is not None and row.entry is not None
        rig.alive.add(row.entry)
    elif condition == "claim_lost":
        rig.tracker.beads["tl-1"] = replace(rig.tracker.beads["tl-1"], assignee="person")
    else:
        root = rig.slot.repo.worktree(rig.slot.repo.path)
        root.checkout("task/tl-1")
        root.write_file("owner.txt", "keep")
        root.record("owner", paths="all")
        root.checkout("main")
    specs = repair_agent(rig)
    repair = rig.starting().check_repeat
    assert repair is not None
    result = repair.repair(rig.request(), previous, source)
    assert isinstance(result, Failed) and not specs
    assert rig.store.attempts("tasks", "tl-1")[0].key == previous


def test_command_uses_checked_commit_after_main_and_worktree_profile_changes(rig: Repairing) -> None:
    failed(rig)
    root = rig.slot.repo.worktree(rig.slot.repo.path)
    changed = {**MAIN_PROFILE, "checks": [{"name": "test", "argv": ["wrong", "command"], "timeout": 10}]}
    root.write_file(".task-loop.json", json.dumps(changed))
    root.record("new profile on main", paths="all")
    specs = repair_agent(rig)
    result = start(rig.starting(), rig.request())
    assert isinstance(result, Started) and 'Command argv: ["just", "test"]' in specs[0].stdin


def test_mismatched_profile_refuses_before_admission_and_never_fabricates_command(rig: Repairing) -> None:
    previous, source = failed(rig)
    rig.con.execute("UPDATE checks_attempt SET profile_digest=?", ("0" * 64,))
    specs = repair_agent(rig)
    result = start(rig.starting(), rig.request())
    assert isinstance(result, Failed) and result.reason == "check_profile" and not specs
    assert CheckRepeatStore(lambda: rig.con).state(previous, source) is not None


def test_required_order_selects_one_failure_and_optional_failure_alone_does_not_repeat(rig: Repairing) -> None:
    previous, source = failed(rig)
    rig.con.execute("UPDATE check_result SET conclusion='failed',rc=1")  # includes the optional check
    row = rig.checks.row(source)
    assert row is not None
    # Required order differs from both the command order and display order.
    rig.con.execute("UPDATE checks_attempt SET required=?", (json.dumps(list(reversed(row.required))),))
    specs = repair_agent(rig)
    assert isinstance(start(rig.starting(), rig.request()), Started)
    assert "Check: test\n" in specs[0].stdin and "Check: slow\n" not in specs[0].stdin
    # The same structured evidence with only an optional failure is ineligible.
    results = tuple(replace(each, conclusion="failed" if each.name == "slow" else "passed",
                            rc=1 if each.name == "slow" else 0) for each in rig.checks.results(source))
    assert decision(1, row, results) is CheckRepeatDecision.INELIGIBLE
    assert previous != rig.store.attempts("tasks", "tl-1")[0].key


@pytest.mark.parametrize("cause", ["main_moved", "expired", "setup:failed", "profile:missing"])
def test_infrastructure_causes_with_old_test_results_do_not_trigger_repair(rig: Repairing, cause: str) -> None:
    _, source = failed(rig)
    row = rig.checks.row(source)
    assert row is not None
    assert decision(1, replace(row, reason=cause), rig.checks.results(source)) is CheckRepeatDecision.INELIGIBLE


def test_a_released_check_with_a_command_still_alive_cannot_launch_repair(rig: Repairing) -> None:
    previous, source = failed(rig)
    rig.con.execute("UPDATE check_result SET pid=900,pgid=900,proc_start='start-900',boot='boot' WHERE name='test'")
    rig.groups[900] = "alive"
    specs = repair_agent(rig)
    result = start(rig.starting(), rig.request())
    assert isinstance(result, Failed) and result.reason == "check_running" and not specs
    assert rig.store.attempts("tasks", "tl-1")[0].key == previous
    assert rig.checks.row(source) is not None


def test_no_clean_slot_is_transient_and_does_not_hold_the_task(rig: Repairing) -> None:
    failed(rig)
    repair_agent(rig)
    rig.slot.write_file("owner-scratch.txt", "keep")
    rig.round()
    assert rig.last.stopped == "no_free_slot" and not rig.tracker.holds
    assert rig.next_words() == {"tl-1": ("check", "repeat")}
    rig.slot.remove_file("owner-scratch.txt")
    assert rig.round() == [("tl-1", "implement", "repeat", "started")]


@pytest.mark.parametrize("after", [False, True])
def test_crash_before_or_after_admission_continues_without_spending_an_extra_attempt(
    rig: Repairing, monkeypatch: pytest.MonkeyPatch, after: bool
) -> None:
    failed(rig)
    specs = repair_agent(rig)
    original = CheckRepeatStore.admit

    def crash(self: CheckRepeatStore, previous: AttemptKey, evidence: FailedCheck, key: AttemptKey, ref: FileRef,
              free: tuple[Free, ...], deadline: float) -> Admitted | AdmitRefused:
        if after:
            original(self, previous, evidence, key, ref, free, deadline)
        raise RuntimeError("coordinator died")

    monkeypatch.setattr(CheckRepeatStore, "admit", crash)
    with pytest.raises(RuntimeError, match="coordinator died"):
        start(rig.starting(), rig.request())
    monkeypatch.setattr(CheckRepeatStore, "admit", original)
    result = start(rig.starting(), rig.request())
    assert isinstance(result, Started) and len(specs) == 1
    assert [row.number for row in rig.store.attempts("tasks", "tl-1") if row.step == "implement"] == [2, 1]


def test_overlapping_starts_adopt_one_successor(rig: Repairing, monkeypatch: pytest.MonkeyPatch) -> None:
    failed(rig)
    specs = repair_agent(rig)
    original = CheckRepeatStore.admit
    winners: list[Started | Failed] = []

    def competing(self: CheckRepeatStore, previous: AttemptKey, evidence: FailedCheck, key: AttemptKey, ref: FileRef,
                  free: tuple[Free, ...], deadline: float) -> Admitted | AdmitRefused:
        monkeypatch.setattr(CheckRepeatStore, "admit", original)
        winners.append(start(rig.starting(), rig.request()))
        return original(self, previous, evidence, key, ref, free, deadline)

    monkeypatch.setattr(CheckRepeatStore, "admit", competing)
    result = start(rig.starting(), rig.request())
    assert isinstance(result, Started) and isinstance(winners[0], Started)
    assert result.attempt_id == winners[0].attempt_id and len(specs) == 1
    assert len([row for row in rig.store.attempts("tasks", "tl-1") if row.source_checks_id is not None]) == 1


def test_a_prior_path_repeat_consumes_the_same_budget(rig: Repairing) -> None:
    rig.round()  # plan
    rig.round()  # verify, release, publish
    rig.agents["tl-1", "implement"] = scripted(rig.slot.repo, {
        "disposition": "implemented", "paths": ["src/x.py"], "message": "Implement", "explanation": "ran checks",
    }, {"src/x.py": "x = 1\n", "scratch.txt": "leftover"})
    rig.round()  # implement 1
    rig.round()  # commit its listed path, leaving the scratch file
    view = current_view(rig.ports().reads, "tasks", "tl-1")
    assert view is not None and view.next == "repeat"
    specs = repair_agent(rig)
    unchanged = rig.agents["tl-1", "implement"]

    def tidy(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        rig.slot.repo.worktree(Path(spec.cwd)).remove_file("scratch.txt")
        return unchanged(harness, spec, timeout, hooks)

    rig.agents["tl-1", "implement"] = tidy
    rig.round()  # path repeat 2
    rig.round()  # verify, release, publish
    rig.bodies = ["failed"]
    rig.round()
    repair_agent(rig)
    assert rig.round() == [("tl-1", "implement", "repeat", "started")]
    assert rig.store.attempts("tasks", "tl-1")[0].number == 3 and len(specs) == 1
    rig.round()
    rig.bodies = ["failed"]
    rig.round()
    assert rig.next_words() == {"tl-1": ("check", "hold")}


@pytest.mark.parametrize("path", ["src/.gitattributes", "src/.git\x1b[31mfile"])
def test_unsafe_feedback_names_a_nearby_git_file_even_when_not_listed_in_the_answer(rig: Repairing, path: str) -> None:
    rig.round()
    rig.round()
    rig.agents["tl-1", "implement"] = scripted(rig.slot.repo, {
        "disposition": "implemented", "paths": ["src/x.py"], "message": "Implement", "explanation": "ran checks",
    }, {"src/x.py": "x = 1\n", path: "unsafe"})
    rig.round()
    row = rig.store.attempts("tasks", "tl-1")[0]
    found = rig.ports().verifier.verify(row.key)
    assert isinstance(found, Unsettled) and found.reason == "unsafe" and found.unsafe_path == path
    step = kind("implement")
    text = step.feedback(found, step.rules("tl-1"), 1, "Task", "NONCE", unrecorded=True)
    assert json.dumps(path, ensure_ascii=True) in text.splitlines()[0] and "\x1b" not in text


def test_status_and_dashboard_reads_only_describe_the_repeat(rig: Repairing) -> None:
    failed(rig)
    before = rig.con.total_changes
    listing = list_attempts(rig.ports().reads)
    shown = show_attempt(rig.ports().reads, rig.tmp, "tasks", "tl-1")
    assert not isinstance(listing, Failed) and listing.attempts[0].next == "repeat"
    assert not isinstance(shown, Failed) and shown.view.next == "repeat"
    assert rig.con.total_changes == before and not rig.tracker.holds


@pytest.mark.parametrize("harness", [HarnessKind.CLAUDE, HarnessKind.OPENCODE])
def test_rounds_switch_harness_and_check_repair_keeps_the_captured_policy_after_reopening(rig: Repairing, harness: HarnessKind) -> None:
    policy = rig.tmp / "machine-policy.json"
    policy.write_text('{"env":{"CAPTURED":"first"}}' if harness is HarnessKind.CLAUDE else '{"scratch":".kept"}')
    field = "settings_file" if harness is HarnessKind.CLAUDE else "sandbox_file"
    settings, _sources = resolve_agents({"plan": {"model": "plan-model"}, "implement": {
        "harness": harness.value, "model": "chosen-model", "access": {field: str(policy)}}}, rig.tmp)
    request = NextRequest("tasks", "/tracker", rig.slot.repo.path, "auto", settings, Overrides(), 30)
    for _turn in range(4):
        rig.now += 1
        assert isinstance(run_round(rig.ports(), request), Round)
    rows = rig.store.attempts("tasks", "tl-1")
    assert rows[0].step == "implement" and rows[0].run == settings.implement
    assert rows[1].run == settings.plan and not rig.environment.probes
    rig.bodies = ["failed"]
    rig.now += 1
    assert isinstance(run_round(rig.ports(), request), Round)
    rig.failing = LaunchUnavailable("start")
    assert isinstance(start(rig.starting(), rig.request()), Failed)
    admitted = rig.store.attempts("tasks", "tl-1")[0]
    assert admitted.run == settings.implement and admitted.number == 2
    policy.unlink()
    reopened = Store(SCHEMA).open_rw(rig.path)
    assert reopened is not None
    try:
        assert AttemptStore(lambda: reopened).attempts("tasks", "tl-1")[0].run == settings.implement
    finally:
        reopened.close()
    specs = repair_agent(rig)
    assert isinstance(start(rig.starting(), rig.request()), Started)
    assert len(specs) == 1 and "chosen-model" in specs[0].argv and "changed-model" not in specs[0].argv
    if harness is HarnessKind.CLAUDE:
        assert json.loads(specs[0].argv[specs[0].argv.index("--settings") + 1]) == {"env": {"CAPTURED": "first"}}
    assert rig.store.attempts("tasks", "tl-1")[0].run == settings.implement
