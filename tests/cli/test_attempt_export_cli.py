"""`tl attempt export` and `tl slot list` print read-only listings: CSV or a JSON array, never writing the database."""

import csv
import io
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


@pytest.fixture
def database(tmp_path: Path) -> Path:
    db = tmp_path / "factory.db"
    con = Store(SCHEMA).open_rw(db)
    assert con is not None
    with con:
        pin_workflow(con)
        con.execute("INSERT INTO slot (repo_id,name,path) VALUES ('repo','s1','/slots/s1')")
        con.execute("INSERT INTO slot (repo_id,name,path) VALUES ('repo','s2','/slots/s2')")
        con.execute("INSERT INTO reservation VALUES ('s1','repo',1,'attempt')")
        con.execute("""INSERT INTO attempt
            (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,
            schema_version,model,effort,access_policy,deadline,number,seq,slot_head,engine_digest,workflow_digest,workflow_sha,admitted_at)
            VALUES ('attempt','token',1,'plan','beads','tasks','tl-1','/tracker','repo','s1','input',?,1,'m','high',
            '{"harness":"codex","sandbox":"workspace-write"}',100,1,1,?,?,(SELECT digest FROM workflow_file),?,1.0)""",
                    ("d" * 64, "b" * 40, "a" * 64, "e" * 40))
    con.close()
    return db


def test_the_export_prints_csv_with_a_header_or_a_json_array_and_writes_nothing(
    database: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    before = database.read_bytes()
    assert main(["attempt", "export", "--db", str(database)]) == 0
    (row,) = csv.DictReader(io.StringIO(capsys.readouterr().out))
    assert (row["task_id"], row["step"], row["ended_at"], row["wall_seconds"]) == ("tl-1", "plan", "", "")
    assert main(["attempt", "export", "--db", str(database), "--backlog", "tasks", "--json"]) == 0
    (found,) = json.loads(capsys.readouterr().out)
    assert found["task_id"] == "tl-1" and found["wall_seconds"] is None and found["t_in"] is None
    assert main(["attempt", "export", "--db", str(database), "--backlog", "other", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert database.read_bytes() == before


def test_the_slot_list_shows_free_and_held_slots(database: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["slot", "list", "--db", str(database), "--json"]) == 0
    held, free = json.loads(capsys.readouterr().out)
    assert (held["name"], held["state"], held["attempt_id"], held["repo_id"]) == ("s1", "held", "attempt", "repo")
    assert (free["name"], free["state"], free["attempt_id"]) == ("s2", "free", None)
    assert main(["slot", "list", "--db", str(database)]) == 0
    assert "s2\tfree\t-\trepo\t/slots/s2" in capsys.readouterr().out


@pytest.mark.parametrize("command", [["attempt", "export"], ["slot", "list"]], ids=" ".join)
def test_an_absent_database_is_refused_and_not_created(tmp_path: Path, capsys: pytest.CaptureFixture[str], command: list[str]) -> None:
    db = tmp_path / "absent.db"
    assert main([*command, "--db", str(db), "--json"]) == 1
    assert json.loads(capsys.readouterr().err)["error"]["reason"] == "database"
    assert not db.exists()
