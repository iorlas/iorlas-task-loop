"""A history row that cannot be written is counted and said, never silently dropped (tl-sqd3.24, Z20)."""

import io
import json
import time
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

import hermetic  # noqa: F401

from delegate.app import doctor, env
from delegate.contracts import history as hist
from delegate.contracts import stores
from tltestkit.tmpdir import TemporaryDirectory


def row(run_id: str) -> hist.CanaryRow:
    return hist.CanaryRow(ts=time.time(), run_id=run_id, account="L", model="m")


def test_a_lock_timeout_loses_the_row_loudly_and_the_loss_is_counted():
    with TemporaryDirectory() as d, mock.patch.object(env, "config_dir", return_value=Path(d)):
        err = io.StringIO()
        with mock.patch.object(stores, "locked", side_effect=TimeoutError("history.jsonl is locked")), redirect_stderr(err):
            env.history_add(row("lost-1"))
        assert "history row lost" in err.getvalue() and "run lost-1" in err.getvalue()
        assert [json.loads(x)["run_id"] for x in env.history_lost_path().read_text().splitlines()] == ["lost-1"]
        assert not env.history_path().exists()


def test_doctor_shows_the_count_of_lost_rows():
    with TemporaryDirectory() as d, mock.patch.object(env, "config_dir", return_value=Path(d)):
        with mock.patch.object(stores, "locked", side_effect=TimeoutError("x")), redirect_stderr(io.StringIO()):
            env.history_add(row("a"))
            env.history_add(row("b"))
        found = [n for n in doctor.history_loss_notes() if n["id"] == "history_lost"]
        assert len(found) == 1 and "2 history rows" in found[0]["say"]


def test_a_row_that_is_written_leaves_no_loss_record():
    with TemporaryDirectory() as d, mock.patch.object(env, "config_dir", return_value=Path(d)):
        env.history_add(row("fine"))
        assert not env.history_lost_path().exists()
        assert [n for n in doctor.history_loss_notes() if n["id"] == "history_lost"] == []


def test_doctor_shows_the_count_of_lock_answers():
    with TemporaryDirectory() as d, mock.patch.object(env, "config_dir", return_value=Path(d)):
        for outcome in ("lock", "lock", "busy"):
            env.history_add(hist.RefusalRow(ts=time.time(), outcome=outcome, role="worker"))
        env.history_add(row("fine"))
        assert doctor.lock_answer_notes() == [
            {
                "id": "lock_answers",
                "say": "2 calls were answered `lock` (the state lock stayed held 10 s) "
                "in the last 14 days; with several accounts running, find the holder",
            }
        ]


def test_doctor_has_no_lock_answer_note_when_none():
    with TemporaryDirectory() as d, mock.patch.object(env, "config_dir", return_value=Path(d)):
        assert doctor.lock_answer_notes() == []
        env.history_add(hist.RefusalRow(ts=time.time(), outcome="busy", role="worker"))
        env.history_add(row("fine"))
        assert doctor.lock_answer_notes() == []
