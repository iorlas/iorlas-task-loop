"""Loop tests, part 2: network, health, stop requests, self-update. Split from test_loop."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401

# isort: split

from support import (  # noqa: E402
    looptest,
)

from loop.test_loop import LoopBase  # noqa: E402
from taskloop.adapters import (  # noqa: E402
    ident,
)

NET = {"kind": "pause_network", "why": "paused: network on write; resume when it is back"}


class LoopHealth(LoopBase):
    """tl-7y6.2.12: a loop that exits says why; a repo with ready beads and no loop alive is a red line; the log outlives the session."""

    def status(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.main(["loop", "status", "--repo", str(self.repo)])
        return out.getvalue()


    def test_a_loop_killed_without_an_exit_line_leaves_its_state_as_died_pid_json(self):
        self.beads({})
        looptest.write_state(str(self.repo), pid=999999, started=self.clock.t)
        self.assertEqual(looptest.live(str(self.repo)), [])  # no such process
        died = looptest.files(str(self.repo)).runs() / "died-999999.json"
        self.assertEqual(json.loads(died.read_text())["pid"], 999999)


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


    def test_a_command_that_is_not_a_command_is_ignored(self):
        f = looptest.command(self.repo_s)
        f.parent.mkdir(parents=True, exist_ok=True)
        for text in ("", "after", json.dumps({"mode": "after", "time": 1}), json.dumps({"v": 2, "action": "stop_now"})):
            f.write_text(text)
            self.assertEqual(self.files.stop_for(self.old_pid, self.clock.t), "", text)


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


    def pin(self, **v):
        (ident.config_dir() / "pinned.json").write_text(json.dumps(v))


if __name__ == "__main__":
    unittest.main()
