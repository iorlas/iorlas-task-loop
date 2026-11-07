"""The pytest plugin every package inherits (entry point pytest11): a test module collects the classes it defines, not the imported ones."""
import importlib
import inspect
from collections.abc import Iterator

import pytest

from tltestkit.case import install_case_helpers

MEMBER_GUARDS = "tltestkit.member_guards"


def pytest_configure(config: pytest.Config) -> None:
    """Member runs (rootdir packages/<name>) get the layer guards the root tests/conftest.py gives the root tests; the root run does not.

    Loaded here, not at plugin import: the guards need the member's vendored paths, which exist only once its ini is applied."""
    if config.rootpath.parent.name == "packages":
        config.pluginmanager.register(importlib.import_module(MEMBER_GUARDS), MEMBER_GUARDS)


def pytest_pycollect_makeitem(collector: pytest.Collector, name: str, obj: object) -> list[object] | None:
    if isinstance(collector, pytest.Module) and inspect.isclass(obj) and obj.__module__ != collector.obj.__name__:
        return []
    return None


@pytest.fixture(autouse=True)
def case_helpers(request: pytest.FixtureRequest) -> Iterator[None]:
    """Give member tests the same unittest names as the root tests."""
    if request.config.pluginmanager.hasplugin(MEMBER_GUARDS):
        request.getfixturevalue("member_procs")  # the guard is set up first, so it is checked last
    with install_case_helpers(request):
        yield
