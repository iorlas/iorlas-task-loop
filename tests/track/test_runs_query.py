"""RUNSQ: `tl runs show` and `tl runs slow` print the timed rows the engine wrote while it logged; they write nothing."""
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.track import runs
from taskloop.contracts import log, timedrows
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.stores import RunLog


def row(kind: str, t: float, **kw):
    return {"v": 3, "kind": kind, "t": t, "run_id": "R1", "bead": "tl-x", **kw}


FIXTURE = [
    row("run_start", 1.0, worktree="/w", branch="task/x"),
    row("step_start", 2.0, id="n1", step="write"),
    row("step_end", 130.0, id="n1", step="write", outcome="ok", exec_seconds=128.0),
    row("check_start", 131.0, id="c1", check="unit", group="g", cmd="just test", round=1),
    row("check_end", 191.0, id="c1", exit=0, status="pass", exec_seconds=60.0, wait_seconds=12.0),
    row("cmd_start", 191.5, id="m1", text="git fetch -q origin"),
    row("cmd_end", 197.5, id="m1", exit=0),
    row("wait_start", 192.0, id="w1", what="lane"),
    row("wait_end", 300.0, id="w1", wait_seconds=108.0),
    row("close", 301.0, outcome="landed", why="done"),
]


def say(fn, *args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = fn(*args)
    return rc, buf.getvalue()


def home(tmp_path):
    """The log as the engine writes it: each record through the run's log store, which adds the timed rows."""
    cfg = ConfigDir(tmp_path)
    cfg.engine_dir().mkdir()
    store = RunLog(cfg, "R1")
    for r in FIXTURE:
        store.append(log.decode(r))
    with cfg.engine_log("R1").open("a", encoding="utf-8") as f:
        f.write("torn{\n")
    return cfg


def test_show_prints_the_run_end_to_end(tmp_path):
    rc, out = say(runs.show, "R1", home(tmp_path))
    assert rc == 0
    assert "bead tl-x" in out
    assert "step   write" in out and "2.1m" in out
    assert "check  unit" in out and "wait 12s" in out
    assert "wait   lane" in out
    assert "total exec 3.2m  wait 2.0m  -> landed: done" in out


def test_a_command_is_timed_from_its_start_and_end_records(tmp_path):
    """The land's fetch, rebase and push are commands of the engine log: their dated spans are the gap between the two records."""
    cfg = home(tmp_path)
    rc, out = say(runs.show, "R1", cfg)
    assert rc == 0 and "cmd    git fetch -q origin" in out and "6s" in out
    rc, out = say(runs.slow, cfg, 3, "exec", 10)
    assert any(ln.split()[2] == "cmd" and "git fetch" in ln for ln in out.splitlines())


def test_show_of_an_unknown_run_exits_1(tmp_path):
    rc, out = say(runs.show, "nope", ConfigDir(tmp_path))
    assert rc == 1 and "no engine log" in out


def test_slow_ranks_by_exec_then_by_wait(tmp_path):
    cfg = home(tmp_path)
    rc, out = say(runs.slow, cfg, 2, "exec", 10)
    assert rc == 0 and [ln.split()[2] for ln in out.splitlines()] == ["step", "check"]
    rc, out = say(runs.slow, cfg, 1, "wait", 10)
    assert rc == 0 and out.split()[2] == "wait"


def test_slow_with_no_logs_says_so(tmp_path):
    rc, out = say(runs.slow, ConfigDir(tmp_path), 5, "exec", 10)
    assert rc == 0 and "no timed items" in out


def test_show_lists_the_attempts_of_the_run_from_factory_db(tmp_path):
    """A run that was taken up again (a retry inside one run id) shows each attempt: the DB rows, read-only."""
    cfg = ConfigDir(tmp_path)
    where = RunLocator(cfg)
    run = where.take_up("R2", "/repo", "tl-x", 10).manifest.run
    where.take_up("R2", "/repo", "tl-x", 20)
    cfg.engine_log(run).parent.mkdir(parents=True, exist_ok=True)
    cfg.engine_log(run).write_text(json.dumps(row("run_start", 1.0, worktree="/w", branch="b", run_id=run)) + "\n", encoding="utf-8")
    rc, out = say(runs.show, run, cfg)
    assert rc == 0
    lines = [ln for ln in out.splitlines() if ln.strip().startswith("attempt")]
    assert len(lines) == 2 and "yielded" in lines[0] and "taken up by another process" in lines[0]
    assert "open" in lines[1]


def test_the_rows_are_all_show_and_slow_read(tmp_path):
    """No row, no line: with the log gone but the rows kept, the timed lines are the same; with the rows gone, there are none."""
    cfg = home(tmp_path)
    assert [(i.kind, i.name) for i in timedrows.of_run(cfg, "R1")] == [
        ("step", "write"), ("check", "unit"), ("cmd", "git fetch -q origin"), ("wait", "lane")]
    cfg.engine_log("R1").write_text("", encoding="utf-8")
    rc, out = say(runs.show, "R1", cfg)
    assert rc == 0 and "step   write" in out and "2.1m" in out


def test_a_process_that_takes_the_log_up_again_pairs_the_starts_of_the_earlier_one(tmp_path):
    cfg = ConfigDir(tmp_path)
    cfg.engine_dir().mkdir()
    RunLog(cfg, "R1").append(log.decode(FIXTURE[1]))  # a step starts in the first process...
    RunLog(cfg, "R1").append(log.decode(FIXTURE[2]))  # ...and ends in the next
    assert [(i.kind, i.name, i.exec_s) for i in timedrows.of_run(cfg, "R1")] == [("step", "write", 128.0)]
