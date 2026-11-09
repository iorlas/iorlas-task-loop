"""One authoritative admitted attempt, real SQLite and the owning semantic agent fake."""

import dataclasses
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from any_agent import RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from sqlite_store import begin_immediate

from taskloop.plan import PlanAttempts
from taskloop.plan_files import PlanFiles
from taskloop.plan_store import SCHEMA, PlanStore
from taskloop.plan_types import AttemptKey

KEY = AttemptKey("attempt", "dispatch", 1)
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
PLAN = {"disposition": "planned", "plan_path": "docs/design/tl-1/plan.md", "commit": "a" * 40, "explanation": "Plan committed"}


def database(tmp_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:", isolation_level=None)
    con.execute("PRAGMA foreign_keys=ON")
    with begin_immediate(con):
        for statement in SCHEMA.ddl.split(";"):
            if statement.strip():
                con.execute(statement)
        con.execute("PRAGMA user_version=1")
        con.execute("INSERT INTO reservation VALUES ('slot','repo',?,1,'attempt')", (str(tmp_path),))
        digest = hashlib.sha256(b"Plan the actual task").hexdigest()
        con.execute(
            """INSERT INTO plan_attempt
            (attempt_id,dispatch_token,generation,adapter,backlog,task_id,repo_id,slot,input_path,input_digest,
             schema_version,model,effort,sandbox,deadline,entry_pid,entry_start,entry_boot)
            VALUES ('attempt','dispatch',1,'beads','tasks','tl-1','repo','slot','input.txt',?,1,'chosen','high','workspace-write',100,7,'entry-start','boot')""",
            (digest,),
        )
    (tmp_path / "input.txt").write_text("Plan the actual task")
    return con


def fake(answer: str | None = None, *, rc: int = 0, refs: tuple[str, ...] = ()) -> FakeRun:
    return FakeRun(
        RunOutcome(rc=rc, worker=WORKER, summary=Summary(
            text=json.dumps(PLAN) if answer is None else answer, rc=rc, stands=True,
            res={"ref": refs[-1] if refs else None, "tokens": {"in": 8, "cached": None, "out": 3}},
        )), refs=refs,
    )


def app(con: sqlite3.Connection, tmp_path: Path, execution: FakeRun) -> PlanAttempts:
    return PlanAttempts(PlanStore(lambda: con), PlanFiles(tmp_path), lambda: ("/bin/codex", {"SECRET": "credential"}), execution, lambda: 10)


def test_execute_and_independent_collection_preserve_facts_and_reservation(tmp_path: Path) -> None:
    con = database(tmp_path)
    execution = fake(refs=("native-session",))
    result = app(con, tmp_path, execution).execute(KEY)
    assert result.status == "collected"
    assert result.execution is not None
    assert result.execution.answer.kind == "valid"
    assert result.execution.facts.tokens == (8, None, 3)
    assert result.execution.facts.cost_usd is None
    assert result.execution.custody == "unresolved"
    assert con.execute("SELECT session_ref FROM plan_attempt").fetchone() == ("native-session",)
    other = fake()
    reader = app(con, tmp_path, other)
    assert reader.collect(KEY) == result
    assert reader.execute(KEY) == result
    assert not other.calls
    harness, spec, timeout, hooks = execution.calls[0]
    assert harness.kind == "codex" and spec.argv[1] == "exec"
    assert "chosen" in spec.argv and "workspace-write" in spec.argv
    assert "--output-schema" in spec.argv
    assert spec.env == {"SECRET": "credential"} and timeout == 90
    assert hooks is not None and hooks.unattended is False
    assert con.execute("SELECT count(*) FROM reservation").fetchone() == (1,)
    dump = "\n".join(con.iterdump())
    assert "credential" not in dump and "Plan committed" not in dump and "Plan the actual task" not in dump


@pytest.mark.parametrize("change", ["missing", "stale", "entry", "expired", "choices", "input", "version"])
def test_invalid_admission_never_executes(tmp_path: Path, change: str) -> None:
    con = database(tmp_path)
    if change == "missing":
        con.execute("DELETE FROM plan_attempt")
    elif change == "stale":
        con.execute("UPDATE reservation SET generation=2")
    elif change == "entry":
        con.execute("UPDATE plan_attempt SET entry_boot=NULL")
    elif change == "expired":
        con.execute("UPDATE plan_attempt SET deadline=1")
    elif change == "choices":
        con.execute("UPDATE plan_attempt SET model=''")
    elif change == "input":
        (tmp_path / "input.txt").write_text("Changed")
    else:
        con.execute("PRAGMA user_version=2")
    execution = fake()
    assert app(con, tmp_path, execution).execute(KEY).status in {"refused", "unavailable"}
    assert execution.calls == []


def test_failed_execution_valid_answer_is_not_success(tmp_path: Path) -> None:
    con = database(tmp_path)
    result = app(con, tmp_path, fake(rc=7)).execute(KEY)
    assert result.execution is not None
    assert result.execution.facts.rc == 7
    assert result.execution.facts.reason == "worker_failed"
    assert result.execution.answer.kind == "valid"


@pytest.mark.parametrize("text, kind", [("", "missing"), ("not json", "json_invalid"), ('{"plan":3}', "schema_invalid")])
def test_bad_answer_has_one_execution(tmp_path: Path, text: str, kind: str) -> None:
    con = database(tmp_path)
    execution = fake(text)
    result = app(con, tmp_path, execution).execute(KEY)
    assert result.execution is not None and result.execution.answer.kind == kind
    assert len(execution.calls) == 1


def test_decoder_fault_leaves_captured_facts_and_can_resume_without_agent(tmp_path: Path) -> None:
    con = database(tmp_path)
    execution = fake()
    owner = app(con, tmp_path, execution)

    def broken(_value: object, _path: str):
        raise RuntimeError("decoder bug")

    owner.decoder = broken
    with pytest.raises(RuntimeError, match="decoder bug"):
        owner.execute(KEY)
    reader = app(con, tmp_path, fake())
    captured = reader.collect(KEY)
    assert captured.execution is not None and captured.execution.answer.kind == "validation_pending"
    assert captured.execution.facts.rc == 0
    assert reader.execute(KEY).status == "collected"
    assert not reader.execution.calls


def test_dispatch_is_consumed_and_wrong_key_cannot_publish(tmp_path: Path) -> None:
    con = database(tmp_path)
    store = PlanStore(lambda: con)
    admitted = store.load(KEY)
    assert admitted is not None
    assert store.dispatch(admitted) == "accepted"
    assert store.dispatch(admitted) == "conflict"
    execution = fake()
    assert app(con, tmp_path, execution).execute(KEY).status == "pending"
    assert execution.calls == []
    assert app(con, tmp_path, fake()).collect(dataclasses.replace(KEY, dispatch_token="other")).status == "refused"
