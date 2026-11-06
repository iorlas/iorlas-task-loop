"""The end-of-run summary of `just test` (dev/testtimes_report.py): the slowest tests always, a warning for each over the CPU budget."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "dev"))
import testtimes_report as report  # noqa: E402


def worker_file(tmp_path, name, cpus):
    rows = {f"tests/x/test_{i}.py::t": {"call_cpu": cpu, "call_wall": cpu} for i, cpu in enumerate(cpus)}
    path = tmp_path / name
    path.write_text(json.dumps({"tests": rows, "fixtures": {}}), encoding="utf-8")
    return str(path)


def test_the_slowest_table_is_printed_even_when_nothing_is_over_budget(tmp_path):
    out = report.budget_warning([worker_file(tmp_path, "a.json", [0.2, 0.9, 0.1])])
    assert out.startswith("slowest 3 tests")
    assert "WARNING" not in out
    assert out.index("0.9 s") < out.index("0.2 s") < out.index("0.1 s")


def test_a_test_over_five_seconds_adds_a_warning_with_its_fix_class(tmp_path):
    out = report.budget_warning([worker_file(tmp_path, "a.json", [6.5, 0.1])])
    assert "WARNING: 1 tests over the 5 s CPU budget" in out
    assert "6.5 s CPU" in out and "[" in out.split("WARNING")[1]


def test_the_table_and_the_warning_hold_ten_lines_and_count_the_rest(tmp_path):
    out = report.budget_warning([worker_file(tmp_path, "a.json", [6.0 + i for i in range(14)])])
    table, warning = out.split("WARNING")
    assert len(table.strip().splitlines()) == 1 + 10
    assert len(warning.strip().splitlines()) == 1 + 10 + 1
    assert warning.strip().splitlines()[-1] == "+4 more"


def test_no_worker_file_prints_nothing(tmp_path):
    assert report.budget_warning([str(tmp_path / "missing.json")]) == ""


def test_a_real_test_that_waits_is_not_told_to_inject_the_clock():
    wait = {"call_cpu": 0.1, "call_wall": 9.0}
    assert "inject the clock" not in report.hint("tests/loop/real/test_x.py::t", wait)
    assert "real process or socket" in report.hint("tests/loop/real/test_x.py::t", wait)
    assert "inject the clock" in report.hint("tests/loop/test_x.py::t", wait)
    assert report.hint("tests/loop/real/test_x.py::t", {"call_cpu": 6.0, "call_wall": 6.0}).startswith("real: keep the contract")


def test_a_unit_test_whose_wait_is_in_setup_is_not_told_to_inject_the_clock():
    slow_setup = {"setup_cpu": 0.1, "setup_wall": 6.0, "call_cpu": 0.1, "call_wall": 0.1}
    hint = report.hint("tests/loop/test_x.py::t", slow_setup)
    assert "inject the clock" not in hint
    assert "setup" in hint
