"""The Z.AI and DeepSeek lanes: priority, backoff, readiness, the opencode watchdog."""

import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from any_agent.harnesses import opencode_sandbox
from any_agent.harnesses.opencode import OpenCodeHarness
from any_agent.supervisor import RunHooks
from delegate.adapters import agent_runs
from delegate.app import env, harnesses, launch, onboard
from delegate.contracts.json_types import Json
from delegate.domain.lanes.lane import Lane
from support.case import Case
from support.procsim import real_proc

import hermetic  # noqa: F401  (a home of its own for every test)
import routing_support as support
from delegate_fakes.fake_run import replay
from test_route import CFG, T, lanes, obj


class ZaiTests(Case):
    def choose(self, role, ls, **kwargs):
        cfg = copy.deepcopy(CFG)
        return support.decide(role, cfg, ls, {}, T, dict(authored_by=None, premium=None, allow_degraded=False, **kwargs))

    @real_proc("delegate: a worker, git or CLI process")
    def test_worker_priority_and_backoff(self):
        ls = lanes()
        ls["DEEPSEEK_FREE"] = Lane("DEEPSEEK_FREE", "deepseek", "subscription")
        ls["ZAI_CODING_SUBSCRIPTION"] = Lane("ZAI_CODING_SUBSCRIPTION", "zai", "subscription")
        assert self.choose("worker", ls)["lane"] == "DEEPSEEK_FREE"
        ls["DEEPSEEK_FREE"].out = True
        d = self.choose("worker", ls)
        assert d["lane"] == "ZAI_CODING_SUBSCRIPTION"
        assert d["how"]["model"] == "zai-coding-plan/glm-5.3"
        assert self.choose("light", ls)["model"] == "glm-5.3-flash"
        ls["ZAI_CODING_SUBSCRIPTION"].out = True
        assert self.choose("worker", ls)["lane"] == "OPENAI_SUBSCRIPTION"

    @real_proc("delegate: a worker, git or CLI process")
    def test_zai_author_gets_other_family(self):
        cfg = copy.deepcopy(CFG)
        args = {"authored_by": "zai", "premium": None, "allow_degraded": False}
        d = support.decide("reviewer", cfg, lanes(), {}, T, args)
        assert d["lane"] == "OPENAI_SUBSCRIPTION"
        ls = {"ZAI_CODING_SUBSCRIPTION": Lane("ZAI_CODING_SUBSCRIPTION", "zai", "subscription")}
        d = support.decide("reviewer", cfg, ls, {}, T, args)
        assert d["flag"] == "same_family"

    def test_disabled_does_not_change_original_rungs(self):
        cfg = copy.deepcopy(CFG)
        steps = support.build_tiers("worker", cfg, {}, frozenset({"deepseek", "zai"}))[0]
        assert steps[0]["on"] == "openai"
        assert steps[0]["idx"] == 0

    def test_readiness_needs_subscription_credential(self):
        cfg = copy.deepcopy(CFG)
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(os.environ, {"XDG_DATA_HOME": tmp}),
            patch.object(OpenCodeHarness, "find_exe", return_value="opencode"),
            patch.object(env, "load_routing", return_value=cfg),
            patch.object(onboard.sys, "platform", "darwin"),
        ):
            p = Path(tmp) / "opencode/auth.json"
            p.parent.mkdir()
            for auth, expected in [
                ({"zai": {"type": "api", "key": "test"}}, False),
                ({"zai-coding-plan": {}}, False),
                ({"zai-coding-plan": {"type": "api", "key": "test"}}, True),
            ]:
                p.write_text(json.dumps(auth))
                assert onboard.check_opencode_zai_coding() == expected

    @real_proc("delegate: a worker, git or CLI process")
    def test_launch_pins_provider_and_removes_override(self):
        d: dict[str, Json] = {
            "lane": "ZAI_CODING_SUBSCRIPTION",
            "model": "glm-5.3",
            "effort": "high",
            "role": "worker",
            "how": {"kind": "opencode", "model": "zai-coding-plan/glm-5.3", "cwd": "/tmp", "write": False},
        }
        a = SimpleNamespace(resume=None, schema=None, timeout=10)
        env_in = {"OPENCODE_AUTH_JSON": "override", "OPENCODE_CONFIG": "override", "ZHIPU_API_KEY": "override"}
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(env, "config_dir", return_value=Path(tmp)),
            patch.object(OpenCodeHarness, "find_exe", return_value="opencode"),
            patch.object(sys, "platform", "darwin"),
            patch.object(opencode_sandbox, "write_shell"),
            patch.object(agent_runs, "run"),
            patch.object(agent_runs, "lanes"),
            patch.object(env, "child_env", return_value=env_in),
        ):
            run = replay(["{}"])
            with run:
                assert launch.launch_worker(d, "OK", a, "test1234", 1, env.load_routing(), {}, RunHooks()).get("outcome") is None
            # Inspect the actual child process environment.
            wenv = obj(run).specs[0].env
            assert json.loads(wenv["OPENCODE_CONFIG_CONTENT"])["enabled_providers"] == ["zai-coding-plan"]
            assert "ZHIPU_API_KEY" not in wenv
            assert "OPENCODE_AUTH_JSON" not in wenv
            obj(d)["how"]["model"] = "zai/glm-5.3"
            run = replay(["{}"])
            with run:
                assert launch.launch_worker(d, "OK", a, "test1234", 1, env.load_routing(), {}, RunHooks())["outcome"] == "setup"
            assert obj(run).specs == []

    @real_proc("delegate: a worker, git or CLI process")
    def test_both_ported_lanes_run_under_the_opencode_watchdog(self):
        a = SimpleNamespace(resume=None, schema=None, timeout=10)
        for lane, model in (("ZAI_CODING_SUBSCRIPTION", "zai-coding-plan/glm-5.3"), ("DEEPSEEK_FREE", "opencode/deepseek-v4.1-flash-free")):
            d: dict[str, Json] = {
                "lane": lane,
                "model": "m",
                "effort": "high",
                "role": "worker",
                "how": {"kind": "opencode", "model": model, "cwd": "/tmp", "write": False},
            }
            seen = []

            def spy(self, *args, real=launch.Supervisor.__init__, seen=seen, **kw):
                real(self, *args, **kw)
                seen.append(self)

            with (
                self.subTest(lane=lane),
                tempfile.TemporaryDirectory() as tmp,
                patch.object(env, "config_dir", return_value=Path(tmp)),
                patch.object(OpenCodeHarness, "find_exe", return_value="opencode"),
                patch.object(sys, "platform", "darwin"),
                patch.object(opencode_sandbox, "write_shell"),
                patch.object(OpenCodeHarness, "free_model_ok", return_value=True),
                patch.object(launch.Supervisor, "__init__", spy),
                replay(["{}"]),
                patch.object(agent_runs, "run"),
                patch.object(agent_runs, "lanes"),
                patch.object(env, "child_env", return_value={}),
            ):
                launch.launch_worker(d, "OK", a, "test1234", 1, env.load_routing(), {}, RunHooks())
                assert (seen[0].dog.first_event_s, seen[0].dog.silence_s) == (
                    harnesses.LIMITS["opencode"].first_event_s,
                    harnesses.LIMITS["opencode"].silence_s,
                )
                assert seen[0].log is not None, "no watch on opencode's own log"
