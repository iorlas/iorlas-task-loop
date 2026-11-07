"""A check that waits is not a hung check: only its wall limit stops it. Real processes, a real process table (CPU flat while one
sleeps), short limits. On 0.23.101 a silent sleeping check was stopped as hung after check_idle_min (this file failed there)."""
import contextlib
import io
import json
import sys
from pathlib import Path

import pytest
from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import procsim
from support.tmpdir import TemporaryDirectory

from checks.test_checks_speed import SpeedTest
from taskloop.app.wire import slots as wslots
from tlkernel import config


class Quiet(SpeedTest):
    def run_one(self, cmd, **check):
        eng = self.checks_engine(checks=[dict({"id": "q", "cmd": cmd, "group": "tests"}, **check)])  # pyrefly: ignore[bad-argument-type]
        return eng, eng.run_checks({"checks": [], "files": []}, "s")[0]

    def log(self, eng, kind):
        rows = eng.records()
        return [r for r in rows if r["kind"] == kind]

    def test_a_silent_sleeping_check_is_not_stopped(self):
        eng, res = self.run_one(procsim.fake("sleep-1", procsim.takes(1)))
        assert (res.status, res.exit) == ("passed", 0)
        assert self.log(eng, "kill") == []

    def test_a_busy_silent_check_passes(self):
        _eng, res = self.run_one(procsim.fake("busy", procsim.exits(0)))
        assert res.status == "passed"


class RetiredKeys(Case):
    """check_idle_min (engine) and idle_min (a check) cannot stop anything any more: a profile that still has them loads, says so
    once on one line each, and the file is not touched."""

    def test_a_profile_with_the_retired_keys_loads_warns_once_and_is_left_as_it_was(self):
        raw = json.dumps({"engine": {"check_idle_min": 3, "check_wall_min": 20,
                                     "checks": [{"id": "u", "argv": ["just", "u"], "idle_min": 2, "wall_min": 90}]}}, indent=1)
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        f = Path(tmp.name) / ".task-loop.json"
        f.write_text(raw)
        before = f.read_bytes()
        err = io.StringIO()
        config._SAID.clear()
        with contextlib.redirect_stderr(err):
            for _ in range(2):
                profile = wslots.load_profile(json.loads(f.read_text()))
        assert (profile.engine.check_wall_min, profile.engine.checks[0].wall_min) == (20, 90)
        lines = err.getvalue().splitlines()
        assert len(lines) == 2, lines  # one per key, not per load
        assert all(".task-loop.json" in x and "retired and ignored; safe to delete" in x for x in lines)
        assert "engine.check_idle_min" in lines[0]
        assert "engine.checks[0].idle_min" in lines[1]
        assert f.read_bytes() == before

    def test_each_renamed_key_fails_naming_the_new_one_and_a_retired_one_does_not(self):
        rows = [({"engine": {"checks": [{"id": "a", "argv": ["x"]}, {"id": "b", "argv": ["x"], "timeout_min": 5}]}},
                 "checks[1]: timeout_min was renamed to wall_min"),
                ({"engine": {"check_timeout_min": 30}}, "engine: check_timeout_min was renamed to check_wall_min")]
        for raw, msg in rows:
            with self.subTest(msg):
                with pytest.raises(config.ConfigError) as cm:
                    config.load(raw)
                assert msg in str(cm.value)
        assert config.load({"engine": {"check_idle_min": 3}}).engine.check_wall_min == 60

    def test_an_unknown_key_still_fails(self):
        with pytest.raises(SystemExit):
            wslots.load_profile({"engine": {"check_idle_mins": 3}})
