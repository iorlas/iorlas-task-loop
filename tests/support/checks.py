"""A CheckResult for a test, in one call: the status follows the exit code unless given."""
from support import fake_route
from taskloop.contracts import plancheck
from taskloop.contracts.checks import CheckResult
from taskloop.contracts.plancheck import Adhoc, Ref, adhoc


def res(cmd="c", exit=1, **kw):
    kw.setdefault("id", cmd)
    kw.setdefault("group", "tests")
    kw.setdefault("status", "skipped" if exit is None else "passed" if exit == 0 else "failed")
    return CheckResult(cmd=cmd, exit=exit, **kw)


def ck(texts):
    """A stage's check list from command texts: each an adhoc check that reads nothing (a Ref or an Adhoc passes through)."""
    return [t if isinstance(t, (Ref, Adhoc)) else adhoc(t) for t in texts]


def typed(plan):
    """A plan the way the engine holds it after parse: every check a Ref or an Adhoc (a text check is an adhoc that reads nothing)."""
    out = fake_route.as_argv(plan)
    plancheck.parse(out)
    return out
