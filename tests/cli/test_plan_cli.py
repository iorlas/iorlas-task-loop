"""The config/slot/plan surface: flags to requests through stubbed composition openers, one table of result -> exit code,
human text and exact JSON keys, the placeholders, and one real read-only path over a factory.db file under tmp_path."""

import hashlib
import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import get_args

import pytest
from sqlite_store import Store, begin_immediate

from taskloop import cli_composition, cli_plan, rounds_lock
from taskloop.admit import AdmitRequest, AdmitResult, Admitted
from taskloop.attempt import SANDBOX
from taskloop.attempt_reads import PublishedRow, ReleaseRow
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, AttemptResult
from taskloop.cli import main
from taskloop.factory_schema import SCHEMA
from taskloop.launch import Entry, Launched, LaunchResult
from taskloop.operations import (
    Adoption,
    AttemptStatus,
    Checked,
    Ended,
    EntryState,
    Failed,
    FailureKind,
    Freed,
    Listed,
    Move,
    Next,
    PublishedTask,
    Result,
    Round,
    Shown,
    Started,
    Starting,
)
from taskloop.publish import AlreadyPublished, BranchPublished, PublishResult
from taskloop.slot_release import AlreadyReleased, Released, ReleaseResult
from taskloop.slots import Adopted, NotAdopted, SlotView

KEY = AttemptKey("attempt", "dispatch-token-never-shown", 1)
ENTRY = (7, "entry-start", "boot")
START = ["plan", "start", "tl-1", "--backlog", "tasks", "--tracker-root", "/tracker", "--checkout", "/checkout", "--model", "m",
         "--effort", "high", "--minutes", "30"]
STATUS = AttemptStatus("tasks", "tl-1", "attempt", "s1", "captured", "gone", AttemptResult("pending", "verification"), False, "verify")
ERROR = {"kind", "reason", "message"}  # every refusal or unknown but an admission's
ADMISSION_ERROR = ERROR | {"claim_leaked", "admitted", "slots"}  # `tl plan start`
STATUS_KEYS = {
    "backlog", "task", "attempt_id", "slot", "phase", "entry", "result", "succeeded", "deadline_passed", "next", "entry_process", "worker",
    "leftovers", "number", "previous_attempt_id", "repeat_reason", "earlier", "last_entry", "seq", "release", "published",
}
REPEAT = AttemptStatus(
    "tasks", "tl-1", "attempt", "s1", "captured", "gone", AttemptResult("pending", "repeat"), False, "repeat", ENTRY, (42, 41),
    ("uncommitted", "?? docs/design/tl-1/note.md", "+3 more"), 2, "first", "uncommitted", (("first", "uncommitted"),),
)
D = "d" * 40
ABANDONED = AttemptStatus(
    "tasks", "tl-1", "second", "s1", "admitted", "none", AttemptResult("pending", "admitted"), False, "start",
    earlier=(("first", "abandoned"),), seq=2, release=ReleaseRow(D, 30.0, True, "unclaimed"),
)
RELEASE = ["plan", "release", "tl-1", "--backlog", "tasks"]
FREED = {"status", "backlog", "task", "attempt_id", "slot", "parked", "reservation_removed", "claim", "abandoned"}
X, T = "a" * 40, "b" * 40
PUBLISH = ["plan", "publish", "tl-1", "--backlog", "tasks"]
PUBLISHED = {"status", "backlog", "task", "attempt_id", "commit", "remote_head"}
CHECKED = {"status", "backlog", "task", "attempt_id", "release", "published"}
NEXT = ["plan", "next", "--backlog", "tasks", "--tracker-root", "/tracker", "--checkout", "/checkout", "--label", "auto", "--model", "m",
        "--effort", "high", "--minutes", "30"]
ROUND = {"status", "backlog", "moves", "stopped", "logged"}
MOVES = (Move("tl-3", "start", "started", "a3"), Move("tl-2", "report", "stuck:hung", "a2"), Move("tl-10", "skip", "abandoned"),
         Move("tl-4", "report", "failed:rejected:paths", "a4", "never shown"), Move("tl-5", "report", "claim_leaked"))
DONE = AttemptStatus(
    "tasks", "tl-1", "attempt", "s1", "captured", "gone", AttemptResult("collected", "verified"), False, "done",
    release=ReleaseRow(D, 30.0, False, "kept"), published=PublishedRow(X, X, 40.0),
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


class Launcher:
    def launch(self, backlog: str, task_id: str, minutes: int) -> LaunchResult:
        return Launched(KEY, ENTRY)


class NoRepeat:
    def repeat(self, backlog: str, task_id: str, current: AttemptKey, entry: Entry | None, minutes: int) -> Started | Failed:
        raise AssertionError("a first start never repeats")


def test_start_flags_and_config_reach_the_request_and_the_openers(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    con = Store(SCHEMA).open_rw(tmp_path / "empty.db")
    assert con is not None
    admission, opened = Admission(), list[tuple[Path, Path]]()

    @contextmanager
    def opener(database: Path, artifacts: Path) -> Generator[Starting | Failed]:
        opened.append((database, artifacts))
        yield Starting(AttemptStore(lambda: con), admission, Launcher(), lambda: 1000, NoRepeat())

    monkeypatch.setattr(cli_composition, "open_start", opener)
    config = tmp_path / "scratch.toml"
    config.write_text(f'db = "{tmp_path / "file.db"}"\nartifacts = "{tmp_path / "file-art"}"\n')
    assert main(["--config", str(config), *START, "--artifacts", str(tmp_path / "flag-art"), "--json"]) == 0
    con.close()
    assert opened == [(tmp_path / "file.db", tmp_path / "flag-art")]
    request = admission.requests[0]
    assert (request.task_id, request.backlog, request.tracker_root, request.checkout) == ("tl-1", "tasks", "/tracker", Path("/checkout"))
    assert (request.model, request.effort, request.sandbox, request.deadline) == ("m", "high", SANDBOX, 1000 + 30 * 60)
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "status": "started", "backlog": "tasks", "task": "tl-1", "attempt_id": "attempt", "existing": False,
        "entry": {"pid": 7, "start": "entry-start", "boot": "boot"}, "number": None, "result": "",
    }
    assert "dispatch-token-never-shown" not in output.out + output.err
    assert not home.exists()


VIEW = SlotView("s2", Path("/slots/s2"), "unknown", "dirty")
STARTED = {"status", "backlog", "task", "attempt_id", "existing", "entry", "number", "result"}
CASES: list[tuple[list[str], Result, int, list[str], set[str]]] = [
    (START, Started("started", "tasks", "tl-1", "attempt", False, ENTRY), 0, ["started: attempt attempt for tl-1", cli_plan.HELD], STARTED),
    (START, Started("relaunched", "tasks", "tl-1", "attempt", True, ENTRY), 0, ["existing attempt; its admitted choices stand"], STARTED),
    (START, Started("already_running", "tasks", "tl-1", "attempt", True, ENTRY), 0, ["already_running: attempt"], STARTED),
    (START, Started("already_dispatched", "tasks", "tl-1", "attempt", True), 0, ["already_dispatched: attempt"], STARTED),
    (START, Started("already_dispatched", "tasks", "tl-1", "attempt", True, result="rejected:paths"), 0, ["Result: rejected:paths"],
     STARTED),
    (START, Started("repeated", "tasks", "tl-1", "next", False, ENTRY, number=2), 0,
     ["repeated: attempt next for tl-1", "attempt 2 of at most 3; attempt 1's choices stand; deadline from --minutes", cli_plan.HELD],
     STARTED),
    (START, Failed("refused", "repeats_exhausted"), 1, ["refused:repeats_exhausted", cli_plan.GUIDE["repeats_exhausted"]], ADMISSION_ERROR),
    (START, Failed("refused", "repeat_cap"), 1, ["tl plan start: refused:repeat_cap"], ADMISSION_ERROR),
    (START, Failed("refused", "not_repeatable"), 1, ["tl plan start: refused:not_repeatable"], ADMISSION_ERROR),
    (START, Failed("unsettled", "worker_alive"), 3, ["tl plan start: unsettled:worker_alive", cli_plan.GUIDE["unsettled"]],
     ADMISSION_ERROR),
    (START, Failed("unsettled", "superseded"), 3, ["tl plan start: unsettled:superseded"], ADMISSION_ERROR),
    (START, Failed("refused", "no_free_slot", slots=(VIEW,)), 1, ["tl plan start: refused:no_free_slot", "s2 unknown dirty /slots/s2"],
     ADMISSION_ERROR),
    (START, Failed("refused", "registration_refused"), 1, ["refused:registration_refused"], ADMISSION_ERROR),
    (START, Failed("refused", "registration_conflict"), 1, [cli_plan.GUIDE["registration_conflict"]], ADMISSION_ERROR),
    (START, Failed("unavailable", "start", admitted=True), 3, [f"Admitted: {cli_plan.HELD} Re-run `tl plan start` to retry"],
     ADMISSION_ERROR),
    (START, Failed("unavailable", "tracker", claim_leaked=True), 3, ["unavailable:tracker"], ADMISSION_ERROR),
    (START, Failed("uncertain", "launch"), 3, ["tl plan start: uncertain"], ADMISSION_ERROR),
    (["plan", "show", "tl-1", "--backlog", "tasks"], Shown(STATUS, Path("/a/d"), Path("/a/d/entry.log")), 0,
     ["Phase: captured", "Result: pending verification", "Entry log: /a/d/entry.log", "Next: verify", "Run `tl plan verify`."],
     STATUS_KEYS | {"directory", "entry_log"}),
    (["plan", "show", "tl-1", "--backlog", "tasks"], Shown(REPEAT, Path("/a/d"), Path("/a/d/entry.log")), 0,
     ["Worker: last known pid 42, process group 41 (not checked)", "Result: pending repeat", "Unsettled: uncommitted",
      "  ?? docs/design/tl-1/note.md", "  +3 more", f"Next: repeat\n{cli_plan.GUIDE['repeat']}",
      "Attempt: attempt (2 of at most 3; repeats first, uncommitted)\nEarlier: first repeated (uncommitted)\nSlot: s1"],
     STATUS_KEYS | {"directory", "entry_log"}),
    (["plan", "list", "--stuck"], Listed((STATUS,)), 0,
     ["task\tbacklog\tattempt\tslot", "tl-1\ttasks\t1/3\ts1\tcaptured\tgone\tpending verification\tverify"], {"attempts"}),
    (["plan", "show", "tl-1", "--backlog", "tasks"], Shown(STATUS, Path("/a/d"), Path("/a/d/entry.log")), 0,
     ["Attempt: attempt (1 of at most 3)\nSlot: s1"], STATUS_KEYS | {"directory", "entry_log"}),
    (["plan", "verify", "tl-1", "--backlog", "tasks"], Checked("reused", "tasks", "tl-1", "attempt", "released", "published"), 0,
     ["reused: attempt attempt", "Release: released\nPublish: published"], CHECKED),
    (["plan", "verify", "tl-1", "--backlog", "tasks"],
     Checked("verified", "tasks", "tl-1", "attempt", "held:slot_dirty", "unavailable:remote"), 0,
     ["Release: held:slot_dirty", cli_plan.GUIDE["release"], f"Publish: unavailable:remote\n{cli_plan.PUBLISH}"], CHECKED),
    (PUBLISH, PublishedTask("tasks", "tl-1", "attempt", BranchPublished(X, X)), 0,
     [f"published: task/tl-1 at {X} on origin (attempt attempt, backlog tasks)\n"], PUBLISHED),
    (PUBLISH, PublishedTask("tasks", "tl-1", "attempt", AlreadyPublished(X, X, 40.0)), 0,
     [f"already_published: task/tl-1 at {X} on origin (attempt attempt, backlog tasks)\nNothing changed: it was published before."],
     PUBLISHED),
    (PUBLISH, Failed("refused", "diverged", f"origin's task/tl-1 is at {T}"), 1,
     ["tl plan publish: refused:diverged", cli_plan.GUIDE["diverged"]], ERROR),
    (PUBLISH, Failed("refused", "remote_ahead"), 1, [cli_plan.GUIDE["remote_ahead"]], ERROR),
    (PUBLISH, Failed("refused", "no_remote"), 1, [cli_plan.GUIDE["no_remote"]], ERROR),
    (PUBLISH, Failed("refused", "repository"), 1, [cli_plan.GUIDE["repository"]], ERROR),
    (PUBLISH, Failed("refused", "not_verified"), 1, [cli_plan.GUIDE["not_verified"]], ERROR),
    (PUBLISH, Failed("unavailable", "git"), 3, [cli_plan.GUIDE["git"]], ERROR),
    (PUBLISH, Failed("unavailable", "remote"), 3, ["tl plan publish: unavailable:remote", cli_plan.GUIDE["remote"]], ERROR),
    (["plan", "show", "tl-1", "--backlog", "tasks"], Shown(DONE, Path("/a/d"), Path("/a/d/entry.log")), 0,
     [f"Published: task/tl-1 at {X} on origin, 1970-01-01 00:00:40 UTC\n", "Next: done"],
     STATUS_KEYS | {"directory", "entry_log"}),
    (["plan", "show", "tl-1", "--backlog", "tasks"], Shown(ABANDONED, Path("/a/d"), Path("/a/d/entry.log")), 0,
     ["Earlier: first abandoned", f"Released: 1970-01-01 00:00:30 UTC, slot parked at {D}; claim unclaimed; abandoned",
      f"Next: start\n{cli_plan.GUIDE['abandoned']}"],
     STATUS_KEYS | {"directory", "entry_log"}),
    (RELEASE, Freed("tasks", "tl-1", "attempt", Released("s1", D, True, "kept", False)), 0,
     ["released: attempt attempt for tl-1 (backlog tasks)\n", f"Slot s1 parked at {D}\nReservation of s1 removed\nClaim kept"], FREED),
    ([*RELEASE, "--abandon"], Freed("tasks", "tl-1", "attempt", Released("s1", None, True, "not_held", True)), 0,
     ["Slot s1: no Git write", "Claim not held by taskloop (reverted, or another actor's): check `bd show tl-1`",
      "Abandoned: `tl plan start tl-1` admits a fresh attempt"], FREED),
    (RELEASE, Freed("tasks", "tl-1", "attempt", AlreadyReleased("s1", "unclaimed", True)), 0,
     ["already_released: attempt attempt for tl-1 (backlog tasks); nothing changed", "Claim: unclaimed; abandoned"], FREED),
    (RELEASE, Failed("refused", "slot_dirty", "?? x\nRemove the listed files. Nothing changed."), 1,
     ["tl plan release: refused:slot_dirty\n?? x\nRemove the listed files. Nothing changed.", cli_plan.GUIDE["slot_dirty"]], ERROR),
    (RELEASE, Failed("refused", "not_terminal"), 1, [cli_plan.GUIDE["not_terminal"]], ERROR),
    (RELEASE, Failed("unsettled", "worker_unknown"), 3, [cli_plan.GUIDE["worker_unknown"]], ERROR),
    (RELEASE, Failed("unavailable", "tracker", "Released; the tracker claim is still to be returned (other): rerun"), 3,
     ["unavailable:tracker\nReleased; the tracker claim is still to be returned"], ERROR),
    (["plan", "verify", "tl-1", "--backlog", "tasks"], Failed("rejected", "paths"), 1, ["tl plan verify: rejected:paths"], ERROR),
    (["plan", "verify", "tl-1", "--backlog", "tasks"], Failed("not_applicable", "incomplete"), 1, ["not_applicable:incomplete"], ERROR),
    (["plan", "verify", "tl-1", "--backlog", "tasks"], Failed("unsettled", "dirty"), 3, ["unsettled:dirty", cli_plan.GUIDE["unsettled"]],
     ERROR),
    (["plan", "verify", "tl-1", "--backlog", "tasks"], Failed("unavailable", "slot_busy"), 3,
     ["unavailable:slot_busy", cli_plan.GUIDE["slot_busy"]], ERROR),
    (NEXT, Round("tasks", MOVES, "no_free_slot"), 0,
     ["tl-3   start    started a3\ntl-2   report   stuck:hung a2\ntl-10  skip     abandoned\n", "Stopped: no_free_slot",
      f"stuck:hung: {cli_plan.GUIDE['stuck:hung']}", f"failed: {cli_plan.GUIDE['failed']}",
      f"abandoned_skip: {cli_plan.GUIDE['abandoned_skip']}", f"no_free_slot: {cli_plan.GUIDE['no_free_slot']}",
      "tl-5   report   claim_leaked\n", f"claim_leaked: {cli_plan.GUIDE['claim_leaked']}"], ROUND),
    (NEXT, Round("tasks", (), "unavailable:tracker"), 3, ["Stopped: unavailable:tracker"], ROUND),
    (NEXT, Round("tasks", ()), 0, ["Nothing to do in backlog tasks."], ROUND),
    (NEXT, Failed("refused", "label"), 1, ["tl plan next: refused:label"], ERROR),
    (["slot", "adopt", "/repo"], Adoption((Adopted("s1", Path("/s/s1")),)), 0, ["s1 adopted /s/s1"], {"slots"}),
    (["slot", "adopt", "/repo"], Adoption((NotAdopted("s1", "not_listed", Path("/s/s1")),)), 1,
     ["s1 not_listed /s/s1", "git worktree add --detach"], {"slots"}),
    (["slot", "adopt", "/repo"], Adoption((NotAdopted("s1", "attached", Path("/s/s1")),)), 1,
     ["s1 attached /s/s1", "`git switch --detach` in a slot left on a task branch"], {"slots"}),
    (["slot", "adopt", "/repo"], Adoption((NotAdopted("s1", "store_unavailable", Path("/s/s1")),)), 3, ["s1 store_unavailable"], {"slots"}),
]


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("argv, result, code, lines, keys", CASES)
def test_result_exit_code_text_and_json_keys(
    argv: list[str], result: Result, code: int, lines: list[str], keys: set[str], structured: bool,
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setitem(cli_plan.OPERATIONS, (argv[0], argv[1]), lambda _arguments, _loaded: result)
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
            assert data.startswith("the tracker claim on tl-1 may still be held by taskloop; check `bd show tl-1`\n")


@pytest.mark.parametrize("step", words(Next))
def test_every_next_step_renders_with_its_guidance(step: Next, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    shown = Shown(AttemptStatus("tasks", "tl-1", "a", "s1", "admitted", "none", AttemptResult("pending", "admitted"), False, step),
                  Path("/d"), Path("/d/entry.log"))
    monkeypatch.setitem(cli_plan.OPERATIONS, ("plan", "show"), lambda _arguments, _loaded: shown)
    assert main(["plan", "show", "tl-1", "--backlog", "tasks"]) == 0
    assert f"Next: {step}\n{cli_plan.GUIDE[step]}" in capsys.readouterr().out


@pytest.mark.parametrize("entry", words(EntryState))
def test_every_entry_state_renders(entry: EntryState, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    listed = Listed((AttemptStatus("tasks", "tl-1", "a", "s1", "admitted", entry, AttemptResult("pending", "admitted"), False, "unknown"),))
    monkeypatch.setitem(cli_plan.OPERATIONS, ("plan", "list"), lambda _arguments, _loaded: listed)
    assert main(["plan", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["attempts"][0]["entry"] == entry


@pytest.mark.parametrize("kind", words(FailureKind))
def test_every_failure_kind_has_its_exit_code(
    kind: FailureKind, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(cli_plan.OPERATIONS, ("plan", "list"), lambda _arguments, _loaded: Failed(kind, "r"))
    assert main(["plan", "list"]) == (3 if kind in ("unavailable", "uncertain", "unsettled") else 1)
    assert capsys.readouterr().err.startswith("tl plan list: ")


@pytest.mark.parametrize("argv", [["plan", "abandon", "tl-1", "--backlog", "tasks"], ["slot", "release", "s1"], RELEASE[:3]])
def test_the_placeholders_are_gone_and_release_needs_its_backlog(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    """A hard cut: `tl plan release [--abandon]` replaces both placeholders, with no alias."""
    with pytest.raises(SystemExit) as result:
        main(argv)
    assert result.value.code == 2 and "usage: tl" in capsys.readouterr().err


class Releases:
    def __init__(self) -> None:
        self.calls: list[tuple[AttemptKey, bool]] = []

    def release(self, key: AttemptKey, abandon: bool, me: Entry | None = None) -> ReleaseResult:
        self.calls.append((key, abandon))
        return Released("s1", None, True, "unclaimed", abandon)


@pytest.mark.parametrize("abandon", [False, True])
def test_release_flags_reach_the_operation_through_the_opener(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], abandon: bool
) -> None:
    db, releases, opened = tmp_path / "factory.db", Releases(), list[Path]()
    admitted(db)
    con = Store(SCHEMA).open_ro(db)
    assert con is not None

    @contextmanager
    def opener(database: Path) -> Generator[tuple[AttemptStore, Releases]]:
        opened.append(database)
        yield AttemptStore(lambda: con), releases

    monkeypatch.setattr(cli_composition, "open_release", opener)
    assert main([*RELEASE, *(["--abandon"] if abandon else []), "--db", str(db), "--json"]) == 0
    con.close()
    assert opened == [db] and releases.calls == [(KEY, abandon)]
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
    def opener(database: Path) -> Generator[tuple[AttemptStore, Publishes]]:
        opened.append(database)
        yield AttemptStore(lambda: con), publishes

    monkeypatch.setattr(cli_composition, "open_publish", opener)
    assert main([*PUBLISH, "--db", str(db), "--json"]) == 0
    con.close()
    assert opened == [db] and publishes.keys == [KEY]
    assert json.loads(capsys.readouterr().out) == {
        "status": "published", "backlog": "tasks", "task": "tl-1", "attempt_id": "attempt", "commit": X, "remote_head": X,
    }


def admitted(path: Path) -> None:
    """One admitted, unregistered attempt (tasks/tl-1, deadline 100) and its reservation, as the conftest of tests/steps."""
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    with begin_immediate(con):
        con.execute("INSERT INTO reservation VALUES ('s1','repo','/slots/s1',1,'attempt')")
        con.execute(
            """INSERT INTO plan_attempt (attempt_id,dispatch_token,generation,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,
            input_digest,schema_version,model,effort,sandbox,deadline,number,seq,slot_head)
            VALUES ('attempt',?,1,'beads','tasks','tl-1','/tracker','repo','s1','input.txt',?,1,'m','high','workspace-write',100,1,1,
            'dddddddddddddddddddddddddddddddddddddddd')""",
            (KEY.dispatch_token, hashlib.sha256(b"x").hexdigest()),
        )
    con.close()


def test_the_real_read_paths_write_nothing_and_never_print_the_token(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db, art = tmp_path / "factory.db", tmp_path / "art"
    admitted(db)
    assert main(["plan", "show", "tl-1", "--backlog", "tasks", "--db", str(db), "--artifacts", str(art), "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert (shown["phase"], shown["entry"], shown["next"]) == ("admitted", "none", "stuck:expired_admitted")
    assert set(shown) == STATUS_KEYS | {"directory", "entry_log"} and (shown["entry_process"], shown["worker"]) == (None, None)
    assert main(["plan", "list", "--stuck", "--db", str(db)]) == 0
    listed = capsys.readouterr().out
    assert "stuck:expired_admitted: Nothing ran; rounds only report it. `tl plan release --abandon`" in listed
    assert f"delete {db} and its" in listed
    assert main(["plan", "verify", "tl-1", "--backlog", "tasks", "--db", str(db), "--json"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.err)["error"]["reason"] == "not_captured"
    assert KEY.dispatch_token not in output.out + output.err + json.dumps(shown)
    assert not art.exists()
    con = sqlite3.connect(db)
    assert con.execute("SELECT phase,rev FROM plan_attempt").fetchall() == [("admitted", 0)]
    con.close()


@pytest.mark.parametrize(
    "argv", [["plan", "show", "tl-1", "--backlog", "tasks"], ["plan", "list"], ["plan", "verify", "tl-1", "--backlog", "b"], START, PUBLISH]
)
def test_without_a_factory_database_every_plan_command_refuses_and_creates_none(
    argv: list[str], tmp_path: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "factory.db"  # in an existing directory: a writable open would create it
    assert main([*argv, "--db", str(missing), "--json"]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert (error["kind"], error["reason"]) == ("refused", "database")
    assert not missing.exists() and not home.exists()


def test_adopt_takes_its_paths_and_count_from_flags_config_and_defaults(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[Path, Path, Path, int]] = []

    def adopt(database: Path, checkout: Path, root: Path, count: int) -> Adoption:
        calls.append((database, checkout, root, count))
        return Adoption((Adopted("s1", root / "id" / "s1"), NotAdopted("s2", "not_listed", root / "id" / "s2")))

    monkeypatch.setattr(cli_composition, "adopt", adopt)
    config = tmp_path / "scratch.toml"
    config.write_text("slot_count = 2\n")
    assert main(["--config", str(config), "slot", "adopt", str(tmp_path / "repo"), "--root", str(tmp_path / "slots"), "--json"]) == 1
    assert calls == [(home / ".local/state/task-loop/factory.db", tmp_path / "repo", tmp_path / "slots", 2)]
    assert json.loads(capsys.readouterr().out) == {"slots": [
        {"name": "s1", "adopted": True, "reason": None, "path": str(tmp_path / "slots/id/s1")},
        {"name": "s2", "adopted": False, "reason": "not_listed", "path": str(tmp_path / "slots/id/s2")},
    ]}


class Rounds:
    """`advance`'s ports are opaque to the surface: the opener's value is passed through to the stubbed operation."""


def test_next_flags_reach_the_request_and_the_opener_and_its_json_is_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    opened: list[tuple[Path, Path, str]] = []
    requests: list[object] = []
    ports = Rounds()

    @contextmanager
    def opener(database: Path, artifacts: Path, tracker_root: str) -> Generator[Rounds]:
        opened.append((database, artifacts, tracker_root))
        yield ports

    def advanced(given: object, request: object) -> Round:
        assert given is ports
        requests.append(request)
        return Round("tasks", (MOVES[0],), logged=False)

    monkeypatch.setattr(cli_composition, "open_next", opener)
    monkeypatch.setattr(cli_plan, "advance", advanced)
    assert main([*NEXT, "--db", str(tmp_path / "f.db"), "--artifacts", str(tmp_path / "art"), "--json"]) == 0
    assert opened == [(tmp_path / "f.db", tmp_path / "art", "/tracker")]
    assert requests == [cli_plan.NextRequest("tasks", "/tracker", Path("/checkout"), "auto", "m", "high", 30)]
    assert json.loads(capsys.readouterr().out) == {
        "status": "round", "backlog": "tasks", "stopped": None, "logged": False,
        "moves": [{"task": "tl-3", "action": "start", "word": "started", "attempt_id": "a3", "detail": ""}],
    }
    assert main([*NEXT, "--artifacts", str(tmp_path / "art")]) == 0
    assert f"Log: not written ({tmp_path / 'art' / 'rounds.log'})" in capsys.readouterr().out


@pytest.mark.parametrize("missing", ["--label", "--backlog", "--tracker-root", "--checkout", "--model", "--effort", "--minutes"])
def test_next_requires_every_choice_and_its_help_names_the_round(missing: str, capsys: pytest.CaptureFixture[str]) -> None:
    at = NEXT.index(missing)
    with pytest.raises(SystemExit) as result:
        main([*NEXT[:at], *NEXT[at + 2:]])
    assert result.value.code == 2 and missing in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["plan", "next", "--help"])
    shown = " ".join(capsys.readouterr().out.split())
    assert "Run one scheduling round for the plan step: settle existing attempts, start approved ready tasks" in shown
    assert "plan step only: publishes task/<id>; no merge or land" in shown


def test_next_refuses_an_unusable_tracker_root_and_a_missing_database(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "factory.db"
    assert main([*NEXT, "--db", str(db), "--json"]) == 1
    assert json.loads(capsys.readouterr().err)["error"]["reason"] == "database" and not db.exists()
    admitted(db)
    assert main([*NEXT[:5], str(tmp_path / "absent"), *NEXT[6:], "--db", str(db), "--json"]) == 1
    assert json.loads(capsys.readouterr().err)["error"]["reason"] == "tracker_root"


ROUNDS = ["plan", "rounds", *NEXT[2:]]


class Run:
    """The stubbed rounds: the opener's value passed through, the requests recorded, `ended` returned or raised."""

    def __init__(self, ended: Ended | BaseException) -> None:
        self.ended, self.opened, self.requests = ended, list[tuple[Path, Path, object]](), list[object]()

    @contextmanager
    def opener(self, database: Path, artifacts: Path, request: object) -> Generator[object]:
        self.opened.append((database, artifacts, request))
        yield self

    def run(self, given: object, request: object) -> Ended:
        assert given is self
        self.requests.append(request)
        if isinstance(self.ended, BaseException):
            raise self.ended
        return self.ended


def stubbed(monkeypatch: pytest.MonkeyPatch, ended: Ended | BaseException) -> Run:
    run = Run(ended)
    monkeypatch.setattr(cli_composition, "open_rounds", run.opener)
    monkeypatch.setattr(cli_plan, "run_rounds", run.run)
    return run


def test_rounds_flags_reach_the_opener_and_print_a_start_and_an_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run, art = stubbed(monkeypatch, Ended("tasks", "interrupted")), tmp_path / "art"
    assert main([*ROUNDS, "--db", str(tmp_path / "f.db"), "--artifacts", str(art)]) == 0
    request = cli_plan.NextRequest("tasks", "/tracker", Path("/checkout"), "auto", "m", "high", 30)
    assert run.opened == [(tmp_path / "f.db", art, request)] and run.requests == [cli_plan.RoundsRequest("tasks", 60)]
    output = capsys.readouterr()
    assert output.out.splitlines() == [
        f"Rounds for backlog tasks every 60 s; log: {art / 'rounds.log'}; stop with Ctrl-C",
        "Rounds stopped: interrupted. Launched steps keep running; `tl plan rounds` again continues them.",
    ] and output.err == ""
    config = tmp_path / "scratch.toml"
    config.write_text("round_seconds = 90\n")
    assert main(["--config", str(config), *ROUNDS, "--every", "30", "--artifacts", str(art), "--json"]) == 0
    assert run.requests[-1] == cli_plan.RoundsRequest("tasks", 30)
    assert [json.loads(line) for line in capsys.readouterr().out.splitlines()] == [
        {"status": "rounds", "backlog": "tasks", "every": 30, "log": str(art / "rounds.log")},
        {"status": "ended", "backlog": "tasks", "reason": "interrupted", "detail": ""},
    ]


def test_a_whole_round_refusal_ends_the_rounds_with_exit_1(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    stubbed(monkeypatch, Ended("tasks", "refused:database", "No readable factory.db"))
    assert main(ROUNDS) == 1
    output = capsys.readouterr()
    assert output.out.startswith("Rounds for backlog tasks every 60 s")
    assert output.err.splitlines() == ["tl plan rounds: refused:database", "No readable factory.db"]


@pytest.mark.parametrize("structured", [False, True])
def test_a_second_ctrl_c_exits_130(structured: bool, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    stubbed(monkeypatch, KeyboardInterrupt())
    assert main([*ROUNDS, *(["--json"] if structured else [])]) == 130
    err = capsys.readouterr().err
    assert json.loads(err) == {"status": "ended", "backlog": "tasks", "reason": "abrupt", "detail": ""} if structured else (
        err == "Stopped at once.\n")


def test_a_factory_db_that_exists_but_cannot_be_opened_backs_off_while_an_absent_one_ends(tmp_path: Path) -> None:
    db = tmp_path / "factory.db"
    request = cli_plan.NextRequest("tasks", str(tmp_path), Path("/checkout"), "auto", "m", "high", 30)
    once = cli_composition.one_round(db, tmp_path / "art", request, lambda: False)
    absent = once(frozenset())
    assert isinstance(absent, Failed) and (absent.kind, absent.reason) == ("refused", "database")
    db.write_bytes(b"not a database, or one locked past the busy timeout")
    unopened = once(frozenset())
    assert isinstance(unopened, Failed) and (unopened.kind, unopened.reason) == ("unavailable", "store")


def test_rounds_refuse_a_short_interval_before_opening_anything(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = stubbed(monkeypatch, Ended("tasks", "interrupted"))
    assert main([*ROUNDS, "--every", "4", "--json"]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert (error["kind"], error["reason"]) == ("refused", "interval") and run.opened == []
    assert main([*ROUNDS, "--every", "4"]) == 1
    assert cli_plan.GUIDE["interval"] in capsys.readouterr().err


@pytest.mark.parametrize("missing", ["--label", "--backlog", "--tracker-root", "--checkout", "--model", "--effort", "--minutes"])
def test_rounds_require_every_choice_and_the_help_names_the_stop(missing: str, capsys: pytest.CaptureFixture[str]) -> None:
    at = ROUNDS.index(missing)
    with pytest.raises(SystemExit) as result:
        main([*ROUNDS[:at], *ROUNDS[at + 2:]])
    assert result.value.code == 2 and missing in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["plan", "rounds", "--help"])
    shown = " ".join(capsys.readouterr().out.split())
    assert "Run scheduling rounds until stopped (Ctrl-C): a round at once, then every --every seconds and as soon as a slot" in shown
    assert "Ctrl-C once stops after the current move, twice exits at once; launched steps keep running." in shown


def test_the_real_opener_refuses_inputs_a_missing_database_and_a_second_rounds_process_before_any_round(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every refusal comes before the lock (except `rounds_running`) and before the SIGINT handler: no handler installed."""
    db = tmp_path / "factory.db"
    at = ROUNDS.index("--label") + 1
    assert main([*ROUNDS[:at], " ", *ROUNDS[at + 1:], "--db", str(db), "--json"]) == 1
    assert json.loads(capsys.readouterr().err)["error"]["reason"] == "label"
    assert main([*ROUNDS, "--db", str(db), "--json"]) == 1
    assert json.loads(capsys.readouterr().err)["error"]["reason"] == "database" and list(tmp_path.iterdir()) == []
    admitted(db)
    held = rounds_lock.hold(db, "tasks")
    try:
        assert main([*ROUNDS, "--db", str(db)]) == 1
    finally:
        held.release()
    output = capsys.readouterr()
    assert output.out == "" and "tl plan rounds: refused:rounds_running" in output.err and cli_plan.GUIDE["rounds_running"] in output.err
