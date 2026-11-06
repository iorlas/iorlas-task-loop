"""dev/flakes.py: the flake ledger built from red suite logs, and the quarantine list it feeds (tests/quarantine.txt)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "dev"))
import flakes  # noqa: E402

LOG = """..F.
=========================== short test summary info ============================
FAILED tests/a/test_x.py::T::test_one - AssertionError: boom
FAILED tests/a/test_x.py::T::test_two
ERROR tests/b/test_y.py::test_three - setup
1 failed
"""


def run(root, rid, log, name="01-suite.r1.log"):
    checks = root / rid / "checks"
    checks.mkdir(parents=True)
    (checks / name).write_text(log, encoding="utf-8")


def test_failed_tests_are_the_failed_and_error_lines_of_the_short_summary():
    assert flakes.failed_tests(LOG) == ["tests/a/test_x.py::T::test_one", "tests/a/test_x.py::T::test_two", "tests/b/test_y.py::test_three"]


def test_the_ledger_counts_the_runs_each_test_was_red_in_and_ignores_logs_that_are_not_the_suite(tmp_path):
    run(tmp_path, "R1", LOG)
    run(tmp_path, "R2", "FAILED tests/a/test_x.py::T::test_one\n")
    run(tmp_path, "R3", "FAILED tests/z/test_z.py::t\n", name="00-diff-check.r1.log")
    rows = {r["test"]: r for r in flakes.build(tmp_path)}
    assert rows["tests/a/test_x.py::T::test_one"]["runs"] == ["R1", "R2"]
    assert rows["tests/a/test_x.py::T::test_two"]["fails"] == 1
    assert "tests/z/test_z.py::t" not in rows


def test_the_ledger_is_written_most_red_first_as_one_json_row_a_line(tmp_path):
    run(tmp_path, "R1", LOG)
    run(tmp_path, "R2", "FAILED tests/a/test_x.py::T::test_two\n")
    out = tmp_path / "flakes.jsonl"
    flakes.write(out, flakes.build(tmp_path))
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [r["test"] for r in rows][0] == "tests/a/test_x.py::T::test_two"


def test_the_quarantine_list_skips_comments_and_blank_lines(tmp_path):
    path = tmp_path / "quarantine.txt"
    path.write_text("# why\n\ntests/a/test_x.py::T::test_one\n  tests/b.py::t  \n", encoding="utf-8")
    assert flakes.quarantined(path) == ["tests/a/test_x.py::T::test_one", "tests/b.py::t"]
