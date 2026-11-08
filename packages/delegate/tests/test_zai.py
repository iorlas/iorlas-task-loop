"""The Z.AI and DeepSeek accounts: priority, backoff, readiness, the opencode watchdog."""

import copy
import json
import os
from pathlib import Path
from unittest.mock import patch

import hermetic  # noqa: F401  (a home of its own for every test)
import routing_support as support
from any_agent.harnesses.opencode import OpenCodeHarness
from test_route import CFG, T

from delegate.app import env, onboard
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory


class ZaiTests(Case):
    def choose(self, role, ls, **kwargs):
        cfg = copy.deepcopy(CFG)
        return support.decide(role, cfg, ls, {}, T, dict(authored_by=None, premium=None, allow_degraded=False, **kwargs))

    def test_disabled_does_not_change_original_rungs(self):
        cfg = copy.deepcopy(CFG)
        steps = support.build_tiers("worker", cfg, {}, frozenset({"deepseek", "zai"}))[0]
        assert steps[0]["on"] == "openai"
        assert steps[0]["idx"] == 0

    def test_readiness_needs_subscription_credential(self):
        cfg = copy.deepcopy(CFG)
        with (
            TemporaryDirectory() as tmp,
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
