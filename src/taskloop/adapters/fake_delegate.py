"""`FakeDelegate`: scripted answers and live events, no process. Each `run` takes the next step; the last step repeats.
Like the stand-in route.py it replaces: `--resume X` is echoed as the answer's `ref`, a call without one opens `fake-<n>`."""
import dataclasses
from dataclasses import dataclass
from typing import Any

from taskloop.adapters import delegate_wire
from taskloop.contracts.delegate import DelegateResult, LiveEvent, Retry, RunRequest, StopFacts
from taskloop.contracts.ports import EventSink


@dataclass(frozen=True)
class Step:
    result: DelegateResult
    events: tuple[LiveEvent, ...] = ()


@dataclass(frozen=True)
class Call:
    req: RunRequest
    brief: str
    schema: dict[str, Any]


def done(data: dict[str, Any] | None = None, text: str = "ok", *events: LiveEvent, **fields: Any) -> Step:
    return Step(DelegateResult(status="done", data=data, text=text, lane="FAKE", model="fake-1", **fields), events)


def stopped(reason: str, scope: str = "machine", permanence: str = "transient", retry: str = "none", at: float | None = None,
            *events: LiveEvent, **facts: Any) -> Step:
    """A non-done answer from its stop facts; `facts` are the other StopFacts fields (ref, fix, resumable, partial)."""
    stop = StopFacts(reason=reason, scope=scope, permanence=permanence, retry=Retry(kind=retry, at=at), **facts)  # type: ignore[arg-type]
    res = DelegateResult(status=delegate_wire.status_of(stop), reason=reason, next=delegate_wire.next_of(stop),  # type: ignore[arg-type]
                         say=reason, lane="FAKE", model="fake-1", stop=stop)
    return Step(res, events)


class FakeDelegate:
    def __init__(self, *steps: Step, contract: int = delegate_wire.CONTRACT) -> None:
        self.steps: list[Step] = list(steps) or [done()]
        self.contract = contract
        self.calls: list[Call] = []

    def script(self, *steps: Step) -> None:
        self.steps = list(steps)

    def speaks(self) -> int:
        return self.contract

    def run(self, req: RunRequest, brief: str, schema: dict[str, Any], on_event: EventSink | None = None) -> DelegateResult:
        n = len(self.calls)
        self.calls.append(Call(req, brief, schema))
        step = self.steps[min(n, len(self.steps) - 1)]
        if on_event:
            for e in step.events:
                on_event(e)
        res = step.result
        return res if res.ref else dataclasses.replace(res, ref=req.resume or "fake-%d" % (n + 1))
