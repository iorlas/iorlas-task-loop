"""Effective factory DDL is versioned and incomplete state is never adopted."""

import hashlib
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from sqlite_store import Schema, SchemaError, Store

from taskloop.factory_schema import SCHEMA
from taskloop.factory_store import open_ro

# Append a reviewed pin for each new version; never replace a version's existing digest.
DDL_DIGESTS = {
    26: "728ea63362ce086f01b39e967b837e6875854238f49c3b073fddcdcba1666787",
    27: "62ce0c0793427a8305ef420edd956d5adae7c832969b353265ad51d55a2ed2c0",
    28: "21c4a4af7e596acc352e922680cec640ad249c52e44656fe27d2bef93d1728ac",
}


def assert_pinned_ddl(schema: Schema) -> None:
    assert hashlib.sha256(schema.ddl.encode("utf-8")).hexdigest() == DDL_DIGESTS[schema.version], "DDL requires a schema version bump"


def test_effective_ddl_matches_its_version_pin() -> None:
    assert_pinned_ddl(SCHEMA)


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


@pytest.mark.parametrize("missing", [None, "merge_operation", "drain_action"])
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
