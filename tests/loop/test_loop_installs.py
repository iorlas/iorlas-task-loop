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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import homes

from loop.test_loop import LoopBase
from taskloop.contracts.env import snapshot

# isort: split
from support import (
    looptest,
)
from support.narrow import must

import loop.test_loop_more as more
from taskloop.app.launch import loop as wloop


class Moving(LoopBase):
    """The fake version trees of test_loop_more.LoopSelfUpdate, without its tests."""

    def install(self, ver, **kw):
        return looptest.fake_install(self.cache, ver, **kw)

    def setUp(self):
        super().setUp()
        self.cache = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cache, True)
        self.execs = []

        def execv(exe, argv, env):
            self.execs.append((exe, argv, env.get("TL_LOOP_STATE"), os.getcwd(), env.get("TASK_LOOP_ACTOR")))
            raise more.Moved()
        for p in (mock.patch.object(os, "execve", side_effect=execv),
                  mock.patch.dict(os.environ, {})):
            p.start()
            self.addCleanup(p.stop)
        self.here = self.install("0.1.0")
        os.environ.pop("TL_LOOP_STATE", None)


class Entry(Moving):
    def installed(self, version):
        """installed_plugins.json (user scope) names `version` for task-loop."""
        f = homes.claude_dir() / "plugins" / "installed_plugins.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"plugins": {"iorlas-task-loop@iorlas-marketplace": [
            {"scope": "user", "installPath": str(self.cache / version)}]}}))

    def target(self):
        return wloop.installs(homes.cfg(), snapshot(), here=must(self.here)).target()


    def test_with_no_entry_the_highest_directory_above_the_running_one_is_the_fallback(self):
        self.install("0.2.0")
        self.install("0.3.0")
        self.assertEqual(self.target(), ("0.3.0", self.cache / "0.3.0"))

    def test_a_pin_still_beats_the_entry(self):
        self.install("0.2.0")
        self.install("0.3.0")
        self.installed("0.3.0")
        (homes.config_dir() / "pinned.json").write_text(json.dumps({"v": 1, "task-loop": "0.2.0"}))
        self.assertEqual(self.target(), ("0.2.0", self.cache / "0.2.0"))


if __name__ == "__main__":
    unittest.main()
