"""A hand run and a loop never share a slot (tl-bxk.9.5): run-task --slot takes the slot bead, a live engine in a slot's
worktree keeps it busy whatever its bead says, a hold reserves a slot for a person, and a stopped engine's worker dies
with it."""

import dataclasses
import io
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # python3 -m unittest tests.test_slots, from the repo root
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import homes

# isort: split
from loop.test_loop import LoopBase, rec
from support.engine_locks import put_lock
from support.spawn import port_git, real_spawner
from support.who import who

from taskloop.adapters import pidcheck
from taskloop.app.launch import loop as wloop
from taskloop.app.loop.take import Taker
from taskloop.app.run import (
    engine,
    entry,
)
from taskloop.app.slots import (
    engine_lock,
)
from taskloop.contracts.enums import Result
from taskloop.contracts.env import snapshot
from taskloop.contracts.ids import loop_key
from taskloop.contracts.kinds import Kind
from taskloop.contracts.lockrows import EngineLockRows
from taskloop.contracts.run import RunReport

LIVE_PID = "a live pid that is not this process: a real sleep child (an engine lock, a second loop, a waiter)"

POSIX = os.name != "nt"
REAL_PREPARE = Taker.prepare  # LoopBase stubs it


NO_FCNTL = pytest.mark.skipif(os.name == "nt", reason="the lock is fcntl; tl has none on Windows (documented no-op)")


def sleeper():
    return subprocess.Popen(["sleep", "60"])


class ExplodingGit:
    """The slot's git port when the code under test must not touch the slot."""

    def __getattr__(self, name):
        raise AssertionError("git ran in a live slot: " + name)


class Slots(LoopBase):
    def setup_method(self):
        super().setup_method()
        self.kids = []
        for n in ("s1", "s2"):
            (self.repo / ".slots" / n).mkdir(parents=True)

    def teardown_method(self):
        for k in self.kids:
            k.kill()
            k.wait()
        super().teardown_method()

    def slot(self, n):
        return str(self.repo / ".slots" / n)

    def live_lock(self, n, bead="x-9"):
        k = sleeper()
        self.kids.append(k)
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
        made.return_value.run.side_effect = lambda **_: (engine_run or (lambda: 0))()
        made.return_value.result.return_value = RunReport(outcome=Result.LANDED, bead=bead_id)
        made.return_value.log_path = Path(self.home, "e.jsonl")
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), mock.patch.object(entry, "admit", return_value=(True, "")), \
                mock.patch.object(entry, "Engine", made), \
                mock.patch.object(signal, "signal"), redirect_stdout(out):
            rc = entry.main(a, env=snapshot(), spawner=real_spawner(), git=port_git(), who=who())
        self.made = made
        return rc, json.loads(f.read_text()), out.getvalue()


class RunTaskTakesItsSlot(Slots):
    def test_a_hand_run_holds_the_slot_bead_while_it_runs_and_the_loop_takes_another(self):
        bd = self.beads({"x-1": [], "x-2": [rec("landed")]})
        seen: dict[str, Any] = {}

        def during():  # the loop starts while the hand run is mid-bead (2026-10-21 18:17)
            bd.beads["x-1"].update(status="in_progress", assignee=who().actor)  # run-task's claim (stubbed here)
            seen["slot"] = dict(bd.slots["sl-1"])
            seen["lock"] = EngineLockRows(homes.cfg(), self.slot("s1")).exists()
            lock = engine_lock.read_engine_lock(homes.cfg(), self.slot("s1"))
            seen["env"] = lock.slot_bead if lock else None  # the run's Env names the slot bead; its lock records it
            seen["list"] = self.cli("slot", "list")[1]
            with mock.patch.dict(os.environ, {"TASK_LOOP_ACTOR": "tl-loop0000"}):
                self.run_loop("--max-beads", "1")
            return 0
        rc, _r, _ = self.run_task("x-1", slot="s1", worktree=self.slot("s1"), engine_run=during)
        assert rc == 0
        assert (seen["slot"]["status"], seen["slot"]["assignee"]) == ("in_progress", who().actor)
        assert seen["lock"]
        assert seen["env"] == "sl-1"  # the engine heartbeats it
        assert "run-task x-1" in seen["list"]
        assert self.started == [("x-2", "s2")]
        # released at the end, the lock gone
        assert (bd.slots["sl-1"]["status"], bd.slots["sl-1"]["assignee"]) == ("open", "")
        assert not EngineLockRows(homes.cfg(), self.slot("s1")).exists()

    def test_slot_alone_runs_in_the_slots_worktree(self):
        self.beads({"x-1": []})
        self.run_task("x-1", slot="s1")
        assert self.made.call_args[0][1] == str(Path(self.slot("s1")).resolve())

    def test_run_task_refuses_a_slot_another_session_holds(self):
        bd = self.beads({"x-1": []})
        bd.slots["sl-1"].update(status="in_progress", assignee="tl-loop0000",
                                metadata={"held_by": "tl-loop0000", "held_since": "2026-10-21T18:17:00"})
        rc, r, _out = self.run_task("x-1", slot="s1")
        assert (rc, r["outcome"]) == (1, "taken")
        assert "slot s1 held by tl-loop0000 since 2026-10-21T18:17" in r["why"]
        self.made.assert_not_called()
        assert bd.slots["sl-1"]["assignee"] == "tl-loop0000"  # never released by the refused run

    def test_run_task_refuses_a_held_slot(self):
        bd = self.beads({"x-1": []})
        with mock.patch.dict(os.environ, {"TASK_LOOP_ACTOR": "tl-denis000"}):
            assert self.cli("slot", "hold", "s1", "--why", "screenshots")[0] == 0
        bd.slots["sl-1"].update(status="open", assignee="")  # the holder's lease lapsed and reclaim freed the bead
        _rc, r, _ = self.run_task("x-1", slot="s1")
        assert r["outcome"] == "taken"
        assert "slot s1 held by tl-denis000" in r["why"]
        assert "screenshots" in r["why"]

    def test_the_slot_is_released_when_the_run_is_stopped_before_the_engine_ran(self):
        bd = self.beads({"x-1": []})

        def stopped(*a, **kw):
            raise engine.Blocked("failed: stopped (SIGTERM)", kind=Kind.PAUSE_KILLED)
        with mock.patch.object(entry, "admit", side_effect=stopped):
            f = Path(self.home, "o.json")
            a = entry.Args(id="x-1", worktree=None, slot="s1", dry_run=False, fresh=False, quiet=True,
                            outcome_file=str(f))
            with mock.patch.object(signal, "signal"), redirect_stdout(io.StringIO()):
                rc = entry.main(a, env=snapshot(), spawner=real_spawner(), git=port_git(), who=who())
        assert rc != 0
        assert json.loads(f.read_text())["outcome"] == "failed"
        assert bd.slots["sl-1"]["status"] == "open"
        assert not EngineLockRows(homes.cfg(), self.slot("s1")).exists()

    def test_a_run_the_loop_started_does_not_take_or_release_the_slot_again(self):
        bd = self.beads({"x-1": []})
        bd.slots["sl-1"].update(status="in_progress", assignee=who().actor)
        self.run_task("x-1", slot="s1", TASK_LOOP_SLOT_BEAD="sl-1")
        assert bd.slots["sl-1"]["status"] == "in_progress"
        assert ("unclaim", "sl-1") not in bd.calls
        assert ("update", "sl-1", "--claim") not in bd.calls
    def test_run_task_refuses_a_worktree_with_a_live_engine(self):
        self.beads({"x-1": []})
        k = self.live_lock("s1", bead="x-0")
        _rc, r, _ = self.run_task("x-1", worktree=self.slot("s1"))
        assert r["outcome"] == "taken"
        assert f"pid {k.pid}" in r["why"]
        self.made.assert_not_called()
        assert EngineLockRows(homes.cfg(), self.slot("s1")).exists()  # never removes another run's lock
    def test_a_dead_engines_lock_is_no_obstacle(self):
        self.beads({"x-1": []})
        k = self.live_lock("s1")
        k.kill()
        k.wait()
        rc, _r, _ = self.run_task("x-1", worktree=self.slot("s1"))
        assert rc == 0


class LiveEngineBackstop(Slots):
    def test_the_loop_skips_a_slot_whose_worktree_has_a_live_engine_though_its_bead_is_open(self):
        bd = self.beads({"x-1": [rec("landed")]})
        self.live_lock("s1")
        self.run_loop("--max-beads", "1")
        assert self.started == [("x-1", "s2")]
        assert bd.slots["sl-1"]["status"] == "open"
    def test_a_live_worker_left_by_a_dead_engine_keeps_the_slot_busy(self):
        self.beads({"x-1": [rec("landed")]})
        k = sleeper()
        self.kids.append(k)
        put_lock(self.slot("s1"), {"pid": 0, "bead": "x-0", "workers": [(k.pid, pidcheck.proc_start(k.pid))]})
        assert str(k.pid) in engine_lock.engine_busy(homes.cfg(), self.slot("s1"))
        self.run_loop("--max-beads", "1")
        assert self.started == [("x-1", "s2")]
    def test_slot_reset_never_touches_a_slot_with_a_live_engine(self):
        self.beads({"x-1": []})
        self.live_lock("s1")
        rc, out = self.cli("slot", "reset", "s1", "--bead", "x-1")
        assert rc == 4
        assert "BUSY" in out
        senv = dataclasses.replace(wloop.build(str(self.repo), env=snapshot(), spawner=real_spawner(), git=port_git(),
            who=who()).slot_env(), git=ExplodingGit())  # pyrefly: ignore[bad-argument-type]  # any git in the live slot fails the test
        env = dataclasses.replace(wloop.build(str(self.repo), env=snapshot(), spawner=real_spawner(),
            git=port_git(), who=who()), slot_env=lambda: senv)
        with redirect_stdout(io.StringIO()):
            assert REAL_PREPARE(Taker(env, mock.Mock(), mock.Mock(), mock.Mock(), mock.Mock(), {}), "s1", "x-1") is not None
    def test_slot_list_shows_the_live_engine(self):
        self.beads({})
        k = self.live_lock("s1", bead="x-7")
        out = self.cli("slot", "list")[1]
        line = next(ln for ln in out.splitlines() if ln.startswith("s1"))
        assert f"engine pid {k.pid}" in line
        assert "x-7" in line


class Hold(Slots):
    def test_a_hold_is_skipped_by_the_loop_shown_in_list_and_expires(self):
        bd = self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        self.clock.t = time.time()  # hold deadlines are real epoch seconds
        rc, out = self.cli("slot", "hold", "s1", "--why", "screenshots for the owner", "--for", "30")
        assert rc == 0, out
        bd.slots["sl-1"].update(status="open", assignee="")  # a lapsed lease does not end a hold
        listing = self.cli("slot", "list")[1]
        assert "screenshots for the owner" in listing
        assert who().actor in next(ln for ln in listing.splitlines() if ln.startswith("s1"))
        self.run_loop("--max-beads", "1")
        assert self.started == [("x-1", "s2")]
        self.clock.t += 31 * 60  # expired
        self.run_loop("--max-beads", "1")
        assert self.started[-1] == ("x-2", "s1")


    def test_release_ends_a_hold(self):
        bd = self.beads({"x-1": [rec("landed")]})
        self.cli("slot", "hold", "s1", "--why", "screenshots")
        assert self.cli("slot", "release", "s1")[0] == 0
        assert bd.slots["sl-1"]["status"] == "open"
        assert "hold_until" not in bd.slots["sl-1"].get("metadata", {})
        self.run_loop("--max-beads", "1")
        assert self.started == [("x-1", "s1")]
    def test_a_slot_in_use_cannot_be_held(self):
        bd = self.beads({})
        bd.slots["sl-1"].update(status="in_progress", assignee="tl-loop0000")
        rc, out = self.cli("slot", "hold", "s1", "--why", "x")
        assert rc != 0
        assert "tl-loop0000" in out
        self.live_lock("s2")
        assert self.cli("slot", "hold", "s2", "--why", "x")[0] != 0
    def test_release_refuses_a_slot_with_a_live_engine(self):
        bd = self.beads({})
        bd.slots["sl-1"].update(status="in_progress", assignee="tl-hand0000")
        self.live_lock("s1")
        rc, _ = self.cli("slot", "release", "s1")
        assert rc != 0
        assert bd.slots["sl-1"]["status"] == "in_progress"


@pytest.mark.skipif(not (POSIX), reason="ps start times and zombies")
class StaleLocks(Slots):
    """A lock outlives a SIGKILLed engine: its pid may be reused or a zombie; neither keeps the slot busy forever."""
    def test_a_reused_pid_with_another_start_time_is_dead(self):
        k = sleeper()
        self.kids.append(k)
        put_lock(self.slot("s1"), {"pid": k.pid, "start": "Mon Jan  1 00:00:00 2001", "bead": "x-0"})
        assert engine_lock.engine_busy(homes.cfg(), self.slot("s1")) == ""
        put_lock(self.slot("s1"), {"pid": k.pid, "start": pidcheck.proc_start(k.pid), "bead": "x-0"})
        assert f"pid {k.pid}" in engine_lock.engine_busy(homes.cfg(), self.slot("s1"))
        put_lock(self.slot("s1"), {"pid": 0, "workers": [(k.pid, "Mon Jan  1 00:00:00 2001")]})
        assert engine_lock.engine_busy(homes.cfg(), self.slot("s1")) == ""
    def test_a_zombie_is_dead(self):
        z = subprocess.Popen(["true"])
        try:
            for _ in range(100):
                if not pidcheck.pid_alive(z.pid):
                    break
                time.sleep(0.05)
            assert not pidcheck.pid_alive(z.pid)  # exited and not yet reaped: stream-proc reads it as gone
            put_lock(self.slot("s1"), {"pid": z.pid, "bead": "x-0"})
            assert engine_lock.engine_busy(homes.cfg(), self.slot("s1")) == ""
        finally:
            z.wait()
    def test_busy_names_the_lock_and_force_drops_it_on_reset_and_release(self):
        self.beads({})
        k = self.live_lock("s1")
        rc, out = self.cli("slot", "reset", "s1")
        assert rc == 4
        assert "engine:" + loop_key(self.slot("s1")) in out
        assert str(k.pid) in out
        rc, out = self.cli("slot", "reset", "s1", "--force")
        assert rc != 4
        assert "FORCED" in out
        assert not EngineLockRows(homes.cfg(), self.slot("s1")).exists()
        self.live_lock("s2")
        assert self.cli("slot", "release", "s2", "--force")[0] == 0
        assert not EngineLockRows(homes.cfg(), self.slot("s2")).exists()


class SameActor(Slots):
    """A hand run from the session that started the loop shares the loop's actor: bd lets it re-claim the slot bead."""

    def test_a_held_slot_bead_is_refused_to_its_own_actor_unless_it_is_the_runs_own_slot_bead(self):
        bd = self.beads({"x-1": []})
        bd.slots["sl-1"].update(status="in_progress", assignee=who().actor,
                                metadata={"held_by": who().actor, "held_since": "2026-10-21T18:17:00",
                                          "held_why": "tl loop"})
        rc, r, _ = self.run_task("x-1", slot="s1")
        assert r["outcome"] == "taken"
        assert f"slot s1 held by {who().actor} since 2026-10-21T18:17:00 (tl loop)" in r["why"]
        rc, r, _ = self.run_task("x-1", slot="s1", TASK_LOOP_SLOT_BEAD="sl-2")  # another slot's bead: no pass
        assert r["outcome"] == "taken"
        rc, r, _ = self.run_task("x-1", slot="s1", TASK_LOOP_SLOT_BEAD="sl-1")
        assert rc == 0

    def test_a_hand_run_with_only_a_worktree_that_is_a_slot_takes_that_slot(self):
        bd = self.beads({"x-1": []})
        bd.slots["sl-1"].update(status="in_progress", assignee="tl-loop0000")
        rc, r, _ = self.run_task("x-1", worktree=self.slot("s1"))
        assert r["outcome"] == "taken"
        assert "held by tl-loop0000" in r["why"]
        bd.slots["sl-1"].update(status="open", assignee="")
        seen = {}
        rc, r, _ = self.run_task("x-1", worktree=self.slot("s1"),
                                 engine_run=lambda: seen.update(bd.slots["sl-1"]) or 0)
        assert (rc, seen["status"]) == (0, "in_progress")
        assert bd.slots["sl-1"]["status"] == "open"

    def test_the_loop_locks_the_slot_from_its_take_through_the_reset(self):
        bd = self.beads({"x-1": [rec("landed")], "x-2": []})
        seen: dict[str, Any] = {}

        def reset(taker, slot, bead_id):
            seen["lock"] = engine_lock.read_engine_lock(homes.cfg(), self.slot(slot))
            hand = os.getpid() + 1  # another process of this very session (same actor)
            with mock.patch.dict(os.environ, {"TASK_LOOP_SLOT_BEAD": ""}), mock.patch.object(os, "getpid", return_value=hand):
                bd.slots["sl-1"]["status"] = "open"  # even were its bead open
                _rc, r, _ = self.run_task("x-2", worktree=self.slot(slot))
                bd.slots["sl-1"].update(status="in_progress", assignee=who().actor)
            seen["hand"] = r
        with mock.patch.object(Taker, "prepare", reset):
            self.run_loop("--max-beads", "1")
        assert (seen["lock"].by, seen["lock"].pid, seen["lock"].slot_bead) == ("loop", os.getpid(), "sl-1")
        assert seen["hand"]["outcome"] == "taken"
        assert f"loop pid {os.getpid()}" in seen["hand"]["why"]
        assert not EngineLockRows(homes.cfg(), self.slot("s1")).exists()


class HoldRaces(Slots):

    def test_an_expired_hold_gives_the_slot_bead_back(self):
        bd = self.beads({"x-1": [rec("landed")]})
        self.clock.t = time.time()  # hold deadlines are real epoch seconds
        with mock.patch.dict(os.environ, {"TASK_LOOP_ACTOR": "tl-denis000"}):
            self.cli("slot", "hold", "s1", "--why", "a person", "--for", "10")
        assert (bd.slots["sl-1"]["status"], bd.slots["sl-1"]["assignee"]) == ("in_progress", "tl-denis000")
        self.clock.t += 11 * 60
        self.run_loop("--max-beads", "1")
        assert self.started == [("x-1", "s1")]



    def test_ones_own_hold_keeps_ones_own_runs_and_resets_off_unless_forced(self):
        self.beads({"x-1": []})
        self.cli("slot", "hold", "s1", "--why", "screenshots")
        _rc, r, _ = self.run_task("x-1", slot="s1")
        assert r["outcome"] == "taken"
        assert "screenshots" in r["why"]
        assert self.cli("slot", "reset", "s1")[0] == 4
        assert self.cli("slot", "reset", "s1", "--force")[0] != 4


