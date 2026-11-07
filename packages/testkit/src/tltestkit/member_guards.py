"""Kind, time and process guards for workspace tests outside the shell's conftest."""
import contextlib
import os
import resource
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from tlkernel import factorydb
from tltestkit import procsim, work
from tltestkit.limits import hang_s, kind_of_parts, limit_for
from tltestkit.wall import wall_guard

KIND = pytest.StashKey[str]()
USED = pytest.StashKey[float]()
SKIPPED = pytest.StashKey[bool]()
STREAMS = pytest.StashKey[tuple]()


def member_parts(item) -> tuple[str, ...]:
    parts = Path(str(item.path)).parts
    for index in range(len(parts) - 2):
        if parts[index] == "packages" and parts[index + 2] == "tests":
            return parts[index + 3:]
    return ()


def pytest_configure(config):
    for name in ("real", "e2e", "live", "real_proc", "needs"):
        config.addinivalue_line("markers", f"{name}: test kind or required capability")
    work.calibrate()


def pytest_collection_modifyitems(items):
    for item in items:
        if parts := member_parts(item):
            marked = bool(item.get_closest_marker("needs") or item.get_closest_marker("real_proc")
                          or getattr(getattr(item, "obj", None), "real_git", None))
            kind = kind_of_parts(parts, marked_real=marked)
            item.stash[KIND] = kind
            if kind not in ("logic", "live"):
                item.add_marker(getattr(pytest.mark, kind))


def limit(item):
    return limit_for(item.stash[KIND], module_limit=getattr(item.module, "LIMIT_S", 0))


def guard(item):
    if KIND not in item.stash or item.stash[KIND] == "live":
        return contextlib.nullcontext()
    return wall_guard(hang_s(limit(item), float(os.environ.get("TL_TIME_SCALE") or 1)), item.nodeid)


def cpu_s():
    kids = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.process_time() + kids.ru_utime + kids.ru_stime


@pytest.hookimpl(wrapper=True, trylast=True)
def pytest_runtest_setup(item):
    if KIND not in item.stash:
        return (yield)
    before = sys.stdout, sys.stderr
    try:
        with guard(item):
            return (yield)
    finally:
        item.stash[STREAMS] = tuple(now if now is not old else None
                                    for old, now in zip(before, (sys.stdout, sys.stderr), strict=True))


@pytest.hookimpl(wrapper=True, trylast=True)
def pytest_runtest_teardown(item):
    with guard(item):
        return (yield)


@pytest.hookimpl(wrapper=True, trylast=True)
def pytest_runtest_call(item):
    if KIND not in item.stash:
        return (yield)
    before = sys.stdout, sys.stderr
    cpu, instructions = cpu_s(), work.instructions()
    try:
        with guard(item):
            sys.stdout, sys.stderr = (p or old for p, old in zip(item.stash.get(STREAMS, (None, None)), before, strict=True))
            return (yield)
    finally:
        sys.stdout, sys.stderr = before
        used, done = cpu_s() - cpu, work.instructions()
        if item.stash.get(KIND, "") == "logic" and work.measured() and instructions is not None and done is not None:
            used = work.seconds(done - instructions)
        item.stash[USED] = used


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if call.when != "call" or KIND not in item.stash:
        return
    item.stash[SKIPPED] = report.skipped
    if USED in item.stash and report.passed:
        used, maximum = item.stash[USED], limit(item)
        if used > maximum or call.duration > hang_s(maximum, float(os.environ.get("TL_TIME_SCALE") or 1)):
            report.outcome = "failed"
            report.longrepr = f"{item.nodeid}: a {item.stash[KIND]} test took {used:.2f} s of work, over its {maximum:.2f} s limit or hung"


def procs_guard(request):
    if KIND not in request.node.stash:
        yield
        return
    kind = request.node.stash[KIND]
    world = procsim.Procs(request.node.nodeid, guarded=kind == "logic")
    with contextlib.ExitStack() as stack:
        world.install(stack)
        yield world
    world.check(must_spawn=kind == "real" and not request.node.stash.get(SKIPPED, False))


@pytest.fixture(autouse=True)
def member_procs(request, member_filesystem):
    yield from procs_guard(request)


@pytest.fixture(autouse=True)
def member_filesystem(request):
    if KIND not in request.node.stash:
        yield
        return
    factorydb.close_shared()
    factorydb.clear_filesystem_cache()
    before = set(threading.enumerate())
    tempdir = tempfile.tempdir
    try:
        yield
    finally:
        tempfile.tempdir = tempdir
        for thread in set(threading.enumerate()) - before:
            thread.join(0.5)
        left = [thread.name for thread in set(threading.enumerate()) - before if thread.is_alive()]
        factorydb.close_shared()
        factorydb.clear_filesystem_cache()
        assert not left, f"the test left threads running: {left}"
