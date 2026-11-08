"""The engine's land where the subject is a real child process: a SIGTERM lands in Popen, during the gate, during the land command or
the push retry, and the whole process tree must die (or the push finish). Moved from test_engine_land_1: a fake spawn cannot show a
child that outlives its parent."""
import os
import shlex
import signal
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from support import gitq
from support.engine_case import real_git, real_proc
from support.engine_land import EngineLandMixin, EngineTest

from tltestkit.plans import CLEAN, PLAN, WRITE
from tltestkit.waits import until

# isort: split
from taskloop.app.run import engine
from tlkernel.kinds import Kind


class EngineLandSignals(EngineLandMixin, EngineTest):
    @real_proc("a SIGTERM landing in Popen still stops the new child's whole tree")
    def test_sigterm_landing_inside_popen_still_stops_the_new_child(self):
        # tl-10s: the stop arrived before Popen() returned (a loaded machine runs the check ahead of the engine). TermHold notes the
        # SIGTERM during Popen and replays it after; the stop then kills the group at once, so the signal waits until the child has
        # written its pidfile (a condition, not a sleep): else the group dies before `echo $!` and child_of never sees a pid
        class SignalledPopen(subprocess.Popen):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                assert until(lambda: pidfile.exists() and pidfile.read_text().strip(), 30), "the check never wrote its pid"
                os.kill(os.getpid(), signal.SIGTERM)

        pidfile = Path(self.tmp.name, "child.pid")
        eng = self.checks_engine()
        with self.stoppable(), mock.patch.object(subprocess, "Popen", SignalledPopen), pytest.raises(engine.Blocked) as cm:
            eng.sh(shlex.split(self.spawn(pidfile)))
        assert cm.value.kind == Kind.PAUSE_KILLED
        self.assertDead(self.child_of(pidfile))

    @real_proc("a SIGTERM during the gate must leave no child alive: a real sleeping child is killed")
    def test_sigterm_during_the_land_gate_stops_it_and_pushes_nothing(self):
        pidfile = Path(self.tmp.name, "child.pid")
        with self.stoppable():
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
                                    gate=self.spawn(pidfile, term=True))
        assert rc == 2
        assert "stopped (SIGTERM)" in self.said()
        self.assertDead(self.child_of(pidfile))
        assert self.closed == []
        assert gitq.git("show", "origin/main:f.txt", cwd=str(self.wt)) == ""
        assert gitq.git("status", "--porcelain", cwd=str(self.wt)) == ""

    @real_proc("the land command is a real child that signals its parent, the engine, mid-command")
    @real_git("the land command is a child process that runs git push itself: only a real git answers it")
    def test_a_stop_during_the_push_waits_for_it_and_the_bead_lands(self):
        # a stop between the push and cmd_land left a landed bead failed, and the loop reopened it
        with self.stoppable():
            rc, _ = self.run_engine(
                {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
                land=self.script("land-push.sh", "kill -TERM $PPID\nsleep 0.3\ngit push -q origin HEAD:main\n"),
            )
        assert rc == 0
        assert self.eng.result().outcome == "landed"
        assert gitq.git("show", "origin/main:f.txt", cwd=str(self.wt)) == "d2"
        assert self.closed and self.closed[0].startswith("merged ")
        assert self.blocked == []

    @real_proc("the land command is a real child that signals its parent, the engine, mid-command")
    def test_a_stop_during_a_rejected_push_stops_after_it(self):
        with self.stoppable():
            reject = self.script("land-reject.sh", "kill -TERM $PPID\nsleep 0.3\necho '! [rejected] (fetch first)' >&2\nexit 1\n")
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, land=reject)
        assert rc == 2
        assert "stopped (SIGTERM)" in self.said()

    @real_proc("a SIGTERM during the gate must leave no child alive: a real sleeping child is killed")
    def test_push_race_sigterm_during_retry_check_stops_child_and_keeps_barrier(self):
        with self.stoppable():
            rc, events, race = self.run_push_race(failure="checks_stop", check_wall_min=0.03)
        assert rc == 2, self.blocked
        assert "stopped (SIGTERM)" in self.said()
        self.assertDead(self.child_of(race["pidfile"]))
        assert not race["next_check"].exists(), "another check ran after SIGTERM"
        assert events.count("enter") == 1
        assert events.count("exit") == 1
        assert events[-1] == "exit"
        assert race["pushes"] == 1
        assert not self.closed
        assert not self.eng.landed_sha
        assert self.lands == []

        env = {"XDG_CONFIG_HOME": race["config_home"], "APPDATA": race["config_home"]}
        with mock.patch.dict(os.environ, env):
            ck = self.checkpoint()
            assert ck["closed"]
            assert ck["step"] == "land-verify-red"
            assert "retry checks" in ck["pending_land_validation"]
            assert ck["feedback"] == ck["pending_land_validation"]
