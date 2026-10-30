"""A hand run and a loop never share a slot (tl-bxk.9.5): run-task --slot takes the slot bead, a live engine in a slot's
worktree keeps it busy whatever its bead says, a hold reserves a slot for a person, and a stopped engine's worker dies
with it."""

import io
import json
import os
import signal
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # python3 -m unittest tests.test_slots, from the repo root
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from loop.test_loop import LoopBase
from support import slots as sl
from support.engine_locks import put_lock
from support.spawn import real_spawner

from taskloop.adapters import pidcheck
from taskloop.app.launch import dash as dash_server
from taskloop.app.run import (
    entry,
)
from taskloop.app.slots import (
    engine_lock,
)
from taskloop.app.wire import slots as wslots
from taskloop.contracts.config import SlotsConfig
from taskloop.contracts.enums import Result
from taskloop.contracts.env import snapshot
from taskloop.contracts.run import RunReport

LIVE_PID = "a live pid that is not this process: a real sleep child (an engine lock, a second loop, a waiter)"

POSIX = os.name != "nt"


NO_FCNTL = unittest.skipIf(os.name == "nt", "the lock is fcntl; tl has none on Windows (documented no-op)")


def sleeper():
    return subprocess.Popen(["sleep", "60"])


class Slots(LoopBase):
    def setUp(self):
        super().setUp()
        self.kids = []
        for n in ("s1", "s2"):
            (self.repo / ".slots" / n).mkdir(parents=True)

    def tearDown(self):
        for k in self.kids:
            k.kill()
            k.wait()
        super().tearDown()

    def slot(self, n):
        return str(self.repo / ".slots" / n)

    def live_lock(self, n, bead="x-9"):
        k = sleeper()
        self.kids.append(k)
        f = engine_lock.engine_lock_path(self.slot(n))
        f.parent.mkdir(parents=True, exist_ok=True)
        put_lock(self.slot(n), {"pid": k.pid, "bead": bead, "started": time.time()})
        return k

    def cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            try:
                rc = self.main(list(args))
            except SystemExit as e:
                rc = e.code
        return rc, out.getvalue()

    def run_task(self, bead_id, slot=None, worktree=None, engine_run=None, flags=None, **env):
        """entry.main as `tl run-task` calls it, with the engine itself stubbed: engine_run(eng) is its run(). flags:
        more run-task options (wait, exclusive_area)."""
        f = Path(self.home, f"out-{bead_id}.json")
        a = entry.Args(id=bead_id, worktree=worktree, slot=slot, dry_run=False, fresh=False, quiet=True,
                        outcome_file=str(f), **(flags or {}))
        made = mock.Mock()
        made.return_value.run.side_effect = engine_run or (lambda: 0)
        made.return_value.result.return_value = RunReport(outcome=Result.LANDED, bead=bead_id)
        made.return_value.log_path = Path(self.home, "e.jsonl")
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), mock.patch.object(entry, "admit", return_value=(True, "")), \
                mock.patch.object(entry, "Engine", made), \
                mock.patch.object(signal, "signal"), redirect_stdout(out):
            rc = entry.main(a, env=snapshot(), spawner=real_spawner())
        self.made = made
        return rc, json.loads(f.read_text()), out.getvalue()


class SameActor(Slots):
    """A hand run from the session that started the loop shares the loop's actor: bd lets it re-claim the slot bead."""


    def test_the_loops_child_takes_over_its_lock_and_nobody_else_does(self):
        put_lock(self.slot("s1"), {"pid": os.getppid(), "start": pidcheck.proc_start(os.getppid()), "by": "loop",
                                               "slot_bead": "sl-1"})
        loop = {"TASK_LOOP_SLOT_BEAD": "sl-1", "TASK_LOOP_LOOP_PID": str(os.getppid())}
        with mock.patch.dict(os.environ, loop):
            self.assertEqual(engine_lock.engine_busy(self.slot("s1"), handoff=True), "")
            self.assertTrue(engine_lock.engine_busy(self.slot("s1")))
        with mock.patch.dict(os.environ, {**loop, "TASK_LOOP_SLOT_BEAD": "sl-2"}):
            self.assertTrue(engine_lock.engine_busy(self.slot("s1"), handoff=True))

    def test_the_parent_pid_alone_is_not_the_loop(self):
        """run-task runs under `uv run --script`, so its parent is uv: only the pid the loop exported counts (0.23.169-0.23.173 refused
        every bead the loop started, "taken: loop pid N runs ...")."""
        put_lock(self.slot("s1"), {"pid": os.getppid(), "start": pidcheck.proc_start(os.getppid()), "by": "loop",
                                               "slot_bead": "sl-1"})
        with mock.patch.dict(os.environ, {"TASK_LOOP_SLOT_BEAD": "sl-1"}):
            os.environ.pop("TASK_LOOP_LOOP_PID", None)
            self.assertTrue(engine_lock.engine_busy(self.slot("s1"), handoff=True))


class HoldRaces(Slots):


    def test_releasing_a_slot_claimed_by_another_actor_frees_the_claim_too(self):
        # lifesim 0.23.34: `slot release --force` cleared the marks but the loop actor's claim kept the slot bead in_progress
        bd = self.beads({})
        self.assertTrue(sl.take_slot(str(self.repo), SlotsConfig()))
        bd.slots["sl-1"].update(status="in_progress", assignee="tl-551cf8ee")
        wslots.release_slot(str(self.repo), "s1", spawner=real_spawner())
        self.assertEqual(bd.slots["sl-1"]["assignee"], "tl-551cf8ee")  # without --force another actor's claim is left alone
        wslots.release_slot(str(self.repo), "s1", force=True, spawner=real_spawner())
        self.assertEqual((bd.slots["sl-1"]["status"], bd.slots["sl-1"]["assignee"]), ("open", ""))

    def test_an_expired_hold_frees_the_claim_of_the_loop_that_held_the_slot(self):
        bd = self.beads({})
        self.assertTrue(sl.take_slot(str(self.repo), SlotsConfig()))
        bd.slots["sl-1"].update(status="in_progress", assignee="tl-551cf8ee")
        bd.slots["sl-1"].setdefault("metadata", {}).update(held_by="tl-abcdef12-f296a9", hold_until="1000")
        sl.free_expired(str(self.repo))
        self.assertEqual((bd.slots["sl-1"]["status"], bd.slots["sl-1"]["assignee"]), ("open", ""))


@unittest.skipUnless(POSIX, "process groups")
class NeverSignalOneself(unittest.TestCase):
    """A recorded or parsed pid or group id is a claim: no stop, reap or kill path may act on it when it is ours."""

    def test_stop_server_never_stops_the_calling_process(self):
        v = {"version": "1", "pid": os.getpid(), "urls": [], "started": 0}
        spawner = mock.Mock()
        dash_server.stop_server(v, dash_server.DEFAULT_PORT, spawner)
        spawner.stop_pid.assert_not_called()

    def test_run_main_leaves_no_sigterm_handler_behind(self):
        before = signal.getsignal(signal.SIGTERM)
        with mock.patch.object(entry, "run_main_stoppable", return_value=0):
            entry.run_main(mock.Mock(), env=snapshot(), spawner=real_spawner())
        self.assertIs(signal.getsignal(signal.SIGTERM), before)
