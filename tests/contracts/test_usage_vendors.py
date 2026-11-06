"""Delegate's per-call usage of each vendor reads as it was reported: cache_write and cost are null when the vendor gave none, never 0."""

import pytest

from taskloop.adapters.delegate_wire import usage_of

CLAUDE = {"tokens": {"in_fresh": 120, "cache_read": 900, "cache_write": 40, "out": 30}, "cost": 0.0, "cost_usd": 0.31,
          "cost_source": "harness", "secs": 12.5, "turns": 3}
CODEX = {"tokens": {"in_fresh": 500, "cache_read": 4000, "cache_write": None, "out": 90}, "cost": 0.0, "cost_usd": 0.0,
         "cost_source": "free", "secs": 20, "turns": 2}
GROK = {"tokens": {"in_fresh": 70, "cache_read": 0, "cache_write": None, "out": 15}, "cost": 0.02, "cost_usd": 0.02,
        "cost_source": "harness", "secs": 4, "turns": 1}
ZAI = {"tokens": {"in_fresh": 60, "cache_read": None, "cache_write": None, "out": 10}, "cost": 0.0, "cost_usd": None,
       "cost_source": "unknown", "secs": 3, "turns": 1}


@pytest.mark.parametrize(("raw", "cache_write", "cost_usd", "source"), [
    (CLAUDE, 40, 0.31, "harness"),
    (CODEX, None, 0.0, "free"),
    (GROK, None, 0.02, "harness"),
    (ZAI, None, None, "unknown"),
], ids=["claude", "codex", "opencode-grok", "zai"])
def test_each_vendors_usage_keeps_what_it_reported(raw: dict, cache_write: int | None, cost_usd: float | None, source: str) -> None:
    got = usage_of(raw)
    assert got is not None and got.tokens is not None
    assert (got.tokens.cache_write, got.cost_usd, got.cost_source) == (cache_write, cost_usd, source)
    assert got.tokens.in_fresh == raw["tokens"]["in_fresh"] and got.tokens.out == raw["tokens"]["out"]
