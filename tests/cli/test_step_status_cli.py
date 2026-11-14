"""Default backlog selection and hold diagnostics through the CLI's real read-only composition."""

import json
import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlite_store import Store, begin_immediate

from taskloop import cli_composition
from taskloop.answer_failures import AnswerFailureData, AnswerRule, encode
from taskloop.cli import main
from taskloop.drain.models import Identity, Seen
from taskloop.factory_schema import SCHEMA
from taskloop.hold_store import HoldInsert, HoldStore
from taskloop.recovery.models import ProcessObservation
from taskloop.recovery.observe import NativeProcesses

D = "d" * 40


@pytest.mark.parametrize("seen", [Seen.ALIVE, Seen.UNKNOWN, Seen.GONE])
def test_status_composition_observes_worker_groups_without_writing(
    factory: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], seen: Seen,
) -> None:
    attempt(factory, "a", "tasks", deadline=1e12)
    factory.execute("INSERT INTO reservation VALUES('s1','repo',1,'a')")
    factory.execute(
        """UPDATE attempt SET phase='registered',entry_pid=7,entry_start='entry',entry_boot='boot',
        worker_pid=8,worker_pgid=8,worker_start='worker',worker_boot='boot',session_ref='saved',base_commit=?""", (D,),
    )
    calls: list[int] = []

    def process(_self: NativeProcesses, identity: Identity) -> ProcessObservation:
        calls.append(identity.pid)
        return ProcessObservation(seen=seen, explanation="Worker group observation.")

    monkeypatch.setattr(cli_composition, "entry_seen", lambda _entry: "gone")
    monkeypatch.setattr(NativeProcesses, "entry", lambda _self, _entry: ProcessObservation(
        seen=Seen.GONE, explanation="Entry is absent."))
    monkeypatch.setattr(NativeProcesses, "process", process)
    db, artifacts = tmp_path / "factory.db", tmp_path / "artifacts"
    before, rows = db.read_bytes(), list(factory.iterdump())
    expected = {Seen.ALIVE: "wait", Seen.UNKNOWN: "unknown", Seen.GONE: "release"}[seen]
    for _ in range(2):
        assert main(["step", "show", "tl-1", "--db", str(db), "--artifacts", str(artifacts), "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["next"] == expected
        assert main(["step", "list", "--db", str(db), "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["attempts"][0]["next"] == expected
    assert calls == [8] * 4
    assert db.read_bytes() == before and list(factory.iterdump()) == rows and not artifacts.exists()


@pytest.fixture
def factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[sqlite3.Connection]:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    con = Store(SCHEMA).open_rw(tmp_path / "factory.db")
    assert con is not None
    with begin_immediate(con):
        con.execute("INSERT INTO slot (repo_id,name,path) VALUES ('repo','s1','/slots/s1')")
    try:
        yield con
    finally:
        con.close()


def attempt(con: sqlite3.Connection, key: str, backlog: str, task: str = "tl-1", *, seq: int = 1,
            label: str | None = None, deadline: float = 100) -> None:
    with begin_immediate(con):
        con.execute(
            """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
            input_path,input_digest,schema_version,model,effort,access_policy,deadline,number,seq,slot_head,label) VALUES
            (?,?,1,'plan','beads',?,?,'/tracker','repo','s1','input','digest',1,'m','high','{"harness":"codex","sandbox":"workspace-write"}',?,1,?,?,?)""",
            (key, f"{key}-token", backlog, task, deadline, seq, D, label),
        )


def release(con: sqlite3.Connection, key: str) -> None:
    with begin_immediate(con):
        con.execute("INSERT INTO slot_release VALUES (?,?,1,?,14,'unclaimed')", (key, f"{key}-token", D))


@pytest.mark.parametrize("structured", [False, True])
def test_show_reports_persisted_answer_failure_without_artifacts(
    factory: sqlite3.Connection, tmp_path: Path, capsys: pytest.CaptureFixture[str], structured: bool,
) -> None:
    attempt(factory, "broken", "tasks")
    failure = AnswerFailureData(rule=AnswerRule.MESSAGE, explanation="A commit message must contain 1 to 500 characters")
    with begin_immediate(factory):
        factory.execute("UPDATE attempt SET phase='captured',base_commit=?", (D,))
        factory.execute(
            """INSERT INTO execution (attempt_id,dispatch_token,generation,rc,timed_out,work,stands,stdout_path,
            stdout_digest,stderr_path,stderr_digest,answer_path,answer_digest,diagnostic_path,diagnostic_digest,
            answer_kind,session_state,answer_failure)
            VALUES ('broken','broken-token',1,0,0,1,1,'o','d','e','d','a','d','g','d','schema_invalid','complete',?)""",
            (encode(failure),),
        )
    db, artifacts = tmp_path / "factory.db", tmp_path / "artifacts"
    before = db.read_bytes()
    assert main(["step", "show", "tl-1", "--db", str(db), "--artifacts", str(artifacts),
                 *(["--json"] if structured else [])]) == 0
    output = capsys.readouterr()
    assert not output.err
    if structured:
        result = json.loads(output.out)["result"]
        assert result == {"status": "collected", "reason": "answer:schema_invalid",
                          "explanation": failure.describe() + " Usage was not reported by the agent stream."}
    else:
        assert "Result: collected answer:schema_invalid" in output.out
        assert "Answer: " + failure.describe() in output.out
    assert db.read_bytes() == before and not artifacts.exists()


def config(tmp_path: Path, backlog: str) -> list[str]:
    path = tmp_path / "config.toml"
    path.write_text(f"backlog = {json.dumps(backlog)}\n")
    return ["--config", str(path)]


@pytest.mark.parametrize("structured", [False, True])
def test_show_defaults_to_one_distinct_backlog_and_writes_nothing(
    factory: sqlite3.Connection, tmp_path: Path, capsys: pytest.CaptureFixture[str], structured: bool,
) -> None:
    attempt(factory, "first", "tasks")
    release(factory, "first")
    attempt(factory, "second", "tasks", seq=2)
    db, artifacts = tmp_path / "factory.db", tmp_path / "artifacts"
    before = db.read_bytes()
    assert main(["step", "show", "tl-1", "--db", str(db), "--artifacts", str(artifacts),
                 *(["--json"] if structured else [])]) == 0
    output = capsys.readouterr()
    assert not output.err
    if structured:
        shown = json.loads(output.out)
        assert (shown["backlog"], shown["task"], shown["attempt_id"]) == ("tasks", "tl-1", "second")
        assert shown["earlier"] == ["first"]
    else:
        assert "Task: tl-1 (backlog tasks)" in output.out
        assert "Attempt: second" in output.out
    assert db.read_bytes() == before
    assert not artifacts.exists() and not (tmp_path / "home").exists()


@pytest.mark.parametrize(("chosen", "explicit", "expected"), [
    ("alpha", None, "alpha"), ("alpha", "zeta", "zeta"),
])
@pytest.mark.parametrize("structured", [False, True])
def test_show_prefers_the_explicit_backlog_then_the_machine_config(
    factory: sqlite3.Connection, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    chosen: str, explicit: str | None, expected: str, structured: bool,
) -> None:
    attempt(factory, "a", "alpha")
    attempt(factory, "z", "zeta")
    assert main([*config(tmp_path, chosen), "step", "show", "tl-1", "--db", str(tmp_path / "factory.db"),
                 *(["--backlog", explicit] if explicit is not None else []), *(["--json"] if structured else [])]) == 0
    output = capsys.readouterr()
    assert not output.err
    if structured:
        assert json.loads(output.out)["backlog"] == expected
    else:
        assert f"Task: tl-1 (backlog {expected})" in output.out


@pytest.mark.parametrize("explicit", [False, True])
def test_a_selected_backlog_without_the_task_refuses_absent_without_falling_through(
    factory: sqlite3.Connection, tmp_path: Path, capsys: pytest.CaptureFixture[str], explicit: bool,
) -> None:
    attempt(factory, "a", "alpha", "tl-other")
    attempt(factory, "z", "zeta")
    flags = ["--backlog", "alpha"] if explicit else []
    assert main([*config(tmp_path, "zeta" if explicit else "alpha"), "step", "show", "tl-1", *flags,
                 "--db", str(tmp_path / "factory.db"), "--json"]) == 1
    output = capsys.readouterr()
    error = json.loads(output.err)["error"]
    assert (error["kind"], error["reason"]) == ("refused", "absent")
    assert "No attempt for tl-1 in backlog alpha" in error["message"] and not output.out


@pytest.mark.parametrize("ambiguous", [False, True])
@pytest.mark.parametrize("structured", [False, True])
def test_show_requires_a_selection_when_backlogs_are_empty_or_ambiguous(
    factory: sqlite3.Connection, tmp_path: Path, capsys: pytest.CaptureFixture[str], ambiguous: bool, structured: bool,
) -> None:
    if ambiguous:
        attempt(factory, "z", "zeta")
        release(factory, "z")  # Ended attempts still make the selection ambiguous.
        attempt(factory, "a", "alpha", "tl-other")  # TASK's uniqueness is irrelevant.
    assert main(["step", "show", "tl-1", "--db", str(tmp_path / "factory.db"),
                 *(["--json"] if structured else [])]) == 1
    output = capsys.readouterr()
    if structured:
        error = json.loads(output.err)["error"]
        assert (error["kind"], error["reason"]) == ("refused", "backlog")
        detail = error["message"]
    else:
        assert "tl step show: refused:backlog" in output.err
        detail = output.err
    assert "--backlog KEY" in detail and "machine-config backlog" in detail
    assert ("alpha, zeta" if ambiguous else "No backlogs") in detail and not output.out


def hold(con: sqlite3.Connection, key: str, reason: str, *, completed: bool = False) -> None:
    store = HoldStore(lambda: con)
    row = store.insert(HoldInsert(key, key, reason, 10))
    if completed:
        row = store.labelled(key, row.rev, "moved", 11)
        leased = store.commenting(key, row.rev, 12)
        assert leased is not None
        store.commented(key, leased.rev, 13)
        release(con, key)


@pytest.mark.parametrize("stuck", [False, True])
def test_list_shows_recorded_and_due_hold_causes_without_changing_stuck_membership(
    factory: sqlite3.Connection, tmp_path: Path, capsys: pytest.CaptureFixture[str], stuck: bool,
) -> None:
    for number in range(1, 6):
        attempt(factory, f"a{number}", "tasks", f"tl-{number}", label="auto" if number < 5 else None,
                deadline=100 if number < 5 else 1e12)
    hold(factory, "a1", "failed:needs_owner")
    hold(factory, "a2", "failed:main_moved", completed=True)
    hold(factory, "a4", "failed:test:failed")
    db = tmp_path / "factory.db"
    before = db.read_bytes()
    flags = ["--stuck"] if stuck else []
    assert main(["step", "list", "--db", str(db), *flags]) == 0
    output = capsys.readouterr()
    lines = output.out.splitlines()
    header = lines[0].split("\t")
    assert header == ["task", "backlog", "step", "attempt", "slot", "phase", "entry", "result", "status", "next", "hold cause",
                      "last command"]
    rows = {row["task"]: row for line in lines[1:] if line.startswith("tl-")
            for row in [dict(zip(header, line.split("\t"), strict=True))]}
    expected = {"tl-1": ("hold", "failed:needs_owner"), "tl-2": ("on_hold", "failed:main_moved"),
                "tl-3": ("hold", "stuck:expired_admitted"), "tl-4": ("hold", "failed:test:failed"), "tl-5": ("start", "-")}
    if stuck:
        expected = {key: value for key, value in expected.items() if key in ("tl-1", "tl-3", "tl-4")}
    assert {task: (row["next"], row["hold cause"]) for task, row in rows.items()} == expected
    assert rows["tl-1"]["result"] == "pending admitted"  # The stored cause survives a different current result.
    assert all(row["last command"] == "-" for row in rows.values()) and not output.err
    assert main(["step", "list", "--db", str(db), *flags, "--json"]) == 0
    listed = {row["task"]: row for row in json.loads(capsys.readouterr().out)["attempts"]}
    assert set(listed) == set(expected)
    assert listed["tl-1"]["hold"]["reason"] == "failed:needs_owner"
    assert listed["tl-3"]["hold_due"] == "stuck:expired_admitted" and listed["tl-3"]["hold"] is None
    assert listed["tl-4"]["hold"]["reason"] == "failed:test:failed"
    assert all("hold cause" not in row for row in listed.values())
    assert db.read_bytes() == before and not (tmp_path / "home").exists()


def test_show_without_a_backlog_still_refuses_a_missing_database_without_creating_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    missing = tmp_path / "missing.db"
    assert main(["step", "show", "tl-1", "--db", str(missing), "--json"]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert (error["kind"], error["reason"]) == ("refused", "database")
    assert not missing.exists() and not (tmp_path / "home").exists()
