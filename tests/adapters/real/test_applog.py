"""tl-64i: log files held open. One handle per path per process, every line readable at once, closed at run end and on exec."""
import os
import tempfile
import unittest
import warnings
from pathlib import Path

import support.paths  # noqa: F401  (ROOT/src on sys.path)

from taskloop.adapters import (
    applog,
)

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


if __name__ == "__main__":
    unittest.main()
