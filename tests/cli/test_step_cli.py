"""The config/slot/step surface: flags to requests through stubbed composition openers, one table of result -> exit code,
human text and exact JSON keys, the placeholders, and one real read-only path over a factory.db file under tmp_path."""

import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import get_args

import pytest
from doubles import NO_CHECKS, NoAdvance
from sqlite_store import Store
from step_cli_support import KEY, MOVES, NEXT, ROUNDS, admitted
from stream_proc import OwnedProcess

from taskloop import cli_composition, cli_step, step_guide
from taskloop.admit import AdmitRequest, AdmitResult, Admitted
from taskloop.agents.settings import Overrides, StepSettings
from taskloop.attempt_reads import PublishedRow, ReleaseRow
from taskloop.attempt_result import CommittedStatus
from taskloop.attempt_status import AttemptView, EntryState, Listed, Next, SetupShown, Shown
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, AttemptResult, EntryIdentity
from taskloop.cli import main
from taskloop.command_conclusion import CommandConclusion
from taskloop.factory_schema import SCHEMA
from taskloop.git_views import GitViews
from taskloop.inspection_guide import CONFIG
from taskloop.launch import Launched, LaunchResult
from taskloop.operation_failure import FailureKind
from taskloop.operations import (
    Adoption,
    CommittedTask,
    Failed,
    PublishedTask,
    ReleasedTask,
    Round,
    Started,
    StartPorts,
)
from taskloop.publish import BranchPublished, PublishResult
from taskloop.result_data import Result
from taskloop.round_guide import automatic_guide
from taskloop.setup_store import SetupRow
from taskloop.slot_release import AlreadyReleased, Released, ReleaseResult
from taskloop.slots import Adopted, NotAdopted, SlotGit, SlotView
from taskloop.tracker import leaked_claim

EVENTS = Path("/events.jsonl")

ENTRY = (7, "entry-start", "boot")
START = [
    "step",
    "start",
    "tl-1",
    "--backlog",
    "tasks",
    "--tracker-root",
    "/tracker",
    "--checkout",
    "/checkout",
    "--model",
    "m",
    "--effort",
    "high",
    "--minutes",
    "30",
]
STATUS = AttemptView(
    "tasks", "tl-1", "plan", "attempt", "s1", "captured", "gone", AttemptResult("pending", "commit"), False, "commit", max_attempts=3
)
ERROR = {"kind", "reason", "message"}  # every refusal or unknown but an admission's
ADMISSION_ERROR = ERROR | {"claim_leaked", "admitted", "slots"}  # `tl step start`
STATUS_KEYS = {
    "backlog",
    "task",
    "step",
    "attempt_id",
    "slot",
    "phase",
    "entry",
    "result",
    "succeeded",
    "deadline_passed",
    "next",
    "status",
    "status_note",
    "entry_process",
    "worker",
    "leftovers",
    "number",
    "previous_attempt_id",
    "repeat_reason",
    "earlier",
    "last_entry",
    "seq",
    "release",
    "published",
    "checks",
    "land",
    "label",
    "hold",
    "hold_due",
    "last_command",
    "source_checks_id",
    "agent_stop",
    "stop_cause",
}
REPEAT = AttemptView(
    "tasks",
    "tl-1",
    "plan",
    "attempt",
    "s1",
    "captured",
    "gone",
    AttemptResult("pending", "repeat"),
    False,
    "repeat",
    ENTRY,
    (42, 41),
    ("uncommitted", "?? docs/design/tl-1/note.md", "+3 more"),
    2,
    "first",
    "uncommitted",
    (("first", "uncommitted"),),
    max_attempts=3,
)
D = "d" * 40
ABANDONED = AttemptView(
    "tasks",
    "tl-1",
    "plan",
    "second",
    "s1",
    "admitted",
    "none",
    AttemptResult("pending", "admitted"),
    False,
    "start",
    earlier=(("first", "abandoned"),),
    seq=2,
    release=ReleaseRow(D, 30.0, "unclaimed"),
)
FAILED_SETUP = SetupShown(SetupRow(2, D, "f" * 64, 0, None, CommandConclusion.FAILED, 10.0, 11.0), Path("/a/d/setup-2.log"))
RUNNING_SETUP = SetupShown(SetupRow(3, D, "f" * 64, 1, OwnedProcess(5, 5, "s", "b"), None, 10.0, None), Path("/a/d/setup-3.log"))
RELEASE = ["step", "release", "tl-1", "--backlog", "tasks"]
ABANDON = ["step", "abandon", "tl-1", "--backlog", "tasks"]
FREED = {
    "status",
    "backlog",
    "task",
    "attempt_id",
    "slot",
    "parked",
    "reservation_removed",
    "claim",
    "abandoned",
    "checks",
    "land",
    "candidate",
}
X, T = "a" * 40, "b" * 40
PUBLISH = ["step", "publish", "tl-1", "--backlog", "tasks"]
PUBLISHED = {"status", "backlog", "task", "attempt_id", "commit", "remote_head"}
CHECKED = {"status", "backlog", "task", "attempt_id", "release", "published"}
ROUND = {"status", "backlog", "moves", "stopped", "logged"}
DONE = AttemptView(
    "tasks",
    "tl-1",
    "plan",
    "attempt",
    "s1",
    "captured",
    "gone",
    AttemptResult("collected", "committed"),
    False,
    "done",
    release=ReleaseRow(D, 30.0, "kept"),
    published=PublishedRow(X, X, 40.0),
)


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every command resolves the machine config: under tmp_path, never the real ~/.config or ~/.local."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def words(alias: object) -> list[str]:
    """Every string of a Literal type alias, nested aliases and unions included."""
    found: list[str] = []
    for arg in get_args(getattr(alias, "__value__", alias)):
        found += [arg] if isinstance(arg, str) else words(arg)
    return found


class Admission:
    def __init__(self) -> None:
        self.requests: list[AdmitRequest] = []

    def admit(self, request: AdmitRequest) -> AdmitResult:
        self.requests.append(request)
        return Admitted(KEY, "s1")


class FakeLauncher:
    def launch(self, backlog: str, task_id: str, minutes: int) -> LaunchResult:
        return Launched(KEY, ENTRY)


class NoRepeat:
    def repeat(self, backlog: str, task_id: str, current: AttemptKey, entry: EntryIdentity | None, minutes: int) -> Started | Failed:
        raise AssertionError("a first start never repeats")


def test_start_flags_and_config_reach_the_request_and_the_openers(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    con = Store(SCHEMA).open_rw(tmp_path / "empty.db")
    assert con is not None
    admission, opened = Admission(), list[tuple[Path, Path]]()

    @contextmanager
    def opener(database: Path, artifacts: Path, _views: GitViews) -> Generator[StartPorts | Failed]:
        opened.append((database, artifacts))
        yield StartPorts(AttemptStore(lambda: con), admission, FakeLauncher(), lambda: 1000, NoRepeat(), NoAdvance(), NO_CHECKS)

    monkeypatch.setattr(cli_composition, "open_start", opener)
    config = tmp_path / "scratch.toml"
    config.write_text(f'db = "{tmp_path / "file.db"}"\nartifacts = "{tmp_path / "file-art"}"\n')
    assert main(["--config", str(config), *START, "--artifacts", str(tmp_path / "flag-art"), "--json"]) == 0
    con.close()
    assert opened == [(tmp_path / "file.db", tmp_path / "flag-art")]
    request = admission.requests[0]
    assert (request.task_id, request.backlog, request.tracker_root, request.checkout) == ("tl-1", "tasks", "/tracker", Path("/checkout"))
    assert (request.overrides, request.settings, request.deadline) == (Overrides(model="m", effort="high"), StepSettings(), 1000 + 30 * 60)
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "status": "started",
        "backlog": "tasks",
        "task": "tl-1",
        "step": None,
        "attempt_id": "attempt",
        "existing": False,
        "entry_process": {"pid": 7, "start": "entry-start", "boot": "boot"},
        "number": None,
        "result": None,
    }
    assert "dispatch-token-never-shown" not in output.out + output.err
    assert not home.exists()


VIEW = SlotView("s2", Path("/slots/s2"), "unknown", "dirty")
STARTED = {"status", "backlog", "task", "step", "attempt_id", "existing", "entry_process", "number", "result"}
CASES: list[tuple[list[str], Result, int, list[str], set[str]]] = [
    (
        START,
        Started("started", "tasks", "tl-1", "attempt", False, ENTRY),
        0,
        ["started: attempt attempt for tl-1", step_guide.HELD],
        STARTED,
    ),
    (START, Started("relaunched", "tasks", "tl-1", "attempt", True, ENTRY), 0, ["existing attempt; its admitted choices stand"], STARTED),
    (START, Started("already_running", "tasks", "tl-1", "attempt", True, ENTRY), 0, ["already_running: attempt"], STARTED),
    (START, Started("already_dispatched", "tasks", "tl-1", "attempt", True), 0, ["already_dispatched: attempt"], STARTED),
    (
        START,
        Started("already_dispatched", "tasks", "tl-1", "attempt", True, result="rejected:paths"),
        0,
        ["Result: rejected:paths"],
        STARTED,
    ),
    (
        START,
        Started("repeated", "tasks", "tl-1", "next", False, ENTRY, number=2),
        0,
        [
            "repeated: attempt next for tl-1",
            "attempt 2 of at most 3; attempt 1's choices stand; deadline from the minutes given",
            step_guide.HELD,
        ],
        STARTED,
    ),
    (
        START,
        Failed("refused", "repeats_exhausted"),
        1,
        ["refused:repeats_exhausted", step_guide.GUIDE["repeats_exhausted"]],
        ADMISSION_ERROR,
    ),
    (START, Failed("refused", "repeat_cap"), 1, ["tl step start: refused:repeat_cap"], ADMISSION_ERROR),
    (START, Failed("refused", "not_repeatable"), 1, ["tl step start: refused:not_repeatable"], ADMISSION_ERROR),
    (START, Failed("waiting", "worker_alive"), 3, ["tl step start: waiting:worker_alive", step_guide.GUIDE["waiting"]], ADMISSION_ERROR),
    (START, Failed("refused", "superseded"), 1, ["tl step start: refused:superseded"], ADMISSION_ERROR),
    (
        START,
        Failed("refused", "no_free_slot", slots=(VIEW,)),
        1,
        ["tl step start: refused:no_free_slot", "s2 unknown dirty /slots/s2"],
        ADMISSION_ERROR,
    ),
    (START, Failed("refused", "registration_refused"), 1, ["refused:registration_refused"], ADMISSION_ERROR),
    (START, Failed("refused", "registration_conflict"), 1, [step_guide.GUIDE["registration_conflict"]], ADMISSION_ERROR),
    (
        START,
        Failed("unavailable", "start", admitted=True),
        3,
        [f"Admitted: {step_guide.HELD} Inspect the registered entry"],
        ADMISSION_ERROR,
    ),
    (START, Failed("unavailable", "tracker", claim_leaked=True), 3, ["unavailable:tracker"], ADMISSION_ERROR),
    (START, Failed("uncertain", "launch"), 3, ["tl step start: uncertain:launch"], ADMISSION_ERROR),
    (
        ["attempt", "show", "tl-1", "--backlog", "tasks"],
        Shown(STATUS, Path("/a/d"), Path("/a/d/entry.log"), EVENTS),
        0,
        [
            "Step: plan",
            "Phase: captured",
            "Result: pending commit",
            "Setup: none\nDirectory: /a/d",
            "Entry log: /a/d/entry.log",
            "Next: commit",
            "The result is captured and awaits factory commit before it can be accepted.",
        ],
        STATUS_KEYS | {"directory", "entry_log", "events_path", "setup", "failed_checks"},
    ),
    (
        ["attempt", "show", "tl-1", "--backlog", "tasks"],
        Shown(REPEAT, Path("/a/d"), Path("/a/d/entry.log"), EVENTS),
        0,
        [
            "Worker: last known pid 42, process group 41 (not checked)",
            "Result: pending repeat",
            "Uncommitted: uncommitted",
            "  ?? docs/design/tl-1/note.md",
            "  +3 more",
            f"Next: repeat\n{step_guide.GUIDE['repeat']}",
            "Attempt: attempt (2 of at most 3; repeats first, uncommitted)\nEarlier: first repeated (uncommitted)\nSlot: s1",
        ],
        STATUS_KEYS | {"directory", "entry_log", "events_path", "setup", "failed_checks"},
    ),
    (
        ["attempt", "show", "tl-1", "--backlog", "tasks"],
        Shown(STATUS, Path("/a/d"), Path("/a/d/entry.log"), EVENTS, FAILED_SETUP),
        0,
        [
            f"Deadline passed: no\nSetup: run 2 failed at {D}; log /a/d/setup-2.log; started 1970-01-01 00:00:10 UTC; "
            "ended 1970-01-01 00:00:11 UTC; duration unavailable (no usable recorded duration)\nDirectory"
        ],
        STATUS_KEYS | {"directory", "entry_log", "events_path", "setup", "failed_checks"},
    ),
    (
        ["attempt", "show", "tl-1", "--backlog", "tasks"],
        Shown(STATUS, Path("/a/d"), Path("/a/d/entry.log"), EVENTS, RUNNING_SETUP),
        0,
        [f"Setup: run 3 unfinished at {D}; log /a/d/setup-3.log"],
        STATUS_KEYS | {"directory", "entry_log", "events_path", "setup", "failed_checks"},
    ),
    (
        ["attempt", "list", "--stuck"],
        Listed((STATUS,)),
        0,
        ["task\tbacklog\tstep\tattempt\tslot", "pending commit\tsettling\tcommit"],
        {"attempts"},
    ),
    (
        ["attempt", "show", "tl-1", "--backlog", "tasks"],
        Shown(STATUS, Path("/a/d"), Path("/a/d/entry.log"), EVENTS),
        0,
        ["Attempt: attempt (1 of at most 3)\nSlot: s1"],
        STATUS_KEYS | {"directory", "entry_log", "events_path", "setup", "failed_checks"},
    ),
    (
        ["step", "commit", "tl-1", "--backlog", "tasks"],
        CommittedTask(CommittedStatus.REUSED, "tasks", "tl-1", "attempt", "released", "published"),
        0,
        ["reused: attempt attempt", "Release: released\nPublish: published"],
        CHECKED,
    ),
    (
        ["step", "commit", "tl-1", "--backlog", "tasks"],
        CommittedTask(CommittedStatus.COMMITTED, "tasks", "tl-1", "attempt", "held:slot_dirty", "unavailable:remote"),
        0,
        ["Release: held:slot_dirty", step_guide.GUIDE["slot_dirty"], f"Publish: unavailable:remote\n{step_guide.GUIDE['remote']}"],
        CHECKED,
    ),
    (
        ["step", "commit", "tl-1", "--backlog", "tasks"],
        CommittedTask(CommittedStatus.COMMITTED, "tasks", "tl-1", "attempt", "already_released", "already_published"),
        0,
        ["Release: already_released\nPublish: already_published\n"],
        CHECKED,
    ),
    (
        PUBLISH,
        PublishedTask("tasks", "tl-1", "attempt", BranchPublished(X, X)),
        0,
        [f"published: task/tl-1 at {X} on origin (attempt attempt, backlog tasks)\n"],
        PUBLISHED,
    ),
    (
        PUBLISH,
        PublishedTask("tasks", "tl-1", "attempt", PublishedRow(X, X, 40.0)),
        0,
        [f"already_published: task/tl-1 at {X} on origin (attempt attempt, backlog tasks)\nNothing changed: it was published before."],
        PUBLISHED,
    ),
    (
        PUBLISH,
        Failed("refused", "diverged", f"origin's task/tl-1 is at {T}"),
        1,
        ["tl step publish: refused:diverged", step_guide.GUIDE["diverged"]],
        ERROR,
    ),
    (PUBLISH, Failed("refused", "remote_ahead"), 1, [step_guide.GUIDE["remote_ahead"]], ERROR),
    (PUBLISH, Failed("refused", "no_remote"), 1, [step_guide.GUIDE["no_remote"]], ERROR),
    (PUBLISH, Failed("refused", "repository"), 1, [step_guide.GUIDE["repository"]], ERROR),
    (PUBLISH, Failed("refused", "not_committed"), 1, [step_guide.GUIDE["not_committed"]], ERROR),
    (PUBLISH, Failed("unavailable", "git"), 3, [step_guide.GUIDE["git"]], ERROR),
    (PUBLISH, Failed("unavailable", "remote"), 3, ["tl step publish: unavailable:remote", step_guide.GUIDE["remote"]], ERROR),
    (
        ["attempt", "show", "tl-1", "--backlog", "tasks"],
        Shown(DONE, Path("/a/d"), Path("/a/d/entry.log"), EVENTS),
        0,
        [f"Published: task/tl-1 at {X} on origin, 1970-01-01 00:00:40 UTC\n", "Next: done"],
        STATUS_KEYS | {"directory", "entry_log", "events_path", "setup", "failed_checks"},
    ),
    (
        ["attempt", "show", "tl-1", "--backlog", "tasks"],
        Shown(ABANDONED, Path("/a/d"), Path("/a/d/entry.log"), EVENTS),
        0,
        [
            "Earlier: first abandoned",
            f"Released: 1970-01-01 00:00:30 UTC, slot parked at {D}; claim unclaimed; abandoned",
            f"Next: start\n{step_guide.GUIDE['abandoned']}",
        ],
        STATUS_KEYS | {"directory", "entry_log", "events_path", "setup", "failed_checks"},
    ),
    (
        RELEASE,
        ReleasedTask("tasks", "tl-1", "attempt", Released("s1", D, True, "kept", False)),
        0,
        ["released: attempt attempt for tl-1 (backlog tasks)\n", f"Slot s1 parked at {D}\nReservation of s1 removed\nClaim kept"],
        FREED,
    ),
    (
        ABANDON,
        ReleasedTask("tasks", "tl-1", "attempt", Released("s1", None, True, "not_held", True)),
        0,
        [
            "Slot s1: no Git write",
            "Claim not held by the factory: it was reverted or belongs to another actor.",
            "Abandoned: the next approved admission starts a fresh attempt.",
        ],
        FREED,
    ),
    (
        RELEASE,
        ReleasedTask("tasks", "tl-1", "attempt", AlreadyReleased("s1", "unclaimed", True)),
        0,
        ["already_released: attempt attempt for tl-1 (backlog tasks); nothing changed", "Claim: unclaimed; abandoned"],
        FREED,
    ),
    (
        RELEASE,
        Failed("refused", "slot_dirty", "?? x\nRemove the listed files. Nothing changed."),
        1,
        ["tl step release: refused:slot_dirty\n?? x\nRemove the listed files. Nothing changed.", step_guide.GUIDE["slot_dirty"]],
        ERROR,
    ),
    (RELEASE, Failed("refused", "not_terminal"), 1, [step_guide.GUIDE["not_terminal"]], ERROR),
    (RELEASE, Failed("unsettled", "worker_unknown"), 3, [step_guide.GUIDE["worker_unknown"]], ERROR),
    (
        RELEASE,
        Failed("unavailable", "tracker", "Released; the tracker claim is still to be returned (other): rerun"),
        3,
        ["unavailable:tracker\nReleased; the tracker claim is still to be returned"],
        ERROR,
    ),
    (["step", "commit", "tl-1", "--backlog", "tasks"], Failed("rejected", "paths"), 1, ["tl step commit: rejected:paths"], ERROR),
    (["step", "commit", "tl-1", "--backlog", "tasks"], Failed("not_applicable", "incomplete"), 1, ["not_applicable:incomplete"], ERROR),
    (
        ["step", "commit", "tl-1", "--backlog", "tasks"],
        Failed("uncommitted", "dirty"),
        3,
        ["uncommitted:dirty", step_guide.GUIDE["uncommitted"]],
        ERROR,
    ),
    (
        ["step", "commit", "tl-1", "--backlog", "tasks"],
        Failed("unavailable", "slot_busy"),
        3,
        ["unavailable:slot_busy", step_guide.GUIDE["slot_busy"]],
        ERROR,
    ),
    (
        NEXT,
        Round("tasks", MOVES, "no_free_slot"),
        0,
        [
            "tl-3   start    started a3\ntl-2   report   stuck:hung a2\ntl-10  skip     abandoned\n",
            "Stopped: no_free_slot",
            f"stuck:hung: {automatic_guide('stuck:hung')}",
            f"failed:rejected:paths: {automatic_guide('rejected:paths')}",
            f"abandoned_skip: {automatic_guide('abandoned_skip')}",
            f"no_free_slot: {automatic_guide('no_free_slot')}",
            "tl-5   report   claim_leaked\n",
            f"claim_leaked: {automatic_guide('claim_leaked')}",
        ],
        ROUND,
    ),
    (NEXT, Round("tasks", (), "unavailable:tracker"), 3, ["Stopped: unavailable:tracker"], ROUND),
    (NEXT, Round("tasks", ()), 0, ["Nothing to do in backlog tasks."], ROUND),
    (NEXT, Failed("refused", "label"), 1, ["tl rounds once: refused:label"], ERROR),
    (["slot", "adopt", "/repo"], Adoption((Adopted("s1", Path("/s/s1")),)), 0, ["s1 adopted /s/s1"], {"slots"}),
    (
        ["slot", "adopt", "/repo"],
        Adoption((NotAdopted("s1", "not_listed", Path("/s/s1")),)),
        1,
        ["s1 not_listed /s/s1", "Missing slots need registered detached worktrees"],
        {"slots"},
    ),
    (
        ["slot", "adopt", "/repo"],
        Adoption((NotAdopted("s1", "attached", Path("/s/s1")),)),
        1,
        ["s1 attached /s/s1", "its work preserved and its HEAD detached before adoption"],
        {"slots"},
    ),
    (["slot", "adopt", "/repo"], Adoption((NotAdopted("s1", "store_unavailable", Path("/s/s1")),)), 3, ["s1 store_unavailable"], {"slots"}),
]


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("argv, result, code, lines, keys", CASES)
def test_result_exit_code_text_and_json_keys(
    argv: list[str],
    result: Result,
    code: int,
    lines: list[str],
    keys: set[str],
    structured: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setitem(cli_step.OPERATIONS, (argv[0], argv[1]), lambda _arguments, _loaded: result)
    assert main([*argv, *(["--json"] if structured else [])]) == code
    output = capsys.readouterr()
    data, other = (output.err, output.out) if isinstance(result, Failed) else (output.out, output.err)
    assert other == ""
    if structured:
        found = json.loads(data)
        assert set(found["error"] if isinstance(result, Failed) else found) == keys
    else:
        assert all(line in data for line in lines), data
        if isinstance(result, Failed) and result.claim_leaked:
            assert data.startswith(leaked_claim("tl-1") + "\n")


@pytest.mark.parametrize(
    "release, published, guided",
    [
        ("already_released", "already_published", False),
        ("released", "published", False),
        ("held:slot_dirty", "unavailable:remote", True),
    ],
)
def test_commit_prints_the_release_and_publish_guides_only_when_not_done(
    release: str,
    published: str,
    guided: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = CommittedTask(CommittedStatus.COMMITTED, "tasks", "tl-1", "attempt", release, published)
    monkeypatch.setitem(cli_step.OPERATIONS, ("step", "commit"), lambda _arguments, _loaded: result)
    assert main(["step", "commit", "tl-1", "--backlog", "tasks"]) == 0
    out = capsys.readouterr().out
    assert (step_guide.GUIDE["slot_dirty"] in out) is guided and (step_guide.GUIDE["remote"] in out) is guided


@pytest.mark.parametrize("next_word", words(Next))
def test_every_next_step_renders_with_its_guidance(
    next_word: Next,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shown = Shown(
        AttemptView("tasks", "tl-1", "plan", "a", "s1", "admitted", "none", AttemptResult("pending", "admitted"), False, next_word),
        Path("/d"),
        Path("/d/entry.log"),
        EVENTS,
    )
    monkeypatch.setitem(cli_step.OPERATIONS, ("attempt", "show"), lambda _arguments, _loaded: shown)
    assert main(["attempt", "show", "tl-1", "--backlog", "tasks"]) == 0
    assert f"Next: {next_word}\n{step_guide.GUIDE[next_word]}" in capsys.readouterr().out


def test_an_implement_attempt_shows_the_plan_it_advanced_from(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    view = AttemptView(
        "tasks",
        "tl-1",
        "implement",
        "i",
        "s1",
        "admitted",
        "none",
        AttemptResult("pending", "admitted"),
        False,
        "start",
        earlier=(("r", "uncommitted"), ("p", "advanced"), ("q", "abandoned")),
    )
    shown = Shown(view, Path("/d"), Path("/d/e"), EVENTS)
    monkeypatch.setitem(cli_step.OPERATIONS, ("attempt", "show"), lambda _arguments, _loaded: shown)
    assert main(["attempt", "show", "tl-1", "--backlog", "tasks"]) == 0
    out = capsys.readouterr().out
    assert "Step: implement\n" in out and "Earlier: r repeated (uncommitted)\nEarlier: p advanced\nEarlier: q abandoned\n" in out


@pytest.mark.parametrize("entry", words(EntryState))
def test_every_entry_state_renders(entry: EntryState, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    view = AttemptView("tasks", "tl-1", "plan", "a", "s1", "admitted", entry, AttemptResult("pending", "admitted"), False, "unknown")
    listed = Listed((view,))
    monkeypatch.setitem(cli_step.OPERATIONS, ("attempt", "list"), lambda _arguments, _loaded: listed)
    assert main(["attempt", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["attempts"][0]["entry"] == entry


@pytest.mark.parametrize("kind", words(FailureKind))
def test_every_failure_kind_has_its_exit_code(
    kind: FailureKind, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(cli_step.OPERATIONS, ("attempt", "list"), lambda _arguments, _loaded: Failed(kind, "choices"))
    assert main(["attempt", "list"]) == (3 if kind in ("unavailable", "uncertain", "unsettled", "uncommitted", "waiting") else 1)
    assert capsys.readouterr().err.startswith("tl attempt list: ")


def test_removed_commit_spelling_fails_parsing_before_opening(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli_composition, "open_commit", lambda *_args: pytest.fail("Opened the factory commit ports"))
    obsolete = "ver" + "ify"
    with pytest.raises(SystemExit) as result:
        main(["step", obsolete, "tl-1", "--backlog", "tasks"])
    assert result.value.code == 2
    error = capsys.readouterr().err
    assert "invalid choice" in error and obsolete in error and "commit" in error


def test_release_needs_its_backlog_from_the_flag_or_the_config(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(RELEASE[:3]) == 1
    assert CONFIG["backlog_missing"] in capsys.readouterr().err


class Releases:
    def __init__(self) -> None:
        self.calls: list[tuple[AttemptKey, bool]] = []

    def release(self, key: AttemptKey, abandon: bool, me: EntryIdentity | None = None) -> ReleaseResult:
        self.calls.append((key, abandon))
        return Released("s1", None, True, "unclaimed", abandon)


@pytest.mark.parametrize("abandon", [False, True])
def test_release_flags_reach_the_operation_through_the_opener(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], abandon: bool
) -> None:
    db, releases, checks, opened = tmp_path / "factory.db", Releases(), Releases(), list[Path]()
    admitted(db)
    con = Store(SCHEMA).open_ro(db)
    assert con is not None

    @contextmanager
    def opener(database: Path, _views: GitViews) -> Generator[tuple[AttemptStore, Releases, Releases]]:
        opened.append(database)
        yield AttemptStore(lambda: con), releases, checks

    monkeypatch.setattr(cli_composition, "open_release", opener)
    assert main([*(ABANDON if abandon else RELEASE), "--db", str(db), "--json"]) == 0
    con.close()
    assert opened == [db] and releases.calls == [(KEY, abandon)] and checks.calls == []  # no checks attempt: never called
    assert json.loads(capsys.readouterr().out)["abandoned"] is abandon


class Publishes:
    def __init__(self) -> None:
        self.keys: list[AttemptKey] = []

    def publish(self, key: AttemptKey) -> PublishResult:
        self.keys.append(key)
        return BranchPublished(X, X)


def test_publish_reaches_the_operation_through_the_opener_and_its_json_is_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db, publishes, opened = tmp_path / "factory.db", Publishes(), list[Path]()
    admitted(db)
    con = Store(SCHEMA).open_ro(db)
    assert con is not None

    @contextmanager
    def opener(database: Path, _views: GitViews, _artifacts: Path) -> Generator[tuple[AttemptStore, Publishes]]:
        opened.append(database)
        yield AttemptStore(lambda: con), publishes

    monkeypatch.setattr(cli_composition, "open_publish", opener)
    assert main([*PUBLISH, "--db", str(db), "--json"]) == 0
    con.close()
    assert opened == [db] and publishes.keys == [KEY]
    assert json.loads(capsys.readouterr().out) == {
        "status": "published",
        "backlog": "tasks",
        "task": "tl-1",
        "attempt_id": "attempt",
        "commit": X,
        "remote_head": X,
    }


def test_a_repeat_shows_the_setup_of_the_attempt_whose_environment_it_keeps(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A repeat runs no setup of its own: its `Setup:` line is attempt 1's run, named as such, with that attempt's log."""
    db, art = tmp_path / "factory.db", tmp_path / "art"
    admitted(db)
    con = sqlite3.connect(db)
    with con:
        con.execute(
            "INSERT INTO setup_run (attempt_id,run,dispatch_token,generation,commit_sha,digest,started_at,ended_at,conclusion,rc) "
            "VALUES ('attempt',1,?,1,?,?,1,2,'passed',0)",
            (KEY.dispatch_token, "d" * 40, "f" * 64),
        )
        con.execute("""INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
            input_path,input_digest,schema_version,model,effort,access_policy,deadline,number,seq,slot_head,
            previous_attempt_id,repeat_reason,engine_digest,workflow_digest,workflow_sha,admitted_at)
            SELECT 'second','token-2',1,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,schema_version,
            model,effort,access_policy,deadline,2,2,slot_head,'attempt','uncommitted',engine_digest,workflow_digest,workflow_sha,
            admitted_at FROM attempt WHERE attempt_id='attempt'""")
    con.close()
    assert main(["attempt", "show", "tl-1", "--backlog", "tasks", "--db", str(db), "--artifacts", str(art), "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["attempt_id"] == "second" and shown["setup"]["attempt_id"] == "attempt"
    assert (shown["setup"]["started_at"], shown["setup"]["ended_at"], shown["setup"]["duration_seconds"]) == (1, 2, 1)
    assert shown["setup"]["log"] != f"{shown['directory']}/setup-1.log" and shown["setup"]["log"].endswith("/setup-1.log")
    assert main(["attempt", "show", "tl-1", "--backlog", "tasks", "--db", str(db), "--artifacts", str(art)]) == 0
    assert f"Setup: run 1 passed at {'d' * 40} (attempt attempt's, which this repeat keeps); log" in capsys.readouterr().out


def test_the_real_read_paths_write_nothing_and_never_print_the_token(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db, art = tmp_path / "factory.db", tmp_path / "art"
    admitted(db)
    assert main(["attempt", "show", "tl-1", "--backlog", "tasks", "--db", str(db), "--artifacts", str(art), "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert (shown["step"], shown["phase"], shown["entry"], shown["next"]) == ("plan", "admitted", "none", "stuck:expired_admitted")
    assert set(shown) == STATUS_KEYS | {"directory", "entry_log", "events_path", "setup", "failed_checks"}
    assert (shown["entry_process"], shown["worker"]) == (None, None)
    assert shown["setup"] is None
    con = sqlite3.connect(db)
    with con:
        con.execute(
            "INSERT INTO setup_run (attempt_id,run,dispatch_token,generation,commit_sha,digest,started_at,ended_at,conclusion,rc) "
            "VALUES ('attempt',1,?,1,?,?,1,2,'passed',0)",
            (KEY.dispatch_token, "d" * 40, "f" * 64),
        )
    con.close()
    assert main(["attempt", "show", "tl-1", "--backlog", "tasks", "--db", str(db), "--artifacts", str(art), "--json"]) == 0
    setup = json.loads(capsys.readouterr().out)["setup"]
    assert setup == {
        "run": 1,
        "conclusion": "passed",
        "commit": "d" * 40,
        "log": f"{shown['directory']}/setup-1.log",
        "attempt_id": None,
        "started_at": 1.0,
        "ended_at": 2.0,
        "duration_seconds": 1.0,
    }
    assert main(["attempt", "list", "--stuck", "--db", str(db)]) == 0
    listed = capsys.readouterr().out
    head = "task\tbacklog\tstep\tattempt\tslot\tphase\tentry\tresult\tstatus\tnext\thold cause\tlast command"
    assert listed.startswith(f"{head}\ntl-1\ttasks\tplan\t1/3\ts1\t")
    assert main(["attempt", "list", "--db", str(db), "--json"]) == 0
    assert [each["step"] for each in json.loads(capsys.readouterr().out)["attempts"]] == ["plan"]
    assert main(["attempt", "show", "tl-1", "--backlog", "tasks", "--db", str(db), "--artifacts", str(art)]) == 0
    assert "Task: tl-1 (backlog tasks)\nStep: plan\nAttempt: attempt (1 of at most 3)\n" in capsys.readouterr().out
    assert "stuck:expired_admitted: Nothing ran; rounds only report it." in listed
    assert f"discard {db} and its" in listed
    assert main(["step", "commit", "tl-1", "--backlog", "tasks", "--db", str(db), "--json"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.err)["error"]["reason"] == "not_captured"
    assert KEY.dispatch_token not in output.out + output.err + json.dumps(shown)
    assert not art.exists()
    con = sqlite3.connect(db)
    assert con.execute("SELECT phase,rev FROM attempt").fetchall() == [("admitted", 0)]
    con.close()


@pytest.mark.parametrize(
    "argv",
    [["attempt", "show", "tl-1", "--backlog", "tasks"], ["attempt", "list"], ["step", "commit", "tl-1", "--backlog", "b"], START, PUBLISH],
)
def test_without_a_factory_database_every_step_command_refuses_and_creates_none(
    argv: list[str], tmp_path: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "factory.db"  # in an existing directory: a writable open would create it
    assert main([*argv, "--db", str(missing), "--json"]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert (error["kind"], error["reason"]) == ("refused", "database")
    assert not missing.exists() and not home.exists()


def test_a_running_agents_time_since_its_last_command_is_listed_and_shown(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    view = AttemptView(
        "tasks", "tl-1", "plan", "a", "s1", "registered", "running", AttemptResult("pending", "registered"), False, "wait", last_command=42
    )
    monkeypatch.setitem(cli_step.OPERATIONS, ("attempt", "list"), lambda _arguments, _loaded: Listed((view,)))
    shown = Shown(view, Path("/d"), Path("/d/e"), EVENTS)
    monkeypatch.setitem(cli_step.OPERATIONS, ("attempt", "show"), lambda _arguments, _loaded: shown)
    assert main(["attempt", "list"]) == 0
    assert capsys.readouterr().out.splitlines()[1].endswith("\twait\t-\t42 s ago")
    assert main(["attempt", "show", "tl-1", "--backlog", "tasks"]) == 0
    assert "Last command: 42 s ago\n" in capsys.readouterr().out


LANDING = ["land", "run", "tl-1", "--backlog", "tasks", "--checkout", "/checkout", "--minutes", "20"]


@pytest.mark.parametrize(
    ("argv", "opener"),
    [
        (START, "open_start"),
        (NEXT, "open_next"),
        (ROUNDS, "open_rounds"),
        (["attempt", "list"], "open_reads"),
        (["step", "commit", "tl-1", "--backlog", "tasks"], "open_commit"),
        (RELEASE, "open_release"),
        (PUBLISH, "open_publish"),
        (LANDING, "open_land"),
        (["slot", "adopt", "/checkout"], "adopt"),
    ],
)
def test_every_operation_gets_the_configured_git_read_seconds(
    argv: list[str], opener: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    given: list[object] = []

    @contextmanager
    def opened(*args: object, **_kwargs: object) -> Generator[Failed]:
        given.extend(args)
        yield Failed("refused", "database", "stub")

    def adopted(*args: object) -> Failed:
        given.extend(args)
        return Failed("refused", "database", "stub")

    monkeypatch.setattr(cli_composition, opener, adopted if opener == "adopt" else opened)
    config = tmp_path / "c.toml"
    config.write_text("git_read_seconds = 45\n")
    main(["--config", str(config), *argv])
    seen = [item for item in given if isinstance(item, GitViews)]
    seen += [item.checkouts.__self__ for item in given if isinstance(item, SlotGit) and hasattr(item.checkouts, "__self__")]
    assert seen == [GitViews(45)]
