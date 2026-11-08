"""The Z.AI and DeepSeek accounts: priority, backoff, readiness, the opencode watchdog."""

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import hermetic  # noqa: F401  (a home of its own for every test)
import routing_support as support
from any_agent.harnesses import opencode_sandbox
from any_agent.harnesses.opencode import OpenCodeHarness
from any_agent.supervisor import RunHooks
from delegate_fakes.fake_run import replay
from test_route import CFG, T, accounts, obj

from delegate.app import env, harnesses, launch
from delegate.contracts.json_types import Json
from delegate.domain.accounts.account import Account
from tltestkit.case import Case
from tltestkit.procsim import real_proc
from tltestkit.tmpdir import TemporaryDirectory


class ZaiTests(Case):
    def choose(self, role, ls, **kwargs):
        cfg = copy.deepcopy(CFG)
        return support.decide(role, cfg, ls, {}, T, dict(authored_by=None, premium=None, allow_degraded=False, **kwargs))

    @real_proc("delegate: a worker, git or CLI process")
    def test_worker_priority_and_backoff(self):
        ls = accounts()
        ls["DEEPSEEK_FREE"] = Account("DEEPSEEK_FREE", "deepseek", "subscription")
        ls["ZAI_CODING_SUBSCRIPTION"] = Account("ZAI_CODING_SUBSCRIPTION", "zai", "subscription")
        assert self.choose("worker", ls)["account"] == "DEEPSEEK_FREE"
        ls["DEEPSEEK_FREE"].out = True
        d = self.choose("worker", ls)
        assert d["account"] == "ZAI_CODING_SUBSCRIPTION"
        assert d["how"]["model"] == "zai-coding-plan/glm-5.3"
        assert self.choose("light", ls)["model"] == "glm-5.3-flash"
        ls["ZAI_CODING_SUBSCRIPTION"].out = True
        assert self.choose("worker", ls)["account"] == "OPENAI_SUBSCRIPTION"

    @real_proc("delegate: a worker, git or CLI process")
    def test_zai_author_gets_other_family(self):
        cfg = copy.deepcopy(CFG)
        args = {"authored_by": "zai", "premium": None, "allow_degraded": False}
        d = support.decide("reviewer", cfg, accounts(), {}, T, args)
        assert d["account"] == "OPENAI_SUBSCRIPTION"
        ls = {"ZAI_CODING_SUBSCRIPTION": Account("ZAI_CODING_SUBSCRIPTION", "zai", "subscription")}
        d = support.decide("reviewer", cfg, ls, {}, T, args)
        assert d["flag"] == "same_family"

    @real_proc("delegate: a worker, git or CLI process")
    def test_launch_pins_provider_and_removes_override(self):
        d: dict[str, Json] = {
            "account": "ZAI_CODING_SUBSCRIPTION",
            "model": "glm-5.3",
            "effort": "high",
            "role": "worker",
            "how": {"kind": "opencode", "model": "zai-coding-plan/glm-5.3", "cwd": str(Path.home()), "write": False},
        }
        a = SimpleNamespace(resume=None, schema=None, timeout=10)
        env_in = {"OPENCODE_AUTH_JSON": "override", "OPENCODE_CONFIG": "override", "ZHIPU_API_KEY": "override"}
        with (
            TemporaryDirectory() as tmp,
            patch.object(env, "config_dir", return_value=Path(tmp)),
            patch.object(OpenCodeHarness, "find_exe", return_value="opencode"),
            patch.object(sys, "platform", "darwin"),
            patch.object(opencode_sandbox, "write_shell"),
            patch.object(env, "child_env", return_value=env_in),
        ):
            run = replay(["{}"])
            with run:
                assert launch.launch_worker(d, "OK", a, "test1234", 1, env.load_routing(), RunHooks()).get("outcome") is None
            # Inspect the actual child process environment.
            wenv = obj(run).specs[0].env
            assert json.loads(wenv["OPENCODE_CONFIG_CONTENT"])["enabled_providers"] == ["zai-coding-plan"]
            assert "ZHIPU_API_KEY" not in wenv
            assert "OPENCODE_AUTH_JSON" not in wenv
            obj(d)["how"]["model"] = "zai/glm-5.3"
            run = replay(["{}"])
            with run:
                assert launch.launch_worker(d, "OK", a, "test1234", 1, env.load_routing(), RunHooks())["outcome"] == "setup"
            assert obj(run).specs == []

    @real_proc("delegate: a worker, git or CLI process")
    def test_both_ported_accounts_run_under_the_opencode_watchdog(self):
        a = SimpleNamespace(resume=None, schema=None, timeout=10)
        for account, model in (
            ("ZAI_CODING_SUBSCRIPTION", "zai-coding-plan/glm-5.3"),
            ("DEEPSEEK_FREE", "opencode/deepseek-v4.1-flash-free"),
        ):
            d: dict[str, Json] = {
                "account": account,
                "model": "m",
                "effort": "high",
                "role": "worker",
                "how": {"kind": "opencode", "model": model, "cwd": str(Path.home()), "write": False},
            }
            seen = []

            def spy(self, *args, real=launch.Supervisor.__init__, seen=seen, **kw):
                real(self, *args, **kw)
                seen.append(self)

            with (
                self.subTest(account=account),
                TemporaryDirectory() as tmp,
                patch.object(env, "config_dir", return_value=Path(tmp)),
                patch.object(OpenCodeHarness, "find_exe", return_value="opencode"),
                patch.object(sys, "platform", "darwin"),
                patch.object(opencode_sandbox, "write_shell"),
                patch.object(OpenCodeHarness, "free_model_ok", return_value=True),
                patch.object(launch.Supervisor, "__init__", spy),
                replay(["{}"]),
                patch.object(env, "child_env", return_value={}),
            ):
                launch.launch_worker(d, "OK", a, "test1234", 1, env.load_routing(), RunHooks())
                assert (seen[0].dog.first_event_s, seen[0].dog.silence_s) == (
                    harnesses.LIMITS["opencode"].first_event_s,
                    harnesses.LIMITS["opencode"].silence_s,
                )
                assert seen[0].log is not None, "no watch on opencode's own log"
