"""tl-64i: log files held open. One handle per path per process, every line readable at once, closed at run end and on exec."""
import json
import os
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401  (ROOT/src on sys.path)

from taskloop.adapters import (
    applog,
    ident,
)
from taskloop.app.track import trail

warnings.filterwarnings("ignore", message=".*multi-threaded.*fork", category=DeprecationWarning)


class AppLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "run.jsonl"
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(applog.close_all)


    @unittest.skipIf(os.name == "nt", "fork and exec fd semantics")
    def test_a_handle_does_not_survive_an_exec(self):
        applog.append(self.path, "x\n")
        fd = applog._open[str(self.path)][1].fileno()
        code = f"test -e /dev/fd/{fd} && exit 1; exit 0"  # a shell, not an interpreter: it is the fd table that is looked at
        # a child started the way os.execv does: the fd table survives only for inheritable descriptors
        pid = os.fork()
        if pid == 0:
            try:
                os.execv("/bin/sh", ["sh", "-c", code])
            finally:
                os._exit(9)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.WEXITSTATUS(status), 0)

    @unittest.skipIf(os.name == "nt", "fork semantics")
    def test_a_forked_child_opens_its_own_handle(self):
        applog.append(self.path, "parent\n")
        pid = os.fork()
        if pid == 0:
            try:
                applog.append(self.path, "child\n")
                os._exit(0 if applog.open_count(self.path) == 1 else 3)
            except BaseException:
                os._exit(4)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.WEXITSTATUS(status), 0)
        applog.append(self.path, "parent2\n")
        self.assertEqual(self.path.read_text().split(), ["parent", "child", "parent2"])


class WiringTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(applog.close_all)
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(Path(self.tmp.name) / "cfg"),
                                           "APPDATA": str(Path(self.tmp.name) / "cfg")})
        env.start()
        self.addCleanup(env.stop)

    def test_tl_event_keeps_one_handle_for_events_jsonl_and_flushes_each_line(self):
        path = ident.config_dir() / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        trail.event("a", "b-1")
        with open(path, encoding="utf-8") as reader:
            self.assertEqual(json.loads(reader.readline())["kind"], "a")
            for i in range(100):
                trail.event("n", "b-1", i=i)
                self.assertEqual(json.loads(reader.readline())["i"], i)
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 101)
        self.assertEqual(applog.open_count(path), 1)


if __name__ == "__main__":
    unittest.main()
