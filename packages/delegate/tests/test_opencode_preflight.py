"""delegate-avz: opencode sandbox covers the launcher XDG dirs; a nested sandbox is caught before any token; no sandbox-exec, no account."""

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest import mock

import hermetic  # noqa: F401  (a home of its own for every test)
from any_agent.harnesses import opencode_sandbox as box
from any_agent.harnesses.opencode import OpenCodeHarness, Profile
from any_agent.protocol import LaunchInputs
from test_route import CFG

from delegate.app import cockpit, env, launch, onboard
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory


class XdgWritable(Case):
    def test_every_xdg_var_the_launcher_sets_is_writable_in_the_profile(self):
        for profile in (Profile(), Profile(own_data=True)):
            with self.subTest(own_data=profile.own_data), TemporaryDirectory() as d:
                h = OpenCodeHarness(profile, Path(d))
                spec = h.launch_spec(
                    LaunchInputs(exe="/bin/oc", cwd="/w", model="m", effort="high", prompt="p", env={}, session="rid12345", write=True)
                )
                xdg = {k: v for k, v in spec.env.items() if k.startswith("XDG_")}
                assert xdg
                assert len(xdg) == (4 if profile.own_data else 2)
                assert h.shell is not None
                script = h.shell.read_text()
                for k, v in xdg.items():
                    assert f"(require-not (subpath {json.dumps(str(Path(v).resolve()))}))" in script, k
                    assert Path(v).is_dir(), k  # commands cannot create it: its parent is not writable


class Preflight(Case):
    def setup_method(self):
        saved = list(box._probed)
        box._probed.clear()
        self.addCleanup(lambda: (box._probed.clear(), box._probed.extend(saved)))

    def test_exit_71_names_the_nested_sandbox_once_per_process(self):
        run = mock.Mock(return_value=subprocess.CompletedProcess([], 71, "", "sandbox_apply: Operation not permitted"))
        assert "exited 71" in (box.preflight(run) or "")
        assert "exited 71" in (box.preflight(run) or "")
        run.assert_called_once()

    def test_a_working_sandbox_passes_and_a_missing_one_fails(self):
        assert box.preflight(mock.Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))) is None
        box._probed.clear()
        assert "could not run" in (box.preflight(mock.Mock(side_effect=FileNotFoundError("sandbox-exec"))) or "")

    def test_a_nested_sandbox_stops_the_account_before_any_launch_and_marks_it_out(self):
        marks = []
        settler = mock.Mock(mark_out=lambda *a: marks.append(a))
        how = {"kind": "opencode", "cwd": "/w", "model": "m", "write": True}
        d: dict[str, Any] = {"account": "DEEPSEEK_FREE", "model": "m", "effort": "high", "how": how}
        with (
            mock.patch.object(OpenCodeHarness, "find_exe", return_value="/bin/oc"),
            mock.patch.object(OpenCodeHarness, "supported", return_value=True),
            mock.patch.object(box, "preflight", return_value="sandbox-exec exited 71: x"),
            mock.patch.object(launch, "settler", return_value=settler),
            mock.patch.object(OpenCodeHarness, "launch_spec") as spec,
        ):
            res = launch.prepare_opencode(d, "brief", mock.Mock(schema=None, resume=None), "rid", 1000.0, CFG)
        assert isinstance(res, dict)
        assert res["outcome"] == "setup"
        assert "nested_sandbox" in str(res["say"])
        spec.assert_not_called()  # no worker, so no model tokens
        assert (marks[0][0], marks[0][1]) == ("DEEPSEEK_FREE", 4600.0)


class NoSandbox:
    def test_off_darwin_the_opencode_accounts_are_unavailable_and_others_are_not(self):
        names = ("GROK_SUBSCRIPTION", "DEEPSEEK_FREE", "ZAI_CODING_SUBSCRIPTION", "OPENAI_SUBSCRIPTION")
        cfg: dict[str, Any] = {"accounts": {n: {"opt_in": n in ("DEEPSEEK_FREE", "ZAI_CODING_SUBSCRIPTION")} for n in names}}
        on = {"DEEPSEEK_FREE": "enabled", "ZAI_CODING_SUBSCRIPTION": "enabled"}
        with (
            mock.patch.object(OpenCodeHarness, "supported", return_value=False),
            mock.patch.object(env, "profile_accounts", return_value=on),
        ):
            for account in ("GROK_SUBSCRIPTION", "DEEPSEEK_FREE", "ZAI_CODING_SUBSCRIPTION"):
                assert cockpit.off_reason(account, cfg, (None, "", None)) == cockpit.NO_SANDBOX
            assert "not configured" in cockpit.off_reason("OPENAI_SUBSCRIPTION", cfg, (None, "", None))
            assert "no sandbox" in onboard.fix_hint("GROK_SUBSCRIPTION")
            assert "profile.accounts.DEEPSEEK_FREE" in onboard.fix_hint("DEEPSEEK_FREE")
            assert "codex" in onboard.fix_hint("OPENAI_SUBSCRIPTION")
