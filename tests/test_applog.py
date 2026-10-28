"""tl-64i: log files held open. One handle per path per process, every line readable at once, closed at run end and on exec."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "task-loop"))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from taskloop.adapters import applog  # noqa: E402
from taskloop.app.track import trail  # noqa: E402
from taskloop.app.release import reexec  # noqa: E402
import engine  # noqa: E402
from support.builders import cfg_with  # noqa: E402
from taskloop.adapters import ident


warnings.filterwarnings("ignore", message=".*multi-threaded.*fork", category=DeprecationWarning)


class AppLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "run.jsonl"
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(applog.close_all)

    def test_a_tailing_reader_sees_every_line_at_once(self):
        self.path.write_text("")
        with open(self.path, encoding="utf-8") as reader:  # opened first, like a dashboard tailing the file
            for i in range(50):
                applog.append(self.path, json.dumps({"i": i, "text": "ü %d" % i}, ensure_ascii=False) + "\n")
                self.assertEqual(json.loads(reader.readline())["i"], i)
                self.assertEqual(reader.readline(), "")

    def test_one_handle_per_path_across_1000_writes(self):
        other = Path(self.tmp.name) / "other.jsonl"
        real_open = open
        opened = []

        def counting(file, *a, **kw):
            opened.append(str(file))
            return real_open(file, *a, **kw)
        with mock.patch("builtins.open", counting):
            for i in range(1000):
                applog.append(self.path, "%d\n" % i)
                if i % 100 == 0:
                    applog.append(other, "%d\n" % i)
        self.assertEqual(opened.count(str(self.path)), 1)
        self.assertEqual(opened.count(str(other)), 1)
        self.assertEqual((applog.open_count(self.path), applog.open_count(other)), (1, 1))
        self.assertEqual(len(self.path.read_text().splitlines()), 1000)

    def test_close_releases_the_handle_and_a_later_append_reopens_without_losing_lines(self):
        applog.append(self.path, "a\n")
        applog.close(self.path)
        self.assertEqual(applog.open_count(self.path), 0)
        applog.append(self.path, "b\n")
        applog.close_all()
        self.assertEqual(applog.open_count(), 0)
        self.assertEqual(self.path.read_text(), "a\nb\n")

    def test_a_removed_or_replaced_file_is_opened_afresh(self):
        applog.append(self.path, "old\n")
        self.path.unlink()
        applog.append(self.path, "new\n")
        self.assertEqual(self.path.read_text(), "new\n")

    def test_the_handle_is_not_inheritable_and_the_cache_is_bounded(self):
        applog.append(self.path, "x\n")
        self.assertFalse(os.get_inheritable(applog._open[str(self.path)][1].fileno()))
        for i in range(applog.MAX_OPEN + 5):
            applog.append(Path(self.tmp.name) / ("f%d" % i), "x\n")
        self.assertLessEqual(applog.open_count(), applog.MAX_OPEN)

    @unittest.skipIf(os.name == "nt", "fork and exec fd semantics")
    def test_a_handle_does_not_survive_an_exec(self):
        applog.append(self.path, "x\n")
        fd = applog._open[str(self.path)][1].fileno()
        code = "import os,sys\ntry:\n os.fstat(%d)\nexcept OSError:\n sys.exit(0)\nsys.exit(1)" % fd
        # a child started the way os.execv does: the fd table survives only for inheritable descriptors
        pid = os.fork()
        if pid == 0:
            try:
                os.execv(sys.executable, [sys.executable, "-c", code])
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

    def test_engine_log_is_one_typed_line_per_record_readable_at_once(self):
        eng = engine.Engine("t-1", self.tmp.name, cfg_with())
        with mock.patch.object(engine, "say"):
            for i in range(1000):
                eng.log.note("line %d" % i)
            lines = eng.log_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(x)["text"] for x in lines][-2:], ["line 998", "line 999"])
        self.assertEqual(len(lines), 1000)
        self.assertEqual(applog.open_count(eng.log_path), 0)  # a record opens, appends and closes: no handle outlives the run

    def test_exec_in_place_closes_every_handle_first(self):
        applog.append(Path(self.tmp.name) / "x.log", "x\n")
        with mock.patch.object(engine.os, "execv", side_effect=lambda *a: self.assertEqual(applog.open_count(), 0)):
            reexec.exec_in_place(["x"])


if __name__ == "__main__":
    unittest.main()
