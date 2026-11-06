"""status --cheap: zero process spawns, last snapshot plus cached logins with age_s; next reads the login cache instead of spawning."""

import contextlib
import io
import json
import os
import shutil
import subprocess
from unittest import mock

from any_agent import procs
from delegate.app import env, status, usage
from support.case import Case
from support.tmpdir import TemporaryDirectory

import hermetic  # noqa: F401  (a home of its own for every test)
import routing_support as support
from test_route import route


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

    def test_no_snapshot_yet(self):
        rc, d = self.cheap()
        assert rc == 0
        assert "age_s" in d
        assert d["age_s"] is None
        assert d["cheap"]

    def test_snapshot_and_cached_logins(self):
        now = 1_800_000_000.0
        with mock.patch.dict(os.environ, {"DELEGATE_NOW": str(now)}):  # a pinned clock: the ages do not depend on how slow the run is
            self.snapshot_and_logins(now)

    def snapshot_and_logins(self, now):
        status.write_snapshot(
            {"v": 1, "ts": now - 90, "lanes": {"X": {}}, "cockpit": {"v": 1}, "running": [], "recent": [], "needs_input": []}
        )
        usage.auth_cache().remember("CLAUDE_SUBSCRIPTION", False, "not logged in", now - 30)
        rc, d = self.cheap()
        assert rc == 0
        assert d["age_s"] == 90
        assert d["lanes"] == {"X": {}}
        assert d["auth"]["CLAUDE_SUBSCRIPTION"]["ok"] is False
        assert d["auth"]["CLAUDE_SUBSCRIPTION"]["age_s"] == 30

    def test_running_comes_from_fresh_leases_without_ps(self):
        now = env.now()
        env.update_state(lambda s: s.leases.__setitem__("r1", support.lease(lane="L", role="worker", start=now - 5, expires=now + 60)))
        _rc, d = self.cheap()
        assert [r["run_id"] for r in d["running"]] == ["r1"]



class AuthCache(Case):
    def setup_method(self):
        self.d = TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        p = mock.patch.dict(os.environ, {"DELEGATE_CONFIG_DIR": self.d.name})
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("DELEGATE_NOCACHE", None)

    def next_worker(self):
        calls = []

        def fake(cmd, timeout, **kw):
            calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"loggedIn": True}), "")

        with (
            mock.patch.object(procs, "run_capture", side_effect=fake),
            mock.patch.object(usage, "fetch_codex_limits", return_value=(None, "no codex")),
            mock.patch.object(shutil, "which", side_effect=lambda n, *a, **k: "/bin/" + n if n == "claude" else None),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            route.main(["next", "worker"])
        return [c for c in calls if c[1:3] == ["auth", "status"]]

    def test_fresh_cache_means_no_auth_status_call(self):
        usage.auth_cache().remember("CLAUDE_SUBSCRIPTION", True, "x", env.now() - 60)
        assert self.next_worker() == []

    def test_stale_or_missing_cache_asks_once_and_fills_the_cache(self):
        assert len(self.next_worker()) == 1  # missing
        assert self.next_worker() == []  # now cached
        usage.auth_cache().remember("CLAUDE_SUBSCRIPTION", True, "x", env.now() - usage.AUTH_FILE_TTL - 5)
        assert len(self.next_worker()) == 1  # stale

    def test_cached_logout_is_honoured(self):
        usage.auth_cache().remember("CLAUDE_SUBSCRIPTION", False, "x", env.now())
        with mock.patch.object(procs, "run_capture", side_effect=AssertionError("spawned")):
            assert usage.claude_logged_out()

    def test_ttl_is_ten_minutes(self):
        assert usage.AUTH_FILE_TTL == 600
