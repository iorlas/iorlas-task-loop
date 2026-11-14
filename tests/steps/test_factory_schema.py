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
DDL_DIGESTS = {26: "728ea63362ce086f01b39e967b837e6875854238f49c3b073fddcdcba1666787"}


def assert_pinned_ddl(schema: Schema) -> None:
    assert hashlib.sha256(schema.ddl.encode("utf-8")).hexdigest() == DDL_DIGESTS[schema.version], "DDL requires a schema version bump"


def test_effective_ddl_matches_its_version_pin() -> None:
    assert_pinned_ddl(SCHEMA)


def test_ddl_change_without_a_version_bump_fails_the_guard() -> None:
    changed = replace(SCHEMA, ddl=SCHEMA.ddl.replace("CREATE TABLE merge_operation", "CREATE TABLE changed_merge_operation"))
    with pytest.raises(AssertionError, match="DDL requires a schema version bump"):
        assert_pinned_ddl(changed)


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
