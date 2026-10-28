"""Test tags. `@contract`: one suite run against the real adapter and its fake (or golden output), so they cannot drift.
`@domain`: logic over fakes, no process and no files. `@slow`: a real process. `select(suite, "contract")` keeps one kind."""
import unittest
from collections.abc import Iterator
from typing import Any


def _tag(name: str) -> Any:
    def mark(cls: Any) -> Any:
        cls.tags = frozenset(getattr(cls, "tags", frozenset()) | {name})
        return cls
    return mark


contract = _tag("contract")
domain = _tag("domain")
slow = _tag("slow")  # starts a real process and waits on it; `select(suite, "slow")` keeps these


def _tests(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from _tests(t)
        else:
            yield t


def select(suite: unittest.TestSuite, tag: str) -> unittest.TestSuite:
    return unittest.TestSuite(t for t in _tests(suite) if tag in getattr(type(t), "tags", frozenset()))
