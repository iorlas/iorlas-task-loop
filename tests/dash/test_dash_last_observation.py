"""A factory.db of a foreign schema version shows its error over the last valid observation, not as absence; a corrupt one drops it."""

import sqlite3
from pathlib import Path

import pytest
from support.dashlogs import RunScript, T

from taskloop_dash.index import Indexer
from taskloop_dash.readers import dbruns
from tlkernel import factorydb
from tlkernel.paths import ConfigDir

NOW = T + 3600


def test_a_failing_read_returns_the_last_valid_rows_with_its_error(tmp_path: Path) -> None:
    cfg = ConfigDir(tmp_path)
    RunScript("b-1", at=1).step("plan", 2, 3).close("done").write(cfg.root)
    with Indexer(cfg, clock=lambda: NOW) as index:
        while not index.pass_once(budget=0.2):
            pass
    kept: dict[tuple[str | None, str | None], list[dbruns.StoredRun]] = {}
    rows, error = dbruns.read_kept(kept, cfg, NOW)
    assert error == "" and len(rows) == 1
    con = sqlite3.connect(cfg.factory_db())
    con.execute("PRAGMA user_version=99")  # a producer on a schema this dashboard does not know
    con.close()
    again, error = dbruns.read_kept(kept, cfg, NOW)
    assert "is schema v99" in error
    assert again == rows  # the last valid observation, with the error beside it
    fresh, error = dbruns.read_kept({}, cfg, NOW)
    assert fresh == [] and error  # nothing was ever observed: absence, with the error


def test_a_corrupt_database_still_drops_the_rows(tmp_path: Path) -> None:
    cfg = ConfigDir(tmp_path)
    RunScript("b-1", at=1).step("plan", 2, 3).close("done").write(cfg.root)
    with Indexer(cfg, clock=lambda: NOW) as index:
        while not index.pass_once(budget=0.2):
            pass
    kept: dbruns.Kept = {}
    assert dbruns.read_kept(kept, cfg, NOW)[0]
    factorydb.close_shared()
    cfg.factory_db().write_bytes(b"")
    rows, error = dbruns.read_kept(kept, cfg, NOW)
    assert rows == [] and error, error


@pytest.mark.parametrize("version", range(factorydb.SCHEMA_READ_FROM - 1, factorydb.SCHEMA_VERSION + 2))
def test_a_schema_inside_the_supported_range_reads_and_one_outside_shows_the_error(tmp_path: Path, version: int) -> None:
    cfg = ConfigDir(tmp_path)
    RunScript("b-1", at=1).step("plan", 2, 3).close("done").write(cfg.root)
    with Indexer(cfg, clock=lambda: NOW) as index:
        while not index.pass_once(budget=0.2):
            pass
    kept: dict[tuple[str | None, str | None], list[dbruns.StoredRun]] = {}
    rows, _ = dbruns.read_kept(kept, cfg, NOW)
    con = sqlite3.connect(cfg.factory_db())
    con.execute(f"PRAGMA user_version={version}")
    con.close()
    again, error = dbruns.read_kept(kept, cfg, NOW)
    assert again == rows  # inside the range the rows are read; outside, the last observation stays
    assert (error == "") is (factorydb.SCHEMA_READ_FROM <= version <= factorydb.SCHEMA_VERSION)
