"""What one worker answer says about the run's threads, as a value: the call computes it, the caller applies and persists it."""
from dataclasses import dataclass
from typing import Protocol

from tlkernel.wire import Open


@dataclass(frozen=True)
class SessionUpdate:
    seen: tuple[str, ...]  # the brief and plan hashes it now holds


@dataclass(frozen=True)
class Updates:
    session: SessionUpdate | None = None  # only when the call resumes the writer and delegate gave a ref
    planner_ref: str = ""  # the plan node's session, "" = unchanged
    flag: str = ""  # same_family | degraded | "": what the call reports about its lane


@dataclass(frozen=True)
class Asked:
    """A worker call's result: the answer's data and family, and what it says about the run's threads (the caller applies those)."""

    data: Open
    family: str
    updates: Updates


class AskAi(Protocol):
    """The one verb a stage uses to ask a worker: the node it is (`plan`, `write`, `review`, `verify`, `look`), a title for the step book
    and the prompt; the host applies `updates` to the run before it returns."""

    def ai(self, node: str, title: str, prompt: str, *a: object, **kw: object) -> Asked: ...
