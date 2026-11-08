"""`FakeDelegate`: contract-4 scripted answers and live events, no process. Each `run` takes the next step; the last step repeats.
A scripted ref is preserved; otherwise each call returns `fake-<n>`."""
from dataclasses import dataclass
from typing import Any

from taskloop.adapters import delegate_wire
from tlkernel.delegate import DelegateResult, LiveEvent, Retry, RunRequest, StopFacts
from tlkernel.ports import EventSink


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
    return Step(DelegateResult(data=data, text=text, account="FAKE", model="fake-1", **fields), events)


def stopped(reason: str, scope: str = "machine", permanence: str = "transient", retry: str = "none", at: float | None = None,
            *events: LiveEvent, **facts: Any) -> Step:
    """A non-done answer from its stop facts; `facts` are the other StopFacts fields (ref, fix, resumable, partial)."""
    stop = StopFacts(reason=reason, scope=scope, permanence=permanence, retry=Retry(kind=retry, at=at), **facts)  # type: ignore[arg-type]
    res = DelegateResult(say=reason, account="FAKE", model="fake-1", stop=stop)
    return Step(res, events)


class FakeDelegate:
    def __init__(self, *steps: Step, contract: int = delegate_wire.CONTRACT) -> None:
        self.steps: list[Step] = list(steps) or [done()]
        self.contract = contract
        self.calls: list[Call] = []
        self.results: list[DelegateResult] = []
        self.worker_families: dict[str, str | None] = {}

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
        writer = self.worker_families.get(req.task) if req.reviewer_other_family else None
        if writer and res.family == writer:
            res = res.replace(flag="same_family")
        if req.role == "worker":
            self.worker_families[req.task] = res.family
        res = res if res.ref else res.replace(ref=f"fake-{int(n + 1)}")
        self.results.append(res)
        return res
