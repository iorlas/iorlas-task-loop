"""The live cursor is (run, attempt, offset): a cursor of an earlier attempt of the same run is answered with a reset."""

import time
from pathlib import Path

import pytest
from support.dashlive import make_run
from support.factory_index import ingest
from support.narrow import must

from taskloop_dash.api import live
from tlkernel import factorydb
from tlkernel.paths import ConfigDir


def set_attempt(cfg: ConfigDir, run: str, n: int) -> None:
    con = must(factorydb.open_rw(cfg.factory_db()))
    con.execute("INSERT OR IGNORE INTO attempt (run,n,started) VALUES (?,?,?)", (run, n, time.time()))
    con.commit()
    con.close()


@pytest.mark.parametrize(("then", "reset"), [(1, False), (2, True)])
def test_a_cursor_resets_only_when_the_attempt_moved(tmp_path: Path, then: int, reset: bool) -> None:
    b, _ = make_run(str(tmp_path))
    cfg = ConfigDir(tmp_path / "task-loop")
    run = live.LiveRun(cfg, b.run)
    ingest(cfg, time.time())
    set_attempt(cfg, b.run, 1)
    run.refresh()
    cursor = must(live.decode(live.page(run)["cursor"]))
    assert cursor["_attempt"] == 1
    if then == 2:
        set_attempt(cfg, b.run, 2)
        run.refresh()
    got = live.page(run, cursor)
    assert got["reset"] is reset
    assert bool(got["events"]) is reset
    assert must(live.decode(got["cursor"]))["_attempt"] == then


def test_a_cursor_from_before_attempts_continues(tmp_path: Path) -> None:
    b, _ = make_run(str(tmp_path))
    cfg = ConfigDir(tmp_path / "task-loop")
    run = live.LiveRun(cfg, b.run)
    ingest(cfg, time.time())
    set_attempt(cfg, b.run, 1)
    run.refresh()
    cursor = must(live.decode(live.page(run)["cursor"]))
    del cursor["_attempt"]
    assert live.page(run, cursor)["reset"] is False
