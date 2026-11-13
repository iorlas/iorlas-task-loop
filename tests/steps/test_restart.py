"""A fresh runtime reopens intact state and reconciles unfinished work without starting over."""

from dataclasses import replace
from pathlib import Path

import pytest
from doubles import Done
from round_bench import NoRequired
from sqlite_store import Store
from test_launch import NEW, FakeStart, Observe, launcher
from test_round import ENTRY, REQUEST, Bench, seed

from taskloop.attempt_types import AttemptKey, Seen
from taskloop.cli_composition import open_reads
from taskloop.factory_schema import SCHEMA
from taskloop.git_views import GitViews
from taskloop.operations import Failed, Round
from taskloop.round import run_round

PROGRESS = ("attempt", "execution", "verification", "slot_release", "published_branch")


@pytest.mark.parametrize("phase, seen, action, word, launches", [
    ("dispatching", "matching", "report", "running", 0),
    ("admitted", "gone", "relaunch", "relaunched", 1),
    ("dispatching", "unknown", "report", "unknown", 0),
])
def test_compatible_restart_keeps_progress_sessions_and_reservation_and_reconciles_the_same_attempt(
    done: Done, tmp_path: Path, phase: str, seen: Seen, action: str, word: str, launches: int,
) -> None:
    original = Store(SCHEMA)
    con = original.shared_rw(done.path)
    assert con is not None
    con.execute("UPDATE attempt SET session_ref='completed-session' WHERE attempt_id='implement'")
    seed(con, "tl-2", "unfinished", phase=phase, entry=ENTRY)
    con.execute("UPDATE attempt SET repo_id=(SELECT repo_id FROM slot WHERE name='s1'),session_ref='unfinished-session' "
                "WHERE attempt_id='unfinished'")
    con.execute("INSERT INTO reservation SELECT 's1',repo_id,1,'unfinished' FROM slot WHERE name='s1'")
    progress = {table: con.execute(f"SELECT * FROM {table} WHERE attempt_id='implement'").fetchall() for table in PROGRESS}
    reservation = con.execute("SELECT * FROM reservation").fetchall()
    original.close_shared()  # no fixture or runtime connection survives the restart

    with open_reads(done.path, tmp_path, GitViews(30)) as reads:
        assert not isinstance(reads, Failed)
        assert reads.store.attempt_of("tasks", "tl-2") == (AttemptKey("unfinished", "token-unfinished", 1), phase, ENTRY)

    fresh = Store(SCHEMA)
    reopened = fresh.open_rw(done.path)
    assert reopened is not None
    try:
        bench = Bench(reopened, free=False)
        bench.seen = seen
        started = FakeStart()
        ports = bench.ports()
        starting = replace(ports.starting, launcher=launcher(done.path, started, Observe(seen)),
                           checks=replace(ports.starting.checks, admission=NoRequired()))
        ports = replace(ports, starting=starting)
        result = run_round(ports, REQUEST)
        assert isinstance(result, Round)
        assert [(move.action, move.word, move.attempt_id) for move in result.moves if move.task_id == "tl-2"] == [
            (action, word, "unfinished")]
        assert len(started.calls) == launches
        assert bench.admission.requests == bench.repeats.calls == bench.recorded.calls == []
        assert reopened.execute("SELECT * FROM reservation").fetchall() == reservation
        assert reopened.execute("SELECT count(*) FROM attempt").fetchone() == (2,)
        assert reopened.execute("SELECT session_ref FROM attempt WHERE attempt_id='unfinished'").fetchone() == ("unfinished-session",)
        expected_entry = (NEW.pid, NEW.start, NEW.boot) if launches else ENTRY
        assert bench.store.attempt_of("tasks", "tl-2") == (AttemptKey("unfinished", "token-unfinished", 1), phase, expected_entry)
        for table, rows in progress.items():
            assert reopened.execute(f"SELECT * FROM {table} WHERE attempt_id='implement'").fetchall() == rows
    finally:
        reopened.close()
