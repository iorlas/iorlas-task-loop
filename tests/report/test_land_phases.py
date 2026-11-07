"""The scorecard's land section: how many tries retried and why, and the median seconds of the phases of a try."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.report.card import typed_log
from taskloop.app.report.landphases import land_stats, tries_of
from tlkernel import log as rec


def test_causes_and_median_phase_seconds_of_the_tries() -> None:
    tries = [rec.LandTry(n=1, failing="gate", fetch_s=1.0, rebase_s=2.0, gate_s=100.0),
             rec.LandTry(n=2, failing="stale", fetch_s=3.0, rebase_s=4.0, gate_s=10.0),
             rec.LandTry(n=3, failing="", fetch_s=5.0, rebase_s=6.0, gate_s=20.0)]
    assert land_stats(tries) == {"tries": 3, "retried": 2, "causes": {"gate": 1, "stale": 1},
                                 "median_s": {"fetch": 3.0, "rebase": 4.0, "gate": 20.0}, "biggest": "gate"}


def test_no_tries_say_nothing() -> None:
    assert land_stats([]) == {"tries": 0, "retried": 0, "causes": {}, "median_s": {}, "biggest": ""}


def test_the_tries_are_read_from_a_runs_engine_log(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    row = {"v": 3, "kind": "land_try", "t": 1.0, "run_id": "R", "n": 1, "failing": "gate", "fetch_s": 1.5, "rebase_s": 0.5, "gate_s": 9.0}
    path.write_text(json.dumps(row) + "\ntorn{\n", encoding="utf-8")
    assert land_stats(tries_of(typed_log(path)))["causes"] == {"gate": 1}
