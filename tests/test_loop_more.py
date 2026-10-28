"""Loop tests, part 2: network, health, stop requests, self-update. Split from test_loop."""
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from support import tlbd  # noqa: E402
import loop  # noqa: E402
from taskloop.domain.lanes import netgate  # noqa: E402
import tl  # noqa: E402
from test_loop import Base, LoopBase, bead, rec  # noqa: E402


class UpAt:
    """A NetProbe that says up from a wall time on (the fake clock's), so a test can say how soon after that the loop looked."""

    def __init__(self, clock, t_up):
        self.clock, self.t_up, self.calls = clock, t_up, []

    def up(self):
        self.calls.append(self.clock.t)
        return self.clock.t >= self.t_up


NET = dict(kind="pause_network", why="paused: network on write; resume when it is back")


class LoopNetwork(LoopBase):
    """tl-kyy: a network pause probes every 60 s and resumes the same bead; it counts against nothing."""

    def setUp(self):
        super().setUp()
        self.events = []
        for p in (mock.patch.object(tl, "event", side_effect=lambda kind, bead="", **kw: self.events.append((kind, bead)) or {}),):
            p.start()
            self.addCleanup(p.stop)

    def probe(self, probe):
        p = mock.patch.object(loop, "make_probe", return_value=probe)
        p.start()
        self.addCleanup(p.stop)
        return probe

    def kinds(self):
        return [k for k, _ in self.events if k.startswith("net_")]

    def test_the_probe_is_down_for_three_ticks_then_up_and_the_same_bead_resumes_within_a_minute(self):
        times = []
        t_up = self.clock.t0 + 150  # up between the 3rd and the 4th look
        probe = self.probe(UpAt(self.clock, t_up))
        bd = self.beads({"x-1": [rec("paused", **NET), rec("landed", run="run-1")], "x-2": [rec("landed")]})
        self.during.extend([lambda: times.append(self.clock.t)] * 2)
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-1", "x-2"])  # no other bead while the network is down
        self.assertEqual(len(probe.calls), 4)
        self.assertEqual(probe.calls, [self.clock.t0 + 60 * i for i in range(4)])  # a probe a minute while down
        self.assertEqual(sum(1 for c in probe.calls if c < t_up), 3)
        self.assertGreaterEqual(times[1], t_up)
        self.assertLessEqual(times[1] - t_up, 60)  # resumed within 60 s of the probe going up
        self.assertEqual(self.kinds(), ["net_down", "net_up"])
        self.assertNotIn(loop.PAUSE_RETRY, self.clock.naps)
        self.assertIn(60, self.clock.naps)
        self.assertEqual([l["outcome"] for l in self.lines()], ["paused", "landed", "landed"])
        self.assertEqual(self.lines()[1]["trace"], "run-1")

    def test_a_network_pause_keeps_the_label_the_budget_and_every_counter(self):
        self.probe(netgate.FakeProbe([True]))
        # four network pauses in a row: PAUSES_TO_REST (3) would rest the bead an hour; --max-beads would count them
        bd = self.beads({"x-1": [rec("paused", **NET)] * 4 + [rec("landed")]})
        self.assertEqual(self.run_loop("--max-beads", "1"), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1"] * 5)
        self.assertFalse([n for n in self.clock.naps if n >= 3000])
        self.assertEqual(self.kinds(), ["net_down", "net_up"] * 4)
        self.assertFalse([c for c in bd.calls if c[0] == "label" or {"--add-label", "--remove-label", "--set-labels"} & set(c)])  # none stripped or added
        self.assertEqual(loop.read_rests(str(self.repo)), {})  # never rested, never a failed run
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

        def nap(secs, repo=None, until=0):
            polls.append(round(secs))
            self.clock.t += secs
            if len(polls) == 2:
                loop.paths(str(self.repo))["stop"].write_text(json.dumps({"mode": "after", "t": self.clock.t, "targets": []}))
        with mock.patch.object(loop, "nap", nap), mock.patch.object(loop, "stop_mode", side_effect=lambda r: "after" if len(polls) >= 2 else ""):
            self.assertEqual(self.run_loop(), 0)
        self.assertEqual(polls, [60, 60])
        self.assertEqual(loop.last_exit(str(self.repo))["reason"], "stop_request")

    def test_without_a_delegate_to_probe_a_network_pause_rests_like_a_lane_pause_and_the_next_bead_runs(self):
        self.probe(None)
        self.beads({"x-1": [rec("paused", **NET), rec("landed")], "x-2": [rec("landed")]})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2", "x-1"])
        self.assertIn(loop.PAUSE_RETRY, self.clock.naps)
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
            tl.main(["loop", "status", "--repo", str(self.repo)])
        return out.getvalue()

    def test_ready_beads_with_no_loop_alive_and_no_recent_beat_is_one_red_line_naming_repo_and_command(self):
        self.beads({"x-1": [rec("landed")]})
        out = self.status()
        self.assertEqual(out.count("RED:"), 1)
        self.assertIn("%s has 1 ready bead(s) and no loop alive" % self.repo, out)
        self.assertIn("tl loop --repo %s" % self.repo, out)

    def test_a_bead_parked_on_a_dropped_ask_shows_in_status(self):
        f = tl.config_dir() / "asks" / "x-1.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"v": 1, "id": "x-1-2", "bead": "x-1", "status": "open"}))
        self.assertIn("x-1  ", self.status())
        self.assertIn("its ask was dropped at upgrade", self.status())

    def test_a_live_loop_or_a_recent_beat_or_nothing_ready_is_no_warning(self):
        self.beads({"x-1": [rec("landed")]})
        loop.write_state(str(self.repo), pid=os.getpid(), started=self.clock.t)  # this process is alive
        self.assertNotIn("RED:", self.status())
        os.unlink(next(loop.paths(str(self.repo))["states"][0].glob("*.json")))
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
        ex = loop.last_exit(str(self.repo))
        self.assertEqual((ex["reason"], ex["pid"], ex["v"]), ("drained", os.getpid(), 1))
        self.assertTrue(Path(ex["log_path"]).is_file())
        self.assertIn("last exit: drained", self.status())
        self.beads({"x-1": [rec("landed")]})
        self.run_loop("--max-beads", "1")
        self.assertEqual(loop.last_exit(str(self.repo))["reason"], "max_beads")

    def test_a_loop_killed_without_an_exit_line_leaves_its_state_as_died_pid_json(self):
        self.beads({})
        loop.write_state(str(self.repo), pid=999999, started=self.clock.t)
        with mock.patch.object(loop, "pid_alive", return_value=False):
            self.assertEqual(loop.live_loops(str(self.repo)), [])
        died = loop.paths(str(self.repo))["runs"] / "died-999999.json"
        self.assertEqual(json.loads(died.read_text())["pid"], 999999)

    def test_the_loops_own_log_keeps_what_it_said_and_is_pruned_to_five(self):
        runs = loop.paths(str(self.repo))["runs"]
        runs.mkdir()
        for i in range(8):
            f = runs / ("loop-%d.log" % (100 + i))
            f.write_text("old")
            os.utime(f, (1000 + i, 1000 + i))
        self.beads({"x-1": [rec("landed")]})
        self.run_loop()
        log = runs / ("loop-%d.log" % os.getpid())
        self.assertIn("x-1 in s1", log.read_text())
        self.assertEqual(len(list(runs.glob("loop-*.log"))), loop.LOGS_KEPT)
        self.assertIn("loop-107.log", [f.name for f in runs.glob("loop-*.log")])  # the newest old ones stay
        self.assertNotIn("loop-100.log", [f.name for f in runs.glob("loop-*.log")])

    def test_the_beat_is_refreshed_while_a_bead_runs_at_most_once_a_minute(self):
        st_beats = []
        real = loop.write_state
        with mock.patch.object(loop, "write_state", side_effect=lambda repo, **kw: st_beats.append(kw.get("beat")) or real(repo, **kw)):
            self.beads({"x-1": [rec("landed")]})
            self.hold["x-1"] = 100
            self.run_loop()
        refreshed = [b for b in st_beats if b]
        self.assertGreaterEqual(len(refreshed), 2)
        self.assertTrue(all(b2 - b1 >= loop.BEAT_EVERY for b1, b2 in zip(refreshed, refreshed[1:])))


class StopRequests(LoopBase):
    def setUp(self):
        super().setUp()
        self.repo_s = str(self.repo)
        self.old_pid = 900001
        self.addCleanup(loop.STOP_NOW.clear)
        loop.STOP_NOW.clear()
        patch = mock.patch.object(loop, "pid_alive", side_effect=lambda pid: pid in (os.getpid(), self.old_pid))
        patch.start()
        self.addCleanup(patch.stop)

    def old_loop(self, started=None):
        loop.write_state(self.repo_s, pid=self.old_pid, started=self.clock.t if started is None else started)

    def stop(self, now=False):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(tl.main(["stop", "--repo", self.repo_s] + (["--now"] if now else [])), 0)
        return json.loads(loop.paths(self.repo_s)["stop"].read_text())

    def test_stop_file_names_running_loops(self):
        self.old_loop()
        loop.write_state(self.repo_s, pid=os.getpid(), started=self.clock.t)
        for now in (False, True):
            with self.subTest(now=now):
                request = self.stop(now)
                self.assertEqual(set(request["targets"]), {self.old_pid, os.getpid()})
                self.assertEqual(request["mode"], "now" if now else "after")
                self.assertEqual(request["time"], self.clock.t)

    def test_a_stop_applies_to_the_loops_it_names_only(self):
        self.old_loop()
        for now in (False, True):
            mode = "now" if now else "after"
            request = self.stop(now)
            self.assertEqual(loop.stop_for(request, self.old_pid), mode)
            self.assertEqual(loop.stop_for(request, os.getpid()), "")
        with mock.patch.object(loop.STOP_NOW, "is_set", return_value=True):
            self.assertEqual(loop.stop_mode(self.repo_s), "now")

    def test_a_stop_file_that_is_not_a_targeted_request_is_ignored(self):
        f = loop.paths(self.repo_s)["stop"]
        for text in ("", "after", "now", json.dumps({"mode": "after", "time": 1})):
            f.write_text(text)
            self.assertEqual(loop.read_stop(self.repo_s), {}, text)

    def test_a_stop_does_not_stop_a_loop_started_after_it(self):
        self.old_loop()
        self.stop()
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        self.during.append(lambda: self.assertEqual(loop.stop_mode(self.repo_s), ""))
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2"])
        self.assertEqual(loop.stop_for(loop.read_stop(self.repo_s), self.old_pid), "after")

    def test_start_clears_a_stop_that_names_no_running_loop(self):
        for other in (False, True):
            with self.subTest(other=other):
                self.beads({"x-1": [rec("landed")]})
                if other:
                    self.old_loop()
                f = loop.paths(self.repo_s)["stop"]
                f.write_text(json.dumps({"mode": "after", "targets": [12345], "time": self.clock.t - 10}))
                self.during.append(lambda: self.assertFalse(f.exists()))
                self.assertEqual(self.run_loop(), 0)

    def test_cleanup_preserves_live_targets_and_concurrent_stop(self):
        self.check_cleanup_preserves_live_targets_and_concurrent_stop()

    def check_cleanup_preserves_live_targets_and_concurrent_stop(self):
        import threading
        self.old_loop(self.clock.t - 100)
        self.stop()
        with loop.stop_lock(self.repo_s):
            loop.clean_stop(self.repo_s, loop.live_loops(self.repo_s))
            self.assertTrue(loop.paths(self.repo_s)["stop"].exists())
        # A stop concurrent with startup cleanup must capture the newly registered loop.
        attempted, finished = threading.Event(), threading.Event()
        errors = []

        def stop():
            attempted.set()
            try:
                loop.cmd_stop(mock.Mock(repo=self.repo_s, now=True))
            except Exception as e:
                errors.append(e)
            finally:
                finished.set()

        with redirect_stdout(io.StringIO()):
            with loop.stop_lock(self.repo_s):
                thread = threading.Thread(target=stop)
                thread.start()
                self.assertTrue(attempted.wait(2))
                self.assertFalse(finished.wait(0.05))
                loop.write_state(self.repo_s, pid=os.getpid(), started=self.clock.t)
                loop.clean_stop(self.repo_s, loop.live_loops(self.repo_s))
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        request = loop.read_stop(self.repo_s)
        self.assertEqual(set(request["targets"]), {self.old_pid, os.getpid()})
        with loop.stop_lock(self.repo_s):
            loop.paths(self.repo_s)["state"].unlink()
            loop.clean_stop(self.repo_s, loop.live_loops(self.repo_s))
        self.assertEqual(loop.stop_for(loop.read_stop(self.repo_s), self.old_pid), "now")

    def test_inherited_loop_keeps_targeted_stop(self):
        self.beads({"x-1": [rec("landed")]})
        started = self.clock.t - 100
        loop.write_state(self.repo_s, pid=os.getpid(), started=started)
        self.stop()
        with mock.patch.dict(os.environ, {"TL_LOOP_STATE": json.dumps({"started": started})}):
            self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.started, [])


class Moved(Exception):
    """What the mocked os.execv raises: the real one never returns."""


class LoopSelfUpdate(LoopBase):
    """Between beads the loop re-execs into the newest complete install of the plugin (fake version trees)."""

    def setUp(self):
        super().setUp()
        self.cache = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cache, True)
        self.execs = []

        def execv(exe, argv):
            self.execs.append((exe, argv, os.environ.get("TL_LOOP_STATE"), os.getcwd()))
            raise Moved()
        for p in (mock.patch.object(os, "execv", side_effect=execv),
                  mock.patch.dict(os.environ, {}), mock.patch.object(tl, "HERE", self.install("0.1.0"))):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop("TL_LOOP_STATE", None)

    def install(self, ver, tl_py="import sys\n", missing=(), loop_py=""):
        d = self.cache / ver / "skills" / "task-loop"
        d.mkdir(parents=True)
        (d.parents[1] / ".claude-plugin").mkdir()
        (d.parents[1] / ".claude-plugin" / "plugin.json").write_text("{}")
        for f in ("tl.py", "loop.py", "engine.py"):
            if f not in missing:
                (d / f).write_text(tl_py if f == "tl.py" else loop_py if f == "loop.py" else "")
        return d

    def test_it_moves_to_a_newer_complete_install_between_beads_with_the_same_argv(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        self.during.append(lambda: self.install("0.2.0"))
        with self.assertRaises(Moved):
            self.run_loop("--max-beads", "5")
        self.assertEqual([b for b, _ in self.started], ["x-1"])  # never mid-bead: x-1 ran to its end on 0.1.0
        self.assertEqual([l["outcome"] for l in self.lines()], ["landed"])
        exe, argv, state, _ = self.execs[0]
        self.assertEqual(exe, sys.executable)
        self.assertEqual(argv[:2], [sys.executable, str(self.cache / "0.2.0" / "skills" / "task-loop" / "tl.py")])
        self.assertEqual(argv[2:], ["loop", "--repo", str(self.repo), "--max-beads", "5"])
        self.assertEqual(json.loads(state)["ran"], 1)

    def test_the_move_is_logged_and_the_newest_of_several_wins(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.2.0")
        self.install("0.10.0")  # 0.10 is newer than 0.9: numbers, not text
        self.install("0.9.0")
        with self.assertRaises(Moved), redirect_stdout(io.StringIO()) as out:
            tl.main(["loop", "--repo", str(self.repo)])
        self.assertIn("loop: moving to 0.10.0 (was 0.1.0)", out.getvalue())
        self.assertIn("0.10.0", self.execs[0][1][1])
        self.assertEqual(self.started, [])  # the first look is before any bead

    def test_an_incomplete_or_failing_install_is_ignored_and_warned_once_per_version(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        self.install("0.2.0", missing=("engine.py",))
        self.install("0.3.0", tl_py="raise SystemExit(3)\n")
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.execs, [])
        self.assertEqual([b for b, _ in self.started], ["x-1", "x-2"])
        self.assertEqual(self.out.count("not moving to 0.3.0"), 1)  # three looks, one warn (and one check)
        self.assertEqual(self.out.count("not moving to 0.2.0"), 1)  # once 0.3.0 failed, 0.2.0 is the newest left

    def test_an_incomplete_newest_warns_once(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        self.install("0.2.0", missing=("engine.py",))
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.out.count("not moving to 0.2.0: engine.py is missing"), 1)

    def test_a_half_copied_loop_py_is_not_moved_to(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.2.0", loop_py="def broken(:\n")  # --help alone would pass; the import does not
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.execs, [])
        self.assertIn("not moving to 0.2.0", self.out)

    def test_an_install_without_plugin_json_is_not_moved_to(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.2.0")
        (self.cache / "0.2.0" / ".claude-plugin" / "plugin.json").unlink()
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.execs, [])
        self.assertIn("plugin.json is missing", self.out)

    def pin(self, **v):
        (tl.config_dir() / "pinned.json").write_text(json.dumps(v))

    def test_a_pin_beats_the_newest_install(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.2.0")
        self.install("0.3.0")
        self.pin(**{"task-loop": "0.2.0"})
        with self.assertRaises(Moved):
            self.run_loop()
        self.assertEqual(self.execs[0][1][1], str(self.cache / "0.2.0" / "skills" / "task-loop" / "tl.py"))

    def test_a_pin_to_an_older_install_moves_the_loop_back(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.0.5")
        self.install("0.2.0")
        self.pin(**{"task-loop": "0.0.5"})
        with self.assertRaises(Moved):
            self.run_loop()
        self.assertIn("0.0.5", self.execs[0][1][1])

    def test_a_pin_to_an_install_from_before_pins_execs_it_with_pin_so_it_stays(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.0.5", loop_py="# an old loop: no pin reader\n")
        self.install("0.2.0")
        self.pin(**{"task-loop": "0.0.5"})
        with self.assertRaises(Moved):
            self.run_loop()
        self.assertEqual(self.execs[0][1].count("--pin"), 1)

    def test_a_pin_to_a_pin_aware_install_is_not_given_pin(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.0.5", loop_py="# reads read_pin\n")
        self.pin(**{"task-loop": "0.0.5"})
        with self.assertRaises(Moved):
            self.run_loop()
        self.assertNotIn("--pin", self.execs[0][1])

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
        self.assertFalse((tl.config_dir() / "pinned.json").exists())
        self.pin(**{"task-loop": "0.1.0"})
        before = (tl.config_dir() / "pinned.json").read_bytes()
        self.beads({"x-3": [rec("landed")]})
        self.run_loop()
        self.assertEqual((tl.config_dir() / "pinned.json").read_bytes(), before)
        src = Path(loop.__file__).read_text(encoding="utf-8")
        self.assertNotIn("write_pin", src)
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
                    tl.main(["loop", "--repo", self.repo.name])
            finally:
                os.chdir(old)
        self.assertEqual(os.path.realpath(self.execs[0][3]), os.path.realpath(start))
        self.assertIn(self.repo.name, self.execs[0][1])

    def test_a_stop_written_during_the_check_cancels_the_move(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.2.0")

        def slow_check(d):
            self.assertEqual(tl.main(["stop", "--repo", str(self.repo)]), 0)
        with mock.patch.object(loop, "complete", side_effect=slow_check):
            self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.execs, [])
        self.assertEqual(self.started, [])
        self.assertIn("stopped on request", self.out)

    def test_a_bad_state_field_is_dropped_with_a_warning(self):
        self.beads({"x-1": [rec("landed")]})
        os.environ["TL_LOOP_STATE"] = json.dumps({"ran": "many", "fails": ["x-0"], "later": [1]})
        self.assertEqual(self.run_loop(), 0)
        self.assertIn("'ran' has a bad value", self.out)
        self.assertIn("'later' has a bad value", self.out)
        self.assertNotIn("'fails'", self.out)

    def test_a_help_that_hangs_is_not_moved_to(self):
        self.beads({"x-1": [rec("landed")]})
        self.install("0.2.0", tl_py="import time\ntime.sleep(60)\n")
        with mock.patch.object(loop, "HELP_WAIT", 0.5):
            self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.execs, [])
        self.assertIn("did not finish", self.out)

    def test_the_failure_counter_and_the_actor_survive_the_move(self):
        self.beads({"x-1": [rec("failed")], "x-2": [rec("failed")], "x-3": [rec("landed")]})
        self.during.append(lambda: self.install("0.2.0"))
        with self.assertRaises(Moved):
            self.run_loop()
        actor = os.environ["TASK_LOOP_ACTOR"]
        state = json.loads(self.execs[0][2])
        self.assertEqual(state["fails"], ["x-1"])
        # the new process: same pid, the state in the environment, the new install as the running code
        os.environ["TL_LOOP_STATE"] = self.execs[0][2]
        with mock.patch.object(tl, "HERE", self.cache / "0.2.0" / "skills" / "task-loop"):
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
        with mock.patch.object(tl, "HERE", self.cache / "0.2.0" / "skills" / "task-loop"):
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
        with mock.patch.object(tl, "HERE", dev):
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
        self.assertTrue(loop.landed_on_base(str(self.repo), str(wt), "x-1"))
        self.assertFalse(loop.landed_on_base(str(self.repo), str(wt), "x-2"))  # work not on main
        self.assertFalse(loop.landed_on_base(str(self.repo), str(wt), "x-3"))  # no work: the tip is someone else's
        self.assertFalse(loop.landed_on_base(str(self.repo), str(wt), "x-9"))  # no branch


@unittest.skipIf(os.name == "nt", "POSIX signals")
class LoopStopNow(Base):
    """A real child: --now reaches it as SIGTERM, which it traps to write its outcome (as the engine's close does)."""
    CHILD = (
        "import json, signal, sys, time\n"
        "out = sys.argv[sys.argv.index('--outcome-file') + 1]\n"
        "def stop(*_):\n"
        "    open(out, 'w').write(json.dumps({'outcome': 'failed', 'why': 'failed: stopped (SIGTERM)'}))\n"
        "    sys.exit(2)\n"
        "signal.signal(signal.SIGTERM, stop)\n"
        "print('running', flush=True)\n"
        "time.sleep(60)\n")

    def test_stop_now_sigterms_a_real_child(self):
        self.check_stop_now_sigterms_a_real_child()

    def check_stop_now_sigterms_a_real_child(self):
        script = self.home / "child.py"
        script.write_text(self.CHILD)
        self.config()
        bd = self.fake(bead("x-1"))
        real = loop.spawn
        threads = []

        def spawn(cmd, log):
            p = real([sys.executable, str(script)] + cmd[2:], log)
            import threading
            t = threading.Timer(1.0, lambda: loop.cmd_stop(mock.Mock(repo=str(self.repo), now=True)))
            t.start()
            threads.append(t)
            return p
        with mock.patch.object(loop, "spawn", spawn), mock.patch.object(loop, "prepare", return_value=(0, "")), \
                mock.patch.object(tl, "start_worktree", return_value=str(self.home)), redirect_stdout(io.StringIO()):
            t0 = time.time()
            self.assertEqual(tl.main(["loop", "--repo", str(self.repo)]), 0)
        self.assertLess(time.time() - t0, 30)
        self.assertEqual(bd.beads["x-1"]["status"], "open")
        line = json.loads(loop.paths(str(self.repo))["log"].read_text().splitlines()[0])
        self.assertEqual(line["outcome"], "failed")
        self.assertIn("running", Path(line["run_log"]).read_text())


if __name__ == "__main__":
    unittest.main()
