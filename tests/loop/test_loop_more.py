"""Loop tests, part 2: network, health, stop requests, self-update. Split from test_loop."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401

# isort: split
import itertools  # noqa: E402

from support import (  # noqa: E402
    eventlog,
    looptest,
)
from loop.test_loop import Base, LoopBase, bead, rec  # noqa: E402

from taskloop.adapters import (  # noqa: E402
    beadtools,
    ident,
    procs,
)
from taskloop.app.launch import loop as wloop  # noqa: E402
from taskloop.app.loop.core import Core  # noqa: E402
from taskloop.cli import loop_cmd  # noqa: E402
from taskloop.contracts import wire  # noqa: E402
from taskloop.contracts.config import LoopConfig  # noqa: E402
from taskloop.contracts.loop import LoopCommand, LoopState  # noqa: E402
from taskloop.domain.lanes import netgate  # noqa: E402


class UpAt:
    """A NetProbe that says up from a wall time on (the fake clock's), so a test can say how soon after that the loop looked."""

    def __init__(self, clock, t_up):
        self.clock, self.t_up, self.calls = clock, t_up, []

    def up(self):
        self.calls.append(self.clock.t)
        return self.clock.t >= self.t_up


NET = {"kind": "pause_network", "why": "paused: network on write; resume when it is back"}


class LoopNetwork(LoopBase):
    """tl-kyy: a network pause probes every 60 s and resumes the same bead; it counts against nothing."""

    def setUp(self):
        super().setUp()

    @property
    def events(self):
        return [(e["kind"], e["bead"]) for e in eventlog.read()]

    def probe(self, probe):
        p = mock.patch.object(wloop, "make_probe", return_value=probe)
        p.start()
        self.addCleanup(p.stop)
        return probe

    def kinds(self):
        return [k for k, _ in self.events if k.startswith("net_")]

    def test_the_probe_is_down_for_three_ticks_then_up_and_the_same_bead_resumes_within_a_minute(self):
        times = []
        t_up = self.clock.t0 + 150  # up between the 3rd and the 4th look
        probe = self.probe(UpAt(self.clock, t_up))
        self.beads({"x-1": [rec("paused", **NET), rec("landed", run="run-1")], "x-2": [rec("landed")]})
        self.during.extend([lambda: times.append(self.clock.t)] * 2)
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-1", "x-2"])  # no other bead while the network is down
        self.assertEqual(len(probe.calls), 4)
        self.assertEqual(probe.calls, [self.clock.t0 + 60 * i for i in range(4)])  # a probe a minute while down
        self.assertEqual(sum(1 for c in probe.calls if c < t_up), 3)
        self.assertGreaterEqual(times[1], t_up)
        self.assertLessEqual(times[1] - t_up, 60)  # resumed within 60 s of the probe going up
        self.assertEqual(self.kinds(), ["net_down", "net_up"])
        self.assertNotIn(LoopConfig().pause_retry, self.clock.naps)
        self.assertIn(60, self.clock.naps)
        self.assertEqual([ln["outcome"] for ln in self.lines()], ["paused", "landed", "landed"])
        self.assertEqual(self.lines()[1]["trace"], "run-1")

    def test_a_network_pause_keeps_the_label_the_budget_and_every_counter(self):
        self.probe(netgate.FakeProbe([True]))
        # four network pauses in a row: PAUSES_TO_REST (3) would rest the bead an hour; --max-beads would count them
        bd = self.beads({"x-1": [rec("paused", **NET)] * 4 + [rec("landed")]})
        self.assertEqual(self.run_loop("--max-beads", "1"), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1"] * 5)
        self.assertFalse([n for n in self.clock.naps if n >= 3000])
        self.assertEqual(self.kinds(), ["net_down", "net_up"] * 4)
        self.assertFalse(
            [c for c in bd.calls if c[0] == "label" or {"--add-label", "--remove-label", "--set-labels"} & set(c)]
        )  # none stripped or added
        self.assertEqual(looptest.rests(str(self.repo)), {})  # never rested, never a failed run
        self.assertEqual(bd.beads["x-1"]["status"], "closed")

    def test_one_outage_is_one_down_and_one_up_for_every_slot(self):
        probe = self.probe(UpAt(self.clock, self.clock.t0 + 500))
        self.beads({"x-1": [rec("paused", **NET), rec("landed")], "x-2": [rec("landed")], "x-3": [rec("landed")]})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.kinds(), ["net_down", "net_up"])
        self.assertEqual([b for b, _ in self.started][:2], ["x-1", "x-1"])
        self.assertEqual(len([c for c in probe.calls if c < self.clock.t0 + 500]), 9)

    def test_a_stop_during_an_outage_ends_the_loop_without_probing_forever(self):
        self.probe(netgate.FakeProbe([False]))
        self.beads({"x-1": [rec("paused", **NET)]})
        polls = []

        def nap(secs, until=0):
            polls.append(round(secs))
            self.clock.t += secs

        with (
            mock.patch.object(Core, "nap", staticmethod(nap)),
            mock.patch.object(Core, "stop_mode", side_effect=lambda: "after" if len(polls) >= 2 else ""),
        ):
            self.assertEqual(self.run_loop(), 0)
        self.assertEqual(polls, [60, 60])
        self.assertEqual(looptest.last_exit(str(self.repo))["reason"], "stop_request")

    def test_without_a_delegate_to_probe_a_network_pause_rests_like_a_lane_pause_and_the_next_bead_runs(self):
        self.probe(None)
        self.beads({"x-1": [rec("paused", **NET), rec("landed")], "x-2": [rec("landed")]})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2", "x-1"])
        self.assertIn(LoopConfig().pause_retry, self.clock.naps)
        self.assertIn("no delegate is installed", self.out)
        self.assertEqual(self.kinds(), [])

    def test_a_lane_pause_waits_on_its_role_not_on_a_probe(self):
        probe = self.probe(netgate.FakeProbe([True]))
        self.beads({"x-1": [rec("paused", kind="pause_lane", role="worker"), rec("landed")],
                    "x-2": [rec("paused", kind="pause_lane", role="worker"), rec("landed")]})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(probe.calls, 0)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-1", "x-2", "x-2"])  # the role is usable: the same bead again


class LoopHealth(LoopBase):
    """tl-7y6.2.12: a loop that exits says why; a repo with ready beads and no loop alive is a red line; the log outlives the session."""

    def status(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.main(["loop", "status", "--repo", str(self.repo)])
        return out.getvalue()

    def test_ready_beads_with_no_loop_alive_and_no_recent_beat_is_one_red_line_naming_repo_and_command(self):
        self.beads({"x-1": [rec("landed")]})
        out = self.status()
        self.assertEqual(out.count("RED:"), 1)
        self.assertIn(f"{self.repo} has 1 ready bead(s) and no loop alive", out)
        self.assertIn(f"tl loop --repo {self.repo}", out)

    def test_a_bead_parked_on_a_dropped_ask_shows_in_status(self):
        f = ident.config_dir() / "asks" / "x-1.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"v": 1, "id": "x-1-2", "bead": "x-1", "status": "open"}))
        self.assertIn("x-1  ", self.status())
        self.assertIn("its ask was dropped at upgrade", self.status())

    def test_a_live_loop_or_a_recent_beat_or_nothing_ready_is_no_warning(self):
        self.beads({"x-1": [rec("landed")]})
        looptest.write_state(str(self.repo), pid=os.getpid(), started=self.clock.t)  # this process is alive
        self.assertNotIn("RED:", self.status())
        looptest.state_path(str(self.repo), os.getpid()).unlink()
        self.run_loop()  # drains: a fresh exit line is a fresh beat
        self.assertNotIn("RED:", self.status())
        self.beads({"x-1": [rec("landed")]})  # the bead is ready again
        self.clock.t += 11 * 60
        self.assertIn("RED:", self.status())  # 10 min with no beat and a ready bead
        self.beads({})
        self.assertNotIn("RED:", self.status())  # nothing ready: idle, not absent

    def test_a_loop_that_exits_writes_its_reason_and_status_shows_the_last_one_and_the_log_path(self):
        self.beads({"x-1": [rec("landed")]})
        self.run_loop()
        ex = looptest.last_exit(str(self.repo))
        self.assertEqual((ex["reason"], ex["pid"], ex["v"]), ("drained", os.getpid(), 1))
        self.assertTrue(Path(str(ex["log_path"])).is_file())
        self.assertIn("last exit: drained", self.status())
        self.beads({"x-1": [rec("landed")]})
        self.run_loop("--max-beads", "1")
        self.assertEqual(looptest.last_exit(str(self.repo))["reason"], "max_beads")

    def test_a_loop_killed_without_an_exit_line_leaves_its_state_as_died_pid_json(self):
        self.beads({})
        looptest.write_state(str(self.repo), pid=999999, started=self.clock.t)
        self.assertEqual(looptest.live(str(self.repo)), [])  # no such process
        died = looptest.files(str(self.repo)).runs() / "died-999999.json"
        self.assertEqual(json.loads(died.read_text())["pid"], 999999)

    def test_the_loops_own_log_keeps_what_it_said_and_is_pruned_to_five(self):
        runs = looptest.files(str(self.repo)).runs()
        for i in range(8):
            f = runs / (f"loop-{int(100 + i)}.log")
            f.write_text("old")
            os.utime(f, (1000 + i, 1000 + i))
        self.beads({"x-1": [rec("landed")]})
        self.run_loop()
        log = runs / (f"loop-{os.getpid()}.log")
        self.assertIn("x-1 in s1", log.read_text())
        self.assertEqual(len(list(runs.glob("loop-*.log"))), LoopConfig().logs_kept)
        self.assertIn("loop-107.log", [f.name for f in runs.glob("loop-*.log")])  # the newest old ones stay
        self.assertNotIn("loop-100.log", [f.name for f in runs.glob("loop-*.log")])

    def test_the_beat_is_refreshed_while_a_bead_runs_at_most_once_a_minute(self):
        st_beats = []
        real = looptest.files(str(self.repo)).__class__.write
        with mock.patch.object(
            type(looptest.files(str(self.repo))), "write", lambda f, st: st_beats.append(st.t if st.child else None) or real(f, st)
        ):
            self.beads({"x-1": [rec("landed")]})
            self.hold["x-1"] = 100
            self.run_loop()
        refreshed = [b for b in st_beats if b]  # the writes while a child runs: the start, then a beat at most every minute
        self.assertGreaterEqual(len(refreshed), 3)
        self.assertTrue(all(b2 - b1 >= LoopConfig().beat_every for b1, b2 in itertools.pairwise(refreshed)))


class StopRequests(LoopBase):
    """`tl stop` writes one LoopCommand naming the live loops; a loop it does not name (started later) ignores it."""

    def setUp(self):
        super().setUp()
        self.repo_s = str(self.repo)
        self.old_pid = os.getppid()  # a live process that is no loop of this test
        self.files = looptest.files(self.repo_s)

    def old_loop(self):
        looptest.write_state(self.repo_s, pid=self.old_pid, started=self.clock.t)

    def stop(self, now=False):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.main(["stop", "--repo", self.repo_s] + (["--now"] if now else [])), 0)
        return self.files.command().read()

    def test_the_command_names_the_running_loops(self):
        self.old_loop()
        looptest.write_state(self.repo_s, pid=os.getpid(), started=self.clock.t)
        for now in (False, True):
            with self.subTest(now=now):
                cmd = self.stop(now)
                assert cmd is not None
                self.assertEqual(set(cmd.targets), {self.old_pid, os.getpid()})
                self.assertEqual(cmd.action, "stop_now" if now else "stop_after_current")
                self.assertEqual(cmd.t, self.clock.t)

    def test_a_stop_applies_to_the_loops_it_names_only(self):
        self.old_loop()
        for now in (False, True):
            self.stop(now)
            self.assertEqual(self.files.stop_for(self.old_pid), "now" if now else "after")
            self.assertEqual(self.files.stop_for(os.getpid()), "")

    def test_a_command_that_is_not_a_command_is_ignored(self):
        f = looptest.command(self.repo_s)
        f.parent.mkdir(parents=True, exist_ok=True)
        for text in ("", "after", json.dumps({"mode": "after", "time": 1}), json.dumps({"v": 2, "action": "stop_now"})):
            f.write_text(text)
            self.assertEqual(self.files.stop_for(self.old_pid), "", text)

    def test_a_stop_does_not_stop_a_loop_started_after_it(self):
        self.old_loop()
        self.stop()
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        self.during.append(lambda: self.assertEqual(self.files.stop_for(os.getpid()), ""))
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2"])
        self.assertEqual(self.files.stop_for(self.old_pid), "after")

    def test_start_clears_a_command_that_names_no_running_loop(self):
        for other in (False, True):
            with self.subTest(other=other):
                self.beads({"x-1": [rec("landed")]})
                if other:
                    self.old_loop()
                self.files.command().write(LoopCommand(action="stop_after_current", by="t", t=self.clock.t - 10, targets=[12345]))
                self.during.append(lambda: self.assertFalse(looptest.command(self.repo_s).exists()))
                self.assertEqual(self.run_loop(), 0)

    def test_cleanup_keeps_the_command_while_a_named_loop_lives_and_drops_it_after(self):
        self.old_loop()
        self.stop()
        with self.files.lock():
            self.files.clean_command()
            self.assertTrue(looptest.command(self.repo_s).exists())
            self.files.remove(self.old_pid)
            self.files.clean_command()
        self.assertFalse(looptest.command(self.repo_s).exists())

    def test_a_stop_waits_for_a_registration_in_progress_and_names_the_new_loop(self):
        self.old_loop()
        attempted, finished, errors = threading.Event(), threading.Event(), []

        def stop():
            attempted.set()
            try:
                loop_cmd.cmd_stop(mock.Mock(repo=self.repo_s, now=True))
            except Exception as e:
                errors.append(e)
            finally:
                finished.set()
        with redirect_stdout(io.StringIO()):
            with self.files.lock():
                thread = threading.Thread(target=stop)
                thread.start()
                self.assertTrue(attempted.wait(2))
                self.assertFalse(finished.wait(0.05))
                looptest.write_state(self.repo_s, pid=os.getpid(), started=self.clock.t)
            thread.join(2)
        self.assertEqual(errors, [])
        cmd = self.files.command().read()
        assert cmd is not None
        self.assertEqual(set(cmd.targets), {self.old_pid, os.getpid()})

    def test_a_loop_that_moved_keeps_the_command_that_names_it(self):
        self.beads({"x-1": [rec("landed")]})
        looptest.write_state(self.repo_s, pid=os.getpid(), started=self.clock.t - 100)
        self.stop()
        st = LoopState(pid=os.getpid(), started=self.clock.t - 100, t=1.0, repo=self.repo_s, version="0.0.1", code_dir="/x", actor="tl-a")
        with mock.patch.dict(os.environ, {"TL_LOOP_STATE": json.dumps(wire.dump(st))}):
            self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.started, [])


class Moved(Exception):
    """What the mocked os.execv raises: the real one never returns."""


class LoopSelfUpdate(LoopBase):
    """Between beads the loop re-execs into the newest install of the plugin (fake version trees)."""

    def setUp(self):
        super().setUp()
        self.cache = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cache, True)
        self.execs = []

        def execv(exe, argv):
            self.execs.append((exe, argv, os.environ.get("TL_LOOP_STATE"), os.getcwd()))
            raise Moved()
        for p in (mock.patch.object(os, "execv", side_effect=execv),
                  mock.patch.dict(os.environ, {})):
            p.start()
            self.addCleanup(p.stop)
        self.here = self.install("0.1.0")
        os.environ.pop("TL_LOOP_STATE", None)

    def install(self, ver, tl_py="import sys\n"):
        return looptest.fake_install(self.cache, ver, tl_py)

    def test_it_moves_to_a_newer_complete_install_between_beads_with_the_same_argv(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        self.during.append(lambda: self.install("0.2.0"))
        with self.assertRaises(Moved):
            self.run_loop("--max-beads", "5")
        self.assertEqual([b for b, _ in self.started], ["x-1"])  # never mid-bead: x-1 ran to its end on 0.1.0
        self.assertEqual([ln["outcome"] for ln in self.lines()], ["landed"])
        exe, argv, state, _ = self.execs[0]
        self.assertEqual(exe, argv[0])
        self.assertEqual(argv[:5], procs.script_argv(self.cache / "0.2.0" / "skills" / "task-loop" / "tl.py"))
        self.assertEqual(argv[5:], ["loop", "--repo", str(self.repo), "--max-beads", "5"])
        self.assertEqual(json.loads(state)["carry"]["ran"], 1)

    def test_the_move_is_logged_and_the_newest_of_several_wins(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.2.0")
        self.install("0.10.0")  # 0.10 is newer than 0.9: numbers, not text
        self.install("0.9.0")
        with self.assertRaises(Moved), redirect_stdout(io.StringIO()) as out:
            self.main(["loop", "--repo", str(self.repo)])
        self.assertIn("loop: moving to 0.10.0 (was 0.1.0)", out.getvalue())
        self.assertIn("0.10.0", self.execs[0][1][4])
        self.assertEqual(self.started, [])  # the first look is before any bead

    def pin(self, **v):
        (ident.config_dir() / "pinned.json").write_text(json.dumps(v))

    def test_a_pin_beats_the_newest_install(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.2.0")
        self.install("0.3.0")
        self.pin(**{"task-loop": "0.2.0"})
        with self.assertRaises(Moved):
            self.run_loop()
        self.assertEqual(self.execs[0][1][:5], procs.script_argv(self.cache / "0.2.0" / "skills" / "task-loop" / "tl.py"))

    def test_a_pin_to_an_older_install_moves_the_loop_back(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.0.5")
        self.install("0.2.0")
        self.pin(**{"task-loop": "0.0.5"})
        with self.assertRaises(Moved):
            self.run_loop()
        self.assertIn("0.0.5", self.execs[0][1][4])

    def test_a_pin_to_the_running_version_stays_though_a_newer_one_is_installed(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        self.install("0.2.0")
        self.pin(**{"task-loop": "0.1.0"})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.execs, [])
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2"])

    def test_a_pin_to_a_missing_dir_stays_where_it_is_and_never_falls_back_to_the_newest(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.2.0")
        self.pin(**{"task-loop": "0.9.9"})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.execs, [])

    def test_the_loop_never_writes_pinned_json(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        self.install("0.2.0")
        with self.assertRaises(Moved):
            self.run_loop()
        self.assertFalse((ident.config_dir() / "pinned.json").exists())
        self.pin(**{"task-loop": "0.1.0"})
        before = (ident.config_dir() / "pinned.json").read_bytes()
        self.beads({"x-3": [rec("landed")]})
        self.run_loop()
        self.assertEqual((ident.config_dir() / "pinned.json").read_bytes(), before)
        for f in (ROOT / "src" / "taskloop" / "app" / "loop").glob("*.py"):
            src = f.read_text(encoding="utf-8")
            self.assertNotIn("write_pin", src)
            self.assertNotIn("pin_file", src)

    def test_a_relative_repo_is_resolved_from_the_start_directory_at_the_exec(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.2.0")
        start = self.repo.parent
        with mock.patch.dict(os.environ), mock.patch("os.getcwd", wraps=os.getcwd):
            old = os.getcwd()
            os.chdir(start)
            try:
                with self.assertRaises(Moved), redirect_stdout(io.StringIO()):
                    self.main(["loop", "--repo", self.repo.name])
            finally:
                os.chdir(old)
        self.assertEqual(os.path.realpath(self.execs[0][3]), os.path.realpath(start))
        self.assertIn(self.repo.name, self.execs[0][1])

    def test_a_state_in_an_old_shape_is_dropped_with_one_reload_record_and_a_clean_pass(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        os.environ["TL_LOOP_STATE"] = json.dumps({"ran": "many", "fails": ["x-0"], "later": [1]})
        self.assertEqual(self.run_loop(), 0)
        reloads = [e for e in eventlog.read() if e["kind"] == "reload"]
        self.assertEqual(len(reloads), 1)
        self.assertIn("handover state dropped", reloads[0]["why"])
        self.assertIn("a clean pass starts", self.out)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2"])  # no step twice, none skipped
        self.assertNotIn("TL_LOOP_STATE", os.environ)

    def test_a_state_of_another_version_is_dropped_the_same_way(self):
        self.beads({"x-1": [rec("landed")]})
        st = LoopState(pid=1, started=1.0, t=1.0, repo="r", version="0.0.1", code_dir="/x", actor="tl-a")
        os.environ["TL_LOOP_STATE"] = json.dumps(dict(wire.dump(st), v=1))
        self.assertEqual(self.run_loop(), 0)
        self.assertIn("state handed over could not be read", self.out)
        self.assertEqual([b for b, _ in self.started], ["x-1"])

    def test_the_failure_counter_and_the_actor_survive_the_move(self):
        self.beads({"x-1": [rec("failed")], "x-2": [rec("failed")], "x-3": [rec("landed")]})
        self.during.append(lambda: self.install("0.2.0"))
        with self.assertRaises(Moved):
            self.run_loop()
        actor = os.environ["TASK_LOOP_ACTOR"]
        state = json.loads(self.execs[0][2])
        self.assertEqual(state["carry"]["fails"], ["x-1"])
        # the new process: same pid, the state in the environment, the new install as the running code
        os.environ["TL_LOOP_STATE"] = self.execs[0][2]
        with self.running_from(self.cache / "0.2.0" / "skills" / "task-loop"):
            self.assertEqual(self.run_loop(), 2)  # one more failure is the second in a row
        self.assertIn("STOPPED: 2 failures in a row (x-1, x-2)", self.out)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2"])
        self.assertEqual(os.environ["TASK_LOOP_ACTOR"], actor)
        self.assertNotIn("TL_LOOP_STATE", os.environ)  # not handed on to children

    def test_max_beads_counts_the_beads_run_before_the_move(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")], "x-3": [rec("landed")]})
        self.during.append(lambda: self.install("0.2.0"))
        with self.assertRaises(Moved):
            self.run_loop("--max-beads", "2")
        os.environ["TL_LOOP_STATE"] = self.execs[0][2]
        with self.running_from(self.cache / "0.2.0" / "skills" / "task-loop"):
            self.run_loop("--max-beads", "2")
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2"])

    def test_pin_stays_on_the_running_install(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        self.install("0.2.0")
        self.assertEqual(self.run_loop("--pin"), 0)
        self.assertEqual(self.execs, [])
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2"])

    def test_a_dev_checkout_never_moves(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.2.0")
        dev = self.cache / "checkout" / "skills" / "task-loop"
        dev.mkdir(parents=True)
        with self.running_from(dev):
            self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.execs, [])


class LandedOnBase(Base):
    def git_repo(self):
        def sh(*a, cwd):
            subprocess.run(list(a), cwd=cwd, check=True, capture_output=True)
        os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        origin, wt = self.home / "o.git", self.home / "wt"
        sh("git", "init", "-q", "--bare", "-b", "main", str(origin), cwd=self.home)
        sh("git", "clone", "-q", str(origin), str(wt), cwd=self.home)
        sh("git", "commit", "-q", "--allow-empty", "-m", "init", cwd=wt)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=wt)
        return wt, lambda *a: sh(*a, cwd=wt)

    def test_only_a_land_commit_of_the_bead_on_the_base_counts(self):
        wt, sh = self.git_repo()
        self.fake(bead("x-1"), bead("x-2"), bead("x-3"))
        sh("git", "checkout", "-q", "-b", "task/x-1")
        sh("git", "commit", "-q", "--allow-empty", "-m", "Add f (x-1)")
        sh("git", "push", "-q", "origin", "HEAD:main")
        sh("git", "checkout", "-q", "-b", "task/x-2", "origin/main")
        sh("git", "commit", "-q", "--allow-empty", "-m", "wip (x-2): failed")
        sh("git", "checkout", "-q", "-b", "task/x-3", "origin/main")
        self.assertTrue(wloop.landed_on_base(str(self.repo), beadtools.bd_store(str(self.repo)), str(wt), "x-1"))
        self.assertFalse(wloop.landed_on_base(str(self.repo), beadtools.bd_store(str(self.repo)), str(wt), "x-2"))  # work not on main
        self.assertFalse(
            wloop.landed_on_base(str(self.repo), beadtools.bd_store(str(self.repo)), str(wt), "x-3")
        )  # no work: the tip is someone else's
        self.assertFalse(wloop.landed_on_base(str(self.repo), beadtools.bd_store(str(self.repo)), str(wt), "x-9"))  # no branch


if __name__ == "__main__":
    unittest.main()
