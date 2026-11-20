"""Setup report text and JSON are read-only and never assess the setup duration."""

import json
from pathlib import Path

import pytest
from doubles import pin_workflow
from sqlite_store import Store

from taskloop.cli import main
from taskloop.factory_schema import SCHEMA


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


@pytest.mark.parametrize("count", [0, 3, 10])
def test_empty_partial_and_full_reports_are_read_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    count: int,
) -> None:
    db = tmp_path / "factory.db"
    con = Store(SCHEMA).open_rw(db)
    assert con is not None
    with con:
        for index in range(count):
            identity = f"owner-{index}"
            pin_workflow(con)
            con.execute(
                """INSERT INTO attempt
                (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,
                schema_version,model,effort,access_policy,deadline,number,seq,slot_head,after_commit,engine_digest,workflow_digest,workflow_sha,
                admitted_at)
                VALUES (?,?,1,'implement','beads','tasks',?,'/tracker','repo','s1','input',?,1,'m','high',
                '{"harness":"codex","sandbox":"workspace-write"}',100,1,1,?,?,
        'abababababababababababababababababababababababababababababababab',
        (SELECT digest FROM workflow_file),
        'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',1.0)""",
                (identity, f"secret-{identity}", identity, "d" * 64, "b" * 40, "b" * 40),
            )
            conclusion, end = (None, None) if index == 0 else ("failed", 20) if index == 1 else ("passed", 9 if index == 2 else 10)
            con.execute(
                """INSERT INTO setup_run
                (attempt_id,run,dispatch_token,generation,commit_sha,digest,started_at,ended_at,conclusion)
                VALUES (?,1,?,1,?,?,10,?,?)""",
                (identity, f"secret-{identity}", "b" * 40, "d" * 64, end, conclusion),
            )
    con.close()
    before = db.read_bytes()
    args = ["attempt", "setup-times", "--backlog", "tasks", "--db", str(db)]
    assert main([*args, "--json"]) == 0
    output = capsys.readouterr()
    data = json.loads(output.out)
    usable = max(0, count - 3)
    assert output.err == "" and data["sample_count"] == usable and len(data["rows"]) == count
    assert set(data) == {"backlog", "rows", "sample_count"}
    assert "secret-" not in output.out
    if count:
        rows = {row["attempt_id"]: row for row in data["rows"]}
        assert rows["owner-0"]["ended_at"] is None
        assert rows["owner-1"]["conclusion"] == "failed" and rows["owner-2"]["ended_at"] == 9
        assert all(rows[f"owner-{index}"]["duration_seconds"] is None for index in range(3))
        assert all(rows[f"owner-{index}"]["duration_seconds"] == 0 for index in range(3, count))
    assert main(args) == 0
    output = capsys.readouterr()
    assert output.err == "" and f"Usable samples: {usable} of {count} displayed" in output.out
    if count:
        assert "ended unfinished" in output.out and "failed" in output.out and "1970-01-01 00:00:09 UTC" in output.out
    assert db.read_bytes() == before and not (tmp_path / "home").exists()

    if count:
        assert main(["attempt", "show", "owner-0", "--backlog", "tasks", "--db", str(db), "--json"]) == 0
        setup = json.loads(capsys.readouterr().out)["setup"]
        assert (setup["started_at"], setup["ended_at"], setup["duration_seconds"]) == (10, None, None)
        assert db.read_bytes() == before


def test_absent_database_is_not_created(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "absent.db"
    assert main(["attempt", "setup-times", "--backlog", "tasks", "--db", str(db), "--json"]) == 1
    assert json.loads(capsys.readouterr().err)["error"]["reason"] == "database"
    assert not db.exists()
