"""Shared fixture of the `route.py run` tests: fake `codex` and `claude` on PATH, a temp repo,
a config dir of its own. Not a test module."""

import dataclasses
import io
import json
import os
import subprocess as sp
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest
from any_agent import watch
from delegate.app import env, harnesses, usage
from delegate.contracts import history as hist
from delegate.domain.health import ledger as health_ledger
from support.case import Case

import hermetic  # noqa: F401  (a home of its own for every test)
import routing_support as support
from test_route import no_reader, route

FIX = Path(__file__).resolve().parent / "fixtures"


class RunBase(Case):
    """route.py run executes a step against fake `codex` and `claude` on PATH and prints one JSON object (worker-run v1)."""

    FAKE_CODEX = (FIX / "fake_codex.sh").read_text(encoding="utf-8")
    FAKE_CLAUDE = (FIX / "fake_claude.sh").read_text(encoding="utf-8")

    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.base = base
        (base / "bin").mkdir()
        for name, body in (("codex", self.FAKE_CODEX), ("claude", self.FAKE_CLAUDE)):
            (base / "bin" / name).write_text(body)
            (base / "bin" / name).chmod(0o755)
        (base / "codex_home").mkdir()
        (base / "codex_home" / "auth.json").write_text("{}")
        (base / "repo").mkdir()
        for c in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i"]):
            sp.run(["git", "-C", str(base / "repo"), *c], check=True, capture_output=True)
        keys = (
            "PATH",
            "HOME",
            "USERPROFILE",
            "XDG_CONFIG_HOME",
            "DELEGATE_CONFIG_DIR",
            "CODEX_HOME",
            "FAKE_MODE",
            "FAKE_PIDFILE",
            "FAKE_ARGS",
            "FAKE_ENV",
            "DELEGATE_NOW",
            "CLAUDE_CODE_ENTRYPOINT",
            "CLAUDE_FOO",
            "ANTHROPIC_FOO",
        )
        self.saved = {k: os.environ.get(k) for k in keys}
        os.environ.update(
            PATH=str(base / "bin") + os.pathsep + os.environ["PATH"],
            HOME=self.tmp.name,
            USERPROFILE=self.tmp.name,
            XDG_CONFIG_HOME=self.tmp.name,
            DELEGATE_CONFIG_DIR=self.tmp.name,
            CODEX_HOME=str(base / "codex_home"),
            FAKE_PIDFILE=str(base / "pid"),
            FAKE_ARGS=str(base / "args"),
            FAKE_ENV=str(base / "env"),
            CLAUDE_FOO="1",
            ANTHROPIC_FOO="1",
        )
        for k in ("DELEGATE_NOW", "CLAUDE_CODE_ENTRYPOINT"):
            os.environ.pop(k, None)
        self.repo = str(base / "repo")
        self.real = dict(usage.READERS)
        usage.READERS.update({"codex_app_server": no_reader})  # the real subscription reader reads the status-line file
        self.fresh_usage()

    def fresh_usage(self, age=0):
        """What the status line writes; a unattended call may only spend the shared plan when this is fresh."""
        f = Path(self.tmp.name) / ".claude" / "state" / "max-limits.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        soon = time.time() + 3600
        f.write_text(
            json.dumps(
                {
                    "updated": time.time() - age,
                    "rate_limits": {
                        "five_hour": {"used_percentage": 10, "resets_at": soon},
                        "seven_day": {"used_percentage": 20, "resets_at": soon * 100},
                    },
                }
            )
        )

    def teardown_method(self):
        usage.READERS.update(self.real)
        for k, v in self.saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.tmp.cleanup()

    def run_it(self, *args, mode="ok", brief="do the thing\nthe brief", role="worker", timeout=30, unattended=True):
        os.environ["FAKE_MODE"] = mode
        real_in, real_out, real_err = sys.stdin, sys.stdout, sys.stderr
        sys.stdin, sys.stdout, sys.stderr = io.StringIO(brief), io.StringIO(), io.StringIO()
        try:
            code = route.main(
                ["run", role, "--cwd", self.repo]
                + (["--timeout", str(timeout)] if timeout else [])
                + (["--unattended"] if unattended else [])
                + list(args)
            )
            out = sys.stdout.getvalue()
        finally:
            sys.stdin, sys.stdout, sys.stderr = real_in, real_out, real_err
        return code, json.loads(out)  # stdout is exactly one JSON object

    def args_seen(self):
        return Path(os.environ["FAKE_ARGS"]).read_text() if Path(os.environ["FAKE_ARGS"]).exists() else ""

    def lease(self, rid, lane, task="", expires=None):
        support.put_lease(
            rid, lane=lane, role="worker", start=env.now(), task=task, expires=expires if expires is not None else env.now() + 600
        )

    def fast_clock(self, grace=1, stall=1):
        self.addCleanup(setattr, watch, "STALL_S", watch.STALL_S)
        watch.STALL_S = stall
        p = mock.patch.dict(harnesses.LIMITS, {k: dataclasses.replace(v, grace_s=grace) for k, v in harnesses.LIMITS.items()})
        p.start()
        self.addCleanup(p.stop)

    def pid_dead(self):
        time.sleep(0.3)
        with pytest.raises(OSError):
            os.kill(int(Path(os.environ["FAKE_PIDFILE"]).read_text()), 0)

    def config(self, **kw):
        env.update_config(lambda c: c.update(kw))

    def codex_out(self):
        support.put_out("OPENAI_SUBSCRIPTION", env.now() + 3600)

    FAKE_OPENCODE = (FIX / "fake_opencode.sh").read_text(encoding="utf-8")

    def grok_ready(self):
        (self.base / "bin" / "opencode").write_text(self.FAKE_OPENCODE)
        (self.base / "bin" / "opencode").chmod(0o755)
        auth = Path(self.tmp.name) / ".local" / "share" / "opencode"
        auth.mkdir(parents=True, exist_ok=True)
        (auth / "auth.json").write_text('{"xai": {"type": "oauth"}}')

    def watchdog_fake(self, body):
        self.grok_ready()
        pid = Path(self.tmp.name) / "oc.pid"
        script = self.base / "bin" / "opencode"
        script.write_text(f'#!/bin/sh\n[ "$1" = export ] && exit 1\necho $$ > "{pid}"\ncat >/dev/null &\n{body}\n')
        self.codex_out()
        return pid

    def assert_child_gone(self, pidfile):
        pid = int(pidfile.read_text())
        time.sleep(0.3)
        with pytest.raises(OSError):
            os.kill(pid, 0)

    def launches(self):
        return int(Path(os.environ["FAKE_ARGS"] + ".n").read_text())

    def hist(self, rows):
        for r in rows:
            env.history_add(r)

    def failed_rows(self, n, ago, outcome="worker_failed", lane="OPENAI_SUBSCRIPTION", model="gpt-6.1-sol", say="boom"):
        t = env.now() - ago
        return [
            hist.RunRow(
                ts=t + i,
                run_id=f"f{i}",
                task=f"t{i}",
                role="worker",
                lane=lane,
                model=model,
                effort="high",
                done=False,
                outcome=outcome,
                fingerprint=health_ledger.fingerprint(outcome, "event", say),
                say=say[:240],
                until=None,
            )
            for i in range(n)
        ]


def short_limits(cli, **kw):
    """A context manager: `cli`'s deadlines shortened for the run (first_event_s, silence_s, grace_s)."""
    return mock.patch.dict(harnesses.LIMITS, {cli: dataclasses.replace(harnesses.LIMITS[cli], **kw)})
