"""The pytest plugin every package inherits (entry point pytest11): a test module collects the classes it defines, not the imported ones."""
import inspect
from collections.abc import Iterator

import pytest

from tltestkit.case import install_case_helpers


def pytest_pycollect_makeitem(collector: pytest.Collector, name: str, obj: object) -> list[object] | None:
    if isinstance(collector, pytest.Module) and inspect.isclass(obj) and obj.__module__ != collector.obj.__name__:
        return []
    return None


@pytest.fixture(autouse=True)
def case_helpers(request: pytest.FixtureRequest) -> Iterator[None]:
    """Give member tests the same unittest names as the root tests."""
    with install_case_helpers(request):
        yield
