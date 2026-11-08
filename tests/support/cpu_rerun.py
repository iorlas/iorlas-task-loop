"""Remeasure CPU once; publish only the final attempt, including its subtests."""
from unittest.mock import patch

import pytest
from _pytest.runner import runtestprotocol

from tltestkit.limits import verdict

CPU_S = pytest.StashKey[float]()
WORK_S = pytest.StashKey[float]()
FIRST = pytest.StashKey[tuple[float, str]]()
PENDING = pytest.StashKey[tuple[float, str]]()


def cpu_failure(stash, used, limit, message):
    first = stash.get(FIRST, (used, message))
    retry, failure = verdict(first[0], used if FIRST in stash else None, limit)
    if retry:
        stash[PENDING] = used, message
    if failure:
        return f"{first[1]}; {failure}"
    return None


class BufferedHooks:
    """Subtests emit reports inside the call even with runtestprotocol(log=False)."""

    def __init__(self, hooks, reports):
        self.hooks = hooks
        self.reports = reports

    def __getattr__(self, name):
        return getattr(self.hooks, name)

    def pytest_runtest_logreport(self, report):
        self.reports.append(report)


def attempt(item, nextitem):
    subreports = []
    getproxy = item.session.gethookproxy
    with patch.object(item.session, "gethookproxy", lambda path: BufferedHooks(getproxy(path), subreports)):
        reports = runtestprotocol(item, nextitem=nextitem, log=False)
    return subreports, reports


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    hooks = item.ihook
    hooks.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
    try:
        subreports, reports = attempt(item, nextitem)
        if PENDING in item.stash and all(not report.failed for report in [*subreports, *reports]):
            item.stash[FIRST] = item.stash[PENDING]
            for key in (PENDING, CPU_S, WORK_S):
                if key in item.stash:
                    del item.stash[key]
            item._initrequest()
            subreports, reports = attempt(item, nextitem)
        for report in [reports[0], *subreports, *reports[1:]]:
            hooks.pytest_runtest_logreport(report=report)
    finally:
        for key in (FIRST, PENDING):
            if key in item.stash:
                del item.stash[key]
        hooks.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)
    return True
