"""Free lane must fail closed and keep the actual author family."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import hermetic  # noqa: F401  (a home of its own for every test)
from any_agent.harnesses import opencode_sandbox
from any_agent.harnesses.opencode import OpenCodeHarness
from any_agent.supervisor import RunHooks
from delegate_fakes.fake_run import replay
from support.procsim import real_proc
from support.tmpdir import TemporaryDirectory
from test_route import CFG, decide, lanes

from delegate.app import env, launch
from delegate.app.settle import Settler


class DeepSeekTests:
    def catalog(self, **changes):
        obj = {
            "id": "deepseek-v4.1-flash-free",
            "providerID": "opencode",
            "status": "active",
            "cost": {"input": 0, "output": 0, "cache": {"read": 0, "write": 0}},
        }
        obj.update(changes)
        return "opencode/deepseek-v4.1-flash-free\n" + json.dumps(obj)


    @real_proc("delegate: a worker, git or CLI process")
    def test_deepseek_author_gets_other_family_review(self):
        assert decide("reviewer", lanes(), authored_by="deepseek")["lane"] == "OPENAI_SUBSCRIPTION"
        steps = CFG["roles"]["reviewer"]["by_author"]["deepseek"]
        assert steps[-1]["flag"] == "same_family"
        assert all(s["on"] != "deepseek" for s in steps[:-1])


    @real_proc("delegate: a worker, git or CLI process")
    def test_launch_isolates_credentials_and_refuses_unverified_model(self):
        d: dict[str, Any] = {
            "lane": "DEEPSEEK_FREE",
            "model": "deepseek-v4.1-flash-free",
            "effort": "low",
            "role": "worker",
            "how": {"kind": "opencode", "model": "opencode/deepseek-v4.1-flash-free", "cwd": "/tmp", "write": False},
        }
        a = SimpleNamespace(resume=None, schema=None, timeout=10)
        for valid in (False, True):
            with (
                TemporaryDirectory() as tmp,
                patch.object(env, "config_dir", return_value=Path(tmp)),
                patch.object(OpenCodeHarness, "find_exe", return_value="opencode"),
                patch.object(sys, "platform", "darwin"),
                patch.object(opencode_sandbox, "write_shell"),
                patch.object(OpenCodeHarness, "free_model_ok", return_value=valid) as guard,
                replay(["{}"]),
                patch.object(Settler, "mark_out"),
                patch.object(env, "update_state"),
                patch.object(env, "child_env", return_value={"OPENCODE_CONFIG": "/private/key-config", "OPENCODE_AUTH_JSON": "secret"}),
            ):
                result = launch.launch_worker(d, "Say OK", a, "test1234", 1, env.load_routing(), RunHooks())
                if valid:
                    wenv = guard.call_args.args[1]
                    assert "OPENCODE_CONFIG" not in wenv
                    assert "OPENCODE_AUTH_JSON" not in wenv
                    assert wenv["XDG_DATA_HOME"] == str(Path(tmp) / "opencode-free-data")
                    assert result.get("outcome") is None
                else:
                    assert result["outcome"] == "rate_limited"
