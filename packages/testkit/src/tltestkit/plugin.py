"""The pytest plugin every package inherits (entry point pytest11): a test module collects the classes it defines, not the imported ones."""
import inspect

import pytest


def pytest_pycollect_makeitem(collector: pytest.Collector, name: str, obj: object) -> list[object] | None:
    if isinstance(collector, pytest.Module) and inspect.isclass(obj) and obj.__module__ != collector.obj.__name__:
        return []
    return None
