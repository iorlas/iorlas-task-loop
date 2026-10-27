"""Test tiers as class decorators: `@contract` (one suite run against the real store and its fake) and `@domain` (logic on fakes
only; no disk, no sleep, no process)."""
from typing import Any


def contract[C: type](cls: C) -> C:
    cls.tier = "contract"  # type: ignore[attr-defined]
    return cls


def domain[C: type](cls: C) -> C:
    cls.tier = "domain"  # type: ignore[attr-defined]
    return cls


def tier_of(cls: Any) -> str:
    return getattr(cls, "tier", "")
