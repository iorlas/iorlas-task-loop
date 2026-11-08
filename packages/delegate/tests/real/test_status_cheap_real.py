"""status --cheap: zero process spawns, last snapshot plus cached logins with age_s; next reads the login cache instead of spawning."""

import contextlib
import io
import json
import os
import subprocess
from unittest import mock

import hermetic  # noqa: F401  (a home of its own for every test)
from any_agent import procs
from test_route import route

from delegate.app import env, harnesses, status, usage
from tltestkit.case import Case
from tltestkit.procsim import real_proc
from tltestkit.tmpdir import TemporaryDirectory


def boom(*a, **k):
    raise AssertionError(f"a process was spawned: {a[:1]!r}")


class Cheap(Case):
    def setup_method(self):
        self.d = TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        p = mock.patch.dict(os.environ, {"DELEGATE_CONFIG_DIR": self.d.name})
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("DELEGATE_NOCACHE", None)

    def cheap(self):
        out = io.StringIO()
        with (
            mock.patch.object(subprocess, "run", side_effect=boom),
            mock.patch.object(subprocess, "Popen", side_effect=boom),
            mock.patch.object(procs, "run_capture", side_effect=boom),
            contextlib.redirect_stdout(out),
        ):
            rc = route.main(["status", "--json", "--cheap"])
        return rc, json.loads(out.getvalue())

    def snapshot_and_logins(self, now):
        status.write_snapshot(
            {"v": 1, "ts": now - 90, "accounts": {"X": {}}, "cockpit": {"v": 1}, "running": [], "recent": [], "needs_input": []}
        )
        usage.auth_cache().remember("CLAUDE_SUBSCRIPTION", False, "not logged in", now - 30)
        rc, d = self.cheap()
        assert rc == 0
        assert d["age_s"] == 90
        assert d["accounts"] == {"X": {}}
        assert d["auth"]["CLAUDE_SUBSCRIPTION"]["ok"] is False
        assert d["auth"]["CLAUDE_SUBSCRIPTION"]["age_s"] == 30

    @real_proc("delegate: a worker, git or CLI process")
    def test_full_status_writes_the_snapshot_and_the_cache(self):
        out = io.StringIO()
        with mock.patch.object(harnesses, "probe_login", return_value=(True, "ok")), contextlib.redirect_stdout(out):
            route.main(["status", "--json"])
        assert env.snapshot_path().exists()
        _rc, d = self.cheap()
        assert isinstance(d["age_s"], int)
        assert "cockpit" in d
