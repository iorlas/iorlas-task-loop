"""One delegate call for a test: `call(resolved, role, brief, schema, cwd, runner=, **request)` -> `Got`, the answer with the facts
a test asserts on (the typed result, its wire object, the policy's Stop)."""
from typing import Any

import support.paths  # noqa: F401
from taskloop.adapters import delegate as dl
from taskloop.domain.accounts import policy as lp
from tlkernel import childenv
from tlkernel.delegate import RunRequest
from tlkernel.env import snapshot


class Got:
    def __init__(self, answer):
        self.answer, self.res, self.raw = answer, answer.res, answer.raw
        self.stop = lp.stop_of(answer.res)
        self.done = answer.res.stop is None
        self.data, self.ref, self.say = answer.res.data, answer.res.ref, answer.res.say
        self.source = "delegate" if answer.raw else "synthesized"


def request(role, cwd, **kw: Any):
    fields: dict[str, Any] = dict({"brief_path": "", "schema_path": ""}, **kw)
    return RunRequest(role=role, cwd=cwd, **fields)


def call(resolved, role, brief, schema, cwd, runner, env=None, **kw):
    base = childenv.current_env(snapshot()) if env is None else env
    return Got(dl.call(resolved, request(role, cwd, **kw), brief, schema, runner, base))
