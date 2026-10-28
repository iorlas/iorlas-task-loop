"""A CheckResult for a test, in one call: the status follows the exit code unless given."""
from taskloop.contracts.checks import CheckResult


def res(cmd="c", exit=1, **kw):
    kw.setdefault("id", cmd)
    kw.setdefault("group", "tests")
    kw.setdefault("status", "skipped" if exit is None else "passed" if exit == 0 else "failed")
    return CheckResult(cmd=cmd, exit=exit, **kw)
