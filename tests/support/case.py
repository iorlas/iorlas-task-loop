"""The base of the converted test classes: the few unittest names they still use."""
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any


class Case:
    """tests/conftest.py (case_helpers) sets these on the instance of every test: cleanups run last-in-first-out after the test and its
    teardown_method; subTest is pytest's `subtests.test`; id() is the node id."""

    addCleanup: Callable[..., Any]
    enterContext: Callable[[AbstractContextManager[Any]], Any]
    subTest: Callable[..., AbstractContextManager[None, None]]
    id: Callable[[], str]
    _testMethodName: str
