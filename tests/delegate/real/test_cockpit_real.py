"""The lane cockpit: one row per known lane, an emoji for each state, a plain reason, the unlock time, usage windows with their source."""

import copy
import io
import json
import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch

import routing_support as support
from test_route import CFG, T, route

from delegate.app import cockpit, env, harnesses, onboard, status, usage
from delegate.domain.lanes.lane import Lane
from tltestkit.procsim import real_proc
from tltestkit.tmpdir import TemporaryDirectory

HOUR = 3600


def cfg_all():
    cfg = copy.deepcopy(CFG)
    return cfg


def lane(name, **over):
    c = CFG["lanes"][name]
    ln = Lane(name, c["family"], c["kind"], c.get("shared_with_orchestrator", False))
    for k, v in over.items():
        setattr(ln, k, v)
    return ln


def view(name, ln, st=None, history=(), login=(True, "ok", T), cfg=None, off=None):
    return cockpit.lane_view(name, cfg or cfg_all(), ln, support.doc_of(st or {}), T, history, 0, login, off)








class LoginCheck:
    def fake(self, d, name, body):
        p = Path(d) / name
        p.write_text("#!/bin/sh\n" + body + "\n")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)

    @real_proc("delegate: a worker, git or CLI process")
    def test_codex_login_status_decides_and_the_answer_is_cached(self):
        with (
            TemporaryDirectory() as d,
            patch.dict(os.environ, {"PATH": d + os.pathsep + os.environ["PATH"], "DELEGATE_CONFIG_DIR": d}),
        ):
            os.environ.pop("DELEGATE_NOCACHE", None)
            count = Path(d) / "count"
            self.fake(d, "codex", f'echo x >> "{count}"; [ "$1 $2" = "login status" ] && {{ echo "Not logged in"; exit 1; }}; exit 2')
            a = cockpit.login_state("OPENAI_SUBSCRIPTION", env.load_state(), T)
            b = cockpit.login_state("OPENAI_SUBSCRIPTION", env.load_state(), T + 200)
            c = cockpit.login_state("OPENAI_SUBSCRIPTION", env.load_state(), T + 400)
            assert (a[0], b[0], c[0]) == (False, False, False)
            assert len(count.read_text().split()) == 2  # once, then again after the 5-minute cache ran out
            self.fake(d, "codex", 'echo "Logged in using ChatGPT"')
            assert harnesses.probe_login("OPENAI_SUBSCRIPTION")[0]



class Command:
    def run_status(self, *argv, state=None, ready=None):
        cfg = cfg_all()
        with TemporaryDirectory() as d, patch.dict(os.environ, {"DELEGATE_CONFIG_DIR": d, "CLAUDE_CODE_ENTRYPOINT": "cli"}):
            (Path(d) / "state.json").write_text(json.dumps({"v": 1, **(state or {})}))
            (Path(d) / "config.json").write_text(json.dumps({"profile": {"lanes": {"DEEPSEEK_FREE": "enabled"}}}))
            ready = ready or dict.fromkeys(cfg["lanes"], True)
            noread = {k: (lambda lane_, S, st_, t, *a: None) for k in usage.READERS}
            logins = {"OPENAI_SUBSCRIPTION": (False, "Not logged in"), "GROK_SUBSCRIPTION": (True, "ok")}
            out, sys.stdout = sys.stdout, io.StringIO()
            try:
                with (
                    patch.object(env, "load_routing", return_value=cfg),
                    patch.dict(usage.READERS, noread),
                    patch.object(onboard, "configured_lanes", return_value=ready),
                    patch.object(harnesses, "probe_login", side_effect=lambda n: logins.get(n, (True, "ok"))),
                    patch.object(env, "now", return_value=T),
                ):
                    route.main(["status", *argv])
                return sys.stdout.getvalue()
            finally:
                sys.stdout = out



    @real_proc("delegate: a worker, git or CLI process")
    def test_stdout_gets_a_safe_encoding_for_emoji(self):
        class Narrow(io.StringIO):
            encoding = "cp1252"
            reconfigured = None

            def reconfigure(self, **kw):
                self.reconfigured = kw

        s = Narrow()
        with patch.object(sys, "stdout", s), patch.object(status, "cmd_status", return_value=0):
            route.main(["status"])
        assert s.reconfigured == {"encoding": "utf-8", "errors": "replace"}
