"""Attempt rows share the manifest's atomic ownership and terminal writes."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import pytest

from tlkernel import attemptrows, factorydb
from tlkernel.enums import Outcome, Result
from tlkernel.finish import finish_run
from tlkernel.locator import RunLocator, host_name
from tlkernel.paths import ConfigDir
from tlkernel.run import RunFinish, RunState
from tltestkit.case import Case
from tltestkit.narrow import must
from tltestkit.tmpdir import TemporaryDirectory


class AttemptRows(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = ConfigDir(Path(tmp.name))
        self.where = RunLocator(self.cfg)

    def attempts(self, run):
        with self.where.rows.transaction() as con:
            return con.execute("SELECT n,host,pid,start_id,started,beat,ended,end_kind,reason,fault_class,fingerprint "
                               "FROM attempt WHERE run=? ORDER BY n", (run,)).fetchall()

    def test_take_up_twice_and_create_keep_counter_parity_and_process_identity(self):
        first = self.where.take_up("r", "/repo", "b", 10)
        again = self.where.take_up("r", "/repo", "b", 20)
        rows = self.attempts("r")
        assert (first.manifest.attempts, again.manifest.attempts) == (1, 2)
        assert [r[0] for r in rows] == [1, 2]
        assert rows[-1][0] == must(self.where.get("r")).manifest.attempts
        assert rows[1][1:3] == (host_name(), os.getpid())
        assert rows[1][3]
        assert rows[0][3] == rows[1][3]
        assert rows[1][4:8] == (20, 20, None, None)
        assert rows[0][6:8] == (20, "yielded")
        assert all(r[9:] == (None, None) for r in rows)
        created = self.where.create("/repo", "b", 30)
        assert self.attempts(created.run)[0][:6] == (1, host_name(), os.getpid(), rows[1][3], 30, 30)

    def test_beat_updates_only_current_open_attempt_and_terminal_ticks_do_nothing(self):
        self.where.take_up("r", "/repo", "b", 10)
        self.where.take_up("r", "/repo", "b", 20)
        self.where.beat("r", 25)
        assert [r[5] for r in self.attempts("r")] == [10, 25]
        assert must(self.where.get("r")).manifest.heartbeat == 25
        self.where.end("r", 30, RunState.DONE)
        before = self.attempts("r")
        self.where.beat("r", 40)
        assert self.attempts("r") == before

    def test_mark_lost_end_and_finish_close_once_with_the_winning_reason(self):
        for verb, expected in (("lost", "lost"), ("end", "finished"), ("finish", "yielded")):
            with self.subTest(verb=verb):
                run = self.where.create("/repo", "b", 10).run
                self.where.beat(run, 15)
                if verb == "lost":
                    self.where.mark_lost(run, "gone")
                elif verb == "end":
                    self.where.end(run, 20, RunState.DONE, "done")
                else:
                    finish_run(self.cfg, run, RunFinish(state=RunState.STOPPED, ended=20, outcome=Outcome.FAILED,
                                                       result=Result.PAUSED, kind="pause_network", why="offline"))
                manifest = must(self.where.get(run)).manifest
                assert self.attempts(run)[0][6:9] == (manifest.ended, expected, manifest.reason)
                before = self.attempts(run)
                self.where.end(run, 40, RunState.FAILED, "later")
                assert self.attempts(run) == before

    def test_asked_and_killed_outcomes(self):
        for state, expected in ((RunState.PARKED, "asked"), (RunState.STOPPED, "killed")):
            run = self.where.create("/repo", "b", 10).run
            self.where.end(run, 20, state, "reason")
            assert self.attempts(run)[0][6:9] == (20, expected, "reason")

    def test_two_threads_serialize_counter_and_rows(self):
        self.where.take_up("r", "/repo", "b", 10)
        barrier = Barrier(2, timeout=30)

        def take(_):
            where = RunLocator(self.cfg)
            barrier.wait()
            where.take_up("r", "/repo", "b", 20)

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(take, range(2)))
        assert [r[0] for r in self.attempts("r")] == [1, 2, 3]
        assert must(self.where.get("r")).manifest.attempts == 3
        assert sum(r[6] is None for r in self.attempts("r")) == 1

    def test_failed_attempt_insert_rolls_back_counter_and_previous_attempt_close(self):
        self.where.take_up("r", "/repo", "b", 10)
        before = self.where.rows.snapshot("r"), self.attempts("r")
        with patch.object(attemptrows, "ensure", side_effect=ValueError("abort")), pytest.raises(ValueError):
            self.where.take_up("r", "/repo", "b", 20)
        assert (self.where.rows.snapshot("r"), self.attempts("r")) == before

    def test_attempt_close_failure_rolls_back_terminal_manifest_write(self):
        self.where.take_up("r", "/repo", "b", 10)
        before = self.where.rows.snapshot("r"), self.attempts("r")
        with patch.object(attemptrows, "close", side_effect=ValueError("abort")), pytest.raises(ValueError):
            self.where.end("r", 20, RunState.DONE)
        assert (self.where.rows.snapshot("r"), self.attempts("r")) == before

    def test_counter_cannot_move_backwards(self):
        self.where.take_up("r", "/repo", "b", 10)
        current = self.where.take_up("r", "/repo", "b", 20).manifest
        before = self.where.rows.snapshot("r")
        with pytest.raises(factorydb.DatabaseError):
            self.where.rows.put(current.replace(attempts=1))
        assert self.where.rows.snapshot("r") == before

    def test_resumed_terminal_close_has_its_own_live_attempt_without_replacing_the_answer(self):
        self.where.take_up("r", "/repo", "b", 10)
        self.where.end("r", 20, RunState.DONE, "winner")
        self.where.take_up("r", "/repo", "b", 30)
        self.where.beat("r", 35)
        assert self.attempts("r")[1][5:8] == (35, None, None)
        self.where.end("r", 40, RunState.FAILED, "loser")
        assert self.attempts("r")[1][6:9] == (40, "finished", "winner")
        assert must(self.where.get("r")).manifest.ended == 20
