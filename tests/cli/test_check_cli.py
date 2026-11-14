"""The step surface for a task in its check step (S6d, tl-8bh9.14.6 section 9): `tl step show` lines and JSON of a checks
attempt (its `Check:` lines, `Result:`, the moved `main`, the counted refusals), the `tl step list` row, the start and
the task's abandon (checks first), each through `main` with the operation stubbed."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from stream_proc import OwnedProcess

from taskloop import cli_step
from taskloop.attempt_reads import PublishedRow, ReleaseRow
from taskloop.attempt_status import AttemptView, Listed, Next, SetupShown, Shown
from taskloop.attempt_types import AttemptKey, AttemptResult
from taskloop.check_status import HALF_DONE, ChecksView
from taskloop.check_store import ChecksRow, ResultRow
from taskloop.cli import main
from taskloop.operations import Failed, ReleasedTask, Started
from taskloop.result_data import Result
from taskloop.setup_store import SetupRow
from taskloop.slot_release import Released
from taskloop.step_guide import CHECKS_GUIDE, GUIDE

X, TARGET, D, SEEN = "a" * 40, "b" * 40, "d" * 40, "e" * 40
CHECK, TEST, SMOKE = "1" * 64, "2" * 64, "3" * 64
EVENTS = Path("/events.jsonl")

LOGS = Path("/a/c")
ROW = ChecksRow(
    AttemptKey("checks", "token-never-shown", 3), "implement", 2, "s1", D, TARGET, None,
    (("check", CHECK), ("test", TEST), ("smoke", SMOKE)),
    "f" * 64, 100.0, (42, "entry-start", "boot"), "concluded", 4, None, 0, "failed", "test:failed", 20.0, 30.0, D, False, "tasks", "tl-1",
    "repo", "/tracker", X,
)
RESULTS = (
    ResultRow(1, 0, "check", CHECK, 600, None, 10.0, 51.0, 0, "passed"),
    ResultRow(1, 1, "test", "9" * 64, 600, None, 51.0, 363.0, 1, "failed"),
    ResultRow(1, 2, "slow", "8" * 64, 60, None, 363.0, 364.4, 0, "passed"),
    ResultRow(1, 3, "smoke", None, None, None, 10.0, 10.0, None, "undefined"),
)
VIEW = AttemptView(
    "tasks", "tl-1", "check", "checks", "s1", "concluded", "gone", AttemptResult("collected", "failed:test:failed"), False, "done",
    (42, "entry-start", "boot"), None, (), 2, None, None, (("first", "re-run"), ("implement", "advanced")), None, 2,
    ReleaseRow(D, 1762941600.0, "kept"), PublishedRow(X, X, 6.0),
    ChecksView(ROW, RESULTS, (*(LOGS / f"check-1-{name}.log" for name in ("check", "test", "slow")), None)),
)
SHOWN = Shown(VIEW, LOGS, LOGS / "entry.log", EVENTS, SetupShown(SetupRow(1, X, "f" * 64, 0, None, "passed"), LOGS / "setup-1.log"))
SHOW = ["step", "show", "tl-1", "--backlog", "tasks"]


def run(argv: list[str], result: Result, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setitem(cli_step.OPERATIONS, (argv[0], argv[1]), lambda _arguments, _loaded: result)
    assert main(argv) == 0
    output = capsys.readouterr()
    assert output.err == ""
    return output.out


def test_show_prints_the_checks_attempt_s_lines_in_order(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    lines = run(SHOW, SHOWN, capsys, monkeypatch).splitlines()
    assert lines[:lines.index("Directory: /a/c")] == [
        "Task: tl-1 (backlog tasks)", "Step: check", "Attempt: checks (run 2)", "Earlier: first re-run", "Earlier: implement advanced",
        "Slot: s1", "Phase: concluded", "Entry: gone (pid 42)", f"Commit: {X}",
        f"Required: check, test, smoke (main at {TARGET})", f"Profile: {'f' * 64} at X",
        f"Setup: run 1 passed at {X}; log /a/c/setup-1.log",
        "Check: check passed, exit 0, 41 s; log /a/c/check-1-check.log",
        "Check: test failed, exit 1, 312 s; log /a/c/check-1-test.log (argv differs from main)",
        "Check: slow passed, exit 0, 1 s; log /a/c/check-1-slow.log (not required)",
        "Check: smoke undefined (required by main, not defined at X)",
        "Result: collected failed:test:failed", "Succeeded: no",
        f"Released: 2025-11-12 10:00:00 UTC, slot parked at {D}; claim kept",
    ]
    assert lines[-2:] == ["Next: done", GUIDE["done"]] and "Worker" not in "\n".join(lines)


@pytest.mark.parametrize(("row", "line"), [
    (replace(ROW, target_seen=SEEN, reason="main_moved"), f"Main: moved from {TARGET} to {SEEN}"),
    (replace(ROW, reason="main_moved"), f"Main: moved from {TARGET} to nothing (deleted)"),
    (replace(ROW, refusal="checks:running", refusals=2), "Refused: checks:running (2 in a row)"),
    (replace(ROW, profile_digest=None), "Profile: not read yet"),
], ids=["main_moved", "main_deleted", "refused", "unprofiled"])
def test_show_names_a_moved_main_the_counted_refusals_and_an_unread_profile(
    row: ChecksRow, line: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert line in run(SHOW, Shown(_with(ChecksView(row, RESULTS)), LOGS, LOGS / "entry.log", EVENTS), capsys, monkeypatch).splitlines()


def _with(checks: ChecksView) -> AttemptView:
    return replace(VIEW, checks=checks)


def test_show_of_no_block_yet_and_of_an_unfinished_check(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    out = run(SHOW, Shown(_with(ChecksView(ROW, ())), LOGS, LOGS / "entry.log", EVENTS), capsys, monkeypatch)
    assert "Check: none yet" in out.splitlines()
    unfinished = ResultRow(1, 0, "check", CHECK, 600, None, 10.0, None, None, None)
    out = run(SHOW, Shown(_with(ChecksView(ROW, (unfinished,))), LOGS, LOGS / "entry.log", EVENTS), capsys, monkeypatch)
    assert "Check: check unfinished" in out.splitlines()


def test_show_json_adds_the_checks_facts_and_results(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    data = json.loads(run([*SHOW, "--json"], SHOWN, capsys, monkeypatch))
    assert (data["step"], data["attempt_id"], data["earlier"], data["release"]["abandoned"]) == ("check", "checks", ["first", "implement"],
                                                                                                False)
    checks = data["checks"]
    assert {key: checks[key] for key in ("commit", "target", "target_seen", "required", "profile_digest", "refusal", "refusals")} == {
        "commit": X, "target": TARGET, "target_seen": None, "required": ["check", "test", "smoke"], "profile_digest": "f" * 64,
        "refusal": None, "refusals": 0}
    assert checks["results"][1] == {"name": "test", "required": True, "conclusion": "failed", "rc": 1, "block": 1, "started_at": 51.0,
                                    "ended_at": 363.0, "argv_differs": True, "log": "/a/c/check-1-test.log"}
    assert checks["results"][3]["log"] is None  # an undefined result has no log
    assert [(each["required"], each["argv_differs"]) for each in checks["results"]] == [(True, False), (True, True), (False, False),
                                                                                         (True, False)]
    assert "token-never-shown" not in json.dumps(data)


def test_list_shows_the_check_step_s_row_and_json(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    listed = Listed((_with(ChecksView(ROW, RESULTS)),))
    out = run(["step", "list"], listed, capsys, monkeypatch)
    row = "tl-1\ttasks\tcheck\t2\ts1\tconcluded\tgone\tcollected failed:test:failed\tneeds a person (failed:test:failed)\tdone\t-\t-"
    assert row in out.splitlines()
    data = json.loads(run(["step", "list", "--json"], listed, capsys, monkeypatch))
    assert data["attempts"][0]["checks"]["results"][0]["log"] is None  # logs are `tl step show`'s


def test_a_checks_start_names_its_step(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    started = Started("already_dispatched", "tasks", "tl-1", "checks", True, result="failed:test:failed", step="check")
    argv = ["step", "start", "tl-1", "--backlog", "tasks", "--tracker-root", "/t", "--checkout", "/c", "--model", "m", "--effort", "high",
            "--minutes", "5"]
    out = run(argv, started, capsys, monkeypatch)
    assert "already_dispatched: attempt checks for tl-1 (backlog tasks)" in out and "Result: failed:test:failed" in out
    assert json.loads(run([*argv, "--json"], started, capsys, monkeypatch))["step"] == "check"


ABANDON = ReleasedTask("tasks", "tl-1", "implement", Released("s0", None, False, "unclaimed", True),
                       ReleasedTask("tasks", "tl-1", "checks", Released("s1", D, True, "kept", True)))


RELEASE = ["step", "release", "tl-1", "--backlog", "tasks", "--abandon"]


def test_the_task_s_abandon_shows_the_checks_attempt_first_then_the_claim(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert run(RELEASE, ABANDON, capsys, monkeypatch).splitlines() == [
        "released: attempt checks for tl-1 (backlog tasks)", f"Slot s1 parked at {D}", "Reservation of s1 removed", "Claim kept",
        "released: attempt implement for tl-1 (backlog tasks)", "Slot s0: no Git write", "Claim returned to the tracker",
        "Abandoned: `tl step start tl-1` admits a fresh attempt",
    ]
    data = json.loads(run([*RELEASE, "--json"], ABANDON, capsys, monkeypatch))
    assert (data["attempt_id"], data["claim"], data["checks"]["attempt_id"], data["checks"]["claim"]) == ("implement", "unclaimed",
                                                                                                         "checks", "kept")
    assert data["checks"]["checks"] is None and data["checks"]["abandoned"] is True


@pytest.mark.parametrize("word", ["start", "wait", "stuck:hung", "release"])
def test_a_checks_view_gets_its_own_guide_never_the_agent_s(
    word: Next, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    running = ResultRow(1, 0, "check", CHECK, 600, OwnedProcess(600, 601, "start", "boot"), 10.0, None, None, None)
    view = replace(VIEW, next=word, release=None, checks=ChecksView(ROW, (running,)))
    out = run(SHOW, Shown(view, LOGS, LOGS / "entry.log", EVENTS), capsys, monkeypatch)
    assert CHECKS_GUIDE[word] in out and GUIDE[word] not in out and "attempt_entry" not in out and "Worker" not in out
    assert "Check: check unfinished, process group 601" in out.splitlines()  # the group the hung guide verifies
    assert "round relaunches the checks entry" in CHECKS_GUIDE["start"] and "late_relaunch" in CHECKS_GUIDE["start"]
    assert "until the deadline" in CHECKS_GUIDE["start"] and "cannot finish counts" not in CHECKS_GUIDE["start"]
    assert "taskloop.check_entry" in CHECKS_GUIDE["stuck:hung"]
    listed = run(["step", "list", "--stuck"], Listed((replace(view, next="stuck:hung"),)), capsys, monkeypatch)
    assert f"stuck:hung: {CHECKS_GUIDE['stuck:hung']}" in listed.splitlines()


def test_the_half_done_detail_keeps_the_structured_release_guide(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    argv = ["step", "start", "tl-1", "--backlog", "tasks", "--tracker-root", "/t", "--checkout", "/c", "--model", "m", "--effort", "high",
            "--minutes", "5"]
    monkeypatch.setitem(cli_step.OPERATIONS, ("step", "start"), lambda _arguments, _loaded: Failed("refused", "release", HALF_DONE))
    assert main(argv) == 1
    err = capsys.readouterr().err
    assert HALF_DONE in err and GUIDE["release"] in err
