"""A registered entry and agent retain custody across rounds stop, restart, observations and adoption of five slots."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from git_porcelain.testing import FakeRepo, FakeWorktree
from sqlite_store import Store
from test_agent_stop import ENTRY, KEY, WORKER, running
from test_launch import FakeStart, Observe, launcher
from test_round import REQUEST, Bench
from test_slots import add, adopted, derived

from taskloop.attempt_store import AttemptStore
from taskloop.factory_schema import SCHEMA
from taskloop.launch import LaunchRefused
from taskloop.operations import Ended, Round
from taskloop.round import run_round
from taskloop.rounds import RoundsPorts, RoundsRequest, run_rounds


def scheduling(bench: Bench, con: sqlite3.Connection, repo: FakeRepo, root: Path, abrupt: bool) -> None:
    def during() -> None:
        assert len(adopted(con, repo, root, 5)) == 5

    bench.during = during  # adoption while the round observes the live entry
    now, stopped = [10.0], [False]

    def wait(seconds: float) -> None:
        now[0] += seconds
        if abrupt:
            raise KeyboardInterrupt
        stopped[0] = True

    ports = bench.ports()
    rounds = RoundsPorts(lambda quiet: run_round(ports, replace(REQUEST, quiet=quiet)), bench.store.slot_use,
                         lambda: now[0], lambda: now[0], wait, bench.lines.append, lambda: None, lambda: stopped[0], 77)
    if abrupt:
        with pytest.raises(KeyboardInterrupt):
            run_rounds(rounds, RoundsRequest("tasks", 60))
    else:
        assert isinstance(run_rounds(rounds, RoundsRequest("tasks", 60)), Ended)
    for _ in range(3):
        assert isinstance(run_round(ports, REQUEST), Round)


@pytest.mark.parametrize("abrupt", [False, True])
def test_live_entry_and_agent_survive_rounds_restart_and_adoption(
    admitted: Path, slot: FakeWorktree, repo: FakeRepo, root: Path, abrupt: bool,
) -> None:
    con = Store(SCHEMA).open_rw(admitted)
    assert con is not None
    attempts = AttemptStore(lambda: con)
    assert attempts.register_entry(KEY, ENTRY, 10) == "accepted"
    admission = running(con)
    attempts.session(admission, "surviving-session")
    slot.write_file("unfinished-work", "keep this agent's changes")
    before = con.execute("SELECT * FROM attempt").fetchall()
    reservation = con.execute("SELECT * FROM reservation").fetchall()
    add(repo, root, "s2", "s3", "s4", "s5")
    try:
        for restart in range(2):
            if restart:
                con.close()
                con = Store(SCHEMA).open_rw(admitted)
                assert con is not None
            bench = Bench(con, free=False)
            bench.seen = "matching"

            scheduling(bench, con, repo, root, abrupt)
            assert bench.admission.requests == bench.launcher.calls == bench.repeats.calls == bench.recorded.calls == []
            assert con.execute("SELECT * FROM attempt").fetchall() == before
            assert con.execute("SELECT * FROM reservation").fetchall() == reservation
            assert con.execute("SELECT count(*) FROM slot").fetchone() == (5,)
            assert con.execute("SELECT count(*) FROM agent_stop").fetchone() == (0,)
            assert slot.read_file("unfinished-work") == "keep this agent's changes"
            assert derived(repo, root, "s1") == slot.path
            start = FakeStart()
            assert launcher(admitted, start, Observe("matching")).launch("tasks", "tl-1", 30) == LaunchRefused("dispatched")
            assert start.calls == []
            record = bench.store.load(KEY)
            assert record is not None and record.admission.entry == ENTRY
            assert record.worker == WORKER and record.session_ref == "surviving-session"
    finally:
        con.close()
