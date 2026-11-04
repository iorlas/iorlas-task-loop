"""tl-64i: log files held open. One handle per path per process, every line readable at once, closed at run end and on exec."""
import json
import os
import tempfile
import warnings
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import homes
from support.builders import cfg_with
from support.case import Case
from support.fakegit import FakeGit
from support.spawn import real_spawner
from support.who import who

from taskloop.adapters import (
    applog,
)
from taskloop.app.release import reexec
from taskloop.app.run import engine
from taskloop.app.track import trail
from taskloop.contracts.env import snapshot
from taskloop.contracts.ids import BeadId

warnings.filterwarnings("ignore", message=".*multi-threaded.*fork", category=DeprecationWarning)


class AppLogTest(Case):
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "run.jsonl"
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(applog.close_all)

    def test_a_tailing_reader_sees_every_line_at_once(self):
        self.path.write_text("")
        with open(self.path, encoding="utf-8") as reader:  # opened first, like a dashboard tailing the file
            for i in range(50):
                applog.append(self.path, json.dumps({"i": i, "text": f"ü {i}"}, ensure_ascii=False) + "\n")
                assert json.loads(reader.readline())["i"] == i
                assert reader.readline() == ""

    def test_one_handle_per_path_across_1000_writes(self):
        other = Path(self.tmp.name) / "other.jsonl"
        real_open = open
        opened = []

        def counting(file, *a, **kw):
            opened.append(str(file))
            return real_open(file, *a, **kw)
        with mock.patch("builtins.open", counting):
            for i in range(1000):
                applog.append(self.path, f"{i}\n")
                if i % 100 == 0:
                    applog.append(other, f"{i}\n")
        assert opened.count(str(self.path)) == 1
        assert opened.count(str(other)) == 1
        assert (applog.open_count(self.path), applog.open_count(other)) == (1, 1)
        assert len(self.path.read_text().splitlines()) == 1000

    def test_close_releases_the_handle_and_a_later_append_reopens_without_losing_lines(self):
        applog.append(self.path, "a\n")
        applog.close(self.path)
        assert applog.open_count(self.path) == 0
        applog.append(self.path, "b\n")
        applog.close_all()
        assert applog.open_count() == 0
        assert self.path.read_text() == "a\nb\n"

    def test_a_removed_or_replaced_file_is_opened_afresh(self):
        applog.append(self.path, "old\n")
        self.path.unlink()
        applog.append(self.path, "new\n")
        assert self.path.read_text() == "new\n"

    def test_the_handle_is_not_inheritable_and_the_cache_is_bounded(self):
        applog.append(self.path, "x\n")
        assert not os.get_inheritable(applog._open[str(self.path)][1].fileno())
        for i in range(applog.MAX_OPEN + 5):
            applog.append(Path(self.tmp.name) / (f"f{i}"), "x\n")
        assert applog.open_count() <= applog.MAX_OPEN


class WiringTest(Case):
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(applog.close_all)
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(Path(self.tmp.name) / "cfg"),
                                           "APPDATA": str(Path(self.tmp.name) / "cfg"),
                                           "TASK_LOOP_ACTOR": "tl-test"})  # the actor is named: git is not asked for one
        env.start()
        self.addCleanup(env.stop)

    def test_engine_log_is_one_typed_line_per_record_readable_at_once(self):
        eng = engine.Engine(BeadId("t-1"), self.tmp.name, cfg_with(), env=snapshot(), spawner=real_spawner(), git=FakeGit(), who=who())
        with mock.patch.object(engine, "say"):
            for i in range(1000):
                eng.log.note(f"line {i}")
            lines = eng.log_path.read_text(encoding="utf-8").splitlines()
        assert [json.loads(x)["text"] for x in lines][-2:] == ["line 998", "line 999"]
        assert len(lines) == 1000
        assert applog.open_count(eng.log_path) == 0  # a record opens, appends and closes: no handle outlives the run

    def test_exec_in_place_closes_every_handle_first(self):
        applog.append(Path(self.tmp.name) / "x.log", "x\n")
        def execve(*_):
            assert applog.open_count() == 0
        with mock.patch.object(os, "execve", side_effect=execve):
            reexec.exec_in_place(["x"], {})

    def test_tl_event_keeps_one_handle_for_events_jsonl_and_flushes_each_line(self):
        path = homes.config_dir() / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        trail.event(who(), "stage", "b-1", repo=self.tmp.name)  # a given repo: no git to ask (its answer is memoized by earlier tests)
        with open(path, encoding="utf-8") as reader:
            assert json.loads(reader.readline())["kind"] == "stage"
            for i in range(100):
                trail.event(who(), "stage", "b-1", repo=self.tmp.name, text=str(i))
                assert json.loads(reader.readline())["text"] == str(i)
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 101
        assert applog.open_count(path) == 1
