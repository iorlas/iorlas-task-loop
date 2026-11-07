"""The test kit owns kernel-only config and answer builders."""

from tlkernel.config import EngineConfig
from tltestkit import cfgs, plans


def test_cfg_with_returns_engine_config():
    assert isinstance(cfgs.cfg_with(base_red=True), EngineConfig)


def test_plan_top_level_keys():
    assert set(plans.PLAN) == {
        "summary", "stages", "risks", "question", "options", "decided", "cases", "leftovers",
    }
