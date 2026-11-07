"""The base of the converted test classes: the few unittest names they still use."""
import sys
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from typing import Any

import pytest


class Case:
    """The case_helpers fixture sets these on the instance of every test: cleanups run last-in-first-out after the test and its
    teardown_method; subTest is pytest's `subtests.test`; id() is the node id."""

    addCleanup: Callable[..., Any]
    enterContext: Callable[[AbstractContextManager[Any]], Any]
    subTest: Callable[..., AbstractContextManager[None, None]]
    id: Callable[[], str]
    _testMethodName: str


@contextmanager
def install_case_helpers(request: pytest.FixtureRequest) -> Iterator[None]:
    """Install the unittest names until cleanup after the test and its teardown_method."""
    case = request.instance
    if case is None:
        yield
        return
    assert isinstance(request.node, pytest.Function)
    with ExitStack() as stack:
        case._testMethodName = request.node.originalname
        case.id = lambda: request.node.nodeid
        case.addCleanup = stack.callback
        case.enterContext = stack.enter_context

        @contextmanager
        def sub_test(msg: str | None = None, **params: object) -> Iterator[None]:
            """Keep the test's streams while pytest's subtest swaps its own capture."""
            streams = sys.stdout, sys.stderr
            try:
                with request.getfixturevalue("subtests").test(msg, **params):
                    sys.stdout, sys.stderr = streams
                    yield
            finally:
                sys.stdout, sys.stderr = streams
        case.subTest = sub_test
        yield
    case.__dict__.clear()  # pytest retains the instance for the session; release its stores and logs
