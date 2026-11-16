"""Effective factory DDL is versioned and incomplete state is never adopted."""

import hashlib
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from sqlite_store import Schema, SchemaError, Store

from taskloop.factory_schema import SCHEMA
from taskloop.factory_store import current, open_ro, refusal

# Schema 32's pin includes the authorized factory-commit storage rename (tl-8bh9.14.159.2.3.1).
# Append a reviewed pin and bump the version for subsequent DDL changes.
DDL_DIGESTS = {
    26: "728ea63362ce086f01b39e967b837e6875854238f49c3b073fddcdcba1666787",
    27: "62ce0c0793427a8305ef420edd956d5adae7c832969b353265ad51d55a2ed2c0",
    28: "21c4a4af7e596acc352e922680cec640ad249c52e44656fe27d2bef93d1728ac",
    29: "0e6ec8a2ed329c07b67e95721833da0d974b9dc825f5e6702a36890743413a82",
    30: "020fa74580ac5d32910fb6b09b29bd00b2992d5dc3511d3808e4174d56ffd595",
    31: "2ca9b05fb3210127f561e74133cfcac7443d486c2e833eb4c2b427529ae1fe6d",
    32: "234a15273fc75a3cef589704dbf9a1c104154fb6fc57f15b1b7d9a86e7f8dfda",
}


def assert_pinned_ddl(schema: Schema) -> None:
    assert hashlib.sha256(schema.ddl.encode("utf-8")).hexdigest() == DDL_DIGESTS[schema.version], "DDL requires a schema version bump"


def test_effective_ddl_matches_its_version_pin() -> None:
    assert_pinned_ddl(SCHEMA)


@pytest.mark.parametrize(("kind", "reason", "reused", "valid"), [
    ("committed", None, 0, True), ("committed", None, 1, True), ("rejected", "paths", 0, True),
    ("invalid", None, 0, False), ("committed", "paths", 0, False), ("rejected", None, 0, False),
    ("rejected", "paths", 1, False), ("committed", None, 2, False),
])
def test_factory_commit_verdict_constraints_at_schema_32(
    registered: sqlite3.Connection, kind: str, reason: str | None, reused: int, valid: bool,
) -> None:
    assert SCHEMA.version == 32
    registered.execute(
        """INSERT INTO execution (attempt_id,dispatch_token,generation,timed_out,work,stands,stdout_path,stdout_digest,
        stderr_path,stderr_digest,answer_path,answer_digest,diagnostic_path,diagnostic_digest,session_state)
        SELECT attempt_id,dispatch_token,generation,0,1,1,'o','d','e','d','a','d','g','d','complete' FROM attempt""",
    )
    statement = """INSERT INTO factory_commit (attempt_id,dispatch_token,generation,verdict,reason,reused,observed_at)
    SELECT attempt_id,dispatch_token,generation,?,?,?,10 FROM execution"""
    if valid:
        registered.execute(statement, (kind, reason, reused))
        assert registered.execute("SELECT verdict,reason,reused FROM factory_commit").fetchall() == [(kind, reason, reused)]
    else:
        with pytest.raises(sqlite3.IntegrityError):
            registered.execute(statement, (kind, reason, reused))


def test_factory_commit_foreign_keys(registered: sqlite3.Connection) -> None:
    for table, parent in (("factory_commit", "execution"), ("published_branch", "factory_commit")):
        keys = registered.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        assert [(key[2], key[3], key[4]) for key in keys] == [(parent, "attempt_id", "attempt_id")]
    with pytest.raises(sqlite3.IntegrityError):
        registered.execute(
            "INSERT INTO factory_commit (attempt_id,dispatch_token,generation,verdict,observed_at) "
            "VALUES ('missing','dispatch',1,'committed',10)",
        )
    with pytest.raises(sqlite3.IntegrityError):
        registered.execute(
            "INSERT INTO published_branch VALUES ('attempt','dispatch',1,?,?,10)", ("e" * 40, "e" * 40),
        )


@pytest.mark.parametrize(("value", "valid"), [(None, True), (False, True), (True, True), (2, False), (-1, False), ("true", False)])
def test_usage_completeness_is_a_nullable_boolean(registered: sqlite3.Connection, value: object, valid: bool) -> None:
    registered.execute(
        """INSERT INTO execution (attempt_id,dispatch_token,generation,timed_out,work,stands,stdout_path,stdout_digest,
        stderr_path,stderr_digest,answer_path,answer_digest,diagnostic_path,diagnostic_digest,session_state)
        SELECT attempt_id,dispatch_token,generation,0,1,1,'o','d','e','d','a','d','g','d','complete' FROM attempt""",
    )
    if valid:
        registered.execute("UPDATE execution SET usage_incomplete=?", (value,))
        assert registered.execute("SELECT usage_incomplete FROM execution").fetchone() == (value,)
    else:
        with pytest.raises(sqlite3.IntegrityError):
            registered.execute("UPDATE execution SET usage_incomplete=?", (value,))


@pytest.mark.parametrize(("kind", "failure", "valid"), [
    ("validation_pending", None, True), ("valid", None, True),
    ("missing", None, False), ("json_invalid", None, False), ("schema_invalid", None, False),
    ("valid", '{}', False), ("validation_pending", '{}', False), ("schema_invalid", 'not json', False),
    ("schema_invalid", '{"rule":"shape","explanation":"Object required"}', True),
])
def test_answer_failure_storage_requires_detail_only_for_rejections(
    registered: sqlite3.Connection, kind: str, failure: str | None, valid: bool,
) -> None:
    registered.execute(
        """INSERT INTO execution (attempt_id,dispatch_token,generation,timed_out,work,stands,stdout_path,stdout_digest,
        stderr_path,stderr_digest,answer_path,answer_digest,diagnostic_path,diagnostic_digest,session_state)
        SELECT attempt_id,dispatch_token,generation,0,1,1,'o','d','e','d','a','d','g','d','complete' FROM attempt""",
    )
    if valid:
        registered.execute("UPDATE execution SET answer_kind=?,answer_failure=?", (kind, failure))
    else:
        with pytest.raises(sqlite3.IntegrityError):
            registered.execute("UPDATE execution SET answer_kind=?,answer_failure=?", (kind, failure))


def test_ddl_change_without_a_version_bump_fails_the_guard() -> None:
    changed = replace(SCHEMA, ddl=SCHEMA.ddl.replace("CREATE TABLE merge_operation", "CREATE TABLE changed_merge_operation"))
    with pytest.raises(AssertionError, match="DDL requires a schema version bump"):
        assert_pinned_ddl(changed)


@pytest.mark.parametrize("value,valid", [(None, True), (1, True), (100000, True), (0, False), (-1, False),
                                        (0.5, False), ("invalid", False)])
def test_attempt_compaction_storage_requires_a_positive_integer_or_null(
    registered: sqlite3.Connection, value: object, valid: bool,
) -> None:
    if valid:
        registered.execute("UPDATE attempt SET compaction_token_limit=?", (value,))
        assert registered.execute("SELECT compaction_token_limit FROM attempt").fetchone() == (value,)
    else:
        with pytest.raises(sqlite3.IntegrityError):
            registered.execute("UPDATE attempt SET compaction_token_limit=?", (value,))


@pytest.mark.parametrize("missing", [None, "merge_operation", "drain_action", "task_content"])
def test_read_only_open_requires_every_factory_table(tmp_path: Path, missing: str | None) -> None:
    path = tmp_path / "factory.db"
    writer = Store(SCHEMA).open_rw(path)
    assert writer is not None
    if missing is not None:
        writer.execute(f'DROP TABLE "{missing}"')
    writer.close()
    before = path.read_bytes()
    if missing is None:
        reader = open_ro(path)
        assert reader is not None
        assert reader.execute("SELECT * FROM merge_operation").fetchall() == []
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.execute("DELETE FROM merge_operation")
        reader.close()
    else:
        with pytest.raises(SchemaError, match=f"incompatible: missing required tables: {missing}") as refused:
            open_ro(path)
        assert len(str(refused.value).splitlines()) == 1
    assert path.read_bytes() == before


@pytest.mark.parametrize("version", [0, SCHEMA.version - 1, SCHEMA.version, SCHEMA.version + 1])
def test_current_reads_the_borrowed_connection_without_changing_it(version: int) -> None:
    con = sqlite3.connect(":memory:")
    con.execute(f"PRAGMA user_version={version}")
    assert current(con) is (version == SCHEMA.version)
    assert not con.in_transaction
    assert con.execute("PRAGMA user_version").fetchone() == (version,)
    con.close()


@pytest.mark.parametrize("contents", ["missing", "corrupt", "version"])
def test_refusal_diagnosis_is_read_only_and_closes_its_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, contents: str,
) -> None:
    path = tmp_path / "factory.db"
    if contents == "corrupt":
        path.write_bytes(b"not a SQLite database")
    elif contents == "version":
        con = sqlite3.connect(path)
        con.execute(f"PRAGMA user_version={SCHEMA.version - 1}")
        con.close()
    before = path.read_bytes() if path.exists() else None
    opened: list[sqlite3.Connection] = []
    connect = sqlite3.connect

    def diagnostic(database: str, *, uri: bool) -> sqlite3.Connection:
        assert database == f"{path.resolve().as_uri()}?mode=ro" and uri
        con = connect(database, uri=uri)
        opened.append(con)
        return con

    monkeypatch.setattr(sqlite3, "connect", diagnostic)
    detail = refusal(SchemaError("incompatible"), path)
    expected = f"records schema version {SCHEMA.version - 1}" if contents == "version" else "schema version could not be read"
    assert expected in detail and "The database has been preserved" in detail
    assert (path.read_bytes() if path.exists() else None) == before
    assert len(opened) == (0 if contents == "missing" else 1)
    for con in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            con.execute("SELECT 1")
