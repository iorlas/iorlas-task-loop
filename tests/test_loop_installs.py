"""Which install a loop moves to (O2): the one installed_plugins.json names, never a directory that merely exists; and a loop
that breaks soon after a move goes back to the install it came from, once, in red."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from test_loop import LoopBase, rec

# isort: split
import loop_env
import test_loop_more as more
from support import (
    eventlog,
    looptest,
)

from taskloop.adapters import ident
from taskloop.app.loop.loop import Loop
from taskloop.app.run import (
    console,
    )
from taskloop.contracts import codec
from taskloop.contracts.loop import Carry, LoopState


class Moving(LoopBase):
    """The fake version trees of test_loop_more.LoopSelfUpdate, without its tests."""

    def install(self, ver, **kw):
        return looptest.fake_install(self.cache, ver, **kw)

    def setUp(self):
        super().setUp()
        self.cache = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cache, True)
        self.execs = []

        def execv(exe, argv):
            self.execs.append((exe, argv, os.environ.get("TL_LOOP_STATE"), os.getcwd()))
            raise more.Moved()
        for p in (mock.patch.object(os, "execv", side_effect=execv),
                  mock.patch.dict(os.environ, {})):
            p.start()
            self.addCleanup(p.stop)
        self.here = self.install("0.1.0")
        os.environ.pop("TL_LOOP_STATE", None)


class Entry(Moving):
    def installed(self, version):
        """installed_plugins.json (user scope) names `version` for task-loop."""
        f = ident.claude_dir() / "plugins" / "installed_plugins.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"plugins": {"iorlas-task-loop@iorlas-marketplace": [
            {"scope": "user", "installPath": str(self.cache / version)}]}}))

    def target(self):
        return loop_env.installs(loop_env.cfgdir(), here=self.here).target()

    def test_the_installed_entry_decides_not_the_highest_directory(self):
        self.install("0.2.0")
        self.install("0.99.0")  # a directory the plugin manager never installed
        self.installed("0.2.0")
        self.assertEqual(self.target(), ("0.2.0", self.cache / "0.2.0"))
        self.beads({"x-1": [rec("landed")]})
        with self.assertRaises(more.Moved):
            self.run_loop()
        self.assertEqual(self.execs[0][1][1], str(self.cache / "0.2.0" / "skills" / "task-loop" / "tl.py"))

    def test_a_directory_that_is_not_installed_is_ignored_when_the_loop_runs_what_is_installed(self):
        self.install("0.99.0")
        self.installed("0.1.0")
        self.assertIsNone(self.target())
        self.beads({"x-1": [rec("landed")]})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.execs, [])

    def test_an_entry_whose_directory_is_gone_falls_through_with_one_warning_per_run_and_a_pin_never_does(self):
        self.install("0.3.0")
        self.installed("0.2.0")  # recorded, but its directory is not there
        inst = loop_env.installs(loop_env.cfgdir(), here=self.here)
        self.assertEqual(inst.target(), ("0.3.0", self.cache / "0.3.0"))
        self.assertEqual(inst.dangling, "0.2.0")
        (ident.config_dir() / "pinned.json").write_text(json.dumps({"task-loop": "0.3.0"}))
        inst.target()
        self.assertEqual(inst.dangling, "")  # a pin is strict: nothing fell through
        os.unlink(ident.config_dir() / "pinned.json")
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        with self.assertRaises(more.Moved):
            self.run_loop()
        self.assertEqual([e["version"] for e in eventlog.read() if e["kind"] == "install_missing"], ["0.2.0"])

    def test_the_missing_entry_warning_is_not_repeated_on_the_next_pass(self):
        self.installed("0.2.0")  # no such directory, and nothing higher to fall to
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([e["version"] for e in eventlog.read() if e["kind"] == "install_missing"], ["0.2.0"])

    def test_with_no_entry_the_highest_directory_above_the_running_one_is_the_fallback(self):
        self.install("0.2.0")
        self.install("0.3.0")
        self.assertEqual(self.target(), ("0.3.0", self.cache / "0.3.0"))

    def test_a_pin_still_beats_the_entry(self):
        self.install("0.2.0")
        self.install("0.3.0")
        self.installed("0.3.0")
        (ident.config_dir() / "pinned.json").write_text(json.dumps({"task-loop": "0.2.0"}))
        self.assertEqual(self.target(), ("0.2.0", self.cache / "0.2.0"))


class Fallback(Moving):
    """The loop on 0.2.0, moved there from 0.1.0 five seconds ago, whose logic breaks."""

    def setUp(self):
        super().setUp()
        self.said = []
        self.enterContext(mock.patch.object(console, "say", side_effect=self.said.append))
        self.back = self.cache / "0.1.0"
        self.here = self.install("0.2.0")  # this loop runs the new dir
        self.beads({"x-1": [rec("landed")]})
        carry = Carry(back=str(self.back), moved_at=self.clock.t - 5)
        st = LoopState(pid=1, started=1.0, t=1.0, repo=str(self.repo), version="0.1.0", code_dir=str(self.back), actor="tl-a", carry=carry)
        os.environ["TL_LOOP_STATE"] = json.dumps(codec.to_json(st))
        p = mock.patch.object(Loop, "step", side_effect=RuntimeError("logic broken in the new dir"))
        p.start()
        self.addCleanup(p.stop)

    def test_a_loop_that_breaks_soon_after_a_move_goes_back_once_and_says_red(self):
        with self.assertRaises(more.Moved):
            self.run_loop()
        self.assertEqual(self.execs[0][1][1], str(self.back / "skills" / "task-loop" / "tl.py"))
        self.assertTrue(json.loads(self.execs[0][2])["carry"]["fallback"])
        self.assertTrue([x for x in self.said if "RED: task-loop 0.2.0 broke" in x and "back to 0.1.0" in x], self.said)
        events = [e for e in eventlog.read() if e["kind"] == "reload_fallback"]
        self.assertEqual((len(events), events[0]["old"], events[0]["new"]), (1, "0.2.0", "0.1.0"))
        self.assertIn("logic broken", events[0]["why"])
        bad = json.loads((ident.config_dir() / "bad-versions.json").read_text())["entries"]
        self.assertEqual([e["version"] for e in bad], ["0.2.0"])

    def test_a_loop_that_already_went_back_is_not_sent_again(self):
        st = json.loads(os.environ["TL_LOOP_STATE"])
        st["carry"]["fallback"] = True
        os.environ["TL_LOOP_STATE"] = json.dumps(st)
        with self.assertRaises(RuntimeError):
            self.run_loop()
        self.assertEqual(self.execs, [])

    def test_a_break_long_after_the_move_is_no_fallback(self):
        st = json.loads(os.environ["TL_LOOP_STATE"])
        st["carry"]["moved_at"] = self.clock.t - 3600
        os.environ["TL_LOOP_STATE"] = json.dumps(st)
        with self.assertRaises(RuntimeError):
            self.run_loop()
        self.assertEqual(self.execs, [])


if __name__ == "__main__":
    unittest.main()
