"""Per-test and per-fixture CPU time recorder: a pytest plugin, loaded by dev/runtests.py (`-p testtimes`, PYTHONPATH=dev) and by hand.

`TL_TEST_TIMES=<file.json> PYTHONPATH=dev pytest -p testtimes ...` writes (a `%p` in the name is the process id: one file per xdist worker),
at the end of the run, one record per test (setup, call and
teardown: CPU seconds = user+sys of this process plus the children it waited for, and wall seconds) and one per fixture setup (its own
time, with the fixtures it pulled in subtracted). Without TL_TEST_TIMES the plugin records nothing. Read the file with
dev/testtimes_report.py."""
import json
import os
import resource
import time

import pytest

_TESTS: dict[str, dict[str, float]] = {}
_FIXTURES: dict[str, dict[str, float]] = {}
_STACK: list[list[float]] = []  # per running fixture setup: [children's cpu, children's wall]


def _cpu() -> float:
    kids = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.process_time() + kids.ru_utime + kids.ru_stime


def _add(table: dict[str, dict[str, float]], key: str, cpu: float, wall: float, phase: str) -> None:
    row = table.setdefault(key, {})
    row[phase + "_cpu"] = row.get(phase + "_cpu", 0.0) + cpu
    row[phase + "_wall"] = row.get(phase + "_wall", 0.0) + wall
    row["n"] = row.get("n", 0) + (phase == "setup")


def _phase(item, phase):
    cpu, wall = _cpu(), time.perf_counter()
    try:
        return (yield)
    finally:
        _add(_TESTS, item.nodeid, _cpu() - cpu, time.perf_counter() - wall, phase)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item):
    return (yield from _phase(item, "setup"))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    return (yield from _phase(item, "call"))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item, nextitem):
    return (yield from _phase(item, "teardown"))


@pytest.hookimpl(wrapper=True)
def pytest_fixture_setup(fixturedef, request):
    _STACK.append([0.0, 0.0])
    cpu, wall = _cpu(), time.perf_counter()
    try:
        return (yield)
    finally:
        spent_cpu, spent_wall = _cpu() - cpu, time.perf_counter() - wall
        kids = _STACK.pop()
        if _STACK:
            _STACK[-1][0] += spent_cpu
            _STACK[-1][1] += spent_wall
        key = f"{os.path.relpath(fixturedef.func.__code__.co_filename)}::{fixturedef.argname}"
        _add(_FIXTURES, key, spent_cpu - kids[0], spent_wall - kids[1], "setup")


def _dump() -> None:
    path = os.environ.get("TL_TEST_TIMES", "").replace("%p", str(os.getpid()))
    if path:
        with open(path + ".part", "w", encoding="utf-8") as out:
            json.dump({"tests": _TESTS, "fixtures": _FIXTURES}, out)
        os.replace(path + ".part", path)


def pytest_runtest_logfinish(nodeid, location):
    """A run killed half way still leaves the file: rewritten every 25 tests."""
    if len(_TESTS) % 25 == 0:
        _dump()


def pytest_sessionfinish(session):
    _dump()
