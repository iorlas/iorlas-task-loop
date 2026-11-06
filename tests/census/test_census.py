"""dev/census.py: the paths a week of records say fired, the runs by mode, owners per hour, and the tests that build an Engine."""
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import support.paths

census_path = support.paths.ROOT / "dev" / "census.py"
spec = importlib.util.spec_from_file_location("census", census_path)
assert spec is not None and spec.loader is not None
census = importlib.util.module_from_spec(spec)
sys.modules["census"] = census
spec.loader.exec_module(census)

NOW = 1_800_000_000.0


def put(config: Path, run: str, *recs: dict) -> None:
    log = config / "runs" / run / "engine.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("".join(json.dumps({"t": NOW - 60, "step": "", "text": "", **r}) + "\n" for r in recs))


def test_each_path_counts_by_kind_and_step_and_an_unfired_path_is_zero(workdir):
    put(workdir, "r1",
        {"kind": "step_start", "step": "land:fetch"}, {"kind": "step_start", "step": "land:gate"},
        {"kind": "lock"}, {"kind": "step_start", "step": "land:gate"},
        {"kind": "step_start", "step": "land:claude/x"}, {"kind": "note", "text": "PR #9 merged as abc"},
        {"kind": "cmd_start", "text": "opencode run x"}, {"kind": "step_start", "step": "look:shots"})
    put(workdir, "old", {"kind": "cmd_start", "text": "opencode run y", "t": NOW - 30 * 86400})
    got = census.census(workdir, workdir / "tests", 7, NOW).paths
    assert got["land-stack"] == {"step_start land:claude/x": 1, "note": 1}
    assert got["opencode"] == {"cmd_start": 1}  # the run 30 days ago is outside the week
    assert got["look"] == {"step_start look:shots": 1}
    assert (got["gate-outside-lock"], got["gate-inside-lock"]) == ({"step_start land:gate": 1}, {"step_start land:gate": 1})
    assert (got["hop"], got["reflect"]) == ({}, {})


def test_runs_by_mode_and_landed_per_hour_by_owners_running(workdir):
    con = sqlite3.connect(workdir / "factory.db")
    con.execute("CREATE TABLE run (started REAL, owner TEXT, outcome TEXT, mode TEXT)")
    hour = int(NOW // 3600) * 3600 - 3600
    con.executemany("INSERT INTO run VALUES (?,?,?,?)", [
        (hour, "a", "landed", "stage:land"), (hour + 1, "b", "landed", "stage:land-stack"), (hour + 2, "b", "failed", "stage:check"),
        (hour - 3600, "a", "landed", "stage:land")])
    con.commit()
    con.close()
    modes, loops = census.runs_table(workdir / "factory.db", NOW - 86400)
    assert modes == {"stage:land": 2, "stage:land-stack": 1, "stage:check": 1}
    assert loops == {1: {"hours": 1, "landed_per_hour": 1.0}, 2: {"hours": 1, "landed_per_hour": 2.0}}


def test_tests_that_build_an_engine_are_counted(workdir):
    (workdir / "test_a.py").write_text("def test_x():\n    make_engine(1)\n")
    (workdir / "test_b.py").write_text("class T(StagesTest):\n    pass\n")
    (workdir / "test_c.py").write_text("def test_y():\n    pass\n")
    assert census.engine_tests(workdir) == {"test_files": 3, "build_an_engine": 2}
