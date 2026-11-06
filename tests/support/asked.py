"""An `Asked` for a test that stands in for the worker's answer."""
from typing import Any

from taskloop.contracts.asked import Asked, Updates


def ans(data: dict[str, Any], family: str = "") -> Asked:
    return Asked(data=data, family=family, updates=Updates())
