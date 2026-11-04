"""One generated config directory proves age retention for history, files and traces."""

import json
import os
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from support.shells import quiet_shell
from support.who import who

from taskloop.app.prune import runs, verb
from taskloop.app.prune.traces import prune_traces
from taskloop.contracts import factorydb
from taskloop.contracts.config import LoopConfig
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Beads
from taskloop.contracts.run import RunManifest, RunState
from taskloop.contracts.runrows import RunRows

DAY = 86400


@pytest.fixture
def cfg(tmp_path: Path) -> ConfigDir:
    return ConfigDir(tmp_path)


@pytest.fixture
def db(cfg: ConfigDir) -> Iterator[sqlite3.Connection]:
    con = factorydb.open_rw(cfg.factory_db())
    assert con is not None
    try:
        yield con
    finally:
        factorydb.close_shared()
        con.close()


def seed(cfg: ConfigDir, db: sqlite3.Connection, now: float) -> None:
    for name, age, state in (("old", 45, RunState.DONE), ("fresh", 1, RunState.DONE),
                             ("kept", 45, RunState.DONE), ("live", 45, RunState.RUNNING)):
        at = now - age * DAY
        m = RunManifest(run=name, repo="/repo", bead=name, started=at - 1, state=state,
                        ended=None if state.live else at)
        with factorydb.begin_immediate(db):
            RunRows(cfg).write(db, m)
            db.execute("INSERT INTO step(run,key,try,attempt,status,started,ended) VALUES (?,'s',1,1,'done',?,?)",
                       (name, at - 1, at))
        cfg.run_dir(name).mkdir(parents=True)
        evidence = cfg.run_dir(name) / "evidence.txt"
        evidence.write_text(name)
        os.utime(evidence, (at, at))
        os.utime(cfg.run_dir(name), (at, at))
    rows = [
        {"ended": now - 45 * DAY, "bead": "old", "outcome": "failed"},
        {"ended": now - DAY, "outcome": "failed"},
        {"ended": now - 45 * DAY, "outcome": "landed"},
        {"ended": now - 45 * DAY, "event": "LANDED"},
        {"ended": now - 45 * DAY, "bead": "kept"},
        {"ended": now - 45 * DAY, "bead": "live"},
    ]
    cfg.traces().write_text("".join(json.dumps(r) + "\n" for r in rows) + "unparseable\n")


def no_store(repo: str) -> Beads:
    raise AssertionError(f"unexpected bead lookup: {repo}")


def invoke(cfg: ConfigDir, now: float, dry_run: bool, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    monkeypatch.setattr(runs, "open_beads", lambda repos, store: ({"kept"}, ""))
    monkeypatch.setattr(verb, "sweep", lambda *args: ([], []))
    output: list[str] = []
    verb.run(cfg, LoopConfig(keep_days=7), [], no_store, now, dry_run, quiet_shell(), output.append, who=who())
    return output


def history(db: sqlite3.Connection) -> list[tuple[str, list[tuple[object, ...]]]]:
    tables = ("run", "attempt", "step", "check_round", "ask_ledger", "effect")
    return [(t, db.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall()) for t in tables]


def test_generated_config_plan_counts_real_removal_and_idempotence(
    cfg: ConfigDir, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = time.time()
    seed(cfg, db, now)
    before = history(db)
    traces = cfg.traces().read_bytes()
    output = invoke(cfg, now, True, monkeypatch)
    assert any("factory.db history: would remove" in line and "1 run(s)" in line and "1 step(s)" in line for line in output)
    assert "prune: traces.jsonl: would remove 1 row(s)" in output
    assert history(db) == before  # the one-time legacy import may add `source` markers; history rows must not change
    assert cfg.traces().read_bytes() == traces
    assert cfg.run_dir("old").exists()
    output = invoke(cfg, now, False, monkeypatch)
    assert any("factory.db history: removed" in line and "1 run(s)" in line and "1 step(s)" in line for line in output)
    assert "prune: traces.jsonl: removed 1 row(s)" in output
    assert db.execute("SELECT run FROM run ORDER BY run").fetchall() == [("fresh",), ("kept",), ("live",)]
    assert db.execute("SELECT count(*) FROM step").fetchone() == (3,)
    assert db.execute("SELECT count(*) FROM attempt").fetchone() == (3,)
    assert cfg.traces().read_bytes() == traces.split(b"\n", 1)[1]
    assert not cfg.run_dir("old").exists()
    assert all(cfg.run_dir(name).exists() for name in ("fresh", "kept", "live"))
    output = invoke(cfg, now, False, monkeypatch)
    assert any("factory.db history: removed" in line and "0 run(s)" in line for line in output)
    assert "prune: traces.jsonl: removed 0 row(s)" in output


def test_unopenable_database_keeps_everything_and_reports_it(cfg: ConfigDir, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg.factory_db().write_bytes(b"not a database")
    cfg.traces().write_text('{"ended": 1}\n')
    cfg.run_dir("old").mkdir(parents=True)
    evidence = cfg.run_dir("old") / "evidence.txt"
    evidence.write_text("keep")
    output = invoke(cfg, time.time(), False, monkeypatch)
    assert "prune: factory.db history kept: database unavailable" in output
    assert cfg.factory_db().read_bytes() == b"not a database"
    assert cfg.traces().read_text() == '{"ended": 1}\n'
    assert evidence.read_text() == "keep"


def test_missing_database_is_never_created(cfg: ConfigDir, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg.run_dir("legacy").mkdir(parents=True)
    cfg.traces().write_text('{"ended": 1}\n')
    output = invoke(cfg, time.time(), True, monkeypatch)
    assert "prune: traces.jsonl: would remove 1 row(s)" in output
    assert not cfg.factory_db().exists()
    output = invoke(cfg, time.time(), False, monkeypatch)
    assert "prune: traces.jsonl: removed 1 row(s)" in output
    assert not cfg.factory_db().exists()


@pytest.mark.parametrize("line", ["garbage\n", "[]\n", '{"ended": "old"}\n', '{"ended": null}\n',
                                  '{"ended": true}\n', '{"ended": NaN}\n', '{"ended": 1, "bead": []}\n'])
def test_malformed_trace_lines_survive(cfg: ConfigDir, line: str) -> None:
    cfg.traces().write_text('{"ended": 1}\n' + line)
    assert prune_traces(cfg, 30, 100 * DAY, False) == 1
    assert cfg.traces().read_text() == line


def test_trace_cutoff_uses_ended_and_keeps_the_boundary(cfg: ConfigDir) -> None:
    old = json.dumps({"started": 99 * DAY, "ended": 70 * DAY - 1}) + "\n"
    boundary = json.dumps({"started": 1, "ended": 70 * DAY}) + "\n"
    cfg.traces().write_text(old + boundary)
    assert prune_traces(cfg, 30, 100 * DAY, True) == 1
    assert cfg.traces().read_text() == old + boundary
    assert prune_traces(cfg, 30, 100 * DAY, False) == 1
    assert cfg.traces().read_text() == boundary
