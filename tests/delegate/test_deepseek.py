"""Free lane must fail closed and keep the actual author family."""

import copy
import json
from unittest.mock import patch

from delegate.app import decide as dec
from delegate.app import env, usage
from delegate.domain.lanes.lane import Lane

import hermetic  # noqa: F401  (a home of its own for every test)
from test_route import CFG, decide, lanes


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

    def test_free_first_light_and_worker_then_existing_fallback(self):
        ls = lanes()
        ls["DEEPSEEK_FREE"] = Lane("DEEPSEEK_FREE", "deepseek", "subscription")
        assert decide("light", ls)["lane"] == "DEEPSEEK_FREE"
        assert decide("worker", ls)["lane"] == "DEEPSEEK_FREE"
        ls["OPENAI_SUBSCRIPTION"].out = True
        assert decide("worker", ls)["lane"] == "DEEPSEEK_FREE"
        ls["DEEPSEEK_FREE"].out = True
        assert decide("light", ls)["lane"] != "DEEPSEEK_FREE"


    def test_disabled_is_skipped_even_with_enabled_profile(self):
        cfg = copy.deepcopy(CFG)
        env.config_store().set_lane("DEEPSEEK_FREE", "declined")
        with patch.dict(usage.READERS, {k: lambda *a: None for k in usage.READERS}):
            assert "DEEPSEEK_FREE" not in dec.fleet_builder(cfg).build(env.load_state(), 1, check_config=False).lanes
